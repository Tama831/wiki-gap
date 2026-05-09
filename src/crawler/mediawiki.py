"""
MediaWiki API クライアント。

Wikidata の QID から各言語の記事メタデータを取得する:
  - sitelinks (en/ja タイトル)
  - revisions (バイト数, 最終更新日時)
  - parse sections (セクション数)
  - images (画像数)
  - extracts (リード冒頭) は今回はスコープ外
  - 参考文献数 = 本文中の <ref ...> タグ数 (parse?prop=wikitext で取得して count)

Wikimedia エチケット:
  - User-Agent に GitHub リポ URL を明記
  - maxlag=5 を必須付与 (errorformat=plaintext)
  - 1〜2 req/sec (asyncio.Semaphore + sleep)
  - 429 / maxlag は exponential backoff (1 → 2 → 4 → ... 最大 60s)
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


def _wikipedia_api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


@dataclass
class LangArticleMeta:
    title: str | None = None
    bytes_: int | None = None
    sections: int | None = None
    refs: int | None = None
    images: int | None = None
    last_edit: str | None = None  # ISO8601


@dataclass
class ArticleMeta:
    qid: str
    en: LangArticleMeta = field(default_factory=LangArticleMeta)
    ja: LangArticleMeta = field(default_factory=LangArticleMeta)


class MediaWikiClient:
    """MediaWiki API への薄いラッパー。レート制限と backoff を内蔵。"""

    def __init__(
        self,
        rate_limit_rps: float = 1.5,
        max_concurrency: int = 3,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._min_interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._next_slot: dict[str, float] = {}  # endpoint -> next allowed time
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": _user_agent()},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "MediaWikiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    async def _wait_slot(self, endpoint: str) -> None:
        """Per-endpoint レート制限。同 endpoint への連続呼び出しに最小間隔を保証。"""
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            slot = self._next_slot.get(endpoint, 0.0)
            wait = max(0.0, slot - now)
            self._next_slot[endpoint] = max(now, slot) + self._min_interval
        if wait > 0:
            await asyncio.sleep(wait)

    async def _get(
        self, endpoint: str, params: dict[str, Any], max_retries: int = 5
    ) -> dict[str, Any]:
        """
        共通 GET。maxlag を必ず付与し、429 / maxlag エラーは exponential backoff。
        """
        params = {**params, "format": "json", "maxlag": "5"}

        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(max_retries):
            await self._wait_slot(endpoint)
            async with self._semaphore:
                try:
                    response = await self._client.get(endpoint, params=params)
                    if response.status_code == 429:
                        retry_after = float(response.headers.get("retry-after", delay))
                        await asyncio.sleep(min(retry_after, 60.0))
                        delay = min(delay * 2, 60.0)
                        continue
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    last_error = exc
                    if attempt < max_retries - 1:
                        await asyncio.sleep(min(delay, 60.0))
                        delay *= 2
                        continue
                    raise

            # MediaWiki specific errors
            if isinstance(payload, dict) and "error" in payload:
                err = payload["error"]
                code = err.get("code", "")
                if code in {"maxlag", "ratelimited"}:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(min(delay, 60.0))
                        delay *= 2
                        continue
                # Other errors: surface but do not retry forever
                raise RuntimeError(f"MediaWiki API error: {err}")

            return payload

        raise RuntimeError(f"MediaWiki API failed after {max_retries} retries") from last_error

    # ── public API ──

    async def fetch_lang_meta(self, lang: str, title: str) -> LangArticleMeta:
        """単一記事の詳細メタを取得。title が空なら None なメタを返す。"""
        if not title:
            return LangArticleMeta()

        meta = LangArticleMeta(title=title)
        endpoint = _wikipedia_api(lang)

        # 1) revisions: size, last edit timestamp
        rev = await self._get(
            endpoint,
            {
                "action": "query",
                "prop": "revisions|images",
                "titles": title,
                "rvprop": "size|timestamp",
                "rvlimit": "1",
                "imlimit": "max",
                "redirects": "1",
            },
        )
        pages = (rev.get("query") or {}).get("pages") or {}
        if pages:
            page = next(iter(pages.values()))
            if "missing" in page:
                return LangArticleMeta(title=title)
            revs = page.get("revisions") or []
            if revs:
                meta.bytes_ = revs[0].get("size")
                meta.last_edit = revs[0].get("timestamp")
            images = page.get("images") or []
            meta.images = len(images)

        # 2) parse: sections + wikitext (for ref count)
        try:
            parsed = await self._get(
                endpoint,
                {
                    "action": "parse",
                    "page": title,
                    "prop": "sections|wikitext",
                    "redirects": "1",
                },
            )
        except RuntimeError:
            parsed = {}

        parse_obj = parsed.get("parse") or {}
        sections = parse_obj.get("sections") or []
        meta.sections = len(sections)
        wikitext_obj = parse_obj.get("wikitext") or {}
        wikitext = wikitext_obj.get("*", "") if isinstance(wikitext_obj, dict) else ""
        meta.refs = _count_refs(wikitext)

        return meta

    async def fetch_article_meta(
        self, qid: str, en_title: str, ja_title: str
    ) -> ArticleMeta:
        en, ja = await asyncio.gather(
            self.fetch_lang_meta("en", en_title),
            self.fetch_lang_meta("ja", ja_title),
        )
        return ArticleMeta(qid=qid, en=en, ja=ja)


_REF_PATTERNS = [
    re.compile(r"<ref\b", re.IGNORECASE),       # inline <ref> / <ref name=.../> / <ref name=...>...</ref>
    re.compile(r"\{\{sfn\b", re.IGNORECASE),    # {{sfn|Author|Year|p=...}} short footnote
    re.compile(r"\{\{sfnp\b", re.IGNORECASE),   # {{sfnp|...}} variant
    re.compile(r"\{\{r\|", re.IGNORECASE),      # {{r|name}} list-defined-references macro
    re.compile(r"\{\{harv\b", re.IGNORECASE),   # {{harv}} / {{harvnb}} variants
]


def _count_refs(wikitext: str) -> int:
    """
    本文中の citation 数を素朴にカウント。

    対象パターン:
      - <ref ...> 系 (en/ja で最もポピュラー)
      - {{sfn|...}} {{sfnp|...}} (short footnote, en で多い)
      - {{r|name}} (list-defined-references macro)
      - {{harv|...}} {{harvnb|...}} (Harvard 参照)

    完璧な数ではないが、ja/en 比較用には十分。
    """
    if not wikitext:
        return 0
    return sum(len(p.findall(wikitext)) for p in _REF_PATTERNS)


async def _smoke() -> int:
    """単体動作確認: 1 記事だけ叩く。"""
    qid = "Q11085"  # Parkinson's disease
    en_title = "Parkinson's disease"
    ja_title = "パーキンソン病"
    async with MediaWikiClient() as client:
        meta = await client.fetch_article_meta(qid, en_title, ja_title)
        print(f"qid={meta.qid}")
        print(f"  en: title={meta.en.title!r} bytes={meta.en.bytes_} "
              f"sections={meta.en.sections} refs={meta.en.refs} "
              f"images={meta.en.images} last_edit={meta.en.last_edit}")
        print(f"  ja: title={meta.ja.title!r} bytes={meta.ja.bytes_} "
              f"sections={meta.ja.sections} refs={meta.ja.refs} "
              f"images={meta.ja.images} last_edit={meta.ja.last_edit}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_smoke()))

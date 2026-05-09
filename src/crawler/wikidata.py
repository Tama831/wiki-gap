"""
Wikidata SPARQL から医学系 seed QID を取得する。

カテゴリ:
  - disease   : Q12136 (disease) の subclass-of (P279) transitive 配下
  - drug      : Q12140 (medication) の subclass-of transitive 配下
  - procedure : Q796194 (medical procedure) の subclass-of transitive 配下

Wikimedia エチケット遵守:
  - User-Agent に GitHub リポ URL を明記
  - SPARQL 1 クエリで取得 (高負荷ではない)
  - failure 時は exponential backoff で最大 3 回リトライ

使い方:
  python -m src.crawler.wikidata --category disease --limit 100
  python -m src.crawler.wikidata --category disease           # 上限なし
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent

# 医学カテゴリの root QID
CATEGORY_ROOTS: dict[str, str] = {
    "disease": "Q12136",     # disease
    "drug": "Q12140",        # medication
    "procedure": "Q796194",  # medical procedure
}


@dataclass
class SeedItem:
    qid: str
    category: str
    en_label: str | None = None
    ja_label: str | None = None
    en_title: str | None = None  # URL-decoded Wikipedia title (en)
    ja_title: str | None = None  # URL-decoded Wikipedia title (ja)

    @property
    def has_en_sitelink(self) -> bool:
        return bool(self.en_title)

    @property
    def has_ja_sitelink(self) -> bool:
        return bool(self.ja_title)


def _title_from_sitelink(uri: str, lang: str) -> str:
    """
    sitelink URI (例: https://en.wikipedia.org/wiki/Parkinson%27s_disease) から
    記事タイトル ("Parkinson's disease") を取り出す。
    """
    prefix = f"https://{lang}.wikipedia.org/wiki/"
    if not uri.startswith(prefix):
        return ""
    raw = uri[len(prefix):]
    # underscore → space, percent-decode
    return unquote(raw).replace("_", " ")


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


def _sparql_endpoint() -> str:
    return os.getenv("WIKIDATA_SPARQL_ENDPOINT", "https://query.wikidata.org/sparql")


def _build_query(root_qid: str, limit: int | None) -> str:
    """
    指定 root QID の配下にある item を取得する。

    パターン: ?item wdt:P31/wdt:P279* wd:<root>
      = item は X の instance であり、X は <root> の transitive subclass

    sitelinks フィルタ: 英語版か日本語版のいずれかに記事がある item に絞る
    (両方無い item は意味がない)。

    Note:
      SERVICE wikibase:label は外して直接 rdfs:label を使う
      (高負荷時に label service が timeout する事があるため)。
    """
    limit_clause = f"LIMIT {int(limit)}" if limit is not None else ""
    return f"""
SELECT DISTINCT ?item ?enLabel ?jaLabel ?enSitelink ?jaSitelink WHERE {{
  ?item wdt:P31/wdt:P279* wd:{root_qid} .

  OPTIONAL {{
    ?enSitelink schema:about ?item ;
                schema:isPartOf <https://en.wikipedia.org/> .
  }}
  OPTIONAL {{
    ?jaSitelink schema:about ?item ;
                schema:isPartOf <https://ja.wikipedia.org/> .
  }}
  FILTER(BOUND(?enSitelink) || BOUND(?jaSitelink))

  OPTIONAL {{ ?item rdfs:label ?enLabel . FILTER(LANG(?enLabel) = "en") }}
  OPTIONAL {{ ?item rdfs:label ?jaLabel . FILTER(LANG(?jaLabel) = "ja") }}
}}
{limit_clause}
""".strip()


def fetch_seeds(
    category: str,
    limit: int | None = 100,
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
) -> list[SeedItem]:
    if category not in CATEGORY_ROOTS:
        raise ValueError(
            f"unknown category: {category!r} (expected one of {list(CATEGORY_ROOTS)})"
        )

    root_qid = CATEGORY_ROOTS[category]
    query = _build_query(root_qid, limit)
    endpoint = _sparql_endpoint()
    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/sparql-results+json",
    }

    last_error: Exception | None = None
    payload: dict | None = None
    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.post(
                    endpoint,
                    data={"query": query, "format": "json"},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
                break
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                # WDQS recommends >=5s backoff on errors
                delay = 5 * (2**attempt)
                print(
                    f"[wikidata] attempt {attempt + 1}/{max_retries} failed: {exc}. "
                    f"sleeping {delay}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
            else:
                raise

    if payload is None:
        raise RuntimeError("SPARQL fetch did not produce a payload") from last_error

    bindings = payload.get("results", {}).get("bindings", [])
    seeds: list[SeedItem] = []
    seen_qids: set[str] = set()

    for row in bindings:
        item_uri = row.get("item", {}).get("value", "")
        qid = item_uri.rsplit("/", 1)[-1] if item_uri else ""
        if not qid or qid in seen_qids:
            continue
        seen_qids.add(qid)

        en_label = row.get("enLabel", {}).get("value")
        ja_label = row.get("jaLabel", {}).get("value")
        en_sitelink_uri = row.get("enSitelink", {}).get("value")
        ja_sitelink_uri = row.get("jaSitelink", {}).get("value")

        en_title = _title_from_sitelink(en_sitelink_uri, "en") if en_sitelink_uri else None
        ja_title = _title_from_sitelink(ja_sitelink_uri, "ja") if ja_sitelink_uri else None

        seeds.append(
            SeedItem(
                qid=qid,
                category=category,
                en_label=en_label,
                ja_label=ja_label,
                en_title=en_title,
                ja_title=ja_title,
            )
        )

    return seeds


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--category",
        choices=list(CATEGORY_ROOTS),
        default="disease",
        help="医学カテゴリ (default: disease)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="取得上限 (0 で無制限)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON で標準出力に書き出す",
    )
    args = parser.parse_args(argv)

    limit: int | None = args.limit if args.limit > 0 else None

    print(
        f"[wikidata] category={args.category} root={CATEGORY_ROOTS[args.category]} "
        f"limit={limit if limit is not None else 'unlimited'}"
    )
    print(f"[wikidata] User-Agent: {_user_agent()}")

    started = time.time()
    seeds = fetch_seeds(args.category, limit=limit)
    elapsed = time.time() - started

    en_only = sum(1 for s in seeds if s.has_en_sitelink and not s.has_ja_sitelink)
    ja_only = sum(1 for s in seeds if s.has_ja_sitelink and not s.has_en_sitelink)
    both = sum(1 for s in seeds if s.has_en_sitelink and s.has_ja_sitelink)

    print(f"[wikidata] fetched {len(seeds)} seeds in {elapsed:.2f}s")
    print(f"[wikidata]   both en+ja : {both}")
    print(f"[wikidata]   en only    : {en_only}")
    print(f"[wikidata]   ja only    : {ja_only}")

    if args.json:
        payload = [
            {
                "qid": s.qid,
                "category": s.category,
                "en_label": s.en_label,
                "ja_label": s.ja_label,
                "has_en": s.has_en_sitelink,
                "has_ja": s.has_ja_sitelink,
            }
            for s in seeds
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\nfirst 10:")
        for s in seeds[:10]:
            mark = ("E" if s.has_en_sitelink else "-") + ("J" if s.has_ja_sitelink else "-")
            print(f"  [{mark}] {s.qid:>10} | en={s.en_label!s:<40.40} | ja={s.ja_label!s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

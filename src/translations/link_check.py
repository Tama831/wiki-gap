"""
ja Wikipedia リンクチェッカー: 訳文中の `[[link]]` を抽出して
ja Wikipedia に該当記事があるか確認し、無いものは英語版へ
の interwiki link 候補を提案する。

ロジック:
  1. dst 中の `[[target|display]]` または `[[target]]` を抽出
  2. すでに `[[:en:foo]]` `[[:meta:foo]]` 等の interwiki 形式は skip
  3. ja.wikipedia.org の MediaWiki API で複数 title 一括存在確認
  4. ja に無い title については、対応する英語タイトル候補を:
     a. 同じ chunk の en src 中に同じ位置の `[[Foo]]` リンクがあれば、それを en title に採用
     b. なければ display 文字列を en title 候補にする (素朴だが多くは合う)
  5. en.wikipedia.org でも存在確認
  6. 結果: link, ja_exists, en_exists, suggested_replacement
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache

import httpx

from src.translations.term_check import load_dictionary as _load_term_dict

WIKILINK_RE = re.compile(r"\[\[(?P<target>[^\[\]|\n]+?)(?:\|(?P<display>[^\[\]\n]+?))?\]\]")
ANNOTATED_LINK_RE = re.compile(r"\{\{annotated link\s*\|\s*(?P<target>[^|}\n]+?)\s*(?:\|[^}]*)?\}\}", re.IGNORECASE)
INTERWIKI_RE = re.compile(r"^:?(en|de|fr|zh|ko|es|meta|mw|wikt|commons|wikidata|d|q):", re.IGNORECASE)


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


@lru_cache(maxsize=1)
def _ja_to_en_map() -> dict[str, str]:
    """
    term_dictionary.json から ja → en の逆引きマップを作る。
    例: 自己定量化 → quantified self
    """
    out: dict[str, str] = {}
    terms = _load_term_dict().get("terms", {})
    for canonical_en, entry in terms.items():
        ja = entry.get("ja")
        if ja:
            out.setdefault(ja, canonical_en)
        for ja_alias in entry.get("ja_aliases") or []:
            out.setdefault(ja_alias, canonical_en)
    return out


def _capitalize_en_title(en: str) -> str:
    """Wikipedia 慣行: 記事タイトルは先頭大文字。"""
    if not en:
        return en
    return en[0].upper() + en[1:]


@dataclass
class LinkRef:
    chunk_id: int
    target: str        # dst で見つかったリンク先 (例: "group comparison study")
    display: str       # 表示テキスト (例: "群間比較試験")
    ja_exists: bool = False
    en_candidate: str | None = None
    en_exists: bool = False
    suggested: str | None = None  # 置換後のリンク wikitext

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "target": self.target,
            "display": self.display,
            "ja_exists": self.ja_exists,
            "en_candidate": self.en_candidate,
            "en_exists": self.en_exists,
            "suggested": self.suggested,
            "is_redlink": (not self.ja_exists),
        }


def extract_links(text: str) -> list[tuple[str, str, int, int]]:
    """
    text 内のリンクを抽出する。`[[...]]` と `{{annotated link|...}}` の両方を対象に。
    返り値: [(target, display, start, end), ...]
    interwiki / File:/Image: / フラグメントは skip。
    """
    results = []
    for m in WIKILINK_RE.finditer(text):
        target = (m.group("target") or "").strip()
        display = (m.group("display") or target).strip()
        if not target:
            continue
        if INTERWIKI_RE.match(target):
            continue
        if re.match(r"^(File|Image|Category|画像|ファイル|カテゴリ):", target, re.IGNORECASE):
            continue
        if target.startswith("#"):
            continue
        results.append((target, display, m.start(), m.end()))
    # {{annotated link|term}} 形式 (関連項目セクションでよく使われる)
    for m in ANNOTATED_LINK_RE.finditer(text):
        target = (m.group("target") or "").strip()
        if not target:
            continue
        # display は target と同じ扱い
        results.append((target, target, m.start(), m.end()))
    return results


def _check_titles_exist(client: httpx.Client, lang: str, titles: list[str]) -> dict[str, bool]:
    """
    複数タイトルの存在チェック (MediaWiki batch API)。
    返り値: {正規化タイトル: True/False}
    titles が大文字小文字違い等は normalized にマージされる。
    """
    if not titles:
        return {}
    api = f"https://{lang}.wikipedia.org/w/api.php"
    out: dict[str, bool] = {}
    # MediaWiki API: titles= は最大 50 件まで (anon)。一応 chunk して安全に。
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "format": "json",
            "redirects": "1",
            "maxlag": "30",
        }
        r = client.get(api, params=params)
        if r.status_code >= 400:
            continue
        try:
            payload = r.json()
        except Exception:
            continue

        # normalized name mapping (input → normalized)
        normalized_map: dict[str, str] = {}
        for n in (payload.get("query") or {}).get("normalized") or []:
            normalized_map[n.get("from", "")] = n.get("to", "")
        for r_ in (payload.get("query") or {}).get("redirects") or []:
            normalized_map[r_.get("from", "")] = r_.get("to", "")

        pages = (payload.get("query") or {}).get("pages") or {}
        existing_normalized: set[str] = set()
        for _, p in pages.items():
            if "missing" in p:
                continue
            existing_normalized.add(p.get("title", ""))

        # 入力タイトルごとに判定
        for t in chunk:
            normalized = normalized_map.get(t, t)
            out[t] = normalized in existing_normalized
    return out


def check_chunks(chunks: list[dict]) -> dict:
    """
    全 chunks の dst を見て、ja Wikipedia 上の wikilink について
    存在チェック + en へのフォールバック候補を返す。
    """
    refs: list[LinkRef] = []

    for ch in chunks:
        cid = int(ch.get("id", -1))
        dst = ch.get("dst", "") or ""
        en_src = ch.get("src", "") or ""
        if not dst.strip():
            continue

        # dst 中の wikilink
        dst_links = extract_links(dst)
        if not dst_links:
            continue

        # en src 中の wikilink もマップを作る (display → target)
        # 「ja の display と一致する en target」を見つけるためのヒント
        en_links = extract_links(en_src)
        en_target_by_display: dict[str, str] = {}
        for tgt, disp, _, _ in en_links:
            en_target_by_display.setdefault(disp.lower(), tgt)
            en_target_by_display.setdefault(tgt.lower(), tgt)

        ja2en = _ja_to_en_map()

        for target, display, _, _ in dst_links:
            ref = LinkRef(chunk_id=cid, target=target, display=display)
            # en candidate の推定 (優先順位):
            # (a) target が英語ならそれを採用
            # (b) term_dictionary 逆引き: ja の target / display → en
            # (c) en src で同 display の target があればそれを使う (位置一致)
            # (d) 英語 display があればそれ
            if re.match(r"^[A-Za-z][A-Za-z0-9 \-'(),\.]+$", target):
                ref.en_candidate = _capitalize_en_title(target)
            elif target in ja2en:
                ref.en_candidate = _capitalize_en_title(ja2en[target])
            elif display in ja2en:
                ref.en_candidate = _capitalize_en_title(ja2en[display])
            elif display.lower() in en_target_by_display:
                ref.en_candidate = _capitalize_en_title(en_target_by_display[display.lower()])
            elif target.lower() in en_target_by_display:
                ref.en_candidate = _capitalize_en_title(en_target_by_display[target.lower()])
            elif re.match(r"^[A-Za-z][A-Za-z0-9 \-'(),\.]+$", display):
                ref.en_candidate = _capitalize_en_title(display)
            refs.append(ref)

    # ja の存在チェック (重複排除して 1 回でまとめる)
    ja_titles = sorted({r.target for r in refs})
    en_titles = sorted({r.en_candidate for r in refs if r.en_candidate})

    headers = {"User-Agent": _user_agent()}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        ja_existence = _check_titles_exist(client, "ja", ja_titles)
        en_existence = _check_titles_exist(client, "en", en_titles)

    for r in refs:
        r.ja_exists = ja_existence.get(r.target, False)
        if r.en_candidate:
            r.en_exists = en_existence.get(r.en_candidate, False)
        # suggested replacement: ja Wikipedia 標準慣行に従い {{仮リンク}} を使う。
        # {{仮リンク|<日本語表示>|en|<英語タイトル>}}
        # → ja に該当記事があればそれにリンク、無ければ「<日本語表示>（英語版）」と表示
        #   して英語版にリンク。将来 ja 記事が作られたら自動で青リンク化される。
        if not r.ja_exists and r.en_candidate and r.en_exists:
            r.suggested = f"{{{{仮リンク|{r.display}|en|{r.en_candidate}}}}}"
        elif not r.ja_exists and r.en_candidate and not r.en_exists:
            r.suggested = None
        elif r.ja_exists:
            r.suggested = None

    total = len(refs)
    redlinks = [r for r in refs if not r.ja_exists]
    fixable = [r for r in redlinks if r.suggested]

    return {
        "total_links": total,
        "ja_existing": total - len(redlinks),
        "redlinks": len(redlinks),
        "fixable": len(fixable),
        "links": [r.to_dict() for r in refs],
    }


_BARE_INTERWIKI_RE = re.compile(
    r"\[\[:(?P<lang>en|de|fr|zh|ko|es):(?P<target>[^\[\]|\n]+?)(?:\|(?P<display>[^\[\]\n]+?))?\]\]"
)


def upgrade_bare_interwiki_to_karilink(chunks: list[dict]) -> tuple[list[dict], int]:
    """
    `[[:en:Foo|表示]]` 形式の interwiki link を `{{仮リンク|表示|en|Foo}}` に
    アップグレードする。ja Wikipedia の標準慣行に従い、表示には自動的に
    「（英語版）」が付き、ja 側に同名記事ができたら自動で青リンク化される。
    """
    n_changed = 0
    new_chunks = []
    for ch in chunks:
        ch = dict(ch)
        dst = ch.get("dst", "") or ""

        def _replace(m: re.Match) -> str:
            nonlocal n_changed
            lang = m.group("lang")
            target = (m.group("target") or "").strip()
            display = (m.group("display") or target).strip()
            if not target:
                return m.group(0)
            n_changed += 1
            return f"{{{{仮リンク|{display}|{lang}|{target}}}}}"

        ch["dst"] = _BARE_INTERWIKI_RE.sub(_replace, dst)
        new_chunks.append(ch)
    return new_chunks, n_changed


def apply_interwiki_fix(chunks: list[dict]) -> tuple[list[dict], int]:
    """
    chunks の dst にある赤リンクを `[[:en:Foo|display]]` 形式に書き換える。
    返り値: (新しい chunks, 置換件数)
    """
    result = check_chunks(chunks)
    suggestions = {(c["chunk_id"], c["target"], c["display"]): c["suggested"]
                   for c in result["links"] if c.get("suggested")}
    if not suggestions:
        return chunks, 0

    n_changed = 0
    new_chunks = []
    for ch in chunks:
        ch = dict(ch)
        cid = int(ch.get("id", -1))
        dst = ch.get("dst", "") or ""

        def _replace_wikilink(m: re.Match) -> str:
            nonlocal n_changed
            target = (m.group("target") or "").strip()
            display = (m.group("display") or target).strip()
            sugg = suggestions.get((cid, target, display))
            if sugg:
                n_changed += 1
                return sugg
            return m.group(0)

        def _replace_annotated(m: re.Match) -> str:
            nonlocal n_changed
            target = (m.group("target") or "").strip()
            sugg = suggestions.get((cid, target, target))
            if sugg:
                n_changed += 1
                # annotated link → 通常 list item で仮リンク
                return sugg
            return m.group(0)

        new_dst = WIKILINK_RE.sub(_replace_wikilink, dst)
        new_dst = ANNOTATED_LINK_RE.sub(_replace_annotated, new_dst)
        ch["dst"] = new_dst
        new_chunks.append(ch)

    return new_chunks, n_changed

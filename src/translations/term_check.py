"""
医学用語チェッカー: en src 中の専門用語を抽出 + ja dst で適切な訳語が使われているか判定。

辞書: term_dictionary.json (MeSH / 日本医学会医学用語辞典 / ja Wikipedia 慣行)

判定ロジック:
  1. 各 chunk の en src から、辞書の英語 lemma + aliases にヒットする語を抽出 (大文字小文字無視, word-boundary)
  2. 同じ chunk の ja dst で、辞書が指定する標準 ja 訳が含まれているか確認
  3. 含まれていれば ✅ matched
     含まれていなければ ⚠ not_found ("辞書の標準訳と異なる訳語を使っている可能性")
  4. en src に該当用語が出てこなければ skip
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DICT_PATH = Path(__file__).parent / "term_dictionary.json"

# 出典 / テンプレート / リンクラベルなど、用語検出の対象外にしたい部分をマスクする
_REF_TAG_RE = re.compile(r"<ref\b[^>]*>.*?</ref>|<ref\b[^/]*/>", re.DOTALL | re.IGNORECASE)
_CITE_TEMPLATE_RE = re.compile(r"\{\{(cite|citation|sfn|harv|refbegin|refend|reflist|r\|)[^}]*?\}\}", re.IGNORECASE | re.DOTALL)


def _strip_noise(text: str) -> str:
    """出典タグ / cite テンプレートを取り除いた本文テキストを返す。"""
    text = _REF_TAG_RE.sub(" ", text)
    text = _CITE_TEMPLATE_RE.sub(" ", text)
    return text


@lru_cache(maxsize=1)
def load_dictionary() -> dict:
    with open(DICT_PATH, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class TermHit:
    en_term: str            # 英語 src で見つかった文字列
    canonical_en: str       # 辞書での見出し語 (lower-case)
    expected_ja: str        # 辞書の推奨 ja 訳
    sources: list[str]      # 出典 (MeSH:Dxxx 等)
    found_in_dst: bool      # ja dst にこの訳語が含まれていたか


@dataclass
class ChunkCheck:
    chunk_id: int
    hits: list[TermHit] = field(default_factory=list)

    @property
    def n_total(self) -> int:
        return len(self.hits)

    @property
    def n_matched(self) -> int:
        return sum(1 for h in self.hits if h.found_in_dst)

    @property
    def n_missing(self) -> int:
        return sum(1 for h in self.hits if not h.found_in_dst)


def _build_term_patterns() -> list[tuple[str, str, dict]]:
    """
    [(英語 lemma 候補文字列, 標準 lemma, dict_entry)] のリストを返す。
    aliases も含む。
    """
    d = load_dictionary().get("terms", {})
    patterns: list[tuple[str, str, dict]] = []
    for canonical, entry in d.items():
        candidates = [canonical] + list(entry.get("aliases") or [])
        # 長いものを先にマッチさせる (例: "randomized controlled trial" > "trial")
        for c in sorted(set(candidates), key=lambda x: -len(x)):
            patterns.append((c, canonical, entry))
    return patterns


def check_chunk(chunk_id: int, en_src: str, ja_dst: str,
                *, chunk_type: str = "para") -> ChunkCheck:
    """
    1 chunk について en src 中の医学用語を辞書とマッチさせ、
    各用語について ja dst に標準訳が含まれるかチェックする。

    chunk_type:
      "para"    : 通常の段落 (チェック対象)
      "heading" : 見出しのみ → スキップ
      "block"   : table / refbegin..refend など → スキップ (false positive 多い)
    """
    result = ChunkCheck(chunk_id=chunk_id)
    if not en_src or chunk_type in {"heading", "block"}:
        return result

    # 出典 / cite テンプレを除いた本文だけを検査対象に
    en_src_clean = _strip_noise(en_src)
    ja_dst_clean = _strip_noise(ja_dst or "")

    patterns = _build_term_patterns()
    seen_canonical: set[str] = set()

    for cand, canonical, entry in patterns:
        if canonical in seen_canonical:
            continue
        regex = re.compile(r"\b" + re.escape(cand) + r"\b", re.IGNORECASE)
        m = regex.search(en_src_clean)
        if not m:
            continue
        seen_canonical.add(canonical)
        expected_ja = entry["ja"]
        ja_aliases = entry.get("ja_aliases") or []
        # expected_ja か任意の ja_alias が ja_dst に含まれていれば OK
        ja_candidates = [expected_ja] + ja_aliases
        found = any(c in ja_dst_clean for c in ja_candidates if c)
        result.hits.append(TermHit(
            en_term=m.group(0),
            canonical_en=canonical,
            expected_ja=expected_ja,
            sources=entry.get("sources") or [],
            found_in_dst=found,
        ))

    return result


def check_all_chunks(chunks: list[dict]) -> dict:
    """
    全 chunks をチェック。
    返り値: {
      "total_terms": int,
      "matched": int,
      "missing": int,
      "by_chunk": {chunk_id: {"hits": [...]}},
      "summary": [{en, ja, found, sources}]
    }
    """
    by_chunk: dict[int, dict] = {}
    total = 0
    matched = 0
    summary: list[dict] = []

    for ch in chunks:
        cid = int(ch.get("id", -1))
        en_src = ch.get("src", "") or ""
        ja_dst = ch.get("dst", "") or ""
        ctype = ch.get("type", "para")
        cc = check_chunk(cid, en_src, ja_dst, chunk_type=ctype)
        if not cc.hits:
            continue
        by_chunk[cid] = {
            "n_total": cc.n_total,
            "n_matched": cc.n_matched,
            "n_missing": cc.n_missing,
            "hits": [
                {
                    "en": h.en_term,
                    "canonical_en": h.canonical_en,
                    "expected_ja": h.expected_ja,
                    "found_in_dst": h.found_in_dst,
                    "sources": h.sources,
                }
                for h in cc.hits
            ],
        }
        total += cc.n_total
        matched += cc.n_matched
        for h in cc.hits:
            summary.append({
                "chunk_id": cid,
                "en": h.en_term,
                "expected_ja": h.expected_ja,
                "found": h.found_in_dst,
                "sources": h.sources,
            })

    return {
        "total_terms": total,
        "matched": matched,
        "missing": total - matched,
        "by_chunk": by_chunk,
        "summary": summary,
    }

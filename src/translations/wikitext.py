"""
Wikitext を section heading で分割する。

各 chunk:
  id: 0-indexed 番号
  level: 0 (intro / 見出し前) or 2..6 (=== ...===)
  heading: 見出し文字 ("Background" 等)、intro は "(intro)"
  src: その chunk の wikitext (見出し行を含む)
  dst: 訳文 (初期値 "")

Note: paragraph 単位の細かい分割はしない (Phase 2A.5 で増分実装)。
      最初は heading 単位で同期するだけで十分実用的。
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ^==..== ... ==..==$ (空白許容、level 2-6)
HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


@dataclass
class Chunk:
    id: int
    level: int          # 0 = intro before any heading; else 2..6
    heading: str        # "(intro)" if level == 0
    src: str            # original en wikitext for this chunk
    dst: str = ""       # ja translation

    def to_dict(self) -> dict:
        return asdict(self)


def parse_sections(wikitext: str) -> list[Chunk]:
    """
    wikitext を heading 単位で分割。

    Returns:
      list[Chunk] (id 順)。空リストにはしない (intro chunk が最低 1 つは入る)。
    """
    if not wikitext:
        return [Chunk(id=0, level=0, heading="(intro)", src="", dst="")]

    matches = list(HEADING_RE.finditer(wikitext))
    chunks: list[Chunk] = []

    if not matches:
        # 見出しが 1 つもない wikitext (短い記事) は全体を 1 chunk
        return [Chunk(id=0, level=0, heading="(intro)", src=wikitext, dst="")]

    # intro: 最初の heading より前
    first_heading_start = matches[0].start()
    intro_text = wikitext[:first_heading_start]
    if intro_text.strip():
        chunks.append(
            Chunk(id=0, level=0, heading="(intro)", src=intro_text, dst="")
        )

    # 各 section: heading 行を含み、次の heading 直前まで
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        section_text = wikitext[start:end]
        chunks.append(
            Chunk(
                id=len(chunks),
                level=level,
                heading=heading,
                src=section_text,
                dst="",
            )
        )

    return chunks


def chunks_to_wikitext(chunks: list[dict]) -> str:
    """
    全 chunks の `dst` を連結して 1 つの wikitext にする (export 用)。

    空の dst は skip する (= まだ訳してないセクションは出力されない)。
    src の見出しは dst が空でも残したい場合は別 path を作る。
    """
    parts: list[str] = []
    for ch in chunks:
        dst = (ch.get("dst") or "").rstrip()
        if not dst:
            continue
        # heading section の dst が "" でなければそのまま出す。
        # ユーザは dst に heading を含めて書く想定 (e.g. == 背景 ==\n本文)
        parts.append(dst)
    return "\n\n".join(parts) + "\n"


def chunks_to_wikitext_with_skeleton(chunks: list[dict]) -> str:
    """
    export 第二モード: 未訳 section も skeleton (heading のみ + コメント) で出す。
    人間が編集を続けやすい体裁。
    """
    parts: list[str] = []
    for ch in chunks:
        level = ch.get("level", 0)
        heading = ch.get("heading", "")
        dst = (ch.get("dst") or "").rstrip()
        if dst:
            parts.append(dst)
        else:
            if level == 0:
                # intro 未訳
                parts.append("<!-- TODO: introduction (未訳) -->")
            else:
                marks = "=" * level
                parts.append(f"{marks} {heading} {marks}\n<!-- TODO: 未訳 -->")
    return "\n\n".join(parts) + "\n"

"""
Wikitext を section heading + 段落で分割する (Phase 2A.5)。

各 chunk:
  id: 0-indexed 通し番号
  type: 'heading' (=見出し行のみ) | 'para' (=段落本文) | 'block' (=表/リスト/template ブロック)
  section_id: 親 section の通し番号 (intro = 0)
  section_heading: "(intro)" / "Design" など
  section_level: 0 (intro) or 2..6
  src: その chunk の wikitext
  dst: 訳文 (初期値 "")

設計:
  - 見出し行 (`== Design ==`) は単独の heading chunk として扱う
    (見出し自体を訳すため、独立した textarea が要る)
  - 段落本文は空行 (\\n\\s*\\n) で区切る → para chunk
  - {| ... |} (表), <gallery>...</gallery>, {{reflist}}, {{refbegin}}..{{refend}}
    などの複数行ブロックは分割せず block chunk として 1 塊にする
  - {{annotated link|...}} だけが並ぶ See also も 1 段落扱いにできるよう
    箇条書きは block 扱いにする
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# ^==..== ... ==..==$ (空白許容、level 2-6)
HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)


@dataclass
class Chunk:
    id: int
    type: str           # 'heading' | 'para' | 'block'
    section_id: int
    section_heading: str
    section_level: int
    src: str
    dst: str = ""
    # 後方互換 (古いテンプレート/エクスポート用)
    level: int = 0      # = section_level
    heading: str = ""   # = section_heading

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def parse_sections(wikitext: str) -> list[Chunk]:
    """
    Phase 2A 旧版: wikitext を heading 単位だけで分割 (1 section = 1 chunk)。
    新コードは parse_paragraphs を使うこと。後方互換用に残す。
    """
    if not wikitext:
        return [Chunk(id=0, type="para", section_id=0,
                      section_heading="(intro)", section_level=0,
                      level=0, heading="(intro)", src="", dst="")]
    matches = list(HEADING_RE.finditer(wikitext))
    chunks: list[Chunk] = []
    if not matches:
        return [Chunk(id=0, type="para", section_id=0,
                      section_heading="(intro)", section_level=0,
                      level=0, heading="(intro)", src=wikitext, dst="")]
    first_heading_start = matches[0].start()
    intro_text = wikitext[:first_heading_start]
    if intro_text.strip():
        chunks.append(Chunk(
            id=0, type="para", section_id=0,
            section_heading="(intro)", section_level=0,
            level=0, heading="(intro)", src=intro_text, dst="",
        ))
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        section_text = wikitext[start:end]
        sid = len(chunks)
        chunks.append(Chunk(
            id=sid, type="para", section_id=sid,
            section_heading=heading, section_level=level,
            level=level, heading=heading, src=section_text, dst="",
        ))
    return chunks


# ── 新パーサー: 段落単位 ────────────────────────────────────────────

# 開始マーカー → そのブロックを 1 塊として扱う閉じパターン
# Wikitext の表 / template / gallery 等は段落分割するとマークアップが壊れる
BLOCK_PATTERNS: list[tuple[re.Pattern, re.Pattern]] = [
    # {| ... |}  wikitable (ネスト未対応、N-of-1 trial 程度の単純構造で OK)
    (re.compile(r"^\{\|", re.MULTILINE), re.compile(r"^\|\}", re.MULTILINE)),
    # <gallery> ... </gallery>
    (re.compile(r"<gallery\b", re.IGNORECASE), re.compile(r"</gallery>", re.IGNORECASE)),
    # <math> ... </math>
    (re.compile(r"<math\b", re.IGNORECASE), re.compile(r"</math>", re.IGNORECASE)),
]


def _split_section_body(body: str) -> list[tuple[str, str]]:
    """
    section の本文 (heading 行を除く) を段落 / ブロックに分割。
    返り値: [(type, text), ...]  type は 'para' | 'block'

    分割ルール:
      - {| ... |}, <gallery>, <math> などの複数行ブロックはまるごと 1 塊
      - その他は空行 (連続改行) で段落分割
      - 単独行で {{reflist}} / {{refbegin}}...{{refend}} / [[Category:..]] / [[File:..]] /
        {{DEFAULTSORT:..}} なども独立 chunk 扱い (誤って段落結合しない)
    """
    if not body or not body.strip():
        return []

    # まず block 領域を切り出す (位置を記録)
    spans: list[tuple[int, int, str]] = []  # (start, end, type)
    for open_re, close_re in BLOCK_PATTERNS:
        cursor = 0
        while True:
            mo = open_re.search(body, cursor)
            if not mo:
                break
            start = mo.start()
            mc = close_re.search(body, mo.end())
            if not mc:
                # 閉じが見つからなければ末尾までブロック扱い
                spans.append((start, len(body), "block"))
                cursor = len(body)
                break
            spans.append((start, mc.end(), "block"))
            cursor = mc.end()

    spans.sort()
    # 重複/包含を素朴に解消 (start でソート済、後続 span が前と被るなら捨てる)
    merged: list[tuple[int, int, str]] = []
    for s, e, t in spans:
        if merged and s < merged[-1][1]:
            continue
        merged.append((s, e, t))

    # 残りの領域を段落分割 (空行で split)
    pieces: list[tuple[str, str]] = []
    last = 0
    for s, e, t in merged:
        if last < s:
            pieces.extend(_split_paragraphs(body[last:s]))
        pieces.append((t, body[s:e]))
        last = e
    if last < len(body):
        pieces.extend(_split_paragraphs(body[last:]))
    return pieces


# {{refbegin}}..{{refend}} は 1 ブロック扱い
_REFBLOCK_RE = re.compile(r"\{\{refbegin\}\}.*?\{\{refend\}\}", re.IGNORECASE | re.DOTALL)


def _split_paragraphs(text: str) -> list[tuple[str, str]]:
    """空行区切りで段落分割。空段落は除外。
    {{refbegin}}..{{refend}} はブロック扱い。"""
    if not text or not text.strip():
        return []

    out: list[tuple[str, str]] = []

    # まず {{refbegin}}..{{refend}} を block として切り出し、残りは段落 split
    cursor = 0
    for mo in _REFBLOCK_RE.finditer(text):
        if cursor < mo.start():
            out.extend(_split_paragraphs_simple(text[cursor:mo.start()]))
        out.append(("block", text[mo.start():mo.end()]))
        cursor = mo.end()
    if cursor < len(text):
        out.extend(_split_paragraphs_simple(text[cursor:]))
    return out


def _split_paragraphs_simple(text: str) -> list[tuple[str, str]]:
    """単純な空行区切り。連続する箇条書き (* / # 行) は 1 段落としてまとめる。"""
    out: list[tuple[str, str]] = []
    if not text or not text.strip():
        return out
    # 空行 = 改行を 2 つ以上含む区切り
    raw_paragraphs = re.split(r"\n\s*\n", text)
    for p in raw_paragraphs:
        if not p.strip():
            continue
        # 完全にマークアップ行のみ ([[Category:..]] / {{DEFAULTSORT:..}} 等)
        # = block 扱い (訳文側でカテゴリを書き換えるため独立 textarea にしたい)
        if _is_metadata_only(p):
            out.append(("block", p))
        else:
            out.append(("para", p))
    return out


_METADATA_LINE_RE = re.compile(
    r"^\s*(\[\[(Category|File|Image):[^\]]+\]\]|\{\{DEFAULTSORT:[^}]+\}\}|"
    r"\{\{reflist\}\}|\{\{Authority control\}\})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _is_metadata_only(p: str) -> bool:
    lines = [ln for ln in p.splitlines() if ln.strip()]
    if not lines:
        return False
    return all(_METADATA_LINE_RE.match(ln) for ln in lines)


# ── en 専用テンプレートの剥がし (ja Wikipedia 翻訳前処理) ──

# ja Wikipedia で非推奨 / 不要な en 専用テンプレート
_EN_ONLY_TEMPLATES = [
    "short description",          # ja 非推奨 (en アプリ用の短い説明)
    "use dmy dates",              # en 用日付フォーマット指定
    "use mdy dates",              # 同上
    "use american english",       # en 用方言指定
    "use british english",        # 同上
    "use indian english",         # 同上
    "use canadian english",       # 同上
    "use australian english",     # 同上
    "use new zealand english",    # 同上
    "cs1 config",                 # 引用スタイル設定 (cs1)
    "good article",               # en の good article バッジ
    "featured article",           # en の featured article バッジ
    "pp-protected",               # en の保護バッジ
    "pp-semi",                    # 同上
    "pp-move",                    # 同上
    "pp-vandalism",               # 同上
]


def _build_strip_template_re() -> "re.Pattern[str]":
    names = "|".join(re.escape(n) for n in _EN_ONLY_TEMPLATES)
    # {{<name>}} or {{<name>|...}} (multi-line, ネストなしを仮定)
    return re.compile(
        r"\{\{\s*(?:" + names + r")\b[^{}]*?\}\}\s*\n?",
        re.IGNORECASE | re.DOTALL,
    )


_STRIP_TPL_RE = _build_strip_template_re()


def strip_en_only_templates(wikitext: str) -> tuple[str, list[str]]:
    """
    en 専用 / ja で不要なテンプレートを wikitext から取り除く。
    返り値: (clean_text, removed_template_strings)
    """
    if not wikitext:
        return wikitext, []
    removed: list[str] = []

    def _capture(m: re.Match) -> str:
        removed.append(m.group(0).strip())
        return ""

    cleaned = _STRIP_TPL_RE.sub(_capture, wikitext)
    return cleaned, removed


# ── 文単位 split (Phase 2A.6) ──────────────────────────────────────

# 文末記号の後の空白で split。<ref>...</ref> 内部の . は無視する必要がある
_REF_TAG_RE = re.compile(r"<ref\b[^>]*>.*?</ref>|<ref\b[^/]*/>", re.DOTALL | re.IGNORECASE)
_ELLIPSIS_RE = re.compile(r"\.\.\.|……?|…")
_JA_TERMINATORS = "。!？"
_EN_TERMINATORS = ".!?"
_CLOSING_QUOTES = "」』）)"


def _find_sentence_boundaries(text: str) -> list[int]:
    """
    text 中の「文の切れ目」位置リストを返す。

    切れ目の定義:
      - 日本語: 。 / ! / ？ の直後 (閉じ括弧の前は切れ目にしない)
      - 英語  : . / ! / ? の後にホワイトスペース (任意で <ref>...</ref> を間に挟んでよい)
      - 省略記号 (... / …) は文末扱いしない
      - <ref>...</ref> 内部の . は無視する
    返す int は「次の文が始まる位置」(= text[boundary:] が次の文)。
    """
    if not text:
        return []

    ref_spans = [(m.start(), m.end()) for m in _REF_TAG_RE.finditer(text)]
    ell_spans = [(m.start(), m.end()) for m in _ELLIPSIS_RE.finditer(text)]

    def in_span(pos: int, spans: list[tuple[int, int]]) -> tuple[int, int] | None:
        for s, e in spans:
            if s <= pos < e:
                return (s, e)
        return None

    boundaries: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        rs = in_span(i, ref_spans)
        if rs:
            i = rs[1]
            continue
        es = in_span(i, ell_spans)
        if es:
            i = es[1]
            continue

        c = text[i]
        if c in _JA_TERMINATORS:
            j = i + 1
            if j < n and text[j] in _CLOSING_QUOTES:
                i = j
                continue
            # Attach following <ref>..</ref> to the preceding sentence
            while j < n:
                rs = in_span(j, ref_spans)
                if rs and rs[0] == j:
                    j = rs[1]
                else:
                    break
            # Skip a single trailing whitespace if any (else the space starts next sentence)
            if j < n and text[j] == " ":
                j += 1
            boundaries.append(j)
            i = j
            continue
        if c in _EN_TERMINATORS:
            j = i + 1
            # 直後が ref タグなら、その先まで進める (ref を sentence 1 に含める)
            while j < n:
                rs = in_span(j, ref_spans)
                if rs and rs[0] == j:
                    j = rs[1]
                else:
                    break
            if j < n and text[j].isspace():
                while j < n and text[j].isspace():
                    j += 1
                boundaries.append(j)
                i = j
                continue
            i = j
            continue
        i += 1

    return boundaries


def split_into_sentences(text: str) -> list[str]:
    """段落内の wikitext を文のリストに分解する。"""
    if not text or not text.strip():
        return []
    bounds = _find_sentence_boundaries(text)
    parts: list[str] = []
    last = 0
    for b in bounds:
        if b <= last:
            continue
        parts.append(text[last:b])
        last = b
    if last < len(text):
        parts.append(text[last:])
    return [p.strip() for p in parts if p.strip()]


def parse_paragraphs(wikitext: str) -> list[Chunk]:
    """
    Phase 2A.5: 段落単位で分割する新パーサー。

    chunk 構造:
      heading 行: type='heading', src="== Design ==\\n"
      段落本文 : type='para'   , src="..."
      表/template/カテゴリ等: type='block', src=塊全体

    各 chunk は section_id と section_heading を持ち、UI 上で section
    ごとにグルーピングして表示できる。
    """
    chunks: list[Chunk] = []

    if not wikitext or not wikitext.strip():
        return [Chunk(
            id=0, type="para", section_id=0,
            section_heading="(intro)", section_level=0,
            level=0, heading="(intro)", src="", dst="",
        )]

    matches = list(HEADING_RE.finditer(wikitext))

    def add_chunks(section_id: int, section_heading: str, section_level: int,
                   pieces: list[tuple[str, str]]):
        for ptype, ptext in pieces:
            chunks.append(Chunk(
                id=len(chunks),
                type=ptype,
                section_id=section_id,
                section_heading=section_heading,
                section_level=section_level,
                level=section_level,
                heading=section_heading,
                src=ptext,
                dst="",
            ))

    # intro
    intro_end = matches[0].start() if matches else len(wikitext)
    intro_body = wikitext[:intro_end]
    if intro_body.strip():
        add_chunks(0, "(intro)", 0, _split_section_body(intro_body))

    # 各 section
    for i, m in enumerate(matches):
        level = len(m.group(1))
        heading = m.group(2)
        section_start = m.start()
        body_start = m.end()
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(wikitext)
        section_id = i + 1

        # heading 行自体を 1 chunk
        heading_line = wikitext[section_start:body_start]
        chunks.append(Chunk(
            id=len(chunks), type="heading",
            section_id=section_id,
            section_heading=heading, section_level=level,
            level=level, heading=heading,
            src=heading_line, dst="",
        ))

        body = wikitext[body_start:section_end]
        if body.strip():
            add_chunks(section_id, heading, level, _split_section_body(body))

    if not chunks:
        chunks.append(Chunk(
            id=0, type="para", section_id=0,
            section_heading="(intro)", section_level=0,
            level=0, heading="(intro)", src="", dst="",
        ))
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

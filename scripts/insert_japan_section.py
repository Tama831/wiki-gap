"""
N-of-1 trial (Q6956315) の翻訳に「日本における N-of-1 試験」節を挿入する。

挿入位置: section_id=6 (See also = 関連項目) の直前
新しい section_id = 100 を使う (既存 ID と衝突しないように)
新しい chunk ID は max(existing) + 1 から振る (既存の textarea が壊れないように)

ja Wikipedia の慣習に従い、英語版にない独自節として:
  - 出典は KAKEN, J-Stage の論文, NCNP プレスリリース, JPMA レポート, FDA 資料
  - src は HTML コメントで「日本語版独自」マーカー (左側ペインに表示される)

冪等性: 既に「日本における N-of-1 試験」が挿入されていれば何もしない。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wiki_gap.db"
QID = "Q6956315"
JP_SECTION_ID = 100  # 既存 0..8 と被らない値
SECTION_HEADING = "日本における N-of-1 試験"
SRC_NOTE = "<!-- This section is unique to the Japanese Wikipedia draft. No English counterpart. -->"

# (id 相対値, type, dst)
NEW_CHUNK_PROTOS: list[tuple[int, str, str]] = [
    (
        0,
        "heading",
        "==日本における N-of-1 試験==",
    ),
    (
        1,
        "para",
        (
            "日本においては、N-of-1試験は[[家庭医療]]領域における[[慢性疾患]]の"
            "個別化治療や、近年では[[希少疾患]]・[[指定難病]]を対象とする個別化"
            "治療開発の文脈で関心が持たれてきた。"
        ),
    ),
    (
        2,
        "para",
        (
            r"""日本国内における先駆的な臨床応用研究として、自治医科大学医学部の岡山雅信らが 1998 年から 1999 年にかけて実施した、慢性疾患を有する高齢患者 10 名(平均年齢 68.2 ± 6.4 歳)と担当医師 5 名を対象とした N-of-1 試験研究が知られている<ref>{{Cite web |author=岡山 雅信 |title=N-of-1 trial によって、医師の処方行動ならび患者の受療行動は変わるか |publisher=日本学術振興会 科学研究費助成事業 |year=1998 |id=KAKENHI-PROJECT-10770174 |url=https://kaken.nii.ac.jp/grant/KAKENHI-PROJECT-10770174/ |access-date=2026-05-08}}</ref>。膝痛、不眠、しびれ、腰痛など加齢に伴う慢性症状を対象に N-of-1 試験を実施したところ、治療効果判定における医師と患者の一致率は試験前の 40 %(10 例中 4 例)から試験後には 80 %(10 例中 8 例)に上昇したと報告されており、個別化された治療判断における N-of-1 試験の有用性を示した日本国内の早期事例として位置づけられる。"""
        ),
    ),
    (
        3,
        "para",
        (
            r"""日本語の代表的な総説としては、東北大学大学院医工学研究科の門間陽樹による「集団を対象とする疫学研究と N = 1 研究」(2018 年、バイオメカニズム学会誌)<ref>{{Cite journal |author=門間 陽樹 |title=集団を対象とする疫学研究と N = 1 研究 |journal=バイオメカニズム学会誌 |volume=42 |issue=1 |pages=47–52 |year=2018 |doi=10.3951/sobim.42.1_47 |url=https://www.jstage.jst.go.jp/article/sobim/42/1/42_47/_article/-char/ja/}}</ref>がある。集団を対象とする疫学研究と N=1 研究の方法論的連続性、[[ランダム化比較試験]]との対比、N-of-1試験の歴史的展開と今後の展望が論じられている。実験医学(羊土社)では「N-of-1解析」がキーワードとして紹介されており<ref>{{Cite web |title=N-of-1解析 |publisher=羊土社「実験医学online」キーワード集 |url=https://yodosha.co.jp/jikkenigaku/keyword/3148.html |access-date=2026-05-08}}</ref>、医学研究方法論の用語として一定の認知が進んでいる。"""
        ),
    ),
    (
        4,
        "para",
        (
            r"""2020 年代以降、超[[希少疾患]]を対象とする個別化治療(N-of-1 治療)が国際的に注目されており、米国食品医薬品局(FDA)は超希少疾患を対象とする個別化治療開発の枠組みを公表した<ref>{{Cite web |title=FDA Launches Framework for Accelerating Development of Individualized Therapies for Ultra-Rare Diseases |publisher=U.S. Food and Drug Administration |url=https://www.fda.gov/news-events/press-announcements/fda-launches-framework-accelerating-development-individualized-therapies-ultra-rare-diseases |access-date=2026-05-08}}</ref>。[[アンチセンス核酸|アンチセンスオリゴヌクレオチド]](ASO)などを患者個別に設計する N-of-1 治療への関心は国内でも高まっており、[[国立精神・神経医療研究センター]]内には 2024 年に「日本希少疾患コンソーシアム」(Rare Disease Consortium Japan: RDCJ)が設立された<ref>{{Cite web |title=日本希少疾患コンソーシアム(Rare Disease Consortium Japan：RDCJ)、会員募集を開始 |publisher=国立精神・神経医療研究センター |year=2024 |url=https://www.ncnp.go.jp/topics/detail.php?@uid=EYZtSXpdIfAm2GEe |access-date=2026-05-08}}</ref>。また、日本製薬工業協会 医薬品評価委員会 データサイエンス部会の希少疾患タスクフォースは、希少疾患における治療効果推測法のひとつとして N-of-1 デザインの活用可能性を検討しており<ref>{{Cite report |author=日本製薬工業協会 医薬品評価委員会 データサイエンス部会 |title=Rare disease の治療効果の推測法 |year=2021 |url=https://www.jpma.or.jp/information/evaluation/results/allotment/jtrngf000000085m-att/ds_202212_rare.pdf}}</ref>、希少疾患・難病領域における N-of-1 試験の臨床的・規制科学的位置づけが議論されている。"""
        ),
    ),
]


def main() -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT chunks_json FROM translations WHERE qid = ?", (QID,)
    ).fetchone()
    if row is None:
        print(f"ERROR: no translation row for {QID}", file=sys.stderr)
        return 1

    chunks = json.loads(row["chunks_json"])

    # 冪等性チェック
    for c in chunks:
        if c.get("section_id") == JP_SECTION_ID or c.get("section_heading") == SECTION_HEADING:
            print(f"already inserted (section_id={c.get('section_id')}, "
                  f"heading={c.get('section_heading')!r}). skipping.")
            return 0

    # 挿入位置: 最初に出てくる section_id=6 (See also) の chunk index
    insert_at = None
    for i, c in enumerate(chunks):
        if c.get("section_id") == 6:
            insert_at = i
            break

    if insert_at is None:
        # See also が無いなら References (7) の前
        for i, c in enumerate(chunks):
            if c.get("section_id") == 7:
                insert_at = i
                break

    if insert_at is None:
        print("ERROR: cannot find See also or References section to insert before",
              file=sys.stderr)
        return 1

    next_id = max(int(c["id"]) for c in chunks) + 1
    new_chunks: list[dict] = []
    for offset, ctype, dst in NEW_CHUNK_PROTOS:
        new_chunks.append({
            "id": next_id + offset,
            "type": ctype,
            "section_id": JP_SECTION_ID,
            "section_heading": SECTION_HEADING,
            "section_level": 2,
            "level": 2,
            "heading": SECTION_HEADING,
            "src": SRC_NOTE,
            "dst": dst,
        })

    merged = chunks[:insert_at] + new_chunks + chunks[insert_at:]

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE translations SET chunks_json = ?, updated_at = ? WHERE qid = ?",
        (json.dumps(merged, ensure_ascii=False), now, QID),
    )
    conn.commit()
    conn.close()

    print(f"inserted {len(new_chunks)} new chunks (ids {next_id}..{next_id + len(new_chunks) - 1}) "
          f"at position {insert_at} (before section_id=6)")
    print(f"total chunks now: {len(merged)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

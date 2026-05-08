"""
N-of-1 trial (Q6956315) の下訳を Claude セッションで作成し、
chunks_json に書き込む 1 回限りのスクリプト (段落単位、Phase 2A.5)。

訳語の方針:
  - 準実験 → 準実験的研究 (たまさん指摘)
  - quasi-experimental type-2 N-of-1 study → 「準実験的タイプ 2 N-of-1 試験」
  - quantified self → クオンティファイド・セルフ (ja Wikipedia 既存記事に対応)
  - group comparison study → [[group comparison study|群間比較研究]] (定訳)
  - washout period → ウォッシュアウト期間
  - 出典 (<ref>...</ref>) はそのまま残す
  - リンク [[foo]] は ja Wikipedia に対応記事があれば置換
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

# chunk_id -> ja translation
T: dict[int, str] = {}

# id=0  intro 段落 1 (定義 + 設計の概要)
T[0] = (
    r"""{{Short description|単一の患者を対象とする臨床試験}}
'''N-of-1試験'''('''N=1試験''')とは、単一の患者を対象として複数回のクロスオーバー法で実施される[[臨床試験]]である。<ref>{{Cite web |title=Introduction to N-of-1 Trials: Indications and Barriers (Chapter 1) {{!}} Effective Health Care (EHC) Program |url=https://effectivehealthcare.ahrq.gov/products/n-1-trials/research-2014-4#toc-1 |access-date=2023-12-31 |website=effectivehealthcare.ahrq.gov}}</ref> 1 人の患者に対して試験介入と対照介入を行う順序を[[無作為化|無作為割付]]によって決定する場合、これを N-of-1[[ランダム化比較試験]]と呼ぶ。N-of-1試験のなかには[[無作為化|ランダム化]]と[[盲検試験|盲検化]]を取り入れるものもあるが、試験介入と対照介入の順序を研究者があらかじめ固定することもある。<ref>{{Cite journal |last1=Punja |first1=Salima |last2=Bukutu |first2=Cecilia |last3=Shamseer |first3=Larissa |last4=Sampson |first4=Margaret |last5=Hartling |first5=Lisa |last6=Urichuk |first6=Liana |last7=Vohra |first7=Sunita |date=August 2016 |title=N-of-1 trials are a tapestry of heterogeneity |journal=Journal of Clinical Epidemiology |volume=76 |pages=47–56 |doi=10.1016/j.jclinepi.2016.03.023 |issn=1878-5921 |pmid=27079847}}</ref>"""
)

# id=1  intro 段落 2 (意義: group comparison 不要 / 個別化医療)
T[1] = (
    r"""このデザインによって、臨床家は[[group comparison study|群間比較研究]]を新たに設計するという作業を経ずとも実証的な知見を得ることができる。とくに盲検化とウォッシュアウト期間を組み合わせた場合、[[因果関係]]の確認に有効である。N-of-1試験は、当該試験に参加した患者本人の治療判断に直接活用される場合、個々の患者の治療反応性に関するエビデンスとなり、[[個別化医療]]の理念を実現する手段となりうる。<ref>{{Cite journal |last1=Serpico |first1=Davide |last2=Maziarz |first2=Mariusz |date=2023-12-14 |title=Averaged versus individualized: pragmatic N-of-1 design as a method to investigate individual treatment response |journal=European Journal for Philosophy of Science |language=en |volume=13 |issue=4 |page=59 |doi=10.1007/s13194-023-00559-0 |issn=1879-4920|doi-access=free |hdl=2434/1045468 |hdl-access=free }}</ref><ref>{{cite book |last=Nikles, J., & Mitchell, G. |editor-first1=Jane |editor-first2=Geoffrey |editor-last1=Nikles |editor-last2=Mitchell |date=2015 |title=The Essential Guide to N-of-1 Trials in Health |url=https://link.springer.com/content/pdf/10.1007/978-94-017-7200-6.pdf  |language=en |doi=10.1007/978-94-017-7200-6|isbn=978-94-017-7199-3 |s2cid=33597874 }}</ref>"""
)

# id=2  heading == Design ==
T[2] = "==デザイン=="

# id=3  Design 段落 1 (SPOTs / ABA / type-2 / 因果性)
T[3] = (
    r"""N-of-1試験はさまざまな形でデザインしうる。たとえば「単一患者オープン試験」(Single-Patient Open Trials, SPOTs)は、形式的(説明的)な N-of-1試験と、日常臨床で行われる試行錯誤的アプローチとの中間に位置するもので、少なくとも 1 回のクロスオーバー期間とその間にウォッシュアウト期間を置くことを特徴とする。<ref>{{Citation |last1=Smith |first1=Jane |title=Single Patient Open Trials (SPOTs) |date=2015 |work=The Essential Guide to N-of-1 Trials in Health |pages=195–209 |editor-last=Nikles |editor-first=Jane  |place=Dordrecht |publisher=Springer Netherlands |language=en |doi=10.1007/978-94-017-7200-6_15 |isbn=978-94-017-7200-6 |last2=Yelland |first2=Michael |last3=Del Mar |first3=Christopher |editor2-last=Mitchell |editor2-first=Geoffrey}}</ref> 最もよく用いられる手法のひとつが「ABA 中止デザイン (ABA withdrawal design)」である。これは、治療を導入する前(ベースライン)に患者の問題を測定し、治療中に再度測定し、治療終了後にもう一度測定するというものである。治療中に問題が消失すれば、当該治療が有効であったと結論しうる。一方、N=1 試験は AB 型の[[Quasi-experiment|準実験的研究]]としても実施できる。こうした準実験的タイプ 2 の N-of-1 試験は、介入の期待効果が交絡因子の効果量を上回るような重症かつ稀少な疾患に対する治療を検証する場合に有効である。<ref>{{Cite journal |last1=Selker |first1=Harry P. |last2=Cohen |first2=Theodora |last3=D'Agostino |first3=Ralph B. |last4=Dere |first4=Willard H. |last5=Ghaemi |first5=S. Nassir |last6=Honig |first6=Peter K. |last7=Kaitin |first7=Kenneth I. |last8=Kaplan |first8=Heather C. |last9=Kravitz |first9=Richard L. |last10=Larholt |first10=Kay |last11=McElwee |first11=Newell E. |last12=Oye |first12=Kenneth A. |last13=Palm |first13=Marisha E. |last14=Perfetto |first14=Eleanor |last15=Ramanathan |first15=Chandra |date=August 2022 |title=A Useful and Sustainable Role for N-of-1 Trials in the Healthcare Ecosystem |journal=Clinical Pharmacology & Therapeutics |language=en |volume=112 |issue=2 |pages=224–232 |doi=10.1002/cpt.2425 |issn=0009-9236 |pmc=9022728 |pmid=34551122}}</ref> 別のバリエーションとして、異なる時点を相互に比較する非同時実験デザイン(non-concurrent experimental design)もある。標準的な治療選択法である[[Trial and error|試行錯誤法]]も N-of-1 のデザインに取り込みうる。<ref>{{Cite book |last=Kravitz, R. L., Duan, N., Vohra, S., Li, J. |title=Introduction to N-of-1 trials: indications and barriers. Design and implementation of N-of-1 trials: A user's guide |publisher=AHRQ Publication No. 13(14)-EHC122-EF |year=2014}}</ref> ただしこの実験デザインも因果性の問題を抱えており、[[Frequentist probability|頻度論]]の枠組みでは統計的有意性を解釈できない場合がある。そのため、臨床的有意性<ref>{{cite journal | vauthors = Chapple AG, Blackston JW | title = Finding Benefit in n-of-1 Trials | journal = JAMA Internal Medicine | volume = 179 | issue = 3 | pages = 453–454 | date = March 2019 | pmid = 30830189 | doi = 10.1001/jamainternmed.2018.8379 | s2cid = 73463184 }}</ref>や[[ベイズ統計|ベイズ法]]などの代替的な手法を併せて検討するべきである。"""
)

# id=4  Design 段落 2 (proof of concept)
T[4] = (
    "このフレームワークは、後続のより大規模な臨床試験を導くための"
    "概念実証 (proof of concept) ないし仮説生成プロセスと位置づけられることが多い。"
)

# id=5  heading == List of variation in N-of-1 trial ==
T[5] = "==N-of-1試験のバリエーション一覧=="

# id=6  block: wikitable
T[6] = (
    r"""{| class="wikitable"
|-
! デザイン
! 因果性
! 用途
|-
| A-B
| 準実験的研究
| 多くの場合、唯一実施可能な方法
|-
| A-A<sup>1</sup>-A
| 実験
| プラセボデザイン。A は薬剤なし、A<sup>1</sup> はプラセボ
|-
| A-B-A
| 実験
| 中止デザイン。B 期の効果を確認できる
|-
| A-B-A-B
| 実験
| 中止デザイン。B 期の効果を確認できる
|-
| A-B-A-B-A-B
| 実験
| 中止デザイン。B 期の効果を確認できる
|-
| A-B<sup>1</sup>-B<sup>2</sup>-B<sup>3</sup>-B<sup>n</sup>-A
| 実験
| B 期の異なるバージョンの効果を確認できる
|}"""
)

# id=7  <small> 説明
T[7] = (
    "<small>「準実験的研究」は因果関係を確定的には示せないことを意味し、"
    "「実験」は確定的に示しうることを意味する。</small>"
)

# id=8  [[File:..]] キャプション
T[8] = (
    r"[[File:Single subject blood pressure example.png|center|thumb|500px|A-A<sup>1</sup>-A 型 N-of-1 試験の合成データ例。1〜30 日目、61〜90 日目、121〜150 日目に被験者は[[高血圧]]治療薬を服用し、それ以外の期間はプラセボを服用している。正常な[[収縮期血圧]]は 120 mmHg をやや下回る程度である。]]"
)

# id=9  heading == Examples ==
T[9] = "==適用例=="

# id=10  Examples 段落 1 (慢性疾患・OA・神経障害性疼痛・ADHD)
T[10] = (
    r"""N-of-1試験は通常、[[慢性疾患]]を対象とする治療への個別の反応性を評価するために用いられる。<ref>{{Cite journal |last1=Duan |first1=Naihua |last2=Kravitz |first2=Richard L. |last3=Schmid |first3=Christopher H. |date=2013-08-01 |title=Single-patient (n-of-1) trials: a pragmatic clinical decision methodology for patient-centered comparative effectiveness research |journal=Journal of Clinical Epidemiology |series=Methods for Comparative Effectiveness Research/Patient-Centered Outcomes Research: From Efficacy to Effectiveness |volume=66 |issue=8, Supplement |pages=S21–S28 |doi=10.1016/j.jclinepi.2013.04.006 |pmid=23849149 |pmc=3972259 |issn=0895-4356}}</ref> このデザインは、[[変形性関節症]]、慢性[[末梢神経障害|神経障害性]]疼痛、[[注意欠如・多動症]]など多様な疾患を持つ患者の最適な治療を決定するために有効に活用されてきた。<ref>{{cite journal | vauthors = Scuffham PA, Nikles J, Mitchell GK, Yelland MJ, Vine N, Poulos CJ, Pillans PI, Bashford G, del Mar C, Schluter PJ, Glasziou P | display-authors = 6 | title = Using N-of-1 trials to improve patient management and save costs | journal = Journal of General Internal Medicine | volume = 25 | issue = 9 | pages = 906–13 | date = September 2010 | pmid = 20386995 | pmc = 2917656 | doi = 10.1007/s11606-010-1352-7 | url = http://iospress.metapress.com/content/t51wg3207328hv38/?genre=article&issn=1387-2877&volume=21&issue=3&spage=967 | archive-url = https://archive.today/20130923221601/http://iospress.metapress.com/content/t51wg3207328hv38/?genre=article&issn=1387-2877&volume=21&issue=3&spage=967 | archive-date = 2013-09-23 }}</ref>"""
)

# id=11  Examples 段落 2 (観察研究 + 因果推論)
T[11] = (
    r"""N-of-1 デザインは観察的にも実施可能であり、健康関連行動や症状の個人内変動を縦断的に記述することもできる。N-of-1 観察研究のデータには複雑な統計解析が必要となるが、初学者向けに 10 ステップの簡易な手順も紹介されている。<ref>{{cite journal |last1=McDonald |first1=S |last2=Vieira |first2=R |last3=Johnston |first3=D W. |title=Analysing N-of-1 observational data in health psychology and behavioural medicine: a 10-step SPSS tutorial for beginners |journal=Health Psychology and Behavioral Medicine |date=1 January 2020 |volume=8 |issue=1 |pages=32–54 |doi=10.1080/21642850.2019.1711096|pmid=34040861 | pmc=8114402 |doi-access=free }}</ref> また、N-of-1 観察研究を後続の N-of-1 試験設計に活かすため、[[因果推論]]の[[反事実条件法|反実仮想]]的手法を応用する研究も進んでいる。<ref>{{cite journal | vauthors = Daza EJ | title = Causal Analysis of Self-tracked Time Series Data Using a Counterfactual Framework for N-of-1 Trials | journal = Methods of Information in Medicine | volume = 57 | issue = 1 | pages = e10–e21 | date = February 2018 | pmid = 29621835 | pmc = 6087468 | doi = 10.3414/ME16-02-0044 | doi-access = free }}</ref><ref>{{cite journal | vauthors = Daza EJ, Matias I, Schneider L | title = Model-Twin Randomization (MoTR) for Estimating the Recurring Individual Treatment Effect | journal = Statistics in Medicine | volume = 44 | issue = 25-27 | article-number = e70290 | date = November 2025 | pmid = 41222445 | doi = 10.1002/sim.70290 }}</ref>"""
)

# id=12  Examples 段落 3 (システマティックレビュー)
T[12] = (
    r"""N-of-1試験は増加傾向にあるが、近年のシステマティックレビューによれば、これらの研究における統計解析は、研究のあらゆる段階でより方法論的・統計的厳密性を高める余地があるとされる。<ref>{{cite journal | vauthors = Shaffer JA, Kronish IM, Falzon L, Cheung YK, Davidson KW | title = N-of-1 Randomized Intervention Trials in Health Psychology: A Systematic Review and Methodology Critique | journal = Annals of Behavioral Medicine | volume = 52 | issue = 9 | pages = 731–742 | date = August 2018 | pmid = 30124759 | pmc = 6128372 | doi = 10.1093/abm/kax026 }}</ref>"""
)

# id=13  heading == The Quantified Self ==
T[13] = "==クオンティファイド・セルフ=="

# id=14  Quantified Self 段落 1
T[14] = (
    r"""[[クオンティファイド・セルフ]] (Quantified Self) という文化的潮流の高まりとともに、N=1 試験に類する個人実験が急増しており、その詳細な報告も増えている。この傾向の背景には、データの収集と解析がますます容易になったこと、そして個人がそうしたデータを手軽に発信できるようになったことがある。<ref>{{cite journal | vauthors = Swan M | title = The Quantified Self: Fundamental Disruption in Big Data Science and Biological Discovery | journal = Big Data | volume = 1 | issue = 2 | pages = 85–99 | date = June 2013 | pmid = 27442063 | doi = 10.1089/big.2012.0002 | doi-access = free }}</ref>"""
)

# id=15  Quantified Self 段落 2 (Seth Roberts)
T[15] = (
    r"""著名な提唱者かつ実践者として[[セス・ロバーツ]] (Seth Roberts) が知られている。彼は自身のブログで自己実験の知見を公表し、後にこれらの自己実験から導いた結論をもとに『''[[The Shangri-La Diet]]''』を出版した。"""
)

# id=16  heading == Global networks ==
T[16] = "==国際的なネットワーク=="

# id=17  Global networks 段落
T[17] = (
    r"""「N-of-1試験および単一症例デザインのための国際協同ネットワーク」(International Collaborative Network for N-of-1 Trials and Single-Case Designs, ICN)<ref>{{Cite web |title=International Collaborative Network for N-of-1 Trials and Single-Case Designs |url=https://www.nof1sced.org/ |access-date=2024-07-09 |website=N-of-1 and SCED |language=en}}</ref>は、これらの方法論に関心を持つ臨床家・研究者・一般生活者のための国際ネットワークである。ICN には世界 30 か国以上から 400 名を超えるメンバーが参加している。ICN は 2017 年に設立され、現在は Jane Nikles と Suzanne McDonald が共同議長を務めている。"""
)

# id=18  heading == See also ==
T[18] = "==関連項目=="

# id=19  See also list
T[19] = (
    r"""* {{annotated link|応用行動分析}}
* {{annotated link|逸話的証拠}}
* {{annotated link|B・F・スキナー}}
* {{annotated link|単一症例デザイン}}
* {{annotated link|クロスオーバー試験}}"""
)

# id=20  heading == References ==
T[20] = "==脚注=="

# id=21  block {{reflist}}
T[21] = "{{reflist}}"

# id=22  heading == Further reading ==
T[22] = "==参考文献=="

# id=23  block {{refbegin}}...{{refend}}
T[23] = (
    r"""{{refbegin}}
* {{cite journal | vauthors = Guyatt GH, Keller JL, Jaeschke R, Rosenbloom D, Adachi JD, Newhouse MT | title = The n-of-1 randomized controlled trial: clinical usefulness. Our three-year experience | journal = Annals of Internal Medicine | volume = 112 | issue = 4 | pages = 293–9 | date = February 1990 | pmid = 2297206 | doi = 10.7326/0003-4819-112-4-293 }}
* {{cite journal | vauthors = Johnston BC, Mills E | title = n-of-1 randomized controlled trials: an opportunity for complementary and alternative medicine evaluation | journal = Journal of Alternative and Complementary Medicine | volume = 10 | issue = 6 | pages = 979–84 | date = December 2004 | pmid = 15673992 | doi = 10.1089/acm.2004.10.979 }}
* {{cite journal | vauthors = Avins AL, Bent S, Neuhaus JM | title = Use of an embedded N-of-1 trial to improve adherence and increase information from a clinical study | journal = Contemporary Clinical Trials | volume = 26 | issue = 3 | pages = 397–401 | date = June 2005 | pmid = 15911473 | doi = 10.1016/j.cct.2005.02.004 }}
* {{cite journal | vauthors = Nikles CJ, Mitchell GK, Del Mar CB, Clavarino A, McNairn N | title = An n-of-1 trial service in clinical practice: testing the effectiveness of stimulants for attention-deficit/hyperactivity disorder | journal = Pediatrics | volume = 117 | issue = 6 | pages = 2040–6 | date = June 2006 | pmid = 16740846 | doi = 10.1542/peds.2005-1328 | s2cid = 20325906 }}
{{refend}}"""
)

# id=24  block (DEFAULTSORT + Categories)
T[24] = (
    r"""{{DEFAULTSORT:えぬおぶわんしけん}}
[[Category:臨床試験]]
[[Category:実験計画法]]"""
)


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
    n_updated = 0
    n_skipped = 0

    for c in chunks:
        cid = int(c["id"])
        if cid in T:
            new_dst = T[cid].rstrip()
            old_dst = (c.get("dst") or "").strip()
            if old_dst:
                # 既に手で書かれているなら上書きしない
                print(f"  skip id={cid:>2} type={c.get('type','para'):>7} (already has dst, {len(old_dst)} chars)")
                n_skipped += 1
                continue
            c["dst"] = new_dst
            print(f"  set  id={cid:>2} type={c.get('type','para'):>7} ({len(new_dst):>4} chars)")
            n_updated += 1
        else:
            print(f"  --   id={cid:>2} (no translation provided)")

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE translations SET chunks_json = ?, updated_at = ? WHERE qid = ?",
        (json.dumps(chunks, ensure_ascii=False), now, QID),
    )
    conn.commit()
    conn.close()

    print(f"\nupdated {n_updated} chunks, skipped {n_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

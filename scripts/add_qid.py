"""
任意 QID を articles テーブルに追加する (3 カテゴリ外の記事用)。

使い方:
  python scripts/add_qid.py Q6956315 --category procedure
  python scripts/add_qid.py Q6956315 --category procedure \
      --en-title "N-of-1 trial" --ja-title-proposed "N-of-1試験"

挙動:
  - en/ja の sitelink を MediaWiki API から取得
  - meta/pageviews を取得して articles に upsert
  - gap_score を計算
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.mediawiki import MediaWikiClient  # noqa: E402
from src.crawler.pageviews import fetch_pageviews_90d  # noqa: E402
from src.crawler.wikidata import _user_agent  # noqa: E402
from src.db.queries import connect, upsert_article, write_snapshot  # noqa: E402
from src.scoring.gap import GapInputs, gap_score  # noqa: E402


async def add_qid(
    qid: str,
    category: str,
    en_title: str | None = None,
    ja_title: str | None = None,
) -> None:
    if not en_title:
        # ja は無くても en はあるはずなので確認
        raise SystemExit("--en-title is required (auto-resolution skipped)")

    print(f"[add_qid] qid={qid} category={category}")
    print(f"[add_qid] en_title={en_title!r} ja_title={ja_title!r}")

    headers = {"User-Agent": _user_agent()}
    async with MediaWikiClient() as mw, httpx.AsyncClient(
        timeout=30.0, headers=headers
    ) as pv_client:
        meta = await mw.fetch_article_meta(qid, en_title, ja_title or "")

        en_pv = await fetch_pageviews_90d(pv_client, "en", en_title)
        ja_pv = (
            await fetch_pageviews_90d(pv_client, "ja", ja_title)
            if ja_title else None
        )

    score = gap_score(GapInputs(
        en_bytes=meta.en.bytes_, ja_bytes=meta.ja.bytes_,
        en_pv_90d=en_pv, ja_pv_90d=ja_pv,
    ))

    row = {
        "qid": qid,
        "category": category,
        "en_title": meta.en.title,
        "ja_title": meta.ja.title,
        "en_bytes": meta.en.bytes_,
        "ja_bytes": meta.ja.bytes_,
        "en_sections": meta.en.sections,
        "ja_sections": meta.ja.sections,
        "en_refs": meta.en.refs,
        "ja_refs": meta.ja.refs,
        "en_images": meta.en.images,
        "ja_images": meta.ja.images,
        "en_pv_90d": en_pv,
        "ja_pv_90d": ja_pv,
        "en_last_edit": meta.en.last_edit,
        "ja_last_edit": meta.ja.last_edit,
        "gap_score": score,
    }

    with connect() as conn:
        upsert_article(conn, row)
        write_snapshot(
            conn, qid=qid,
            en_bytes=meta.en.bytes_, ja_bytes=meta.ja.bytes_,
            gap_score_value=score,
        )

    print(f"[add_qid] upserted: en_bytes={meta.en.bytes_} ja_bytes={meta.ja.bytes_} "
          f"gap_score={score}")


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qid", help="Wikidata QID (例: Q6956315)")
    parser.add_argument(
        "--category", required=True,
        choices=["disease", "drug", "procedure", "study", "other"],
    )
    parser.add_argument("--en-title", required=True)
    parser.add_argument("--ja-title", default=None,
                        help="ja Wikipedia title (もし存在するなら)")
    args = parser.parse_args()

    asyncio.run(add_qid(args.qid, args.category, args.en_title, args.ja_title))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
クロール実行のエントリポイント。

使い方:
  python scripts/run_crawl.py --category disease --limit 100
  python scripts/run_crawl.py --category disease --limit 0      # 上限なし
  python scripts/run_crawl.py --all --limit 0                   # 全カテゴリ全件
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.pipeline import crawl_category  # noqa: E402
from src.crawler.wikidata import CATEGORY_ROOTS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=list(CATEGORY_ROOTS), default=None)
    parser.add_argument("--all", action="store_true", help="全カテゴリを順に")
    parser.add_argument("--limit", type=int, default=100, help="0 で上限なし")
    parser.add_argument("--rate-limit", type=float, default=1.5, help="req/sec")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args(argv)

    if args.all:
        categories = list(CATEGORY_ROOTS)
    elif args.category:
        categories = [args.category]
    else:
        parser.error("either --category or --all must be specified")

    limit = args.limit if args.limit > 0 else None

    total_fetched = 0
    total_failed = 0
    for cat in categories:
        fetched, failed = asyncio.run(
            crawl_category(
                cat,
                limit=limit,
                rate_limit_rps=args.rate_limit,
                max_concurrency=args.concurrency,
            )
        )
        total_fetched += fetched
        total_failed += failed

    print(f"[run_crawl] total fetched={total_fetched} failed={total_failed}")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

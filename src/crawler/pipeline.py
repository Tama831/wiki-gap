"""
クロール全体のオーケストレーション。

  1. wikidata.fetch_seeds(category, limit) で SeedItem 群を取得
  2. 各 seed について MediaWikiClient で en/ja のメタを取得
  3. pageviews を別途取得
  4. gap_score を計算
  5. SQLite に upsert + snapshots に書き込み

エラー耐性:
  - 1 記事の取得失敗 (404, タイムアウト, etc) は warn してスキップ
  - 全体は crawl_runs に partial / success / failed を記録
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import asdict

import httpx

from src.crawler.mediawiki import MediaWikiClient
from src.crawler.pageviews import fetch_pageviews_90d
from src.crawler.wikidata import SeedItem, fetch_seeds
from src.db.queries import (
    connect,
    finish_crawl_run,
    start_crawl_run,
    upsert_article,
    write_snapshot,
)
from src.scoring.gap import GapInputs, gap_score

logger = logging.getLogger("wiki-gap.pipeline")


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


async def _process_seed(
    seed: SeedItem,
    mw: MediaWikiClient,
    pv_client: httpx.AsyncClient,
) -> dict | None:
    """1 seed を処理して articles 用 row を返す。失敗時は None。"""
    try:
        meta = await mw.fetch_article_meta(
            seed.qid, seed.en_title or "", seed.ja_title or ""
        )
    except Exception as exc:
        logger.warning(f"[{seed.qid}] meta fetch failed: {exc}")
        return None

    # PV は別途並列取得
    en_pv_task = (
        fetch_pageviews_90d(pv_client, "en", seed.en_title)
        if seed.en_title
        else asyncio.sleep(0, result=None)
    )
    ja_pv_task = (
        fetch_pageviews_90d(pv_client, "ja", seed.ja_title)
        if seed.ja_title
        else asyncio.sleep(0, result=None)
    )
    en_pv, ja_pv = await asyncio.gather(en_pv_task, ja_pv_task)

    score = gap_score(
        GapInputs(
            en_bytes=meta.en.bytes_,
            ja_bytes=meta.ja.bytes_,
            en_pv_90d=en_pv,
            ja_pv_90d=ja_pv,
        )
    )

    return {
        "qid": seed.qid,
        "category": seed.category,
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


async def crawl_category(
    category: str,
    *,
    limit: int | None = 100,
    rate_limit_rps: float = 1.5,
    max_concurrency: int = 3,
) -> tuple[int, int]:
    """
    指定カテゴリの seed を取って各記事のメタ + PV を取得し DB に upsert。

    返り値: (fetched_count, failed_count)
    """
    seeds = fetch_seeds(category, limit=limit)
    logger.info(
        f"[crawl] category={category} seeds={len(seeds)} "
        f"(both={sum(1 for s in seeds if s.has_en_sitelink and s.has_ja_sitelink)})"
    )

    fetched = 0
    failed = 0

    with connect() as conn:
        run_id = start_crawl_run(conn, category, len(seeds))

    pv_headers = {"User-Agent": _user_agent()}
    async with MediaWikiClient(
        rate_limit_rps=rate_limit_rps,
        max_concurrency=max_concurrency,
    ) as mw, httpx.AsyncClient(timeout=30.0, headers=pv_headers) as pv_client:
        # 直列処理: rate_limit を厳守 (並列を上げたい場合は max_concurrency を増やす)
        sem = asyncio.Semaphore(max_concurrency)

        async def _bounded(seed: SeedItem):
            async with sem:
                return seed, await _process_seed(seed, mw, pv_client)

        tasks = [asyncio.create_task(_bounded(s)) for s in seeds]
        for fut in asyncio.as_completed(tasks):
            seed, row = await fut
            if row is None:
                failed += 1
                continue
            try:
                with connect() as conn:
                    upsert_article(conn, row)
                    write_snapshot(
                        conn,
                        qid=seed.qid,
                        en_bytes=row.get("en_bytes"),
                        ja_bytes=row.get("ja_bytes"),
                        gap_score_value=row.get("gap_score"),
                    )
                fetched += 1
                if fetched % 20 == 0:
                    logger.info(
                        f"[crawl] progress: {fetched}/{len(seeds)} fetched, {failed} failed"
                    )
            except Exception as exc:
                logger.warning(f"[{seed.qid}] DB write failed: {exc}")
                failed += 1

    status = "success" if failed == 0 else ("partial" if fetched > 0 else "failed")
    with connect() as conn:
        finish_crawl_run(
            conn, run_id, status=status, fetched=fetched, failed=failed
        )

    logger.info(f"[crawl] done: {fetched} fetched, {failed} failed, status={status}")
    return fetched, failed

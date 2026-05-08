"""
SQLite に対する upsert / read クエリ。

ロジック:
  - articles: PRIMARY KEY (qid) に対して INSERT OR REPLACE で upsert
  - snapshots: PRIMARY KEY (qid, snapshot_date) で日次1件
  - crawl_runs: 実行ログ (障害解析用)
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def db_path() -> Path:
    """env か default から DB ファイルパスを解決する。"""
    p = os.getenv("WIKI_GAP_DB_PATH", "data/wiki_gap.db")
    path = Path(p)
    if not path.is_absolute():
        # repo root from this file: src/db/queries.py → ../..
        root = Path(__file__).resolve().parent.parent.parent
        path = root / path
    return path


@contextmanager
def connect(read_only: bool = False) -> Iterator[sqlite3.Connection]:
    path = db_path()
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not read_only:
            conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_jst() -> str:
    """JST date (YYYY-MM-DD) for snapshot keying."""
    from datetime import timezone
    jst = timezone(__import__("datetime").timedelta(hours=9))
    return datetime.now(jst).strftime("%Y-%m-%d")


def upsert_article(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    """
    articles テーブルに upsert。row はカラム dict (qid 必須)。
    updated_at は自動付与。
    """
    row = dict(row)
    row["updated_at"] = now_iso()
    columns = [
        "qid", "category", "en_title", "ja_title",
        "en_bytes", "ja_bytes",
        "en_sections", "ja_sections",
        "en_refs", "ja_refs",
        "en_images", "ja_images",
        "en_pv_90d", "ja_pv_90d",
        "en_last_edit", "ja_last_edit",
        "gap_score", "updated_at",
    ]
    placeholders = ",".join(f":{c}" for c in columns)
    column_list = ",".join(columns)
    # SQLite "INSERT OR REPLACE" — keeps PK, replaces all other fields
    sql = f"INSERT OR REPLACE INTO articles ({column_list}) VALUES ({placeholders})"
    # Fill missing columns with None
    for c in columns:
        row.setdefault(c, None)
    conn.execute(sql, row)


def write_snapshot(conn: sqlite3.Connection, qid: str, en_bytes: int | None,
                   ja_bytes: int | None, gap_score_value: float | None,
                   snapshot_date: str | None = None) -> None:
    snapshot_date = snapshot_date or today_jst()
    sql = (
        "INSERT OR REPLACE INTO snapshots "
        "(qid, snapshot_date, en_bytes, ja_bytes, gap_score) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    conn.execute(sql, (qid, snapshot_date, en_bytes, ja_bytes, gap_score_value))


def start_crawl_run(conn: sqlite3.Connection, category: str | None,
                    seeds_count: int) -> int:
    cur = conn.execute(
        "INSERT INTO crawl_runs (started_at, status, category, seeds_count, "
        "fetched_count, failed_count) VALUES (?, 'running', ?, ?, 0, 0)",
        (now_iso(), category, seeds_count),
    )
    return cur.lastrowid


def finish_crawl_run(conn: sqlite3.Connection, run_id: int, *,
                     status: str, fetched: int, failed: int,
                     error_message: str | None = None) -> None:
    conn.execute(
        "UPDATE crawl_runs SET finished_at = ?, status = ?, fetched_count = ?, "
        "failed_count = ?, error_message = ? WHERE run_id = ?",
        (now_iso(), status, fetched, failed, error_message, run_id),
    )


def top_gap_articles(conn: sqlite3.Connection, *,
                     limit: int = 100,
                     category: str | None = None,
                     min_score: float | None = None) -> list[sqlite3.Row]:
    where = []
    params: list[Any] = []
    if category:
        where.append("category = ?")
        params.append(category)
    if min_score is not None:
        where.append("gap_score >= ?")
        params.append(min_score)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT * FROM articles"
        + where_clause
        + " ORDER BY gap_score DESC NULLS LAST LIMIT ?"
    )
    params.append(limit)
    return list(conn.execute(sql, params).fetchall())


def article_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

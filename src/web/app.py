"""
FastAPI + Jinja2 ダッシュボード。

ルート:
  GET /            - トップ100 の表 (ソート / カテゴリフィルタ)
  GET /export.csv  - CSV エクスポート
  GET /healthz     - ヘルスチェック (Tailscale 経由 monitoring 用)
"""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.db.queries import article_count, connect, top_gap_articles

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="wiki-gap", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


SORT_COLUMNS = {
    "gap": "gap_score",
    "en_pv": "en_pv_90d",
    "ja_pv": "ja_pv_90d",
    "en_bytes": "en_bytes",
    "ja_bytes": "ja_bytes",
    "updated": "updated_at",
}


def _wikipedia_url(lang: str, title: str | None) -> str | None:
    if not title:
        return None
    from urllib.parse import quote
    return f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    sort: str = Query("gap"),
    direction: str = Query("desc"),
    category: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    sort_col = SORT_COLUMNS.get(sort, "gap_score")
    if direction not in {"asc", "desc"}:
        direction = "desc"

    where = []
    params: list = []
    if category in {"disease", "drug", "procedure"}:
        where.append("category = ?")
        params.append(category)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    # NULLS は最後に
    null_pos = "NULLS LAST" if direction == "desc" else "NULLS FIRST"
    sql = (
        f"SELECT * FROM articles{where_clause} "
        f"ORDER BY {sort_col} {direction.upper()} {null_pos} LIMIT ?"
    )
    params.append(limit)

    with connect(read_only=True) as conn:
        rows = list(conn.execute(sql, params).fetchall())
        total = article_count(conn)

    enriched = []
    for r in rows:
        enriched.append({
            **dict(r),
            "en_url": _wikipedia_url("en", r["en_title"]),
            "ja_url": _wikipedia_url("ja", r["ja_title"]),
        })

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "rows": enriched,
            "total": total,
            "sort": sort,
            "direction": direction,
            "category": category or "",
            "limit": limit,
        },
    )


@app.get("/export.csv")
def export_csv(
    sort: str = Query("gap"),
    direction: str = Query("desc"),
    category: str | None = Query(None),
    limit: int = Query(1000, ge=1, le=100000),
):
    sort_col = SORT_COLUMNS.get(sort, "gap_score")
    direction = direction if direction in {"asc", "desc"} else "desc"

    where = []
    params: list = []
    if category in {"disease", "drug", "procedure"}:
        where.append("category = ?")
        params.append(category)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    sql = (
        f"SELECT * FROM articles{where_clause} "
        f"ORDER BY {sort_col} {direction.upper()} NULLS LAST LIMIT ?"
    )
    params.append(limit)

    buf = io.StringIO()
    writer = csv.writer(buf)
    columns = [
        "qid", "category", "en_title", "ja_title",
        "en_bytes", "ja_bytes", "en_sections", "ja_sections",
        "en_refs", "ja_refs", "en_images", "ja_images",
        "en_pv_90d", "ja_pv_90d",
        "en_last_edit", "ja_last_edit",
        "gap_score", "updated_at",
    ]
    writer.writerow(columns)

    with connect(read_only=True) as conn:
        for row in conn.execute(sql, params):
            writer.writerow([row[c] for c in columns])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=wiki_gap.csv"},
    )


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    try:
        with connect(read_only=True) as conn:
            n = article_count(conn)
        return f"ok articles={n}\n"
    except Exception as exc:
        return PlainTextResponse(f"error: {exc}\n", status_code=500)

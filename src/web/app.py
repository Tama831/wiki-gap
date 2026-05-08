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
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.db.queries import article_count, connect, top_gap_articles
from src.translations import service as translations_service

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


# ─────────────────────────────────────────────────────────────────
# Phase 2A: 翻訳エディタ
# ─────────────────────────────────────────────────────────────────


class ChunkUpdate(BaseModel):
    dst: str


class MetaUpdate(BaseModel):
    ja_title_proposed: str | None = None
    status: str | None = None


def _get_article_meta(qid: str) -> dict | None:
    """ダッシュボード DB から article 行を引く (en/ja title が入る)。"""
    with connect(read_only=True) as conn:
        row = conn.execute(
            "SELECT * FROM articles WHERE qid = ?", (qid,)
        ).fetchone()
    return dict(row) if row else None


@app.get("/translate/{qid}", response_class=HTMLResponse)
def translate_page(request: Request, qid: str):
    """翻訳エディタを表示。translation が無ければ article から init を促す。"""
    article = _get_article_meta(qid)
    with connect(read_only=True) as conn:
        translation = translations_service.get_translation(conn, qid)

    return templates.TemplateResponse(
        request,
        "translate.html",
        {
            "qid": qid,
            "article": article,
            "translation": translation,
        },
    )


@app.post("/translate/{qid}/init")
def translate_init(qid: str, en_title: str | None = None,
                   ja_title_proposed: str | None = None,
                   overwrite: bool = False):
    """
    en wikitext を fetch + parse して翻訳プロジェクトを開始する。
    en_title が空ならダッシュボード DB の articles.en_title を使う。
    """
    if not en_title:
        article = _get_article_meta(qid)
        if not article or not article.get("en_title"):
            raise HTTPException(
                status_code=400,
                detail=f"qid={qid} の en_title が見つかりません。引数に en_title を渡してください。",
            )
        en_title = article["en_title"]

    try:
        with connect() as conn:
            t = translations_service.init_translation(
                conn, qid, en_title,
                ja_title_proposed=ja_title_proposed,
                overwrite=overwrite,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"failed to fetch/parse: {exc}")

    return JSONResponse({
        "qid": t["qid"],
        "en_title": t["en_title"],
        "ja_title_proposed": t.get("ja_title_proposed"),
        "source_revision_id": t.get("source_revision_id"),
        "n_chunks": len(t.get("chunks") or []),
    })


@app.put("/translate/{qid}/chunks/{chunk_id}")
def translate_update_chunk(qid: str, chunk_id: int, body: ChunkUpdate):
    try:
        with connect() as conn:
            chunk = translations_service.update_chunk_dst(
                conn, qid, chunk_id, body.dst
            )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "chunk": chunk}


@app.put("/translate/{qid}/meta")
def translate_update_meta(qid: str, body: MetaUpdate):
    try:
        with connect() as conn:
            translations_service.update_meta(
                conn, qid,
                ja_title_proposed=body.ja_title_proposed,
                status=body.status,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.get("/translate/{qid}/export")
def translate_export(qid: str, mode: str = Query("skeleton")):
    """訳文を 1 つの wikitext として出力 (download)。"""
    if mode not in {"skeleton", "compact"}:
        raise HTTPException(status_code=400, detail="mode must be skeleton|compact")
    with connect(read_only=True) as conn:
        try:
            wt = translations_service.export_wikitext(conn, qid, mode=mode)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    return Response(
        content=wt,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{qid}_ja.wikitext.txt"'
        },
    )


@app.get("/translations", response_class=HTMLResponse)
def translations_index(request: Request):
    with connect(read_only=True) as conn:
        items = translations_service.list_translations(conn)
    return templates.TemplateResponse(
        request, "translations_index.html", {"items": items}
    )


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    try:
        with connect(read_only=True) as conn:
            n = article_count(conn)
        return f"ok articles={n}\n"
    except Exception as exc:
        return PlainTextResponse(f"error: {exc}\n", status_code=500)

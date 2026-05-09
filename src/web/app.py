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
from src.wiki_auth import oauth as wiki_oauth
from src.wiki_auth import service as wiki_auth_service
from src.wiki_auth.client import WikiClient

# CSRF state for OAuth flow (single-process, in-memory)
_oauth_state_store: dict[str, dict] = {}


def _remember_state(state: str, return_to: str = "") -> None:
    import time
    _oauth_state_store[state] = {"time": time.time(), "return_to": return_to}
    cutoff = time.time() - 600
    for s in list(_oauth_state_store.keys()):
        if _oauth_state_store[s]["time"] < cutoff:
            _oauth_state_store.pop(s, None)


def _consume_state(state: str) -> dict | None:
    return _oauth_state_store.pop(state, None)

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
    translation_status: str | None = Query(None, alias="tstatus"),
    limit: int = Query(100, ge=1, le=1000),
):
    sort_col = SORT_COLUMNS.get(sort, "gap_score")
    if direction not in {"asc", "desc"}:
        direction = "desc"

    where = []
    params: list = []
    if category in {"disease", "drug", "procedure", "study"}:
        where.append("a.category = ?")
        params.append(category)
    if translation_status == "none":
        where.append("t.qid IS NULL")
    elif translation_status == "in_progress":
        where.append("t.status IN ('draft', 'review')")
    elif translation_status == "done":
        where.append("t.status = 'submitted'")
    elif translation_status in {"draft", "review", "submitted"}:
        where.append("t.status = ?")
        params.append(translation_status)
    where_clause = (" WHERE " + " AND ".join(where)) if where else ""

    null_pos = "NULLS LAST" if direction == "desc" else "NULLS FIRST"
    sql = (
        "SELECT a.*, t.status AS translation_status, "
        "       t.ja_title_proposed AS translation_ja_title, "
        "       t.updated_at AS translation_updated "
        "FROM articles a "
        "LEFT JOIN translations t ON a.qid = t.qid"
        + where_clause
        + f" ORDER BY a.{sort_col} {direction.upper()} {null_pos} LIMIT ?"
    )
    params.append(limit)

    with connect(read_only=True) as conn:
        rows = list(conn.execute(sql, params).fetchall())
        total = article_count(conn)
        # 翻訳ステータス集計
        status_counts: dict[str, int] = {}
        for s, n in conn.execute(
            "SELECT status, COUNT(*) FROM translations GROUP BY status"
        ).fetchall():
            status_counts[s or "unknown"] = n
        n_translations = sum(status_counts.values())

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
            "translation_status": translation_status or "",
            "limit": limit,
            "status_counts": status_counts,
            "n_translations": n_translations,
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

    sections: list[dict] = []
    if translation:
        # chunks を section_id で連続的にグループ化 + 文単位 split を付与
        from src.translations.wikitext import split_into_sentences
        current: dict | None = None
        for ch in translation.get("chunks") or []:
            sid = ch.get("section_id", 0)
            sheading = ch.get("section_heading") or ch.get("heading") or "(intro)"
            slevel = ch.get("section_level", ch.get("level", 0))
            ctype = ch.get("type", "para")
            # 文単位 split は para にだけ適用 (heading/block は塊のまま)
            if ctype == "para":
                ch["src_sentences"] = split_into_sentences(ch.get("src", ""))
            else:
                ch["src_sentences"] = [ch.get("src", "")]
            if current is None or current["section_id"] != sid:
                current = {
                    "section_id": sid,
                    "section_heading": sheading,
                    "section_level": slevel,
                    "chunks": [],
                }
                sections.append(current)
            current["chunks"].append(ch)

    return templates.TemplateResponse(
        request,
        "translate.html",
        {
            "qid": qid,
            "article": article,
            "translation": translation,
            "sections": sections,
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


def _wiki_user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


@app.get("/translate/{qid}/preview", response_class=HTMLResponse)
def translate_preview(request: Request, qid: str, lang: str = Query("ja")):
    """
    現在の dst を 1 つの wikitext に結合し、MediaWiki Parse API で
    HTML レンダリングしてプレビュー表示する (Wikipedia そっくり表示)。
    """
    if lang not in {"ja", "en"}:
        raise HTTPException(status_code=400, detail="lang must be ja|en")

    with connect(read_only=True) as conn:
        try:
            wt = translations_service.export_wikitext(conn, qid, mode="compact")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        translation = translations_service.get_translation(conn, qid)

    import httpx as _httpx
    url = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "text": wt,
        "contentmodel": "wikitext",
        "prop": "text",
        "disablelimitreport": "1",
        "format": "json",
        "maxlag": "30",
    }
    headers = {"User-Agent": _wiki_user_agent()}
    try:
        with _httpx.Client(timeout=30.0, headers=headers) as client:
            response = client.post(url, data=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Parse API error: {exc}")

    if "error" in payload:
        raise HTTPException(status_code=502, detail=f"MediaWiki: {payload['error']}")

    parsed = payload.get("parse") or {}
    rendered_html = (parsed.get("text") or {}).get("*", "")

    return templates.TemplateResponse(
        request,
        "preview.html",
        {
            "qid": qid,
            "title": (translation or {}).get("ja_title_proposed") or qid,
            "html": rendered_html,
            "lang": lang,
        },
    )


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


# ─────────────────────────────────────────────────────────────────
# Phase 2B: Wikipedia OAuth + 投稿
# ─────────────────────────────────────────────────────────────────


@app.get("/wiki/login")
def wiki_login(return_to: str = Query("", alias="return")):
    """OAuth 認可フロー開始 → meta.wikimedia.org にリダイレクト"""
    try:
        state = wiki_oauth.make_state()
        # 内部URLのみ許可 (open redirect 防止)
        safe_return = return_to if return_to.startswith("/") else ""
        _remember_state(state, safe_return)
        url = wiki_oauth.authorize_url(state)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=url, status_code=302)


@app.get("/wiki/oauth/callback")
def wiki_oauth_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """OAuth callback: code → access_token に交換 + 保存"""
    from fastapi.responses import RedirectResponse

    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code or state")
    state_entry = _consume_state(state)
    if state_entry is None:
        raise HTTPException(status_code=400, detail="invalid or expired state (CSRF check failed)")
    return_to = state_entry.get("return_to") or ""

    try:
        tokens = wiki_oauth.exchange_code_for_token(code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"token exchange failed: {exc}")

    # username を取得して保存 (meta.wikimedia.org = SUL ホーム、常にアカウント存在)
    username = None
    user_id_int = None
    try:
        with WikiClient(tokens.access_token, lang="meta") as wc:
            ui = wc.userinfo()
            username = ui.name
            user_id_int = ui.user_id
    except Exception:
        pass

    with connect() as conn:
        wiki_auth_service.save_tokens(
            conn, tokens, username=username, user_id=user_id_int
        )

    # 認証完了後、ログイン開始時に保存した return_to に戻る
    target = return_to if return_to and return_to.startswith("/") else "/translations"
    return RedirectResponse(url=target, status_code=302)


@app.post("/wiki/logout")
def wiki_logout():
    with connect() as conn:
        wiki_auth_service.clear_auth(conn)
    return {"ok": True}


@app.get("/wiki/userinfo")
def wiki_userinfo(refresh: bool = Query(False)):
    """現在のログイン状態を返す。refresh=true なら meta.wikimedia.org に再問い合わせ。"""
    with connect() as conn:
        auth = wiki_auth_service.get_auth(conn)
        if not auth:
            return {"logged_in": False}
        # username が未取得 or refresh 要求なら meta から取り直す
        if refresh or not auth.get("username"):
            access_token = wiki_auth_service.get_valid_access_token(conn)
            if access_token:
                try:
                    with WikiClient(access_token, lang="meta") as wc:
                        ui = wc.userinfo()
                        wiki_auth_service.update_username(conn, ui.name, ui.user_id)
                        auth = wiki_auth_service.get_auth(conn)
                except Exception:
                    pass
    return {
        "logged_in": True,
        "username": (auth or {}).get("username"),
        "user_id": (auth or {}).get("user_id"),
        "scopes": (auth or {}).get("scopes"),
        "token_expires_at": (auth or {}).get("token_expires_at"),
    }


class PublishRequest(BaseModel):
    target_lang: str = "ja"           # "ja" | "en"
    namespace: str = "下書き"          # "下書き" / "Draft" / "" (本記事 — 注意)
    title: str | None = None           # None なら ja_title_proposed を使う
    summary: str | None = None         # None なら自動生成
    minor: bool = False
    confirm: bool = False              # 投稿確認チェック (true 必須)


@app.post("/translate/{qid}/publish")
def translate_publish(qid: str, body: PublishRequest):
    """
    現在の dst (compact mode) を結合して Wikipedia の指定ページに投稿する。
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm=true が必要です (投稿前確認のため)",
        )
    if body.target_lang not in {"ja", "en"}:
        raise HTTPException(status_code=400, detail="target_lang must be 'ja' or 'en'")

    with connect() as conn:
        access_token = wiki_auth_service.get_valid_access_token(conn)
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail="Wikipedia にログインしていません。/wiki/login から認証してください。",
            )

        translation = translations_service.get_translation(conn, qid)
        if not translation:
            raise HTTPException(status_code=404, detail=f"no translation for {qid}")

        try:
            wikitext = translations_service.export_wikitext(conn, qid, mode="compact")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # タイトル決定
    base_title = body.title or translation.get("ja_title_proposed") or translation.get("en_title")
    if not base_title:
        raise HTTPException(status_code=400, detail="ja_title_proposed が未設定です")

    namespace = body.namespace.strip()
    full_title = f"{namespace}:{base_title}" if namespace else base_title

    # 編集要約
    contact_url = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    auto_summary = body.summary or (
        f"翻訳支援ツール (wiki-gap, {contact_url}) を用いた "
        f"[[:{body.target_lang}:{translation.get('en_title', '')}]] からの翻訳下書き"
    )

    try:
        with WikiClient(access_token, lang=body.target_lang) as wc:
            result = wc.edit_page(
                title=full_title,
                text=wikitext,
                summary=auto_summary,
                minor=body.minor,
            )
    except Exception as exc:
        with connect() as conn:
            wiki_auth_service.log_publish(
                conn,
                qid=qid,
                target_lang=body.target_lang,
                target_namespace=namespace,
                target_title=full_title,
                edit_summary=auto_summary,
                revision_id=None,
                status="failed",
                error_message=str(exc),
            )
        raise HTTPException(status_code=502, detail=f"publish failed: {exc}")

    with connect() as conn:
        wiki_auth_service.log_publish(
            conn,
            qid=qid,
            target_lang=body.target_lang,
            target_namespace=namespace,
            target_title=full_title,
            edit_summary=auto_summary,
            revision_id=result.new_revision_id,
            status="success" if result.success else "failed",
        )

    return {
        "ok": result.success,
        "page_title": result.page_title,
        "page_url": result.page_url,
        "revision_id": result.new_revision_id,
        "edit_summary": auto_summary,
    }


@app.get("/translate/{qid}/link_check")
def translate_link_check(qid: str):
    """
    訳文中の `[[link]]` をすべて検出して、ja Wikipedia に該当記事があるか
    確認する。なければ英語版への interwiki link 候補を提案する。
    """
    from src.translations.link_check import check_chunks
    with connect(read_only=True) as conn:
        translation = translations_service.get_translation(conn, qid)
    if not translation:
        raise HTTPException(status_code=404, detail=f"no translation for {qid}")
    return check_chunks(translation.get("chunks") or [])


@app.post("/translate/{qid}/link_fix")
def translate_link_fix(qid: str):
    """
    赤リンクを `[[:en:Foo|display]]` 形式に一括書き換えて chunks_json を更新。
    返り値: {n_changed, links} (修正された件数 + 結果)
    """
    from src.translations.link_check import apply_interwiki_fix
    import json as _json
    from datetime import UTC as _UTC, datetime as _dt
    with connect() as conn:
        translation = translations_service.get_translation(conn, qid)
        if not translation:
            raise HTTPException(status_code=404, detail=f"no translation for {qid}")
        chunks = translation.get("chunks") or []
        new_chunks, n_changed = apply_interwiki_fix(chunks)
        if n_changed > 0:
            now = _dt.now(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "UPDATE translations SET chunks_json = ?, updated_at = ? WHERE qid = ?",
                (_json.dumps(new_chunks, ensure_ascii=False), now, qid),
            )
            conn.commit()
    return {"n_changed": n_changed}


@app.get("/translate/{qid}/term_check")
def translate_term_check(qid: str):
    """
    医学用語チェック: en src 中の専門用語が ja dst で標準訳語 (MeSH /
    日本医学会用語集 / wiki-ja 慣行) で訳されているかチェック。
    """
    from src.translations.term_check import check_all_chunks
    with connect(read_only=True) as conn:
        translation = translations_service.get_translation(conn, qid)
    if not translation:
        raise HTTPException(status_code=404, detail=f"no translation for {qid}")
    return check_all_chunks(translation.get("chunks") or [])


@app.get("/translate/{qid}/last_publish")
def translate_last_publish(qid: str):
    with connect(read_only=True) as conn:
        last = wiki_auth_service.latest_publish(conn, qid)
    return last or {}


class HandoffLog(BaseModel):
    target_lang: str
    namespace: str
    title: str
    edit_summary: str


@app.post("/translate/{qid}/handoff_log")
def translate_handoff_log(qid: str, body: HandoffLog):
    """半自動 handoff モード (clipboard + 編集画面オープン) の利用ログ。"""
    with connect() as conn:
        wiki_auth_service.log_publish(
            conn,
            qid=qid,
            target_lang=body.target_lang,
            target_namespace=body.namespace,
            target_title=body.title,
            edit_summary=body.edit_summary,
            revision_id=None,
            status="handoff_opened",
        )
    return {"ok": True}


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    try:
        with connect(read_only=True) as conn:
            n = article_count(conn)
        return f"ok articles={n}\n"
    except Exception as exc:
        return PlainTextResponse(f"error: {exc}\n", status_code=500)

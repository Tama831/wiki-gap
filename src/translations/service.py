"""
翻訳プロジェクトの CRUD / fetch / export ロジック。
"""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

import httpx

from src.translations.wikitext import Chunk, parse_paragraphs


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Wikipedia 取得 ──

def _user_agent() -> str:
    import os
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


def fetch_en_wikitext(en_title: str, timeout: float = 30.0) -> tuple[str, int]:
    """
    en Wikipedia から title の wikitext を取得する。
    返り値: (wikitext, revision_id)
    """
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "parse",
        "page": en_title,
        "prop": "wikitext|revid",
        "redirects": "1",
        "format": "json",
        "maxlag": "30",
    }
    with httpx.Client(timeout=timeout, headers={"User-Agent": _user_agent()}) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    if "error" in payload:
        raise RuntimeError(f"MediaWiki error: {payload['error']}")

    parse = payload.get("parse") or {}
    wt = (parse.get("wikitext") or {}).get("*", "")
    revid = parse.get("revid", 0)
    if not wt:
        raise RuntimeError(f"empty wikitext for {en_title!r}")
    return wt, int(revid)


# ── DB ロジック ──

def get_translation(conn: sqlite3.Connection, qid: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM translations WHERE qid = ?", (qid,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["chunks"] = json.loads(d.pop("chunks_json"))
    return d


def list_translations(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT qid, en_title, ja_title_proposed, status, "
        "source_revision_id, created_at, updated_at "
        "FROM translations ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def init_translation(
    conn: sqlite3.Connection,
    qid: str,
    en_title: str,
    ja_title_proposed: str | None = None,
    overwrite: bool = False,
) -> dict:
    """
    新規翻訳プロジェクトを作成する。
    en wikitext を fetch + parse_sections して chunks_json として保存。

    既存の翻訳がある場合:
      overwrite=True なら src のみ更新 (dst は既存値を維持)
      overwrite=False なら何もせず既存を返す
    """
    existing = get_translation(conn, qid)
    if existing and not overwrite:
        return existing

    wikitext, revid = fetch_en_wikitext(en_title)
    new_chunks = parse_paragraphs(wikitext)

    if existing:
        # src を更新するが dst は src 一致で merge (段落単位)
        old_chunks = existing.get("chunks", [])
        old_by_src = {(c.get("src") or "").strip(): c.get("dst", "") for c in old_chunks}
        for nc in new_chunks:
            key = nc.src.strip()
            if key in old_by_src and old_by_src[key]:
                nc.dst = old_by_src[key]

    chunks_json = json.dumps([c.to_dict() for c in new_chunks], ensure_ascii=False)
    now = now_iso()

    if existing:
        conn.execute(
            "UPDATE translations SET source_revision_id = ?, source_wikitext = ?, "
            "chunks_json = ?, updated_at = ? WHERE qid = ?",
            (revid, wikitext, chunks_json, now, qid),
        )
    else:
        conn.execute(
            "INSERT INTO translations (qid, en_title, ja_title_proposed, "
            "source_revision_id, source_wikitext, chunks_json, status, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (
                qid, en_title, ja_title_proposed, revid, wikitext,
                chunks_json, now, now,
            ),
        )

    conn.commit()
    result = get_translation(conn, qid)
    assert result is not None
    return result


def update_chunk_dst(
    conn: sqlite3.Connection, qid: str, chunk_id: int, dst: str
) -> dict:
    """
    指定 chunk の dst (訳文) を更新する。
    """
    row = conn.execute(
        "SELECT chunks_json FROM translations WHERE qid = ?", (qid,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no translation for qid={qid}")

    chunks = json.loads(row["chunks_json"])
    target = None
    for c in chunks:
        if int(c.get("id", -1)) == chunk_id:
            target = c
            break
    if target is None:
        raise KeyError(f"no chunk id={chunk_id} in qid={qid}")

    target["dst"] = dst
    conn.execute(
        "UPDATE translations SET chunks_json = ?, updated_at = ? WHERE qid = ?",
        (json.dumps(chunks, ensure_ascii=False), now_iso(), qid),
    )
    conn.commit()

    return target


def update_meta(
    conn: sqlite3.Connection,
    qid: str,
    *,
    ja_title_proposed: str | None = None,
    status: str | None = None,
) -> None:
    sets: list[str] = []
    params: list[Any] = []
    if ja_title_proposed is not None:
        sets.append("ja_title_proposed = ?")
        params.append(ja_title_proposed)
    if status is not None:
        if status not in {"draft", "review", "submitted"}:
            raise ValueError(f"invalid status: {status}")
        sets.append("status = ?")
        params.append(status)
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(now_iso())
    params.append(qid)
    conn.execute(
        f"UPDATE translations SET {', '.join(sets)} WHERE qid = ?",
        params,
    )
    conn.commit()


def export_wikitext(
    conn: sqlite3.Connection, qid: str, *, mode: str = "skeleton"
) -> str:
    """
    翻訳結果を 1 つの wikitext として書き出す。

    mode:
      'compact'  : dst が空の section を skip
      'skeleton' : dst が空でも heading skeleton を残す (default、編集しやすい)
    """
    from src.translations.wikitext import (
        chunks_to_wikitext,
        chunks_to_wikitext_with_skeleton,
    )

    t = get_translation(conn, qid)
    if t is None:
        raise KeyError(f"no translation for qid={qid}")

    chunks = t["chunks"]
    if mode == "skeleton":
        return chunks_to_wikitext_with_skeleton(chunks)
    return chunks_to_wikitext(chunks)

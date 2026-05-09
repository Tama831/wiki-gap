"""
wiki_auth テーブルの CRUD + 自動 refresh。
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from src.wiki_auth.oauth import OAuthTokens, refresh_access_token


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expires_iso(expires_in_seconds: int) -> str:
    expiry = datetime.now(UTC) + timedelta(seconds=expires_in_seconds - 60)
    return expiry.strftime("%Y-%m-%dT%H:%M:%SZ")


def save_tokens(
    conn: sqlite3.Connection,
    tokens: OAuthTokens,
    *,
    username: str | None = None,
    user_id: int | None = None,
) -> None:
    now = now_iso()
    expiry = _expires_iso(tokens.expires_in)
    # single row: id=1
    conn.execute(
        """
        INSERT INTO wiki_auth (id, username, user_id, access_token, refresh_token,
                               token_expires_at, scopes, created_at, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          username = excluded.username,
          user_id = excluded.user_id,
          access_token = excluded.access_token,
          refresh_token = COALESCE(excluded.refresh_token, wiki_auth.refresh_token),
          token_expires_at = excluded.token_expires_at,
          scopes = excluded.scopes,
          updated_at = excluded.updated_at
        """,
        (
            username, user_id,
            tokens.access_token,
            tokens.refresh_token,
            expiry,
            tokens.scope,
            now, now,
        ),
    )
    conn.commit()


def get_auth(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM wiki_auth WHERE id = 1"
    ).fetchone()
    return dict(row) if row else None


def clear_auth(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM wiki_auth WHERE id = 1")
    conn.commit()


def update_username(conn: sqlite3.Connection, username: str, user_id: int | None) -> None:
    conn.execute(
        "UPDATE wiki_auth SET username = ?, user_id = ?, updated_at = ? WHERE id = 1",
        (username, user_id, now_iso()),
    )
    conn.commit()


def access_token_expired(auth: dict) -> bool:
    expiry_str = auth.get("token_expires_at")
    if not expiry_str:
        return False
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except Exception:
        return False
    return datetime.now(UTC) >= expiry


def get_valid_access_token(conn: sqlite3.Connection) -> str | None:
    """
    現在の access_token を返す。expire 間近なら refresh_token で更新する。
    認証が無いか refresh も失敗したら None。
    """
    auth = get_auth(conn)
    if not auth:
        return None
    if not access_token_expired(auth):
        return auth["access_token"]

    # refresh
    rt = auth.get("refresh_token")
    if not rt:
        # expire 済みで refresh も無い → 再ログイン必要
        return None

    try:
        new_tokens = refresh_access_token(rt)
    except Exception:
        return None

    save_tokens(
        conn, new_tokens,
        username=auth.get("username"),
        user_id=auth.get("user_id"),
    )
    return new_tokens.access_token


def log_publish(
    conn: sqlite3.Connection,
    *,
    qid: str,
    target_lang: str,
    target_namespace: str,
    target_title: str,
    edit_summary: str,
    revision_id: int | None,
    status: str,
    error_message: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO publish_log (
          qid, target_lang, target_namespace, target_title, edit_summary,
          revision_id, status, error_message, posted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            qid, target_lang, target_namespace, target_title, edit_summary,
            revision_id, status, error_message, now_iso(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def latest_publish(conn: sqlite3.Connection, qid: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM publish_log WHERE qid = ? ORDER BY posted_at DESC LIMIT 1",
        (qid,),
    ).fetchone()
    return dict(row) if row else None

"""
利用者ページ管理: テンプレート CRUD + placeholder 自動展開。

サポート placeholder:
  {{wiki_gap:translated_articles}}
    → translations.status='submitted' から投稿済記事の箇条書きを生成
    例 (本記事に投稿された場合):
      * [[Some Article]] (2026年5月)
    例 (利用者サブページに投稿された場合):
      * [[利用者:Username/Foo|Foo]] (2026年6月)
  {{wiki_gap:username}}
    → wiki_auth テーブルから取得した Wikipedia ユーザ名 (OAuth ログイン時に保存)
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


DEFAULT_TEMPLATE = """== このアカウントについて ==

<!-- 自由に書き換えてください。以下は雛形です。 -->
日本語版ウィキペディアの整備に少しずつ参加しています。

特に関心のある分野:
* (関心分野 1)
* (関心分野 2)

== 編集の方針 ==

* 英語版からの翻訳記事は、[[Wikipedia:翻訳のガイドライン]] に従い、編集要約に翻訳元の言語間リンクと版番号 (oldid) を必ず記載します。
* 機械翻訳支援ツールを用いる場合も、人手で全文を通読・確認した上で投稿します。
* 日本語版に該当記事がない用語は {{tlp|仮リンク}} で英語版へのリンクを残します。

== これまでに翻訳した記事 ==

{{wiki_gap:translated_articles}}

== 連絡 ==

ご意見・修正のご提案は[[利用者・トーク:{{wiki_gap:username}}|私のトークページ]]までお気軽にどうぞ。

== Babel ==

{{Babel|ja|en-2}}
"""


def get_user_page(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM user_pages WHERE id = 1").fetchone()
    return dict(row) if row else None


def get_or_init_user_page(conn: sqlite3.Connection, default_username: str | None = None) -> dict:
    existing = get_user_page(conn)
    if existing:
        return existing
    now = now_iso()
    conn.execute(
        "INSERT INTO user_pages (id, username, lang, template_wikitext, created_at, updated_at) "
        "VALUES (1, ?, 'ja', ?, ?, ?)",
        (default_username, DEFAULT_TEMPLATE, now, now),
    )
    conn.commit()
    return get_user_page(conn)  # type: ignore[return-value]


def save_user_page(
    conn: sqlite3.Connection,
    template_wikitext: str,
    *,
    username: str | None = None,
    lang: str | None = None,
) -> None:
    now = now_iso()
    existing = get_user_page(conn)
    if existing:
        sets = ["template_wikitext = ?", "updated_at = ?"]
        params: list = [template_wikitext, now]
        if username is not None:
            sets.append("username = ?")
            params.append(username)
        if lang is not None:
            sets.append("lang = ?")
            params.append(lang)
        params.append(1)
        conn.execute(f"UPDATE user_pages SET {', '.join(sets)} WHERE id = ?", params)
    else:
        conn.execute(
            "INSERT INTO user_pages (id, username, lang, template_wikitext, created_at, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (username, lang or "ja", template_wikitext, now, now),
        )
    conn.commit()


# ── placeholder expansion ──

_PLACEHOLDER_RE = re.compile(r"\{\{wiki_gap:(?P<name>[a-z_]+)\}\}")


def _gen_translated_articles_list(conn: sqlite3.Connection) -> str:
    """status='submitted' の翻訳を箇条書きにする。"""
    rows = conn.execute(
        """
        SELECT t.qid, t.ja_title_proposed, t.en_title, t.updated_at,
               p.target_title, p.target_lang, p.target_namespace
        FROM translations t
        LEFT JOIN (
          SELECT qid, target_lang, target_title, target_namespace,
                 ROW_NUMBER() OVER (
                   PARTITION BY qid
                   ORDER BY
                     CASE
                       WHEN target_namespace = '' OR target_namespace IS NULL THEN 0
                       WHEN target_namespace IN ('利用者', 'User') THEN 1
                       WHEN target_namespace IN ('Draft', 'Wikipedia') THEN 2
                       ELSE 3
                     END,
                     posted_at DESC
                 ) AS rn
          FROM publish_log
          WHERE status IN ('success', 'handoff_opened')
        ) p ON t.qid = p.qid AND p.rn = 1
        WHERE t.status = 'submitted'
        ORDER BY t.updated_at
        """
    ).fetchall()

    if not rows:
        return "* (まだ投稿された翻訳がありません)"

    items: list[str] = []
    for r in rows:
        d = dict(r)
        target_title = d.get("target_title") or d.get("ja_title_proposed") or d.get("en_title")
        if not target_title:
            continue
        # mainspace のときは [[Title]]、namespace 付きは [[ns:Title|displayed]]
        if ":" in target_title and d.get("target_namespace"):
            display = target_title.split("/", 1)[-1]  # 利用者:Foo/Bar → Bar
            link = f"[[{target_title}|{display}]]"
        else:
            link = f"[[{target_title}]]"
        ymd = (d.get("updated_at") or "")[:7]  # YYYY-MM
        if ymd and "-" in ymd:
            y, m = ymd.split("-")
            date_str = f"{y}年{int(m)}月"
        else:
            date_str = ""
        items.append(f"* {link}" + (f" ({date_str})" if date_str else ""))

    return "\n".join(items)


def _get_username(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT username FROM user_pages WHERE id = 1"
    ).fetchone()
    if row and row["username"]:
        return row["username"]
    # fallback: wiki_auth テーブル
    row = conn.execute("SELECT username FROM wiki_auth WHERE id = 1").fetchone()
    if row and row["username"]:
        return row["username"]
    return "<username>"


def expand_placeholders(template: str, conn: sqlite3.Connection) -> str:
    """テンプレ内の {{wiki_gap:<name>}} を実値に置換する。"""
    def _replace(m: re.Match) -> str:
        name = m.group("name")
        if name == "translated_articles":
            return _gen_translated_articles_list(conn)
        if name == "username":
            return _get_username(conn)
        return m.group(0)  # 未知の placeholder はそのまま残す
    return _PLACEHOLDER_RE.sub(_replace, template)

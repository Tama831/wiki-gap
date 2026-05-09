"""
認証付き MediaWiki API クライアント。

- Bearer トークン認証
- userinfo 取得 (ユーザ名検証)
- CSRF token 取得
- ページ編集 (action=edit)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/PLACEHOLDER/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


def api_url(lang: str = "ja") -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


@dataclass
class UserInfo:
    user_id: int
    name: str
    groups: list[str]


@dataclass
class EditResult:
    success: bool
    page_title: str
    revision_id: int | None
    new_revision_id: int | None
    page_url: str
    raw: dict


class WikiClient:
    """
    Bearer 認証付き MediaWiki API client。1 言語 (ja or en) に固定して使う。
    """

    def __init__(
        self,
        access_token: str,
        lang: str = "ja",
        timeout_seconds: float = 30.0,
    ) -> None:
        self._lang = lang
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "User-Agent": _user_agent(),
                "Authorization": f"Bearer {access_token}",
            },
            follow_redirects=True,
        )

    def __enter__(self) -> "WikiClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._client.close()

    def userinfo(self) -> UserInfo:
        url = api_url(self._lang)
        params = {
            "action": "query",
            "meta": "userinfo",
            "uiprop": "groups",
            "format": "json",
            "maxlag": "30",
        }
        r = self._client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(f"userinfo error: {payload['error']}")
        ui = (payload.get("query") or {}).get("userinfo") or {}
        return UserInfo(
            user_id=int(ui.get("id", 0)),
            name=ui.get("name", ""),
            groups=ui.get("groups") or [],
        )

    def csrf_token(self) -> str:
        url = api_url(self._lang)
        params = {
            "action": "query",
            "meta": "tokens",
            "type": "csrf",
            "format": "json",
            "maxlag": "30",
        }
        r = self._client.get(url, params=params)
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(f"csrf token error: {payload['error']}")
        token = (payload.get("query") or {}).get("tokens", {}).get("csrftoken")
        if not token:
            raise RuntimeError(f"no csrf token in response: {payload}")
        return token

    def edit_page(
        self,
        title: str,
        text: str,
        *,
        summary: str = "",
        bot: bool = False,
        minor: bool = False,
        create_only: bool = False,
        no_create: bool = False,
        recreate: bool = True,
    ) -> EditResult:
        """
        action=edit でページを丸ごと書き換える/作成する。

        Args:
          create_only: 既存ページがあるとエラー
          no_create  : 既存ページが無いとエラー
          recreate   : 削除済みページなら再作成する
        """
        token = self.csrf_token()
        url = api_url(self._lang)
        data = {
            "action": "edit",
            "title": title,
            "text": text,
            "summary": summary,
            "format": "json",
            "token": token,
            "maxlag": "30",
        }
        if bot:
            data["bot"] = "1"
        if minor:
            data["minor"] = "1"
        if create_only:
            data["createonly"] = "1"
        if no_create:
            data["nocreate"] = "1"
        if recreate:
            data["recreate"] = "1"

        r = self._client.post(url, data=data)
        r.raise_for_status()
        payload = r.json()
        if "error" in payload:
            raise RuntimeError(f"edit error: {payload['error']}")

        edit = payload.get("edit") or {}
        success = edit.get("result") == "Success"
        from urllib.parse import quote
        page_url = (
            f"https://{self._lang}.wikipedia.org/wiki/"
            f"{quote(title.replace(' ', '_'), safe=':')}"
        )
        return EditResult(
            success=success,
            page_title=edit.get("title", title),
            revision_id=edit.get("oldrevid"),
            new_revision_id=edit.get("newrevid"),
            page_url=page_url,
            raw=payload,
        )

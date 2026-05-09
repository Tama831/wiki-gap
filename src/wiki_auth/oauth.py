"""
Wikipedia (Wikimedia) OAuth 2.0 フロー。

参考:
  https://www.mediawiki.org/wiki/OAuth/For_Developers
  https://api.wikimedia.org/wiki/Authentication

エンドポイント:
  Authorize:    https://meta.wikimedia.org/w/rest.php/oauth2/authorize
  Token:        https://meta.wikimedia.org/w/rest.php/oauth2/access_token

フロー (authorization code grant):
  1. /authorize?response_type=code&client_id=<id>&redirect_uri=<cb>&state=<csrf>
  2. ユーザがブラウザで承認 → callback URL に code + state がリダイレクト
  3. /access_token?grant_type=authorization_code&code=<code>&redirect_uri=<cb>
       (basic auth: client_id:client_secret) → access_token + refresh_token
  4. API 呼び出し時 `Authorization: Bearer <access_token>`
  5. expire したら refresh_token で更新
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/authorize"
TOKEN_URL = "https://meta.wikimedia.org/w/rest.php/oauth2/access_token"


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


_HTTP_HEADERS = {"User-Agent": "WikiGapDetector/0.1 (https://github.com/Tama831/wiki-gap)"}


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_in: int  # seconds
    token_type: str  # "Bearer"
    scope: str = ""


def _client_id() -> str:
    cid = os.getenv("WIKIPEDIA_OAUTH_CLIENT_ID", "").strip()
    if not cid:
        raise RuntimeError("WIKIPEDIA_OAUTH_CLIENT_ID is not set in .env")
    return cid


def _client_secret() -> str:
    cs = os.getenv("WIKIPEDIA_OAUTH_CLIENT_SECRET", "").strip()
    if not cs:
        raise RuntimeError("WIKIPEDIA_OAUTH_CLIENT_SECRET is not set in .env")
    return cs


def callback_url() -> str:
    return os.getenv(
        "WIKIPEDIA_OAUTH_CALLBACK",
        "http://100.104.67.25:8766/wiki/oauth/callback",
    )


def make_state() -> str:
    """CSRF state token (URL-safe)."""
    return secrets.token_urlsafe(24)


def authorize_url(state: str) -> str:
    """
    認可 URL を生成する。ユーザはここに redirect されてブラウザで承認する。
    """
    params = {
        "response_type": "code",
        "client_id": _client_id(),
        "redirect_uri": callback_url(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str, *, timeout_seconds: float = 30.0) -> OAuthTokens:
    """
    callback で受け取った authorization code を access_token に交換する。
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url(),
    }
    auth = (_client_id(), _client_secret())
    headers = {"User-Agent": _user_agent()}

    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        response = client.post(TOKEN_URL, data=data, auth=auth)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OAuth token exchange failed: HTTP {response.status_code} {response.text!r}"
            )
        payload = response.json()

    if "error" in payload:
        raise RuntimeError(f"OAuth error: {payload}")

    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_in=int(payload.get("expires_in", 14400)),
        token_type=payload.get("token_type", "Bearer"),
        scope=payload.get("scope", ""),
    )


def refresh_access_token(refresh_token: str, *, timeout_seconds: float = 30.0) -> OAuthTokens:
    """
    refresh_token から新しい access_token を取得する。
    """
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    auth = (_client_id(), _client_secret())
    headers = {"User-Agent": _user_agent()}

    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        response = client.post(TOKEN_URL, data=data, auth=auth)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OAuth refresh failed: HTTP {response.status_code} {response.text!r}"
            )
        payload = response.json()

    if "error" in payload:
        raise RuntimeError(f"OAuth refresh error: {payload}")

    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", refresh_token),
        expires_in=int(payload.get("expires_in", 14400)),
        token_type=payload.get("token_type", "Bearer"),
        scope=payload.get("scope", ""),
    )

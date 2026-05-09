"""
Wikimedia REST API から記事の pageviews を取得する。

Endpoint:
  https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/{title}/daily/{start}/{end}

Note:
  - 直近 90 日 (今日含めない) の合計を返す
  - title は URL-encode する必要がある (空白 → %20, 日本語 → percent-encoded UTF-8)
  - REST API 自体は maxlag を持たないが、エチケット上 User-Agent 必須
  - 1 記事 = 1 API call (per-article 単位、1 リクエストで 90 日分まとめ取り可)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx

REST_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"


def _user_agent() -> str:
    contact = os.getenv("WIKI_GAP_CONTACT_URL", "https://github.com/Tama831/wiki-gap")
    return f"WikiGapDetector/0.1 ({contact})"


def _yyyymmdd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


async def fetch_pageviews_90d(
    client: httpx.AsyncClient,
    lang: str,
    title: str,
    end_date: datetime | None = None,
) -> int | None:
    """
    指定言語・記事の直近 90 日 pageviews 合計を返す。

    返り値:
      int: 合計閲覧数
      None: 記事が存在しない / 404 / その他取得失敗

    Args:
      client: 共有 httpx.AsyncClient (User-Agent 設定済みであること)
      lang: "en" | "ja"
      title: 記事タイトル (URL-encode 前のまま渡す)
      end_date: 終端日 (UTC, default = 今日)
    """
    if not title:
        return None

    if end_date is None:
        end_date = datetime.now(UTC)

    # 直近 90 日 (end は inclusive、今日も含む)
    start = end_date - timedelta(days=90)
    title_enc = quote(title.replace(" ", "_"), safe="")

    url = (
        f"{REST_BASE}/{lang}.wikipedia/all-access/user/{title_enc}/daily/"
        f"{_yyyymmdd(start)}/{_yyyymmdd(end_date)}"
    )

    try:
        response = await client.get(url, headers={"User-Agent": _user_agent()})
        if response.status_code == 404:
            return 0  # 記事はあるが PV データがない (新規記事等) → 0 扱い
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError:
        return None

    items = payload.get("items", []) or []
    total = sum(int(item.get("views", 0) or 0) for item in items)
    return total


async def _smoke() -> int:
    async with httpx.AsyncClient(timeout=30.0) as client:
        en_pv = await fetch_pageviews_90d(client, "en", "Parkinson's disease")
        ja_pv = await fetch_pageviews_90d(client, "ja", "パーキンソン病")
        print(f"en Parkinson's disease 90d pv: {en_pv}")
        print(f"ja パーキンソン病 90d pv: {ja_pv}")

        # 確実に薄い記事 (en のみ・ja 無し)
        ja_missing = await fetch_pageviews_90d(client, "ja", "Schindler disease")
        print(f"ja Schindler disease (missing) 90d pv: {ja_missing}")
    return 0


if __name__ == "__main__":
    import asyncio
    import sys
    sys.exit(asyncio.run(_smoke()))

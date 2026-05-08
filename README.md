# wiki-gap — Wikipedia 日英ギャップ検出ツール (医学系)

英語版と日本語版 Wikipedia の医学系記事の **情報量ギャップを検出** し、日本語版への加筆・翻訳の起点を提供するツール。

> **方針**: 記事の自動生成・自動投稿はしません。本ツールは **検出 → 人間 (医師) の編集を支援** するだけです。Wikipedia の LLM 利用ポリシーと両立する設計です。

## 設計コンセプト

- **MVP ファースト**: Phase 1 はダッシュボードでギャップが見えるところまで
- **Wikimedia エチケット必守**: User-Agent 明記, `maxlag=5`, レート制限 1.5 req/sec, exponential backoff
- **closure-as-a-service**: 検出結果はダッシュボードで完結。読み流しても OK な設計

## クイックスタート

```bash
cd ~/wiki-gap

# venv + pip
python3 -m venv .venv
. .venv/bin/activate
pip install -e .

# 環境変数の設定
cp .env.example .env
# .env を編集して WIKI_GAP_CONTACT_URL に GitHub リポ URL を入れる

# DB 初期化
python scripts/init_db.py

# クロール (テスト規模)
python scripts/run_crawl.py --category disease --limit 100

# クロール (フル: 段階的に拡張)
python scripts/run_crawl.py --category disease --limit 1000   # 段階1
python scripts/run_crawl.py --category disease --limit 0      # 段階2 (無制限)
python scripts/run_crawl.py --all --limit 0                   # 段階3 (全カテゴリ)

# ダッシュボード起動 (Tailscale IP 限定 bind = public IP には漏らさない)
# Hetzner の Tailscale IP は `tailscale ip -4` で確認 (例: 100.104.67.25)
uvicorn src.web.app:app --host 100.104.67.25 --port 8766
```

> **Note**: 後日 [uv](https://docs.astral.sh/uv/) への移行も `pyproject.toml` を維持しているのでそのまま `uv sync` で動きます。

## アーキテクチャ

```
Wikidata SPARQL ─┐
                  ├─→ pipeline.py ─→ SQLite (data/wiki_gap.db) ─→ FastAPI ダッシュボード
MediaWiki API ──┤                            │
                 │                            └─→ snapshots テーブル (日次)
Pageviews API ──┘
```

### モジュール構成

- `src/crawler/wikidata.py` — Wikidata SPARQL で seed QID + sitelink タイトルを取得
- `src/crawler/mediawiki.py` — MediaWiki API で記事メタデータを取得 (bytes/sections/refs/images/last_edit)
- `src/crawler/pageviews.py` — Wikimedia REST API で 90日 pageviews を取得
- `src/crawler/pipeline.py` — クロール全体のオーケストレーション
- `src/scoring/gap.py` — ギャップスコア算出 (調整しやすいよう独立)
- `src/db/schema.sql` — SQLite スキーマ
- `src/db/queries.py` — upsert / read クエリ
- `src/web/app.py` — FastAPI + Jinja2 ダッシュボード

## ギャップスコア定義

```
両方ある:
  gap_score = log(max_pv + 1) × log(bigger_bytes + 1) × imbalance / 10
  imbalance = 1 - smaller_bytes / bigger_bytes

片側欠損 (完全ギャップ):
  gap_score = log(max_pv + 1) × log(bigger_bytes + 1) × 2 / 10
```

意図: pv が多い + 大記事 + アンバランスが大きい記事を上位に。完全ギャップは ×2 ブースト。

## API エチケット

Wikimedia のインフラに迷惑をかけないため:

- **User-Agent**: `WikiGapDetector/0.1 (<WIKI_GAP_CONTACT_URL>)`
- **maxlag**: `5` (MediaWiki API)
- **レート**: 1.5 req/sec, 並列 3
- **backoff**: 429 / `maxlag` エラーは exponential (1 → 2 → 4 → ... 最大 60s)
- **実行時間帯**: JST 03:00 (Wikimedia の負荷の薄い時間)

## デプロイ (systemd)

サーバー TZ が JST であること (`timedatectl` で確認)。

```bash
# 1) ファイル配置
sudo cp deploy/wiki-gap.service /etc/systemd/system/
sudo cp deploy/wiki-gap-crawl.service /etc/systemd/system/
sudo cp deploy/wiki-gap-crawl.timer /etc/systemd/system/

# 2) reload + 有効化
sudo systemctl daemon-reload
sudo systemctl enable --now wiki-gap.service       # ダッシュボード
sudo systemctl enable --now wiki-gap-crawl.timer   # 日次クロール (JST 03:00)

# 3) 動作確認
systemctl status wiki-gap.service
systemctl list-timers wiki-gap-crawl.timer
journalctl -u wiki-gap-crawl.service -n 50
```

### Tailscale 経由でダッシュボードにアクセス
- ダッシュボードは Tailscale IP (`100.104.67.25:8766`) に bind (public IP には漏らさない)
- Tailnet 内のデバイス (Mac / iPhone / iPad など) からは `http://100.104.67.25:8766` で見れる
- 他人 (Tailnet 外) からは IP もポートも見えない
- Hetzner ノードの Tailscale IP は `tailscale ip -4` で確認

## トラブルシュート

| 症状 | 確認 |
|---|---|
| SPARQL 502/timeout | Wikidata Query Service の lag を疑う ([status](https://www.wikidata.org/wiki/Wikidata:Status_updates)) |
| MediaWiki API 429 | `--rate-limit 0.5` に下げる |
| ダッシュボードが空 | `data/wiki_gap.db` の有無 / `articles` の行数 (`/healthz` で件数表示) |
| systemd timer 動かない | `journalctl -u wiki-gap-crawl.service -n 100` |
| User-Agent placeholder のまま | `.env` の `WIKI_GAP_CONTACT_URL` を実値に差し替え (フルクロール前必須) |

## ai-agent-team との連携 (Phase 1 範囲外)

`~/ai-agent-team/` 側のエージェントが `~/wiki-gap/data/wiki_gap.db` を **read-only** で参照することを想定。逆方向 (wiki-gap が agent-team を呼ぶ) は循環依存防止のため作らない。

| エージェント | 連携内容 | 有効化 |
|---|---|---|
| briefing (Conductor) | 朝の briefing に「今日のギャップ top3」差し込み | Phase 1 完走後 |
| Librarian (司書) | top100 を関心マップに照らして優先 10 件抽出 | Phase 1 完走後 |
| Analyst | ギャップ記事の医学的背景を Deep Dive 化 | Phase 1 完走後 |
| Scribe | ギャップ記事を研修医勉強会ネタに変換 | Phase 1 完走後 |
| Editor | tama さんの草稿を校正・ファクトチェック | Phase 2A 後 |

## ロードマップ

- **Phase 1** (now): ダッシュボード = ギャップ検出のみ
- **Phase 2A**: N-of-1 trial 専用の翻訳エディタ (左右 split + 章同期、ローカル保存)
- **Phase 2B**: Wikipedia API 連携 (下書き空間に保存 → プレビュー → 投稿)
- **Phase 2C**: 他記事への展開 (ダッシュボードから「翻訳する」ボタン)

## ライセンス

未定 (たまさん本人のツール)。

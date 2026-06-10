# wiki-gap — Wikipedia 日英ギャップ検出ツール (医学系)

英語版と日本語版 Wikipedia の医学系記事の **情報量ギャップを検出** し、日本語版への加筆・翻訳の起点を提供するツール。

> ⚠️ **これは個人ツール (single-user tool) です**
> 1 つの Wikimedia アカウントに紐づく形で運用される設計です。別の人が自分用に使う場合は、下の「[自分用にセットアップする](#自分用にセットアップする)」セクションを参照してください。
> リポジトリ内に作者個人 (Wikipedia ユーザ名・GitHub 等) を示唆する記述があれば、すべて環境変数または初回セットアップで上書きできるようにしてあります。

## 自分用にセットアップする

1. **入手**: `git clone` でこのリポジトリを手元に置きます (GitHub アカウントは不要)。改変版を自分で公開したい人だけ fork してください。
2. `cp .env.example .env` して `.env` を編集します。**必ず要るのは 1 つだけ**:

   **必須**
   - `WIKI_GAP_CONTACT_URL` — Wikimedia に渡す**連絡先**。このツールの API リクエストが問題を起こしたとき、運営があなたに連絡するための欄です ([Wikimedia の User-Agent ポリシー](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy)で必須)。**GitHub である必要はありません** — メール・自分の Web サイト・Wikipedia 利用者ページの URL など、連絡が取れるものなら何でも OK。例: `https://ja.wikipedia.org/wiki/利用者:あなたの名前`

   **任意 (触らなくても動きます)**
   - `WIKI_GAP_BIND_HOST` — 既定は `127.0.0.1` (このマシンの中だけ)。Tailscale 越しに見たいときだけ `tailscale ip -4` の出力に変えます
   - `WIKIPEDIA_OAUTH_CLIENT_ID` / `_SECRET` / `_CALLBACK` — **Wikipedia へ投稿する機能を使うときだけ**必要。ギャップを眺めるだけなら空のままで OK。使う場合は [Wikimedia OAuth 2.0 consumer](https://meta.wikimedia.org/wiki/Special:OAuthConsumerRegistration/propose/oauth2) を登録して取得します
3. `python3 -m venv .venv && . .venv/bin/activate && pip install -e .`
4. `python scripts/init_db.py`
5. `uvicorn src.web.app:app --host $WIKI_GAP_BIND_HOST --port $WIKI_GAP_BIND_PORT`
6. ブラウザで `/user-page` を開いて利用者ページのテンプレートを自分用に書き換え (DEFAULT_TEMPLATE は汎用雛形になっています)

詳しい構成と運用は以降のセクションを参照。

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
# .env を編集して WIKI_GAP_CONTACT_URL に連絡先 (メール / Web / Wikipedia 利用者ページ等) を入れる

# DB 初期化
python scripts/init_db.py

# クロール (テスト規模)
python scripts/run_crawl.py --category disease --limit 100

# クロール (フル: 段階的に拡張)
python scripts/run_crawl.py --category disease --limit 1000   # 段階1
python scripts/run_crawl.py --category disease --limit 0      # 段階2 (無制限)
python scripts/run_crawl.py --all --limit 0                   # 段階3 (全カテゴリ)

# ダッシュボード起動
# - ローカルだけで使う: --host 127.0.0.1
# - Tailscale 越しに見る: --host <自分の Tailscale IP> (`tailscale ip -4` で確認)
uvicorn src.web.app:app --host $WIKI_GAP_BIND_HOST --port $WIKI_GAP_BIND_PORT
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

- **User-Agent**: `WikiGapDetector/0.1 (<WIKI_GAP_CONTACT_URL>)` — 括弧内は連絡先 (メール / Web / Wikipedia 利用者ページのいずれか)
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
- ダッシュボードは Tailscale IP (`<ipaddress>:8766`) に bind (public IP には漏らさない)
- Tailnet 内のデバイス (Mac / iPhone / iPad など) からは `http://<ipaddress>:8766` で見れる
- 他人 (Tailnet 外) からは IP もポートも見えない
- 外部専用ノードの Tailscale IP は `tailscale ip -4` で確認

## トラブルシュート

| 症状 | 確認 |
|---|---|
| SPARQL 502/timeout | Wikidata Query Service の lag を疑う ([status](https://www.wikidata.org/wiki/Wikidata:Status_updates)) |
| MediaWiki API 429 | `--rate-limit 0.5` に下げる |
| ダッシュボードが空 | `data/wiki_gap.db` の有無 / `articles` の行数 (`/healthz` で件数表示) |
| systemd timer 動かない | `journalctl -u wiki-gap-crawl.service -n 100` |
| User-Agent placeholder のまま | `.env` の `WIKI_GAP_CONTACT_URL` を自分の連絡先に差し替え (フルクロール前必須) |

## ロードマップ

- **Phase 1** (now): ダッシュボード = ギャップ検出のみ
- **Phase 1.1**: partial coverage フラグ (親記事でカバー済の偽完全ギャップ対応)
  - 例: α-thalassemia は en 独立記事、ja は「サラセミア」記事の 1 セクション
  - 解決: ダッシュボードからユーザーが `coverage_status='partial:サラセミア'` をフラグ立てる UI
  - articles テーブルに `coverage_status` / `coverage_note` 追加、gap_score にペナルティ
- **Phase 2A**: 翻訳エディタ (左右 split + 章同期、ローカル保存)
- **Phase 2B**: Wikipedia API 連携 (下書き空間に保存 → プレビュー → 投稿)
- **Phase 2C**: 他記事への展開 (ダッシュボードから「翻訳する」ボタン)

## ライセンス

[MIT License](LICENSE) — Copyright (c) 2026 Tama831

自由に使用・改変・再配布できます (著作権表示を残す必要あり)。

> **データ側のライセンスとは別**: wiki-gap が取得・処理する Wikipedia コンテンツ
> (記事 wikitext、メタデータ、pageviews 等) は Wikimedia Foundation によって
> **CC BY-SA 4.0 / GFDL** で配布されています。そのデータを使って翻訳記事を投稿する際は、
> [[Wikipedia:翻訳のガイドライン]] に従って翻訳元と版番号 (oldid) を編集要約に記載してください
> (wiki-gap の publish ハンドオフは自動でこの形式に整えてくれます)。

-- wiki-gap SQLite schema
-- Phase 1: 単一ファイル DB に articles と snapshots を持つ

CREATE TABLE IF NOT EXISTS articles (
  qid TEXT PRIMARY KEY,             -- Wikidata QID (例: Q12136)
  category TEXT NOT NULL,           -- 'disease' | 'drug' | 'procedure'
  en_title TEXT,
  ja_title TEXT,
  en_bytes INTEGER,
  ja_bytes INTEGER,
  en_sections INTEGER,
  ja_sections INTEGER,
  en_refs INTEGER,
  ja_refs INTEGER,
  en_images INTEGER,
  ja_images INTEGER,
  en_pv_90d INTEGER,
  ja_pv_90d INTEGER,
  en_last_edit TEXT,                -- ISO8601
  ja_last_edit TEXT,
  gap_score REAL,
  updated_at TEXT NOT NULL          -- ISO8601, upsert ごとに更新
);

CREATE INDEX IF NOT EXISTS idx_gap_score ON articles(gap_score DESC);
CREATE INDEX IF NOT EXISTS idx_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_updated_at ON articles(updated_at);

-- 日次スナップショット (Phase 1.5 で時系列可視化に使う)
CREATE TABLE IF NOT EXISTS snapshots (
  qid TEXT NOT NULL,
  snapshot_date TEXT NOT NULL,      -- YYYY-MM-DD (JST)
  en_bytes INTEGER,
  ja_bytes INTEGER,
  gap_score REAL,
  PRIMARY KEY (qid, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_date ON snapshots(snapshot_date);

-- クロール実行ログ (障害解析用)
CREATE TABLE IF NOT EXISTS crawl_runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,             -- 'running' | 'success' | 'failed' | 'partial'
  category TEXT,                    -- 単一カテゴリ実行のときのみ
  seeds_count INTEGER,
  fetched_count INTEGER,
  failed_count INTEGER,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_started ON crawl_runs(started_at DESC);

-- ─────────────────────────────────────────────────────────────────
-- Phase 2A: 翻訳エディタ
-- ─────────────────────────────────────────────────────────────────

-- 1 翻訳プロジェクト = 1 行 (qid 単位)
CREATE TABLE IF NOT EXISTS translations (
  qid TEXT PRIMARY KEY,
  en_title TEXT NOT NULL,
  ja_title_proposed TEXT,            -- 提案される ja タイトル (例: "N-of-1試験")
  source_revision_id INTEGER,         -- en wikitext を取得した時点の revid
  source_wikitext TEXT NOT NULL,      -- 取得時の en wikitext snapshot
  chunks_json TEXT NOT NULL,          -- [{id, level, heading, src, dst}] JSON
  status TEXT NOT NULL DEFAULT 'draft',  -- 'draft' | 'review' | 'submitted'
  created_at TEXT NOT NULL,           -- ISO8601
  updated_at TEXT NOT NULL            -- ISO8601, chunk 更新ごとに更新
);

CREATE INDEX IF NOT EXISTS idx_translations_updated ON translations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_translations_status ON translations(status);

-- ─────────────────────────────────────────────────────────────────
-- Phase 2B: Wikipedia OAuth 2.0 認証
-- ─────────────────────────────────────────────────────────────────

-- 単一ユーザ前提 (id=1 のみ)
CREATE TABLE IF NOT EXISTS wiki_auth (
  id INTEGER PRIMARY KEY,
  username TEXT,                     -- Wikipedia ユーザ名 (取得後に埋まる)
  user_id INTEGER,                   -- Wikipedia user id
  access_token TEXT NOT NULL,
  refresh_token TEXT,
  token_expires_at TEXT,             -- ISO8601 (UTC)
  scopes TEXT,                       -- スペース区切り
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 投稿履歴ログ
CREATE TABLE IF NOT EXISTS publish_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  qid TEXT NOT NULL,
  target_lang TEXT NOT NULL,         -- "ja" | "en"
  target_namespace TEXT,             -- "下書き" | "" (本記事)
  target_title TEXT NOT NULL,        -- 完全タイトル (例: "下書き:N-of-1試験")
  edit_summary TEXT,
  revision_id INTEGER,               -- 投稿成功時の MW revision id
  status TEXT NOT NULL,              -- "success" | "failed" | "preview_only"
  error_message TEXT,
  posted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_publish_qid ON publish_log(qid, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_publish_posted ON publish_log(posted_at DESC);


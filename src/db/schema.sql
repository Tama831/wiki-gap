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

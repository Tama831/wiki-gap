"""
DB 初期化スクリプト。

冪等: 既存 DB に対しても CREATE TABLE IF NOT EXISTS で安全に再実行可。
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "src" / "db" / "schema.sql"


def main() -> int:
    load_dotenv(ROOT / ".env")
    db_path_str = os.getenv("WIKI_GAP_DB_PATH", "data/wiki_gap.db")
    db_path = (ROOT / db_path_str).resolve() if not Path(db_path_str).is_absolute() else Path(db_path_str)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
        conn.commit()

        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )]

    print(f"[init_db] DB ready at {db_path}")
    print(f"[init_db] tables: {tables}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

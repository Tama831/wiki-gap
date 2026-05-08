# Phase 1.1: Partial Coverage フラグ

## 背景

sitelink ベースの完全ギャップ判定の限界を補正する。
具体例:
- `α-thalassemia` (Q288714) は en に独立記事、ja は「サラセミア」(Q165101) 内の 1 セクション
- 現行: 「ja=完全に無い」と判定 → 不正確
- 実態: partial coverage (親記事カバー)

## スキーマ追加

```sql
ALTER TABLE articles ADD COLUMN coverage_status TEXT;
-- 値の例:
--   NULL                       未確認 (default)
--   'partial:サラセミア'       ja の親記事に統合されている
--   'redirect:..'              ja redirect 先
--   'no_jp_concept'            日本では概念自体が無い (rare)
ALTER TABLE articles ADD COLUMN coverage_note TEXT;
ALTER TABLE articles ADD COLUMN coverage_set_at TEXT;  -- ISO8601
```

## ダッシュボード UI

各行の右端に **「カバー」セル** を追加:
- 未確認 → `[ 親記事を指定 ]` ボタン
- 確認済 → 🟡 partial:サラセミア [編集]

クリックで modal:
```
┌─ Q288714 Alpha-thalassemia のカバー状態 ─────────┐
│ ○ 未確認                                          │
│ ○ ja の親記事内でカバー: [サラセミア_______]      │
│ ○ ja の redirect 先: [_______________]            │
│ ○ 日本では概念自体が無い                          │
│ メモ: [_____________________________]             │
│                                                   │
│             [キャンセル]  [保存]                  │
└────────────────────────────────────────────────────┘
```

## scoring 影響

`gap_score` に `coverage_status` 補正を入れる:
- `NULL` → 補正なし (現行の式)
- `partial:..` → ×0.4 (重要度を下げる)
- `redirect:..` → ×0.2 (ほぼ完了扱い)
- `no_jp_concept` → ×0.1 (重要度低)

## API 追加

`POST /coverage/{qid}` :
```json
{ "status": "partial:サラセミア", "note": "サラセミア記事内でセクションカバー" }
```

## 実装規模

- DB マイグレーションスクリプト 1 ファイル
- queries.py に `set_coverage` 追加
- web/app.py に POST endpoint + JS 1 個
- index.html にセル + modal
- 推定 1〜2 時間

## いつやるか

Phase 2A (N-of-1 trial エディタ) の前 = Phase 1 の段階フルクロール (drug/procedure 全件) の後。

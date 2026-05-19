# 利用者ページ管理 (Phase 2C) ガイド

wiki-gap には「利用者ページ管理」機能があり、`https://<your-host>/user-page` で
ja Wikipedia の利用者ページのテンプレートを編集できます。

## 機能

- テンプレート (wikitext) を SQLite に保存
- placeholder `{{wiki_gap:<name>}}` を実値に自動展開
- ブラウザでプレビュー (MediaWiki Parse API でレンダリング)
- handoff モードで ja Wikipedia の編集画面に直接渡す
  (clipboard コピー + 編集 URL を開く)

## サポート placeholder

| placeholder | 展開内容 |
|---|---|
| `{{wiki_gap:translated_articles}}` | `translations.status = 'submitted'` の翻訳記事リスト (mainspace > User > Draft の優先順位で実際の投稿先にリンク) |
| `{{wiki_gap:username}}` | OAuth ログイン時に保存された Wikipedia ユーザ名 (`wiki_auth.username`) |

新しい placeholder を追加するには `src/user_page/service.py::expand_placeholders`
の if 分岐に書き足してください。候補:
- `{{wiki_gap:translated_total_bytes}}` (累計翻訳字数)
- `{{wiki_gap:current_drafts}}` (進行中の下書き一覧)
- `{{wiki_gap:contribution_count}}` (編集回数、Wikipedia API から取得)

## 初期テンプレート

`src/user_page/service.py::DEFAULT_TEMPLATE` に汎用的な雛形が用意されています。
初回アクセス時に SQLite に挿入されます。あなたのプロフィールに合わせて
書き換えてください。

## 投稿フロー (handoff)

Hetzner などの VPS は Wikimedia 財団によりグローバル IP ブロック対象になっている
場合があるため、wiki-gap は API 経由の直接投稿ではなく **「clipboard コピー +
編集画面オープン」** という半自動フローで投稿します。手順:

1. `/user-page` を開く
2. テンプレートを編集 → 💾 保存
3. 📋 「コピー + 編集画面を開く」 をクリック
4. 別タブで `https://ja.wikipedia.org/wiki/利用者:<username>` の編集画面が開く
5. 本文を Cmd+A → Cmd+V (placeholder 展開済 wikitext が貼り付けされる)
6. 編集要約は pre-fill 済 (`[wiki-gap 経由] 利用者ページ更新`)
7. 「ページを保存」または「変更を公開」

## カスタマイズ tips

- 関心分野、編集方針、自己紹介は自由に書き換えてください
- ツールへの言及 (`wiki-gap`) を残す/外すは任意
  (残す場合は GitHub repo URL を自分の fork に書き換えてください)
- Babel テンプレート (`{{Babel|ja|en-2}}`) はあなたの言語スキルに合わせて変更
- `{{wiki_gap:translated_articles}}` 部分は手書きの自己紹介を上に配置するなど
  自由に配置可

## 書かない方が良い項目

- 健康状態 / プライベートな事情
- 具体的な所属機関名
- 連絡先メールアドレス (Wikipedia ではトークページ経由が原則)
- 本名 (アカウント名で一貫)

## 参考

- [[Wikipedia:利用者ページ]] (ja Wikipedia の利用者ページガイドライン)
- [[Wikipedia:翻訳のガイドライン]] (翻訳記事を扱うなら必読)

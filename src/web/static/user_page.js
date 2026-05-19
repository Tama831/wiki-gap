// 利用者ページ管理: テンプレ編集 → 保存 → handoff モードで投稿

(function () {
  const ta = document.getElementById("user-page-template");
  const expanded = document.getElementById("user-page-expanded");
  const saveBtn = document.getElementById("user-page-save");
  const pubBtn = document.getElementById("user-page-publish");
  const status = document.getElementById("save-status");
  const username = window.WIKI_USERNAME;

  function setStatus(text, cls) {
    status.textContent = text;
    status.classList.remove("saving", "saved", "error");
    if (cls) status.classList.add(cls);
  }

  // ── 保存 ──
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    setStatus("💾 保存中…", "saving");
    try {
      const res = await fetch("/user-page", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template_wikitext: ta.value }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // 展開プレビュー再取得
      const ex = await fetch("/user-page/expanded");
      expanded.textContent = await ex.text();
      setStatus("✅ 保存しました", "saved");
    } catch (e) {
      setStatus(`❌ ${e.message}`, "error");
    } finally {
      saveBtn.disabled = false;
    }
  });

  // ── handoff: clipboard + 編集画面 ──
  pubBtn.addEventListener("click", async () => {
    if (!username) {
      if (confirm("Wikipedia にログインしていません。ログイン画面に進みますか？")) {
        const ret = encodeURIComponent(location.pathname);
        location.href = `/wiki/login?return=${ret}`;
      }
      return;
    }
    pubBtn.disabled = true;
    pubBtn.textContent = "📋 準備中…";
    try {
      // 1) 保存 (最新内容)
      await fetch("/user-page", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ template_wikitext: ta.value, username }),
      });
      // 2) 展開後 wikitext を取得
      const exRes = await fetch("/user-page/expanded");
      if (!exRes.ok) throw new Error(`expand failed HTTP ${exRes.status}`);
      const wikitext = await exRes.text();

      // 3) クリップボード
      let copyOk = false;
      try {
        await navigator.clipboard.writeText(wikitext);
        copyOk = true;
      } catch (_e) {
        const tmpta = document.createElement("textarea");
        tmpta.value = wikitext;
        tmpta.style.position = "fixed";
        tmpta.style.opacity = "0";
        document.body.appendChild(tmpta);
        tmpta.select();
        try { copyOk = document.execCommand("copy"); } catch (_) {}
        document.body.removeChild(tmpta);
      }

      // 4) 編集画面 URL
      const title = `利用者:${username}`;
      const summary = "[wiki-gap 経由] 利用者ページ更新 (翻訳済記事リスト自動更新含む)";
      const editUrl = `https://ja.wikipedia.org/w/index.php?` +
        `title=${encodeURIComponent(title.replace(/ /g, "_"))}` +
        `&action=edit` +
        `&summary=${encodeURIComponent(summary)}`;

      setStatus(
        (copyOk ? "✅ wikitext をクリップボードにコピーしました" : "⚠ コピー失敗") +
        " — 編集画面を新タブで開きます",
        copyOk ? "saved" : "error"
      );
      alert(
        (copyOk ? "✅ wikitext をクリップボードにコピーしました\n\n" : "⚠ コピーに失敗、手動で再コピーが必要です\n\n") +
        "▶ 次のステップ:\n" +
        "1. 開く編集画面で本文を Cmd+A → Cmd+V で貼り付け\n" +
        "2. 編集要約は pre-fill 済\n" +
        "3. 「ページを保存」または「変更を公開」をクリック\n\n" +
        `投稿先: ja.wikipedia.org の「${title}」`
      );
      window.open(editUrl, "_blank");
    } catch (e) {
      setStatus(`❌ ${e.message}`, "error");
    } finally {
      pubBtn.disabled = false;
      pubBtn.textContent = "📋 コピー + 編集画面を開く";
    }
  });
})();

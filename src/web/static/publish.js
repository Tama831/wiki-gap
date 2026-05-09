// Phase 2B: Wikipedia 投稿 + ログイン状態表示

(function () {
  const qid = window.WIKI_GAP_QID;
  const jaTitle = window.WIKI_GAP_JA_TITLE || "";
  const enTitle = window.WIKI_GAP_EN_TITLE || "";

  const statusEl = document.getElementById("wiki-auth-status");
  const publishBtn = document.getElementById("publish-btn");
  const modal = document.getElementById("publish-modal");
  const cancelBtn = document.getElementById("publish-cancel");
  const confirmBtn = document.getElementById("publish-confirm");
  const langSel = document.getElementById("publish-lang");
  const nsSel = document.getElementById("publish-namespace");
  const titleInput = document.getElementById("publish-title");
  const summaryInput = document.getElementById("publish-summary");
  const targetDisplay = document.getElementById("publish-target-display");

  if (!statusEl) return;  // page has no translation yet

  let isLoggedIn = false;
  let currentUser = null;

  // 初期ロード: ログイン状態を取得 (初回は refresh=true で username を確実に取得)
  let _authRefreshed = false;
  async function refreshAuthStatus() {
    try {
      const url = _authRefreshed ? "/wiki/userinfo" : "/wiki/userinfo?refresh=true";
      _authRefreshed = true;
      const res = await fetch(url);
      const data = await res.json();
      if (data.logged_in) {
        isLoggedIn = true;
        currentUser = data.username || "(?)";
        statusEl.innerHTML =
          `🟢 Wiki ログイン中: <strong>${currentUser}</strong> ` +
          `<a href="#" id="wiki-logout" class="link-button">[ログアウト]</a>`;
        const logoutBtn = document.getElementById("wiki-logout");
        if (logoutBtn) {
          logoutBtn.addEventListener("click", async (ev) => {
            ev.preventDefault();
            await fetch("/wiki/logout", { method: "POST" });
            location.reload();
          });
        }
      } else {
        isLoggedIn = false;
        const ret = encodeURIComponent(location.pathname);
        statusEl.innerHTML =
          `🔴 Wiki 未ログイン ` +
          `<a href="/wiki/login?return=${ret}" class="link-button">[ログイン]</a>`;
      }
    } catch (e) {
      statusEl.textContent = `⚠ ログイン状態取得失敗: ${e.message}`;
    }
  }
  refreshAuthStatus();

  // ja は Draft 名前空間が無いので、利用者:<username>/<title> がデフォルト。
  // en は Draft 名前空間が標準。
  function rebuildNamespaceOptions() {
    const lang = langSel.value;
    nsSel.innerHTML = "";
    if (lang === "ja") {
      nsSel.add(new Option("利用者:<ユーザ名>/<タイトル> (個人サブページ — 推奨)", "利用者", true, true));
      nsSel.add(new Option("Wikipedia:サンドボックス (共用、上書きされやすい)", "Wikipedia"));
      nsSel.add(new Option("(本記事空間 — 慎重に)", ""));
    } else {
      nsSel.add(new Option("Draft:<タイトル> (Draft 名前空間 — 推奨)", "Draft", true, true));
      nsSel.add(new Option("User:<ユーザ名>/<タイトル> (個人サブページ)", "User"));
      nsSel.add(new Option("(本記事空間 — 慎重に)", ""));
    }
  }

  function updateTargetDisplay() {
    const lang = langSel.value;
    const ns = nsSel.value;
    let title = (titleInput.value || (lang === "ja" ? jaTitle : enTitle) || "(タイトル未設定)").trim();
    if (ns === "利用者" || ns === "User") {
      title = `${currentUser || "<ユーザ名>"}/${title}`;
    }
    const fullTitle = ns ? `${ns}:${title}` : title;
    targetDisplay.textContent = `${lang}.wikipedia.org の「${fullTitle}」`;
  }

  function openModal() {
    if (!isLoggedIn) {
      if (confirm("Wikipedia にログインしていません。ログイン画面に進みますか？")) {
        const ret = encodeURIComponent(location.pathname);
        location.href = `/wiki/login?return=${ret}`;
      }
      return;
    }
    titleInput.value = "";
    summaryInput.value = "";
    rebuildNamespaceOptions();
    updateTargetDisplay();
    modal.classList.remove("hidden");
  }
  function closeModal() {
    modal.classList.add("hidden");
  }

  if (publishBtn) publishBtn.addEventListener("click", openModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
  modal.querySelector(".modal-backdrop").addEventListener("click", closeModal);

  langSel.addEventListener("change", () => {
    rebuildNamespaceOptions();
    updateTargetDisplay();
  });
  nsSel.addEventListener("change", updateTargetDisplay);
  titleInput.addEventListener("input", updateTargetDisplay);

  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      const lang = langSel.value;
      const ns = nsSel.value;
      let baseTitle = (titleInput.value || "").trim() ||
                      (lang === "ja" ? jaTitle : enTitle) || "";
      if (!baseTitle) {
        alert("タイトルが設定されていません。");
        return;
      }
      // 利用者 / User: ユーザ名を prefix に組み込む
      if (ns === "利用者" || ns === "User") {
        if (!currentUser) {
          alert("ログインユーザ名が取得できていません。再ログインしてください。");
          return;
        }
        baseTitle = `${currentUser}/${baseTitle}`;
      }
      const fullTitle = ns ? `${ns}:${baseTitle}` : baseTitle;
      const summary = (summaryInput.value || "").trim() ||
        `[wiki-gap] [[:${lang === "ja" ? "en" : "ja"}:${enTitle}]] からの翻訳下書き (機械翻訳支援後、人手で確認)`;

      confirmBtn.disabled = true;
      confirmBtn.textContent = "📋 準備中...";
      try {
        // 1) wikitext を取得
        const exportRes = await fetch(`/translate/${qid}/export?mode=compact`);
        if (!exportRes.ok) throw new Error(`export 失敗 HTTP ${exportRes.status}`);
        const wikitext = await exportRes.text();

        // 2) クリップボードにコピー
        let copyOk = false;
        try {
          await navigator.clipboard.writeText(wikitext);
          copyOk = true;
        } catch (e) {
          // clipboard API 拒否時はテキストエリア fallback
          const ta = document.createElement("textarea");
          ta.value = wikitext;
          ta.style.position = "fixed";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          try { copyOk = document.execCommand("copy"); } catch (_) {}
          document.body.removeChild(ta);
        }

        // 3) 編集画面 URL を組み立て (title + action=edit + summary を pre-fill)
        const editUrl = `https://${lang}.wikipedia.org/w/index.php?` +
          `title=${encodeURIComponent(fullTitle.replace(/ /g, "_"))}` +
          `&action=edit` +
          `&summary=${encodeURIComponent(summary)}`;

        // 4) handoff ログ (任意、失敗しても先に進む)
        fetch(`/translate/${qid}/handoff_log`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            target_lang: lang,
            namespace: ns,
            title: fullTitle,
            edit_summary: summary,
          }),
        }).catch(() => {});

        closeModal();
        const msg =
          (copyOk
            ? "✅ wikitext をクリップボードにコピーしました\n\n"
            : "⚠️ クリップボードコピーに失敗 (ブラウザ権限を確認してください)\n手動で /export をダウンロードしてください\n\n") +
          `▶ 次のステップ:\n` +
          `1. 開く編集画面で本文を Cmd+A → Cmd+V で貼り付け\n` +
          `2. 編集要約は既に pre-fill 済み\n` +
          `3. 「変更を公開」または「ページを保存」をクリック\n\n` +
          `投稿先: ${lang}.wikipedia.org の「${fullTitle}」`;
        alert(msg);

        // 5) 編集画面を新タブで開く
        window.open(editUrl, "_blank");

      } catch (e) {
        alert(`❌ ${e.message}`);
      } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "📋 wikitext コピー + 編集画面を開く";
      }
    });
  }
})();

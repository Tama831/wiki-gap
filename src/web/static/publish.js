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
      const body = {
        target_lang: langSel.value,
        namespace: nsSel.value,
        title: (titleInput.value || "").trim() || null,
        summary: (summaryInput.value || "").trim() || null,
        confirm: true,
      };
      // 利用者 / User 名前空間の特別ハンドリング: ユーザ名を prefix に組み込む
      if (body.namespace === "利用者" || body.namespace === "User") {
        if (!currentUser) {
          alert("ログインユーザ名が取得できていません。再ログインしてください。");
          return;
        }
        const t = body.title || (langSel.value === "ja" ? jaTitle : enTitle);
        body.title = `${currentUser}/${t}`;
      }
      confirmBtn.disabled = true;
      confirmBtn.textContent = "📤 投稿中...";
      try {
        const res = await fetch(`/translate/${qid}/publish`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) {
          alert(`❌ 投稿失敗:\n${data.detail || JSON.stringify(data)}`);
          return;
        }
        closeModal();
        const ok = confirm(
          `✅ 投稿成功！\n\n` +
          `ページ: ${data.page_title}\n` +
          `revision: ${data.revision_id}\n\n` +
          `投稿先を新タブで開きますか？`
        );
        if (ok && data.page_url) {
          window.open(data.page_url, "_blank");
        }
      } catch (e) {
        alert(`❌ ${e.message}`);
      } finally {
        confirmBtn.disabled = false;
        confirmBtn.textContent = "🚀 投稿実行";
      }
    });
  }
})();

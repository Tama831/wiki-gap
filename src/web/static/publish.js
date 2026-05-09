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

  // 初期ロード: ログイン状態を取得
  async function refreshAuthStatus() {
    try {
      const res = await fetch("/wiki/userinfo");
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

  function updateTargetDisplay() {
    const lang = langSel.value;
    const ns = nsSel.value;
    let title = (titleInput.value || jaTitle || enTitle || "(タイトル未設定)").trim();
    if (ns === "利用者") {
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
    updateTargetDisplay();
    modal.classList.remove("hidden");
  }
  function closeModal() {
    modal.classList.add("hidden");
  }

  if (publishBtn) publishBtn.addEventListener("click", openModal);
  if (cancelBtn) cancelBtn.addEventListener("click", closeModal);
  modal.querySelector(".modal-backdrop").addEventListener("click", closeModal);

  langSel.addEventListener("change", updateTargetDisplay);
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
      // 利用者名前空間の特別ハンドリング
      if (body.namespace === "利用者") {
        if (!currentUser) {
          alert("ログインユーザ名が取得できていません。再ログインしてください。");
          return;
        }
        const t = body.title || jaTitle || enTitle;
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

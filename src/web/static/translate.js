// Phase 2A 翻訳エディタの client-side JS
// - 右 textarea focus → 左 src ハイライト + scroll into view
// - 右 textarea blur で auto-save (PUT /translate/{qid}/chunks/{chunk_id})
// - typing 後 1.5s idle で auto-save (debounce)
// - init form 送信 → POST /translate/{qid}/init → reload
// - ja タイトル変更 → PUT /translate/{qid}/meta

(function () {
  const qid = window.WIKI_GAP_QID;
  const hasTranslation = window.WIKI_GAP_HAS_TRANSLATION;
  const status = document.getElementById("save-status");

  function setStatus(text, cls) {
    if (!status) return;
    status.textContent = text;
    status.classList.remove("saving", "saved", "error");
    if (cls) status.classList.add(cls);
  }

  // ── init form (translation がまだ無い場合) ──
  const initForm = document.getElementById("init-form");
  if (initForm) {
    initForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(initForm);
      const params = new URLSearchParams();
      const enTitle = fd.get("en_title");
      const jaTitle = fd.get("ja_title_proposed");
      if (enTitle) params.set("en_title", enTitle);
      if (jaTitle) params.set("ja_title_proposed", jaTitle);
      setStatus("📥 en wikitext を取得中...", "saving");
      try {
        const res = await fetch(`/translate/${qid}/init?${params}`, {
          method: "POST",
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setStatus(`✅ ${data.n_chunks} chunks 取得済 — reload します`, "saved");
        setTimeout(() => location.reload(), 600);
      } catch (e) {
        setStatus(`❌ ${e.message}`, "error");
      }
    });
  }

  if (!hasTranslation) return; // ここから下は translation 既存の場合のみ

  // ── ja タイトル編集 ──
  const editJaTitleBtn = document.getElementById("edit-ja-title");
  const jaTitleSpan = document.querySelector(".ja-title-display");
  if (editJaTitleBtn && jaTitleSpan) {
    editJaTitleBtn.addEventListener("click", async () => {
      const current = jaTitleSpan.textContent.trim();
      const initial = current === "(未設定)" ? "" : current;
      const next = prompt("ja タイトル候補を入力してください", initial);
      if (next === null) return;
      try {
        const res = await fetch(`/translate/${qid}/meta`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ja_title_proposed: next }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        jaTitleSpan.textContent = next || "(未設定)";
        setStatus("✅ タイトル更新済", "saved");
      } catch (e) {
        setStatus(`❌ ${e.message}`, "error");
      }
    });
  }

  // ── refetch en ──
  const refetchBtn = document.getElementById("refetch-en");
  if (refetchBtn) {
    refetchBtn.addEventListener("click", async () => {
      if (!confirm("en wikitext を再取得しますか？\n(訳文 dst は heading 一致で merge されます)")) return;
      setStatus("📥 en 再取得中...", "saving");
      try {
        const res = await fetch(`/translate/${qid}/init?overwrite=true`, {
          method: "POST",
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        setStatus("✅ 再取得完了 — reload します", "saved");
        setTimeout(() => location.reload(), 600);
      } catch (e) {
        setStatus(`❌ ${e.message}`, "error");
      }
    });
  }

  // ── chunk auto-save + focus sync ──
  const chunks = document.querySelectorAll(".chunk");
  const debouncers = new Map(); // chunk_id -> timer

  async function saveChunk(chunkId, dst) {
    setStatus("💾 保存中...", "saving");
    try {
      const res = await fetch(`/translate/${qid}/chunks/${chunkId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dst }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const ts = new Date().toLocaleTimeString("ja-JP");
      setStatus(`✅ chunk ${chunkId} 保存済 (${ts})`, "saved");
    } catch (e) {
      setStatus(`❌ ${e.message}`, "error");
    }
  }

  function scheduleAutoSave(chunkId, dst) {
    const old = debouncers.get(chunkId);
    if (old) clearTimeout(old);
    const t = setTimeout(() => {
      saveChunk(chunkId, dst);
      debouncers.delete(chunkId);
    }, 1500);
    debouncers.set(chunkId, t);
  }

  // ── 文単位ハイライト ──
  // Python (wikitext.py::_find_sentence_boundaries) と同じロジックを再実装
  const REF_RE = /<ref\b[^>]*>[\s\S]*?<\/ref>|<ref\b[^/]*\/>/g;
  const ELLIPSIS_RE = /\.\.\.|……?|…/g;
  const JA_TERM = "。!？";
  const EN_TERM = ".!?";
  const CLOSE_QUOTE = "」』）)";

  function findSpans(text, re) {
    const spans = [];
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(text)) !== null) {
      spans.push([m.index, m.index + m[0].length]);
      if (m[0].length === 0) re.lastIndex++;
    }
    return spans;
  }
  function inSpan(pos, spans) {
    for (const [s, e] of spans) {
      if (s <= pos && pos < e) return [s, e];
    }
    return null;
  }

  function countSentencesBefore(text, upTo) {
    const refSpans = findSpans(text, REF_RE);
    const ellSpans = findSpans(text, ELLIPSIS_RE);
    let count = 0;
    let i = 0;
    const n = text.length;
    while (i < n) {
      if (i >= upTo) break;
      let rs = inSpan(i, refSpans);
      if (rs) { i = rs[1]; continue; }
      let es = inSpan(i, ellSpans);
      if (es) { i = es[1]; continue; }
      const c = text[i];
      if (JA_TERM.includes(c)) {
        let j = i + 1;
        if (j < n && CLOSE_QUOTE.includes(text[j])) { i = j; continue; }
        // attach trailing refs
        while (j < n) {
          const r = inSpan(j, refSpans);
          if (r && r[0] === j) j = r[1];
          else break;
        }
        if (j < n && text[j] === " ") j += 1;
        if (j > upTo) break;
        count += 1;
        i = j;
        continue;
      }
      if (EN_TERM.includes(c)) {
        let j = i + 1;
        while (j < n) {
          const r = inSpan(j, refSpans);
          if (r && r[0] === j) j = r[1];
          else break;
        }
        if (j < n && /\s/.test(text[j])) {
          while (j < n && /\s/.test(text[j])) j++;
          if (j > upTo) break;
          count += 1;
          i = j;
          continue;
        }
        i = j;
        continue;
      }
      i++;
    }
    return count;
  }

  function highlightSentence(chunkEl, idx) {
    const pre = chunkEl.querySelector("pre.src");
    if (!pre) return;
    pre.querySelectorAll(".sentence.sentence-active").forEach((el) =>
      el.classList.remove("sentence-active")
    );
    let target = pre.querySelector(`.sentence[data-sentence-idx="${idx}"]`);
    if (!target) {
      // 範囲外: 最後の文を highlight (cursor が末尾にある場合)
      const all = pre.querySelectorAll(".sentence");
      target = all[all.length - 1];
    }
    if (target) target.classList.add("sentence-active");
  }

  function syncSentence(ta, chunkEl) {
    const pos = ta.selectionStart;
    const idx = countSentencesBefore(ta.value, pos);
    highlightSentence(chunkEl, idx);
  }

  chunks.forEach((chunkEl) => {
    const ta = chunkEl.querySelector("textarea.dst");
    if (!ta) return;
    const chunkId = parseInt(ta.dataset.chunkId, 10);

    ta.addEventListener("focus", () => {
      // 全 chunk の active を消して、自分だけつける
      document.querySelectorAll(".chunk.active").forEach((el) =>
        el.classList.remove("active")
      );
      // 全 chunk の sentence-active も消す
      document.querySelectorAll(".sentence-active").forEach((el) =>
        el.classList.remove("sentence-active")
      );
      chunkEl.classList.add("active");
      // 左 src を可視範囲に持ってくる
      const src = chunkEl.querySelector("pre.src");
      if (src) {
        src.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
      syncSentence(ta, chunkEl);
    });

    ta.addEventListener("input", () => {
      scheduleAutoSave(chunkId, ta.value);
      syncSentence(ta, chunkEl);
    });

    ta.addEventListener("click", () => syncSentence(ta, chunkEl));
    ta.addEventListener("keyup", () => syncSentence(ta, chunkEl));

    ta.addEventListener("blur", () => {
      const old = debouncers.get(chunkId);
      if (old) {
        clearTimeout(old);
        debouncers.delete(chunkId);
      }
      saveChunk(chunkId, ta.value);
    });
  });
})();

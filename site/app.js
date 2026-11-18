(function () {
  const cfg = window.SITE_CONFIG || {};
  const assetBase = (cfg.assetBaseUrl || "..").replace(/\/+$/, "");

  const state = {
    papers: [],
    top20: [],
    meta: {},
    region: "",
    year: "",
    status: "",
    format: "",
    query: "",
  };

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function buildAssetUrl(relPath) {
    const encoded = relPath
      .split("/")
      .map((seg) => encodeURIComponent(seg))
      .join("/");
    return `${assetBase}/${encoded}`;
  }

  function initHeaderAndFooter() {
    if (cfg.title) {
      document.title = cfg.title;
      document.getElementById("siteTitle").textContent = cfg.title;
    }
    if (cfg.subtitle) {
      document.getElementById("siteSubtitle").textContent = cfg.subtitle;
    }
    if (cfg.disclaimer) {
      document.getElementById("footerDisclaimer").textContent = cfg.disclaimer;
      document.getElementById("aboutDisclaimer").textContent = cfg.disclaimer;
    }
    const actions = document.getElementById("headerActions");
    if (cfg.repoUrl) {
      const a = document.createElement("a");
      a.href = cfg.repoUrl;
      a.target = "_blank";
      a.rel = "noopener";
      a.className = "btn";
      a.textContent = "开源仓库";
      actions.appendChild(a);
    }
  }

  function initTabs() {
    const btns = document.querySelectorAll(".tab-btn");
    const panels = document.querySelectorAll(".tab-panel");
    btns.forEach((btn) => {
      btn.addEventListener("click", () => {
        btns.forEach((b) => b.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      });
    });
  }

  function renderStats() {
    const total = state.papers.length;
    const ready = state.papers.filter((p) => p.status === "题面可用").length;
    const partial = state.papers.filter((p) => p.status === "部分题面").length;
    const missing = state.papers.filter((p) => p.status === "待补").length;
    const filesCount = state.papers.reduce((acc, p) => acc + p.files.length, 0);

    document.getElementById("statsBar").innerHTML = `
      <span class="stat-pill">编目场次 <strong>${total}</strong> 套</span>
      <span class="stat-pill">题面可用 <strong>${ready}</strong> 套</span>
      <span class="stat-pill">部分题面 <strong>${partial}</strong> 套</span>
      <span class="stat-pill">待补 <strong>${missing}</strong> 套</span>
      <span class="stat-pill">可下载文件 <strong>${filesCount}</strong> 份</span>
    `;
    if (state.meta.generatedAt) {
      document.getElementById("generatedAt").textContent = `目录更新于 ${state.meta.generatedAt}`;
    }
  }

  function renderFilterOptions() {
    const regions = Array.from(new Set(state.papers.map((p) => p.region)));
    const pillsEl = document.getElementById("regionPills");
    pillsEl.innerHTML =
      `<button class="pill active" data-region="">全部考区</button>` +
      regions
        .map((r) => `<button class="pill" data-region="${escapeHtml(r)}">${escapeHtml(r)}</button>`)
        .join("");

    pillsEl.addEventListener("click", (e) => {
      const btn = e.target.closest(".pill");
      if (!btn) return;
      state.region = btn.dataset.region;
      pillsEl.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      renderPapers();
    });

    const years = Array.from(
      new Set(state.papers.map((p) => p.year).filter(Boolean))
    ).sort((a, b) => b - a);
    const yearSelect = document.getElementById("yearFilter");
    years.forEach((y) => {
      const opt = document.createElement("option");
      opt.value = String(y);
      opt.textContent = `${y} 年`;
      yearSelect.appendChild(opt);
    });

    document.getElementById("searchInput").addEventListener("input", (e) => {
      state.query = e.target.value.trim().toLowerCase();
      renderPapers();
    });
    yearSelect.addEventListener("change", (e) => {
      state.year = e.target.value;
      renderPapers();
    });
    document.getElementById("statusFilter").addEventListener("change", (e) => {
      state.status = e.target.value;
      renderPapers();
    });
    document.getElementById("formatFilter").addEventListener("change", (e) => {
      state.format = e.target.value;
      renderPapers();
    });
  }

  function statusBadge(status) {
    if (status === "题面可用") return `<span class="badge badge-ok">题面可用</span>`;
    if (status === "部分题面") return `<span class="badge badge-part">部分题面</span>`;
    return `<span class="badge badge-miss">${escapeHtml(status)}</span>`;
  }

  function renderFileButtons(files, title) {
    return files
      .map((f) => {
        const url = buildAssetUrl(f.path);
        const ext = (f.ext || "").toLowerCase();
        const canPreview = ["pdf", "html", "md", "png", "jpg", "jpeg"].includes(ext);
        const sizeLabel = f.sizeText ? ` (${f.sizeText})` : "";
        const previewBtn = canPreview
          ? `<button class="btn btn-sm" data-preview-url="${escapeHtml(url)}" data-preview-ext="${escapeHtml(ext)}" data-preview-title="${escapeHtml(title + " · " + f.label)}">预览 ${escapeHtml(ext.toUpperCase())}</button>`
          : "";
        const downloadBtn = `<a class="btn btn-sm btn-primary" href="${escapeHtml(url)}" download target="_blank" rel="noopener">下载${escapeHtml(sizeLabel)}</a>`;
        return previewBtn + downloadBtn;
      })
      .join("");
  }

  function renderPapers() {
    const filtered = state.papers.filter((p) => {
      if (state.region && p.region !== state.region) return false;
      if (state.year && String(p.year) !== state.year) return false;
      if (state.status && p.status !== state.status) return false;
      if (state.format && !p.files.some((f) => f.ext === state.format)) return false;
      if (state.query) {
        const hay = `${p.regionFull} ${p.title} ${p.statusDetail} ${p.note}`.toLowerCase();
        if (!hay.includes(state.query)) return false;
      }
      return true;
    });

    document.getElementById("resultCount").textContent = `当前筛选共 ${filtered.length} 条记录`;
    const listEl = document.getElementById("paperList");

    if (!filtered.length) {
      listEl.innerHTML = `<div class="empty-state">没有找到匹配的试卷，试试更换筛选条件。</div>`;
      return;
    }

    listEl.innerHTML = filtered
      .map((p) => {
        const fmtBadges = Array.from(new Set(p.files.map((f) => f.ext)))
          .filter(Boolean)
          .map((ext) => `<span class="badge badge-fmt">${escapeHtml(ext)}</span>`)
          .join("");

        const sourceLinks = p.sources
          .map(
            (s) =>
              `<a class="btn btn-sm" href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.label)}</a>`
          )
          .join("");

        return `
          <div class="paper-row">
            <div class="paper-region">${escapeHtml(p.region)}</div>
            <div class="paper-main">
              <div class="paper-title-line">
                <span class="paper-title">${escapeHtml(p.title)}</span>
                ${statusBadge(p.status)}
                ${fmtBadges}
              </div>
              <div class="paper-note">${escapeHtml(p.note || p.statusDetail)}</div>
            </div>
            <div class="paper-actions">
              ${renderFileButtons(p.files, p.title)}
              ${sourceLinks}
            </div>
          </div>
        `;
      })
      .join("");
  }

  function renderTop20() {
    const el = document.getElementById("top20List");
    if (!state.top20.length) {
      el.innerHTML = `<div class="empty-state">暂无榜单数据</div>`;
      return;
    }

    el.innerHTML = state.top20
      .map((item) => {
        const rankClass = item.rank <= 3 ? "rank-box top3" : "rank-box";
        const radarBtn = item.radarImage
          ? `<button class="btn btn-sm" data-preview-url="${escapeHtml(buildAssetUrl(item.radarImage))}" data-preview-ext="png" data-preview-title="${escapeHtml(item.title + " · 六维雷达图")}">雷达图</button>`
          : "";
        const sourceBtns = item.sources
          .map(
            (s) =>
              `<a class="btn btn-sm" href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${escapeHtml(s.label)}</a>`
          )
          .join("");

        return `
          <div class="top-card">
            <div class="${rankClass}">#${item.rank}</div>
            <div>
              <div class="paper-title-line">
                <span class="paper-title">${escapeHtml(item.title)}</span>
                <span class="badge badge-ok">综合指数 ${item.score}</span>
              </div>
              <div class="top-dims">${escapeHtml(item.dimensions)}</div>
              <p class="top-comment">${escapeHtml(item.comment)}</p>
            </div>
            <div class="paper-actions">
              ${radarBtn}
              ${renderFileButtons(item.files, item.title)}
              ${sourceBtns}
            </div>
          </div>
        `;
      })
      .join("");
  }

  // Modal Preview
  const modal = document.getElementById("previewModal");
  const modalTitle = document.getElementById("modalTitle");
  const modalBody = document.getElementById("modalBody");
  const modalDownloadBtn = document.getElementById("modalDownloadBtn");

  function openPreview(url, ext, title) {
    modalTitle.textContent = title || "文件预览";
    modalDownloadBtn.href = url;
    modalBody.innerHTML = "";

    if (ext === "pdf" || ext === "html") {
      const iframe = document.createElement("iframe");
      iframe.src = url;
      modalBody.appendChild(iframe);
    } else if (["png", "jpg", "jpeg"].includes(ext)) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = title;
      modalBody.appendChild(img);
    } else if (ext === "md") {
      const pre = document.createElement("pre");
      pre.className = "modal-text";
      pre.textContent = "加载中...";
      modalBody.appendChild(pre);
      fetch(url)
        .then((r) => r.text())
        .then((txt) => {
          pre.textContent = txt;
        })
        .catch(() => {
          pre.textContent = "无法直接预览该 Markdown 文件，请点击右上角下载原文件。";
        });
    }

    modal.classList.add("open");
  }

  function closePreview() {
    modal.classList.remove("open");
    modalBody.innerHTML = "";
  }

  document.getElementById("modalCloseBtn").addEventListener("click", closePreview);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closePreview();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("open")) closePreview();
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-preview-url]");
    if (!btn) return;
    openPreview(btn.dataset.previewUrl, btn.dataset.previewExt, btn.dataset.previewTitle);
  });

  async function boot() {
    initHeaderAndFooter();
    initTabs();
    try {
      const res = await fetch("./data/catalog.json");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      state.meta = data.meta || {};
      state.papers = data.papers || [];
      state.top20 = data.top20 || [];
      renderStats();
      renderFilterOptions();
      renderPapers();
      renderTop20();
    } catch (err) {
      document.getElementById("paperList").innerHTML = `
        <div class="empty-state">
          目录数据加载失败（${escapeHtml(err.message)}）。请通过 HTTP 服务器访问，例如在项目根目录运行 <code>python -m http.server 8000</code> 后访问 <code>http://localhost:8000/site/</code>。
        </div>`;
    }
  }

  boot();
})();

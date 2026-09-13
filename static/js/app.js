/* ============================================================
   Mainframe Job Monitor – Frontend Logic
   ============================================================ */

(() => {
  "use strict";

  // ---- State ----
  let allJobs = [];
  let filteredJobs = [];
  let currentStatus = "all";
  let currentFreq = "all";
  let currentSearch = "";
  let currentDateFrom = "";
  let currentDateTo = "";
  let currentView = "table";
  let currentMode = "demo";
  let currentPage = 1;
  let pageSize = 10; // number, or "all"
  let totalJobs = 0;
  let totalPages = 1;
  let sortCol = "last_updated";
  let sortDir = "desc";
  let fetchAbortController = null;

  // ---- DOM References ----
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const jobsContainer = $("#jobsContainer");
  const loadingSkeleton = $("#loadingSkeleton");
  const searchInput = $("#searchInput");
  const refreshBtn = $("#refreshBtn");
  const themeToggle = $("#themeToggle");
  const jobModal = $("#jobModal");
  const modalBody = $("#modalBody");
  const modalTitle = $("#modalTitle");
  const modalClose = $("#modalClose");
  const tableViewBtn = $("#tableView");
  const gridViewBtn = $("#gridView");
  const dateFrom = $("#dateFrom");
  const dateTo = $("#dateTo");
  const liveRegion = $("#liveRegion");

  // ---- Theme ----
  function initTheme() {
    const saved = localStorage.getItem("mf-theme") || "dark";
    document.documentElement.setAttribute("data-theme", saved);
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("mf-theme", next);
  }

  // ---- Accessibility ----
  function announce(message) {
    if (liveRegion) {
      liveRegion.textContent = "";
      requestAnimationFrame(() => { liveRegion.textContent = message; });
    }
  }

  // ---- API ----
  async function fetchJobs() {
    if (fetchAbortController) {
      fetchAbortController.abort();
    }
    fetchAbortController = new AbortController();

    refreshBtn.classList.add("spinning");
    loadingSkeleton.style.display = "flex";

    const params = new URLSearchParams();
    if (currentStatus !== "all") params.set("status", currentStatus);
    if (currentFreq !== "all") params.set("frequency", currentFreq);
    if (currentSearch) params.set("search", currentSearch);
    if (currentDateFrom) params.set("date_from", currentDateFrom);
    if (currentDateTo) params.set("date_to", currentDateTo);
    // Server-side pagination; "All" requests one big page
    if (pageSize === "all") {
      params.set("page", "1");
      params.set("page_size", "1000");
    } else {
      params.set("page", String(currentPage));
      params.set("page_size", String(pageSize));
    }

    try {
      const [jobsRes, summaryRes] = await Promise.all([
        fetch(`/api/jobs?${params}`, { signal: fetchAbortController.signal }),
        fetch(`/api/jobs/summary?${params}`, { signal: fetchAbortController.signal }),
      ]);

      if (!jobsRes.ok || !summaryRes.ok) throw new Error("API error");

      const jobsData = await jobsRes.json();
      const summary = await summaryRes.json();

      // /api/jobs returns a paginated object {items, total, ...} — support plain arrays too
      if (Array.isArray(jobsData)) {
        allJobs = jobsData;
        totalJobs = jobsData.length;
        totalPages = 1;
        currentPage = 1;
      } else {
        allJobs = jobsData.items || [];
        totalJobs = jobsData.total ?? allJobs.length;
        totalPages = jobsData.total_pages || 1;
        currentPage = jobsData.page || currentPage;
      }
      // Clamp current page if filters shrank the result set
      if (currentPage > totalPages && totalPages > 0) {
        currentPage = totalPages;
      }

      updateSummary(summary);
      applySort();
      renderPagination();
      updateConnectionStatus();
      const rangeLabel = pageSize === "all"
        ? `all ${totalJobs} jobs`
        : `page ${currentPage} of ${totalPages} (${totalJobs} jobs)`;
      announce(`Loaded ${rangeLabel} (${currentMode} mode)`);
    } catch (err) {
      if (err.name === "AbortError") return;
      console.error("Fetch error:", err);
      // Clear stale data so production-with-no-DB shows an empty list, not old demo rows
      allJobs = [];
      totalJobs = 0;
      totalPages = 1;
      updateSummary({ total_jobs: 0, running: 0, completed: 0, waiting: 0, failed: 0, queued: 0 });
      applySort();
      renderPagination();
      showConnectionError();
      announce(
        currentMode === "production"
          ? "Production database unavailable. No jobs to display."
          : "Failed to load job data."
      );
    } finally {
      loadingSkeleton.style.display = "none";
      refreshBtn.classList.remove("spinning");
    }
  }

  function showConnectionError() {
    updateConnectionStatus("error");
  }

  // ---- App Mode (demo / production) ----
  function updateModeUI() {
    $$("#modeToggle .mode-btn").forEach((btn) => {
      const isActive = btn.dataset.mode === currentMode;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
    updateConnectionStatus();
  }

  function updateConnectionStatus(state) {
    const cs = $("#connectionStatus");
    if (!cs) return;
    if (state === "error" && currentMode !== "demo") {
      cs.innerHTML = '<span class="status-dot" style="background:var(--danger);box-shadow:0 0 6px var(--danger)"></span><span style="color:var(--danger)">Connection Error</span>';
      return;
    }
    if (currentMode === "demo") {
      cs.innerHTML = '<span class="status-dot" style="background:var(--warning);box-shadow:0 0 6px var(--warning)"></span><span style="color:var(--warning)">Demo Mode &mdash; Sample Data</span>';
    } else {
      cs.innerHTML = '<span class="status-dot"></span><span>Connected &mdash; Live</span>';
    }
  }

  async function fetchMode() {
    try {
      const res = await fetch("/api/mode");
      if (!res.ok) throw new Error("mode fetch failed");
      const data = await res.json();
      currentMode = data.mode === "production" ? "production" : "demo";
    } catch (err) {
      console.warn("Could not fetch app mode, defaulting to demo:", err);
      currentMode = "demo";
    }
    updateModeUI();
  }

  async function setMode(mode) {
    if (mode === currentMode) return;
    try {
      const res = await fetch("/api/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) throw new Error("mode switch failed");
      const data = await res.json();
      currentMode = data.mode;
      currentPage = 1;
      updateModeUI();
      announce(`Switched to ${currentMode} mode`);
      fetchJobs();
    } catch (err) {
      console.error("Mode switch error:", err);
      announce("Failed to switch mode");
    }
  }

  // ---- Pagination ----
  function gotoPage(page) {
    const target = Math.max(1, Math.min(totalPages, page));
    if (target === currentPage) return;
    currentPage = target;
    fetchJobs();
  }

  function pageList() {
    // Compact page list with ellipsis, e.g. 1 … 4 5 6 … 12
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }
    const pages = new Set([1, 2, currentPage - 1, currentPage, currentPage + 1, totalPages - 1, totalPages]);
    const sorted = [...pages].filter((p) => p >= 1 && p <= totalPages).sort((a, b) => a - b);
    const out = [];
    let prev = 0;
    for (const p of sorted) {
      if (p - prev > 1) out.push("…");
      out.push(p);
      prev = p;
    }
    return out;
  }

  function renderPagination() {
    const info = $("#paginationInfo");
    const controls = $("#paginationControls");
    if (!info || !controls) return;

    if (pageSize === "all") {
      info.textContent = totalJobs ? `Showing all ${totalJobs} jobs` : "No jobs to display";
      controls.innerHTML = "";
      lucide.createIcons();
      return;
    }

    if (!totalJobs) {
      info.textContent = "No jobs to display";
      controls.innerHTML = "";
      lucide.createIcons();
      return;
    }

    const start = (currentPage - 1) * pageSize + 1;
    const end = Math.min(currentPage * pageSize, totalJobs);
    info.textContent = `Showing ${start}–${end} of ${totalJobs} jobs`;

    let html = `<button class="page-btn" data-page="prev" ${currentPage <= 1 ? "disabled" : ""} aria-label="Previous page"><i data-lucide="chevron-left"></i></button>`;
    for (const p of pageList()) {
      if (p === "…") {
        html += `<span class="page-ellipsis" aria-hidden="true">…</span>`;
      } else {
        html += `<button class="page-btn ${p === currentPage ? "active" : ""}" data-page="${p}" aria-label="Page ${p}" ${p === currentPage ? 'aria-current="page"' : ""}>${p}</button>`;
      }
    }
    html += `<button class="page-btn" data-page="next" ${currentPage >= totalPages ? "disabled" : ""} aria-label="Next page"><i data-lucide="chevron-right"></i></button>`;

    controls.innerHTML = html;
    lucide.createIcons();

    controls.querySelectorAll(".page-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.page;
        if (target === "prev") gotoPage(currentPage - 1);
        else if (target === "next") gotoPage(currentPage + 1);
        else gotoPage(parseInt(target, 10));
      });
    });
  }

  // ---- Summary ----
  function updateSummary(s) {
    animateCount("totalCount", s.total_jobs);
    animateCount("runningCount", s.running);
    animateCount("completedCount", s.completed);
    animateCount("waitingCount", s.waiting);
    animateCount("failedCount", s.failed);
    animateCount("queuedCount", s.queued);
  }

  function animateCount(id, target) {
    const el = $(`#${id}`);
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;

    const diff = target - current;
    const steps = 20;
    const step = diff / steps;
    let i = 0;

    const timer = setInterval(() => {
      i++;
      el.textContent = Math.round(current + step * i);
      if (i >= steps) {
        el.textContent = target;
        clearInterval(timer);
      }
    }, 20);
  }

  // ---- Filtering & Sorting ----
  function handleSort(col) {
    if (sortCol === col) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortCol = col;
      sortDir = "asc";
    }
    announce(`Sorted by ${col} ${sortDir === "asc" ? "ascending" : "descending"}`);
    applySort();
  }

  function applySort() {
    filteredJobs = [...allJobs];
    filteredJobs.sort((a, b) => {
      let va = a[sortCol];
      let vb = b[sortCol];
      if (va == null) va = "";
      if (vb == null) vb = "";
      if (typeof va === "string") va = va.toLowerCase();
      if (typeof vb === "string") vb = vb.toLowerCase();
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    renderJobs();
  }

  // ---- Rendering ----
  function renderJobs() {
    if (currentView === "table") {
      renderTable();
    } else {
      renderGrid();
    }
  }

  function renderTable() {
    jobsContainer.className = "jobs-container table-view";

    if (!filteredJobs.length) {
      jobsContainer.innerHTML = `
        <div class="empty-state">
          <i data-lucide="inbox"></i>
          <p>No jobs found matching your filters</p>
        </div>`;
      lucide.createIcons();
      return;
    }

    const cols = [
      { key: "job_id", label: "ID" },
      { key: "job_name", label: "Job Name" },
      { key: "job_status", label: "Status" },
      { key: "job_frequency", label: "Freq" },
      { key: "job_owner", label: "Owner" },
      { key: "job_start_time", label: "Start" },
      { key: "job_end_time", label: "End" },
      { key: "job_duration_minutes", label: "Duration" },
      { key: "wait_reason", label: "Wait Reason" },
      { key: "last_updated", label: "Updated" },
    ];

    let html = '<table class="jobs-table"><thead><tr>';
    for (const c of cols) {
      const sortClass = sortCol === c.key ? (sortDir === "asc" ? "sort-asc" : "sort-desc") : "";
      html += `<th class="sortable ${sortClass}" data-col="${c.key}">${c.label}</th>`;
    }
    html += "</tr></thead><tbody>";

    for (const job of filteredJobs) {
      html += `<tr data-job-id="${esc(job.job_id)}">`;
      html += `<td><code style="font-size:0.85rem;color:var(--text-muted)">${esc(job.job_id)}</code></td>`;
      html += `<td><div class="job-name-cell"><span class="job-name-primary">${esc(job.job_name)}</span></div></td>`;
      html += `<td>${statusBadge(job.job_status)}</td>`;
      html += `<td>${freqBadge(job.job_frequency)}</td>`;
      html += `<td style="color:var(--text-secondary);font-size:0.9rem">${esc(job.job_owner || "—")}</td>`;
      html += `<td style="color:var(--text-secondary);font-size:0.9rem;white-space:nowrap">${fmtDateTime(job.job_start_time)}</td>`;
      html += `<td style="color:var(--text-secondary);font-size:0.9rem;white-space:nowrap">${fmtDateTime(job.job_end_time)}</td>`;
      html += `<td style="color:var(--text-secondary);font-size:0.9rem">${job.job_duration_minutes != null ? job.job_duration_minutes + "m" : "—"}</td>`;
      html += `<td>${waitReasonHtml(job)}</td>`;
      html += `<td style="color:var(--text-muted);font-size:0.85rem;white-space:nowrap">${fmtDateTime(job.last_updated)}</td>`;
      html += "</tr>";
    }
    html += "</tbody></table>";

    jobsContainer.innerHTML = html;
    lucide.createIcons();

    // Sort header click and keyboard
    $$(".jobs-table th.sortable").forEach((th) => {
      th.setAttribute("tabindex", "0");
      th.addEventListener("click", () => handleSort(th.dataset.col));
      th.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleSort(th.dataset.col);
        }
      });
    });

    // Row click -> modal + keyboard
    $$(".jobs-table tbody tr").forEach((tr) => {
      tr.setAttribute("tabindex", "0");
      tr.setAttribute("role", "button");
      tr.setAttribute("aria-label", `View details for job ${tr.dataset.jobId}`);
      tr.addEventListener("click", () => openJobModal(tr.dataset.jobId));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openJobModal(tr.dataset.jobId);
        }
      });
    });
  }

  function renderGrid() {
    jobsContainer.className = "jobs-container grid-view";

    if (!filteredJobs.length) {
      jobsContainer.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1">
          <i data-lucide="inbox"></i>
          <p>No jobs found matching your filters</p>
        </div>`;
      lucide.createIcons();
      return;
    }

    let html = "";
    for (const job of filteredJobs) {
      html += `<div class="job-card" data-job-id="${esc(job.job_id)}">`;
      html += `<div class="job-card-header">`;
      html += `<span class="job-card-id">${esc(job.job_id)}</span>`;
      html += statusBadge(job.job_status);
      html += `</div>`;
      html += `<div class="job-card-name">${esc(job.job_name)}</div>`;
      html += `<div class="job-card-meta">`;
      html += `<span class="job-card-detail"><i data-lucide="user"></i> ${esc(job.job_owner || "—")}</span>`;
      html += `<span class="job-card-detail">${freqBadge(job.job_frequency)}</span>`;
      html += `<span class="job-card-detail"><i data-lucide="clock"></i> ${job.job_duration_minutes != null ? job.job_duration_minutes + "m" : "—"}</span>`;
      html += `</div>`;

      if (job.wait_reason && job.job_status === "WAITING") {
        html += `<div class="job-card-wait"><i data-lucide="alert-circle"></i> ${esc(job.wait_reason)}</div>`;
      }
      if (job.error_message && job.job_status === "FAILED") {
        html += `<div class="job-card-error"><i data-lucide="alert-triangle"></i> ${esc(job.error_message)}</div>`;
      }

      html += `<div class="job-card-footer">`;
      html += `<span class="job-card-time"><i data-lucide="play"></i> ${fmtDateTime(job.job_start_time)}</span>`;
      html += `<span class="job-card-time"><i data-lucide="refresh-cw"></i> ${fmtDateTime(job.last_updated)}</span>`;
      html += `</div>`;
      html += `</div>`;
    }

    jobsContainer.innerHTML = html;
    lucide.createIcons();

    $$(".job-card").forEach((card) => {
      card.setAttribute("tabindex", "0");
      card.setAttribute("role", "button");
      card.setAttribute("aria-label", `View details for job ${card.dataset.jobId}`);
      card.addEventListener("click", () => openJobModal(card.dataset.jobId));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openJobModal(card.dataset.jobId);
        }
      });
    });
  }

  // ---- Helpers ----
  const statusIcons = {
    COMPLETED: "check-circle-2",
    RUNNING: "play-circle",
    WAITING: "clock",
    FAILED: "x-circle",
    QUEUED: "list",
    CANCELLED: "ban",
    UNKNOWN: "help-circle",
  };

  const freqIcons = {
    DAILY: "sun",
    WEEKLY: "calendar-days",
    MONTHLY: "calendar-range",
    ONETIME: "calendar",
    UNKNOWN: "help-circle",
  };

  function statusBadge(s) {
    const icon = statusIcons[s] || "help-circle";
    return `<span class="status-badge ${s}"><i data-lucide="${icon}"></i> ${s}</span>`;
  }

  function freqBadge(f) {
    const icon = freqIcons[f] || "help-circle";
    return `<span class="freq-badge"><i data-lucide="${icon}"></i> ${f}</span>`;
  }

  function waitReasonHtml(job) {
    if (!job.wait_reason || job.job_status !== "WAITING") return '<span style="color:var(--text-muted)">—</span>';
    return `<div class="wait-reason"><i data-lucide="alert-circle"></i><span class="wait-reason-text">${esc(job.wait_reason)}</span></div>`;
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }

  function fmtDateTimeFull(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    return d.toLocaleString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function fmtDuration(min) {
    if (min == null) return "—";
    if (min < 60) return `${min} min`;
    const h = Math.floor(min / 60);
    const m = Math.round(min % 60);
    return `${h}h ${m}m`;
  }

  function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ---- Modal ----
  let lastFocusedElement = null;

  function openJobModal(jobId) {
    const job = allJobs.find((j) => j.job_id === jobId);
    if (job) openModal(job);
  }

  function openModal(job) {
    lastFocusedElement = document.activeElement;

    modalTitle.textContent = `${job.job_name} (${job.job_id})`;

    let html = "";

    // Status
    html += detailRow("badge", "Status", statusBadge(job.job_status));
    // Frequency
    html += detailRow("calendar", "Frequency", freqBadge(job.job_frequency));
    // Owner
    html += detailRow("user", "Owner", job.job_owner || "—");
    // Schedule
    html += detailRow("clock", "Schedule", job.job_schedule || "—");
    // Start
    html += detailRow("play", "Start Time", fmtDateTimeFull(job.job_start_time));
    // End
    html += detailRow("square-parking", "End Time", fmtDateTimeFull(job.job_end_time));
    // Duration
    html += detailRow("timer", "Duration", fmtDuration(job.job_duration_minutes));

    // Wait reason
    if (job.wait_reason) {
      html += detailRow("alert-circle", "Wait Reason",
        `<span class="detail-value wait"><i data-lucide="alert-circle"></i> ${esc(job.wait_reason)}</span>`);
    }
    if (job.wait_since) {
      html += detailRow("clock", "Waiting Since", fmtDateTimeFull(job.wait_since));
    }

    // Error
    if (job.error_message) {
      html += detailRow("alert-triangle", "Error",
        `<span class="detail-value error"><i data-lucide="alert-triangle"></i> ${esc(job.error_message)}</span>`);
    }

    // Last updated
    html += detailRow("refresh-cw", "Last Updated", fmtDateTimeFull(job.last_updated));

    modalBody.innerHTML = html;
    lucide.createIcons();
    jobModal.classList.add("open");
    jobModal.setAttribute("aria-hidden", "false");
    modalClose.focus();
    announce(`Opened details for job ${job.job_name}`);
  }

  function detailRow(icon, label, value) {
    return `
      <div class="detail-row">
        <div class="detail-icon"><i data-lucide="${icon}" aria-hidden="true"></i></div>
        <div class="detail-content">
          <span class="detail-label">${label}</span>
          <span class="detail-value">${value}</span>
        </div>
      </div>`;
  }

  function closeModal() {
    jobModal.classList.remove("open");
    jobModal.setAttribute("aria-hidden", "true");
    if (lastFocusedElement) {
      lastFocusedElement.focus();
      lastFocusedElement = null;
    }
  }

  // ---- Debounce ----
  function debounce(fn, ms) {
    let timer;
    const debounced = (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
    debounced.cancel = () => clearTimeout(timer);
    return debounced;
  }

  // ---- Resizable job list (drag left / right edges) ----
  const JOBS_WIDTH_KEY = "mf-jobs-width";

  function applyJobsWidth(widthPx) {
    const section = $("#jobsSection");
    if (!section) return;
    const parent = section.parentElement;
    const cs = getComputedStyle(parent);
    const parentContent = parent.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
    const min = 320;
    const max = Math.max(min, window.innerWidth - 16);
    const width = Math.max(min, Math.min(max, Math.round(widthPx)));
    section.style.width = `${width}px`;
    section.style.maxWidth = "none";
    if (width > parentContent) {
      // Break out of the centered container symmetrically (both sides)
      const over = (width - parentContent) / 2;
      section.style.marginLeft = `${-over}px`;
      section.style.marginRight = `${-over}px`;
    } else {
      section.style.marginLeft = "auto";
      section.style.marginRight = "auto";
    }
  }

  function saveJobsWidth() {
    const section = $("#jobsSection");
    if (!section || !section.style.width) return;
    try {
      localStorage.setItem(JOBS_WIDTH_KEY, section.style.width);
    } catch (e) { /* ignore */ }
  }

  function resetJobsWidth() {
    const section = $("#jobsSection");
    if (!section) return;
    section.style.width = "";
    section.style.maxWidth = "";
    section.style.marginLeft = "";
    section.style.marginRight = "";
    try {
      localStorage.removeItem(JOBS_WIDTH_KEY);
    } catch (e) { /* ignore */ }
    announce("Job list width reset");
  }

  function restoreJobsWidth() {
    try {
      const saved = localStorage.getItem(JOBS_WIDTH_KEY);
      if (saved) {
        const px = parseFloat(saved);
        if (!isNaN(px) && px >= 320) applyJobsWidth(px);
      }
    } catch (e) { /* ignore */ }
  }

  function makeResizable(handle, side) {
    if (!handle) return;
    handle.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (err) { /* ignore */ }
      const section = $("#jobsSection");
      const startX = e.clientX;
      const startW = section.getBoundingClientRect().width;
      handle.classList.add("dragging");
      const move = (ev) => {
        const dx = ev.clientX - startX;
        applyJobsWidth(startW + (side === "right" ? dx : -dx));
      };
      const up = () => {
        handle.classList.remove("dragging");
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        saveJobsWidth();
      };
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
    handle.addEventListener("dblclick", resetJobsWidth);
  }

  // ---- Event Listeners ----
  function bindEvents() {
    // Theme
    themeToggle.addEventListener("click", toggleTheme);

    // App mode toggle
    $$("#modeToggle .mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => setMode(btn.dataset.mode));
    });

    // Resizable job list (left / right handles)
    makeResizable($("#resizeLeft"), "left");
    makeResizable($("#resizeRight"), "right");
    window.addEventListener("resize", debounce(() => {
      const section = $("#jobsSection");
      if (section && section.style.width) {
        applyJobsWidth(parseFloat(section.style.width));
      }
    }, 200));

    // Refresh
    refreshBtn.addEventListener("click", fetchJobs);

    // Page size
    const pageSizeSelect = $("#pageSizeSelect");
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener("change", () => {
        const val = pageSizeSelect.value;
        pageSize = val === "all" ? "all" : parseInt(val, 10);
        currentPage = 1;
        announce(val === "all" ? "Showing all jobs" : `Page size ${val}`);
        fetchJobs();
      });
    }

    // Search (debounced while typing; Enter searches immediately)
    const searchClear = $("#searchClear");
    const updateSearchClear = () => {
      if (searchClear) searchClear.hidden = !searchInput.value;
    };
    const debouncedSearch = debounce(() => {
      currentSearch = searchInput.value.trim();
      currentPage = 1;
      fetchJobs();
    }, 25);
    searchInput.addEventListener("input", () => {
      updateSearchClear();
      debouncedSearch();
    });
    if (searchClear) {
      searchClear.addEventListener("click", () => {
        debouncedSearch.cancel();
        searchInput.value = "";
        currentSearch = "";
        currentPage = 1;
        updateSearchClear();
        searchInput.focus();
        announce("Search cleared");
        fetchJobs();
      });
    }
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        debouncedSearch.cancel();
        currentSearch = searchInput.value.trim();
        currentPage = 1;
        fetchJobs();
      }
    });

    // Status chips
    $$("#statusFilters .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        $$("#statusFilters .chip").forEach((c) => {
          c.classList.remove("active");
          c.setAttribute("aria-pressed", "false");
        });
        chip.classList.add("active");
        chip.setAttribute("aria-pressed", "true");
        currentStatus = chip.dataset.status;
        currentPage = 1;
        announce(`Filter: status ${currentStatus === "all" ? "all" : currentStatus}`);
        fetchJobs();
      });
      chip.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const chips = Array.from($$("#statusFilters .chip"));
          const idx = chips.indexOf(chip);
          const next = e.key === "ArrowRight"
            ? chips[(idx + 1) % chips.length]
            : chips[(idx - 1 + chips.length) % chips.length];
          next.focus();
          next.click();
        }
      });
    });

    // Frequency chips
    $$("#frequencyFilters .chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        $$("#frequencyFilters .chip").forEach((c) => {
          c.classList.remove("active");
          c.setAttribute("aria-pressed", "false");
        });
        chip.classList.add("active");
        chip.setAttribute("aria-pressed", "true");
        currentFreq = chip.dataset.freq;
        currentPage = 1;
        announce(`Filter: frequency ${currentFreq === "all" ? "all" : currentFreq}`);
        fetchJobs();
      });
      chip.addEventListener("keydown", (e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const chips = Array.from($$("#frequencyFilters .chip"));
          const idx = chips.indexOf(chip);
          const next = e.key === "ArrowRight"
            ? chips[(idx + 1) % chips.length]
            : chips[(idx - 1 + chips.length) % chips.length];
          next.focus();
          next.click();
        }
      });
    });

    // Date filters
    dateFrom.addEventListener("change", () => {
      currentDateFrom = dateFrom.value;
      currentPage = 1;
      fetchJobs();
    });

    dateTo.addEventListener("change", () => {
      currentDateTo = dateTo.value;
      currentPage = 1;
      fetchJobs();
    });

    // View toggle
    tableViewBtn.addEventListener("click", () => {
      currentView = "table";
      tableViewBtn.classList.add("active");
      tableViewBtn.setAttribute("aria-checked", "true");
      gridViewBtn.classList.remove("active");
      gridViewBtn.setAttribute("aria-checked", "false");
      announce("Switched to table view");
      renderJobs();
    });

    gridViewBtn.addEventListener("click", () => {
      currentView = "grid";
      gridViewBtn.classList.add("active");
      gridViewBtn.setAttribute("aria-checked", "true");
      tableViewBtn.classList.remove("active");
      tableViewBtn.setAttribute("aria-checked", "false");
      announce("Switched to grid view");
      renderJobs();
    });

    // Modal close
    modalClose.addEventListener("click", closeModal);
    jobModal.addEventListener("click", (e) => {
      if (e.target === jobModal) closeModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && jobModal.classList.contains("open")) {
        closeModal();
      }
    });

    // Modal focus trap
    jobModal.addEventListener("keydown", (e) => {
      if (e.key !== "Tab" || !jobModal.classList.contains("open")) return;
      const focusable = jobModal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    });

    // Summary cards click -> filter + keyboard
    $$(".summary-card").forEach((card) => {
      card.addEventListener("click", () => handleSummaryCard(card.dataset.type));
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleSummaryCard(card.dataset.type);
        }
      });
    });
  }

  function handleSummaryCard(type) {
    if (type === "total") {
      currentStatus = "all";
      $$("#statusFilters .chip").forEach((c) => {
        c.classList.remove("active");
        c.setAttribute("aria-pressed", "false");
      });
      const allChip = $('#statusFilters .chip[data-status="all"]');
      if (allChip) {
        allChip.classList.add("active");
        allChip.setAttribute("aria-pressed", "true");
      }
    } else {
      currentStatus = type;
      $$("#statusFilters .chip").forEach((c) => {
        c.classList.remove("active");
        c.setAttribute("aria-pressed", "false");
      });
      const target = $(`#statusFilters .chip[data-status="${type}"]`);
      if (target) {
        target.classList.add("active");
        target.setAttribute("aria-pressed", "true");
      }
    }
    currentPage = 1;
    announce(`Filter: status ${currentStatus === "all" ? "all" : currentStatus}`);
    fetchJobs();
  }

  // ---- Init ----
  async function init() {
    initTheme();
    bindEvents();
    lucide.createIcons();
    restoreJobsWidth();
    await fetchMode();
    fetchJobs();

    // Auto-refresh every 30 seconds
    setInterval(fetchJobs, 30000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

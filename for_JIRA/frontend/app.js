/* JIRA Cloud Client frontend — talks only to same-origin FastAPI backend. */
const $ = (id) => document.getElementById(id);

/* ---------- theme ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("jira-theme", theme);
  $("themeBtn").textContent = theme === "dark" ? "Light mode" : "Dark mode";
}
applyTheme(localStorage.getItem("jira-theme") || "light");
$("themeBtn").addEventListener("click", () => {
  const cur = document.documentElement.getAttribute("data-theme");
  applyTheme(cur === "dark" ? "light" : "dark");
});

/* ---------- sidenav navigation ---------- */
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $("view-" + btn.dataset.view).classList.add("active");
    $("sidenav").classList.remove("open");
  });
});
$("menuBtn").addEventListener("click", () => $("sidenav").classList.toggle("open"));

/* ---------- helpers ---------- */
function showResult(ok, msg, obj) {
  $("resultMeta").innerHTML = `<span class="dot ${ok ? "ok" : "bad"}"></span> ${msg}`;
  $("output").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

async function api(path, method = "GET", body = null) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { status: res.status, ok: res.ok, data };
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function adfToText(adf) {
  if (!adf) return "";
  const out = [];
  (function walk(node) {
    if (!node) return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (typeof node !== "object") return;
    if (node.type === "text") out.push(node.text || "");
    (node.content || []).forEach(walk);
    if (["paragraph", "heading", "blockquote"].includes(node.type)) out.push("\n");
  })(adf);
  return out.join("").trim();
}

/* ---------- connection ---------- */
async function refreshStatus() {
  try {
    const { ok, data } = await api("/api/jira/status");
    if (!ok) throw new Error("status failed");
    const label = data.connected
      ? `Connected: ${escapeHtml(data.site_name || "")} (${escapeHtml(data.site_url || "")}) — Cloud ${escapeHtml(data.cloud_id || "")}`
      : data.has_token
        ? "Token saved — click Discover site"
        : "Not connected";
    $("connStatus").innerHTML = `<span class="dot ${data.connected ? "ok" : "idle"}"></span> ${label}`;
  } catch (e) {
    $("connStatus").innerHTML = `<span class="dot bad"></span> Backend unreachable`;
  }
}
$("refreshStatusBtn").addEventListener("click", refreshStatus);

$("authUrlBtn").addEventListener("click", async () => {
  const { ok, data } = await api("/api/jira/auth/url");
  if (!ok) { showResult(false, "Could not build auth URL", data); return; }
  $("authUrl").value = data.authorization_url;
  $("authOpenLink").href = data.authorization_url;
  showResult(true, "Authorization URL ready", data);
});

$("exchangeBtn").addEventListener("click", async () => {
  const code = $("authCode").value.trim();
  if (!code) { alert("Paste the authorization code first."); return; }
  const { ok, data } = await api("/api/jira/auth/exchange", "POST", { code });
  showResult(ok, ok ? "Token exchange OK" : "Exchange failed", data);
  refreshStatus();
});

$("refreshBtn").addEventListener("click", async () => {
  const { ok, data } = await api("/api/jira/auth/refresh", "POST", {});
  showResult(ok, ok ? "Token refreshed" : "Refresh failed", data);
  refreshStatus();
});

$("connectBtn").addEventListener("click", async () => {
  const access_token = $("manualToken").value.trim();
  if (!access_token) { alert("Paste an access token first."); return; }
  const { ok, data } = await api("/api/jira/connect", "POST", {
    access_token,
    refresh_token: $("manualRefresh").value.trim() || null,
    cloud_id: $("manualCloud").value.trim() || null,
  });
  showResult(ok, ok ? "Connected" : "Connect failed", data);
  refreshStatus();
});

$("discoverBtn").addEventListener("click", async () => {
  const { ok, data } = await api("/api/jira/site");
  showResult(ok, ok ? "Site discovered" : "Discovery failed", data);
  refreshStatus();
});

/* ---------- projects ---------- */
$("listProjectsBtn").addEventListener("click", async () => {
  const { ok, data, status } = await api("/api/jira/projects");
  showResult(ok, ok ? `Projects (${Array.isArray(data) ? data.length : "?"})` : `Failed — HTTP ${status}`, data);
  if (ok) {
    $("projectList").innerHTML = data.map((p) =>
      `<span class="pill"><b>${escapeHtml(p.key)}</b> — ${escapeHtml(p.name)}</span>`).join("");
  }
});

$("singleProjectBtn").addEventListener("click", async () => {
  const key = $("singleProjectKey").value.trim();
  if (!key) { alert("Enter a project key."); return; }
  const { ok, data, status } = await api("/api/jira/projects/" + encodeURIComponent(key));
  showResult(ok, ok ? `Project ${key}` : `Failed — HTTP ${status}`, data);
});

$("permittedBtn").addEventListener("click", async () => {
  const { ok, data, status } = await api("/api/jira/permissions/project", "POST", {});
  showResult(ok, ok ? "Permitted projects" : `Failed — HTTP ${status}`, data);
  if (ok && data.projects) {
    $("permittedList").innerHTML = data.projects.map((p) =>
      `<span class="pill">ID=${escapeHtml(p.id)} | KEY=${escapeHtml(p.key)}</span>`).join("");
  }
});

/* ---------- issues ---------- */
$("createIssueBtn").addEventListener("click", async () => {
  const project_key = $("cProject").value.trim();
  const summary = $("cSummary").value.trim();
  if (!project_key || !summary) { alert("Project key and summary are required."); return; }
  const { ok, data, status } = await api("/api/jira/issues", "POST", {
    project_key,
    summary,
    description: $("cDesc").value,
    issue_type: $("cType").value,
  });
  showResult(ok, ok ? `Created ${data.key}` : `Create failed — HTTP ${status}`, data);
  if (ok) { $("vKey").value = data.key; $("dKey").value = data.key; $("pKey").value = data.key; $("cmKey").value = data.key; }
});

$("getIssueBtn").addEventListener("click", async () => {
  const key = $("vKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const { ok, data, status } = await api("/api/jira/issues/" + encodeURIComponent(key));
  showResult(ok, ok ? `Retrieved ${key}` : `Retrieve failed — HTTP ${status}`, data);
  if (ok) {
    const f = data.fields || {};
    $("issueCard").innerHTML =
      `<div><span class="pill">${escapeHtml(data.key || "")}</span>` +
      `<span class="pill">${escapeHtml((f.status || {}).name || "?")}</span>` +
      `<span class="pill">${escapeHtml((f.priority || {}).name || "—")}</span></div>` +
      `<p><b>${escapeHtml(f.summary || "")}</b></p>` +
      `<p>${escapeHtml(adfToText(f.description) || "(empty description)")}</p>`;
    if (f.summary) $("uSummary").value = f.summary;
    const t = adfToText(f.description);
    if (t) $("uDesc").value = t;
  } else {
    $("issueCard").innerHTML = `<p>Could not load ${escapeHtml(key)} (HTTP ${status}). See raw JSON.</p>`;
  }
});

$("updateIssueBtn").addEventListener("click", async () => {
  const key = $("vKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const summary = $("uSummary").value.trim() || null;
  const description = $("uDesc").value || null;
  if (!summary && !description) { alert("Nothing to update."); return; }
  const { ok, data, status } = await api("/api/jira/issues/" + encodeURIComponent(key), "PUT", { summary, description });
  showResult(ok, ok ? `Updated ${key}` : `Update failed — HTTP ${status}`, data);
});

/* ---------- description ---------- */
$("getDescBtn").addEventListener("click", async () => {
  const key = $("dKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const { ok, data, status } = await api("/api/jira/issues/" + encodeURIComponent(key) + "/description");
  showResult(ok, ok ? `Description for ${key}` : `Failed — HTTP ${status}`, data);
  if (ok) {
    $("dText").value = data.text || "";
    $("descCard").innerHTML = `<p>${escapeHtml(data.text || "(empty)")}</p>`;
  }
});

$("setDescBtn").addEventListener("click", async () => {
  const key = $("dKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const { ok, data, status } = await api(
    "/api/jira/issues/" + encodeURIComponent(key) + "/description", "PUT",
    { description: $("dText").value });
  showResult(ok, ok ? "Description updated" : `Failed — HTTP ${status}`, data);
});

/* ---------- priority ---------- */
$("listPriBtn").addEventListener("click", async () => {
  const { ok, data, status } = await api("/api/jira/priorities");
  showResult(ok, ok ? `Priorities (${Array.isArray(data) ? data.length : "?"})` : `Failed — HTTP ${status}`, data);
  if (ok) {
    $("priorityList").innerHTML = data.map((p) =>
      `<span class="pill"><b>${escapeHtml(p.name)}</b> (id=${escapeHtml(p.id)})</span>`).join("");
  }
});

$("updatePriBtn").addEventListener("click", async () => {
  const key = $("pKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const { ok, data, status } = await api(
    "/api/jira/issues/" + encodeURIComponent(key) + "/priority", "PUT",
    { priority: $("pValue").value });
  showResult(ok, ok ? `Priority updated for ${key}` : `Failed — HTTP ${status}`, data);
});

/* ---------- comments ---------- */
$("listCmBtn").addEventListener("click", async () => {
  const key = $("cmKey").value.trim();
  if (!key) { alert("Enter an issue key."); return; }
  const { ok, data, status } = await api("/api/jira/issues/" + encodeURIComponent(key) + "/comments");
  showResult(ok, ok ? `Comments for ${key}` : `Failed — HTTP ${status}`, data);
  if (ok) {
    const comments = data.comments || [];
    $("commentList").innerHTML = comments.length
      ? comments.map((c) => `<div class="comment"><div class="comment-id">ID: ${escapeHtml(c.id)} — ${escapeHtml((c.author || {}).displayName || "")}</div><div>${escapeHtml(adfToText(c.body))}</div></div>`).join("")
      : `<p class="muted">No comments yet.</p>`;
  }
});

$("addCmBtn").addEventListener("click", async () => {
  const key = $("cmKey").value.trim();
  const comment = $("cmText").value.trim();
  if (!key || !comment) { alert("Issue key and comment text are required."); return; }
  const { ok, data, status } = await api("/api/jira/issues/" + encodeURIComponent(key) + "/comments", "POST", { comment });
  showResult(ok, ok ? "Comment added" : `Failed — HTTP ${status}`, data);
  if (ok) $("listCmBtn").click();
});

$("updateCmBtn").addEventListener("click", async () => {
  const key = $("cmKey").value.trim();
  const id = $("cmId").value.trim();
  const comment = $("cmEdit").value.trim();
  if (!key || !id || !comment) { alert("Issue key, comment ID and text are required."); return; }
  const { ok, data, status } = await api(
    `/api/jira/issues/${encodeURIComponent(key)}/comments/${encodeURIComponent(id)}`, "PUT", { comment });
  showResult(ok, ok ? "Comment updated" : `Failed — HTTP ${status}`, data);
  if (ok) $("listCmBtn").click();
});

$("deleteCmBtn").addEventListener("click", async () => {
  const key = $("cmKey").value.trim();
  const id = $("cmId").value.trim();
  if (!key || !id) { alert("Issue key and comment ID are required."); return; }
  if (!confirm(`Delete comment ${id} on ${key}?`)) return;
  const res = await fetch(`/api/jira/issues/${encodeURIComponent(key)}/comments/${encodeURIComponent(id)}`, { method: "DELETE" });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  showResult(res.ok, res.ok ? "Comment deleted" : `Failed — HTTP ${res.status}`, data);
  if (res.ok) $("listCmBtn").click();
});

refreshStatus();

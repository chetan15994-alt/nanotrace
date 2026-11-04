// ==========================================================================
// NanoTrace Client-Side Application
// Pure Vanilla JavaScript, zero external dependencies.
// ==========================================================================

let currentTraces = [];
let activeTraceId = null;
let activeTraceSpans = [];
let selectedSpanId = null;
let currentDb = ""; // empty means server default

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  await loadDatabases();
  loadDashboard();
  if (window.location.hash.toLowerCase().includes("guide")) {
    switchView("guide");
  }
});

// ==========================================================================
// Database Management (Dynamic duckdb switching)
// ==========================================================================

async function loadDatabases() {
  try {
    const res = await fetch("/api/databases");
    const dbs = await res.json();
    const select = document.getElementById("dbSelect");
    if (!select || !dbs || dbs.length === 0) return;

    select.innerHTML = dbs.map(d => {
      const isSelected = (currentDb === d.name || (!currentDb && d.is_default)) ? "selected" : "";
      return `<option value="${escapeHtml(d.name)}" ${isSelected}>🦆 ${escapeHtml(d.name)} (${d.total_spans} spans)</option>`;
    }).join("");

    if (!currentDb) {
      const activeObj = dbs.find(d => d.is_default);
      if (activeObj) currentDb = activeObj.name;
    }
  } catch (err) {
    console.error("Failed to list databases", err);
  }
}

function onDatabaseChange(dbName) {
  currentDb = dbName;
  activeTraceId = null;
  selectedSpanId = null;
  loadDashboard();
}

// ==========================================================================
// Theme Management (Light & Dark with persistence)
// ==========================================================================

function initTheme() {
  const savedTheme = localStorage.getItem("nanotrace_theme");
  if (savedTheme) {
    document.documentElement.setAttribute("data-theme", savedTheme);
  } else {
    // Check system preference
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  const target = current === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", target);
  localStorage.setItem("nanotrace_theme", target);
}

// ==========================================================================
// View Navigation (Traces vs. Guide)
// ==========================================================================

function switchView(viewName) {
  const tabTracesBtn = document.getElementById("tabTracesBtn");
  const tabGuideBtn = document.getElementById("tabGuideBtn");
  const viewTraces = document.getElementById("viewTraces");
  const viewGuide = document.getElementById("viewGuide");

  if (viewName === "traces") {
    tabTracesBtn.classList.add("active");
    tabGuideBtn.classList.remove("active");
    viewTraces.classList.add("active");
    viewGuide.classList.remove("active");
  } else {
    tabTracesBtn.classList.remove("active");
    tabGuideBtn.classList.add("active");
    viewTraces.classList.remove("active");
    viewGuide.classList.add("active");
  }
}

// ==========================================================================
// Data Loading (Stats & Traces)
// ==========================================================================

async function loadDashboard() {
  await Promise.all([loadStats(), loadTraces()]);
}

async function loadStats() {
  try {
    const url = currentDb ? `/api/stats?db=${encodeURIComponent(currentDb)}` : "/api/stats";
    const res = await fetch(url);
    const data = await res.json();
    document.getElementById("valTotalTraces").innerText = data.total_traces || 0;
    document.getElementById("valTotalSpans").innerText = data.total_spans || 0;
    document.getElementById("valTotalTokens").innerText = Number(data.total_tokens || 0).toLocaleString();
    document.getElementById("valTotalCost").innerText = "$" + Number(data.total_cost_usd || 0).toFixed(4);
    document.getElementById("valP50").innerText = (data.p50_duration_ms || 0) + " ms";
    document.getElementById("valErrorRate").innerText = (data.error_rate_pct || 0) + "%";
  } catch (err) {
    console.error("Failed to load metrics", err);
  }
}

async function loadTraces() {
  const listEl = document.getElementById("traceList");
  try {
    const url = currentDb ? `/api/traces?db=${encodeURIComponent(currentDb)}` : "/api/traces";
    const res = await fetch(url);
    currentTraces = await res.json();
    renderTraceList(currentTraces);
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Unable to read traces from DuckDB.</div>`;
  }
}

function renderTraceList(traces) {
  const listEl = document.getElementById("traceList");
  if (!traces || traces.length === 0) {
    listEl.innerHTML = `<div class="empty-state">No traces logged yet.<br>Execute an agent script to see spans.</div>`;
    return;
  }

  listEl.innerHTML = traces.map(t => {
    const isError = t.status === "ERROR";
    const statusClass = isError ? "error" : "ok";
    const name = t.root_name || "Agent Run";
    const isActive = t.trace_id === activeTraceId ? "active" : "";

    return `
      <div class="trace-row ${isActive}" onclick="selectTrace('${t.trace_id}')">
        <div class="trace-row-top">
          <span class="trace-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
          <span class="trace-status-pill ${statusClass}">
            <span class="status-dot ${statusClass}"></span>
            ${t.status}
          </span>
        </div>
        <div class="trace-row-meta">
          <span>${t.duration_ms} ms</span>
          <span>•</span>
          <span>${Number(t.total_tokens || 0).toLocaleString()} tok</span>
          <span>•</span>
          <span>${t.total_spans} spans</span>
        </div>
      </div>
    `;
  }).join("");
}

function filterTraces() {
  const q = document.getElementById("traceSearch").value.toLowerCase();
  const filtered = currentTraces.filter(t => 
    (t.root_name || "").toLowerCase().includes(q) || 
    (t.trace_id || "").toLowerCase().includes(q)
  );
  renderTraceList(filtered);
}

// ==========================================================================
// Trace Selection & Waterfall
// ==========================================================================

async function selectTrace(traceId) {
  activeTraceId = traceId;
  selectedSpanId = null;
  renderTraceList(currentTraces);

  document.getElementById("traceActionButtons").style.display = "flex";
  document.getElementById("evalCard").style.display = "none";
  closeDrawer();

  try {
    const url = currentDb ? `/api/traces/${traceId}?db=${encodeURIComponent(currentDb)}` : `/api/traces/${traceId}`;
    const res = await fetch(url);
    activeTraceSpans = await res.json();

    const rootSpan = activeTraceSpans.find(s => !s.parent_span_id) || activeTraceSpans[0];
    document.getElementById("activeTraceTitle").innerText = rootSpan ? rootSpan.name : "Trace: " + traceId.slice(0, 8);
    document.getElementById("activeTraceMeta").innerHTML = `
      <span>TraceID: <code>${traceId}</code></span> • 
      <span>${activeTraceSpans.length} spans</span> • 
      <span>Total latency: ${rootSpan ? rootSpan.duration_ms : 0} ms</span>
    `;

    renderWaterfall(activeTraceSpans);
  } catch (err) {
    console.error("Error loading trace detail", err);
  }
}

function renderWaterfall(spans) {
  const canvas = document.getElementById("waterfallCanvas");
  if (!spans || spans.length === 0) {
    canvas.innerHTML = `<div class="empty-state">No spans found for this trace.</div>`;
    return;
  }

  const minStart = Math.min(...spans.map(s => Number(s.start_time_ns)));
  const maxEnd = Math.max(...spans.map(s => Number(s.end_time_ns)));
  const totalDurationNs = Math.max(1, maxEnd - minStart);
  const totalDurationMs = totalDurationNs / 1_000_000;

  // Build tree depth map
  const depthMap = {};
  spans.forEach(s => {
    let depth = 0;
    let currParent = s.parent_span_id;
    while (currParent) {
      depth++;
      const p = spans.find(x => x.span_id === currParent);
      currParent = p ? p.parent_span_id : null;
    }
    depthMap[s.span_id] = depth;
  });

  // Waterfall timeline ruler header
  const rulerHtml = `
    <div class="waterfall-header-ruler">
      <div class="ruler-title-col">Span / Operation Hierarchy</div>
      <div class="ruler-ticks-col">
        <span>0 ms</span>
        <span>${(totalDurationMs * 0.25).toFixed(1)} ms</span>
        <span>${(totalDurationMs * 0.50).toFixed(1)} ms</span>
        <span>${(totalDurationMs * 0.75).toFixed(1)} ms</span>
        <span>${totalDurationMs.toFixed(1)} ms</span>
      </div>
      <div class="ruler-duration-col">Duration</div>
    </div>
  `;

  const rowsHtml = spans.map(s => {
    const startOffset = Math.max(0, (Number(s.start_time_ns) - minStart) / totalDurationNs * 100);
    const widthPct = Math.max(0.6, (Number(s.end_time_ns) - Number(s.start_time_ns)) / totalDurationNs * 100);
    const depth = depthMap[s.span_id] || 0;
    const indentPx = depth * 16;

    let badgeClass = "kind-internal";
    let badgeLabel = s.kind;
    if (s.gen_ai_operation === "agent_run") {
      badgeClass = "kind-agent";
      badgeLabel = "agent";
    } else if (s.gen_ai_operation === "chat") {
      badgeClass = "kind-chat";
      badgeLabel = s.gen_ai_request_model || "llm";
    } else if (s.gen_ai_operation === "execute_tool" || s.gen_ai_tool_name) {
      badgeClass = "kind-tool";
      badgeLabel = "tool";
    }

    const isError = s.status === "ERROR";
    const barClass = isError ? "span-bar error" : "span-bar";
    const isSelected = s.span_id === selectedSpanId ? "selected" : "";

    return `
      <div class="span-row ${isSelected}" onclick="openDrawer('${s.span_id}')">
        <div class="span-name-col" style="padding-left: ${indentPx}px">
          <span class="kind-badge ${badgeClass}">${escapeHtml(badgeLabel)}</span>
          <span class="span-text" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
        </div>
        <div class="span-timeline-track">
          <div class="${barClass}" style="left: ${startOffset}%; width: ${widthPct}%;"></div>
        </div>
        <div class="span-dur-col">${s.duration_ms} ms</div>
      </div>
    `;
  }).join("");

  canvas.innerHTML = rulerHtml + rowsHtml;
}

// ==========================================================================
// Span Inspection Drawer
// ==========================================================================

function openDrawer(spanId) {
  selectedSpanId = spanId;
  renderWaterfall(activeTraceSpans);

  const span = activeTraceSpans.find(s => s.span_id === spanId);
  if (!span) return;

  const drawer = document.getElementById("spanDrawer");
  document.getElementById("drawerSpanName").innerText = span.name;
  document.getElementById("drawerSpanKind").innerText = span.gen_ai_operation || span.kind;

  // Overview tab
  const kvGrid = document.getElementById("drawerOverviewKv");
  kvGrid.innerHTML = `
    <div class="kv-item"><span class="kv-key">Trace ID</span><span class="kv-val">${span.trace_id}</span></div>
    <div class="kv-item"><span class="kv-key">Span ID</span><span class="kv-val">${span.span_id}</span></div>
    <div class="kv-item"><span class="kv-key">Parent Span</span><span class="kv-val">${span.parent_span_id || "Root (None)"}</span></div>
    <div class="kv-item"><span class="kv-key">Operation</span><span class="kv-val">${span.gen_ai_operation || span.kind}</span></div>
    <div class="kv-item"><span class="kv-key">Provider / System</span><span class="kv-val">${span.gen_ai_system || "—"}</span></div>
    <div class="kv-item"><span class="kv-key">Requested Model</span><span class="kv-val">${span.gen_ai_request_model || "—"}</span></div>
    <div class="kv-item"><span class="kv-key">Duration</span><span class="kv-val">${span.duration_ms} ms</span></div>
    <div class="kv-item"><span class="kv-key">Tokens (In / Out / Total)</span><span class="kv-val">${span.gen_ai_input_tokens} / ${span.gen_ai_output_tokens} / ${span.gen_ai_total_tokens}</span></div>
    <div class="kv-item"><span class="kv-key">Est. Cost (USD)</span><span class="kv-val">$${Number(span.gen_ai_cost_usd || 0).toFixed(6)}</span></div>
    <div class="kv-item"><span class="kv-key">Status</span><span class="kv-val" style="color: ${span.status === 'ERROR' ? 'var(--color-error)' : 'var(--color-success)'}">${span.status}</span></div>
  `;

  // Payloads tab
  let promptText = span.prompt_payload;
  try { promptText = JSON.stringify(JSON.parse(span.prompt_payload), null, 2); } catch (_) {}
  document.getElementById("drawerPrompt").innerText = promptText || "(No input recorded)";

  let compText = span.completion_payload;
  try { compText = JSON.stringify(JSON.parse(span.completion_payload), null, 2); } catch (_) {}
  document.getElementById("drawerCompletion").innerText = compText || "(No completion recorded)";

  // OTel JSON tab
  let attrsText = span.attributes_json;
  try { attrsText = JSON.stringify(JSON.parse(span.attributes_json), null, 2); } catch (_) {}
  document.getElementById("drawerOtelJson").innerText = attrsText || "{}";

  drawer.style.display = "flex";
}

function closeDrawer() {
  document.getElementById("spanDrawer").style.display = "none";
  selectedSpanId = null;
  if (activeTraceSpans.length > 0) {
    renderWaterfall(activeTraceSpans);
  }
}

function switchDrawerTab(tabName) {
  document.querySelectorAll(".drawer-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".drawer-tab-content").forEach(c => c.classList.remove("active"));

  if (tabName === "overview") {
    document.querySelectorAll(".drawer-tab")[0].classList.add("active");
    document.getElementById("dtab-overview").classList.add("active");
  } else if (tabName === "payloads") {
    document.querySelectorAll(".drawer-tab")[1].classList.add("active");
    document.getElementById("dtab-payloads").classList.add("active");
  } else if (tabName === "otel") {
    document.querySelectorAll(".drawer-tab")[2].classList.add("active");
    document.getElementById("dtab-otel").classList.add("active");
  }
}

// ==========================================================================
// Local Heuristic Evaluations
// ==========================================================================

async function runTraceEvals() {
  if (!activeTraceId) return;
  const card = document.getElementById("evalCard");
  card.innerHTML = `<span style="font-size:0.8rem; color:var(--text-muted);">Running diagnostic heuristics on trace...</span>`;
  card.style.display = "flex";

  try {
    const url = currentDb ? `/api/evals/${activeTraceId}?db=${encodeURIComponent(currentDb)}` : `/api/evals/${activeTraceId}`;
    const res = await fetch(url);
    const results = await res.json();

    card.innerHTML = results.map(r => {
      const color = r.passed ? "var(--color-success)" : "var(--color-error)";
      const icon = r.passed ? "✓ Passed" : "✕ Flagged";
      const readableName = r.metric_name.replace(/_/g, " ");

      return `
        <div class="eval-col">
          <span class="eval-col-title">${escapeHtml(readableName)}</span>
          <span class="eval-col-val" style="color: ${color};">
            ${(r.score * 100).toFixed(0)}% <span style="font-size:0.75rem; font-weight:normal;">(${icon})</span>
          </span>
        </div>
      `;
    }).join("");
  } catch (err) {
    card.innerHTML = `<span style="color: var(--color-error); font-size:0.8rem;">Evaluation failed.</span>`;
  }
}

// ==========================================================================
// Utilities
// ==========================================================================

function copyTraceId() {
  if (!activeTraceId) return;
  navigator.clipboard.writeText(activeTraceId);
  const btn = document.getElementById("copyIdBtn");
  const orig = btn.innerHTML;
  btn.innerHTML = `<span>Copied!</span>`;
  setTimeout(() => { btn.innerHTML = orig; }, 1500);
}

function switchGuideCodeTab(tabName, btn) {
  // Update button active state
  const buttons = document.querySelectorAll(".code-tab-btn");
  buttons.forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");

  // Update tab contents
  const tabs = ["native", "langgraph", "crewai", "pydantic", "evals"];
  tabs.forEach(t => {
    const el = document.getElementById(`gcode-${t}`);
    if (el) {
      el.style.display = (t === tabName) ? "block" : "none";
    }
  });
}

function copySnippet(btn) {
  const container = btn.closest(".code-box");
  const codeEl = container.querySelector("code");
  if (!codeEl) return;
  navigator.clipboard.writeText(codeEl.innerText).then(() => {
    const orig = btn.innerText;
    btn.innerText = "Copied!";
    setTimeout(() => { btn.innerText = orig; }, 1500);
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

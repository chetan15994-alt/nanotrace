// ==========================================================================
// NanoTrace Client-Side Application
// Pure Vanilla JavaScript, zero external dependencies.
// ==========================================================================

let currentTraces = [];
let activeTraceId = null;
let activeTraceSpans = [];
let selectedSpanId = null;
let currentDb = ""; // empty means server default
let currentLens = localStorage.getItem("nanotrace_active_lens") || "business";

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  if (window.location.hash.toLowerCase().includes("guide")) {
    switchView("guide");
  }
  await loadDatabases();
  loadDashboard();
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

    if (!activeTraceId && currentTraces.length > 0) {
      if (window.location.hash.includes("trace=")) {
        const hashId = window.location.hash.split("trace=")[1].split("&")[0];
        const match = currentTraces.find(t => t.trace_id === hashId);
        if (match) {
          selectTrace(match.trace_id);
          return;
        }
      }
      selectTrace(currentTraces[0].trace_id);
    }
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

    const lensGroup = document.getElementById("lensToggleGroup");
    if (lensGroup) lensGroup.style.display = "inline-flex";
    updateLensButtons();
    renderActiveLens();
  } catch (err) {
    console.error("Error loading trace detail", err);
  }
}

// ==========================================================================
// Dual-Audience Lens Management (Business vs Hacker)
// ==========================================================================

function switchLens(lensName) {
  currentLens = lensName;
  localStorage.setItem("nanotrace_active_lens", lensName);
  updateLensButtons();
  renderActiveLens();
}

function updateLensButtons() {
  const btnBiz = document.getElementById("lensBtnBiz");
  const btnHacker = document.getElementById("lensBtnHacker");
  if (btnBiz && btnHacker) {
    if (currentLens === "business") {
      btnBiz.classList.add("active");
      btnHacker.classList.remove("active");
    } else {
      btnBiz.classList.remove("active");
      btnHacker.classList.add("active");
    }
  }
}

function renderActiveLens() {
  const bizCanvas = document.getElementById("businessCanvas");
  const waterfallCanvas = document.getElementById("waterfallCanvas");
  if (!bizCanvas || !waterfallCanvas) return;

  if (currentLens === "business") {
    waterfallCanvas.style.display = "none";
    bizCanvas.style.display = "flex";
    renderBusinessLens(activeTraceSpans);
  } else {
    bizCanvas.style.display = "none";
    waterfallCanvas.style.display = "block";
    renderWaterfall(activeTraceSpans);
  }
}

function renderBusinessLens(spans) {
  const canvas = document.getElementById("businessCanvas");
  if (!spans || spans.length === 0) {
    canvas.innerHTML = `<div class="empty-state">No spans found for this trace.</div>`;
    return;
  }

  const rootSpan = spans.find(s => !s.parent_span_id) || spans[0];
  const totalMs = rootSpan ? rootSpan.duration_ms : 0;
  const totalTokens = spans.reduce((acc, s) => acc + Number(s.gen_ai_total_tokens || 0), 0);
  const totalCost = spans.reduce((acc, s) => acc + Number(s.gen_ai_cost_usd || 0), 0);
  const toolCount = spans.filter(s => s.gen_ai_operation === "execute_tool" || s.gen_ai_tool_name).length;
  const llmCount = spans.filter(s => s.gen_ai_operation === "chat").length;
  const isError = spans.some(s => s.status === "ERROR");

  // Executive Scorecard
  const scorecardHtml = `
    <div class="biz-scorecard">
      <div class="biz-metric-item">
        <span class="biz-metric-label">Execution Status</span>
        <span class="biz-metric-val" style="color: ${isError ? 'var(--color-error)' : 'var(--color-success)'}">
          ${isError ? '● Error Detected' : '● Operational OK'}
        </span>
      </div>
      <div class="biz-metric-item">
        <span class="biz-metric-label">Turnaround Time</span>
        <span class="biz-metric-val">${totalMs} ms</span>
      </div>
      <div class="biz-metric-item">
        <span class="biz-metric-label">LLM Consultations</span>
        <span class="biz-metric-val">${llmCount} calls</span>
      </div>
      <div class="biz-metric-item">
        <span class="biz-metric-label">Tools Executed</span>
        <span class="biz-metric-val">${toolCount} tools</span>
      </div>
      <div class="biz-metric-item">
        <span class="biz-metric-label">Total Tokens</span>
        <span class="biz-metric-val">${totalTokens.toLocaleString()}</span>
      </div>
      <div class="biz-metric-item">
        <span class="biz-metric-label">Economic Cost</span>
        <span class="biz-metric-val">$${totalCost.toFixed(5)}</span>
      </div>
    </div>
  `;

  // Conversational Stream Cards
  const cards = [];

  // Card 1: User Objective / Trigger
  let initialPrompt = rootSpan.prompt_payload;
  if (!initialPrompt || initialPrompt === '""' || initialPrompt === "{}") {
    const firstChat = spans.find(s => s.gen_ai_operation === "chat" && s.prompt_payload && s.prompt_payload !== '""');
    if (firstChat) initialPrompt = firstChat.prompt_payload;
  }
  try {
    const parsed = JSON.parse(initialPrompt);
    if (Array.isArray(parsed) && parsed.length > 0) {
      const userMsg = parsed.find(m => m.role === "user") || parsed[0];
      initialPrompt = userMsg.content || userMsg.text || initialPrompt;
    } else if (typeof parsed === "string") {
      initialPrompt = parsed;
    }
  } catch (_) {}

  if (!initialPrompt || initialPrompt.trim() === '""' || initialPrompt.trim() === "") {
    initialPrompt = `Autonomous execution initiated for ${rootSpan.name || 'agent'}`;
  }

  cards.push(`
    <div class="biz-chat-card">
      <div class="biz-card-head">
        <span class="biz-tag biz-tag-user">👤 User Objective / Trigger</span>
        <span style="font-size:0.75rem; color:var(--text-muted);">Root Prompt</span>
      </div>
      <div class="biz-body">${escapeHtml(initialPrompt)}</div>
    </div>
  `);

  // Intermediate Action Cards
  spans.forEach(s => {
    if (s.span_id === rootSpan.span_id && spans.length > 1) return;

    const isTool = s.gen_ai_operation === "execute_tool" || s.gen_ai_tool_name;
    const isChat = s.gen_ai_operation === "chat";

    let bodyText = s.completion_payload || s.prompt_payload || "";
    try {
      const p = JSON.parse(bodyText);
      if (typeof p === "string") bodyText = p;
    } catch (_) {}
    if (!bodyText || bodyText.trim() === '""' || bodyText.trim() === "") {
      bodyText = isTool 
        ? "Tool executed successfully with zero errors." 
        : `Completed operation in ${s.duration_ms} ms (${s.gen_ai_total_tokens || 0} tokens).`;
    }

    if (isTool) {
      cards.push(`
        <div class="biz-chat-card" onclick="openDrawer('${s.span_id}')" style="cursor:pointer;" title="Click to view full tool execution details">
          <div class="biz-card-head">
            <span class="biz-tag biz-tag-tool">🛠️ Tool Invoked: ${escapeHtml(s.gen_ai_tool_name || s.name)}</span>
            <div class="biz-chips">
              <span class="biz-chip">⏱️ ${s.duration_ms} ms</span>
              <span class="biz-chip">Inspect ↗</span>
            </div>
          </div>
          <div class="biz-body">${escapeHtml(bodyText)}</div>
        </div>
      `);
    } else if (isChat) {
      cards.push(`
        <div class="biz-chat-card" onclick="openDrawer('${s.span_id}')" style="cursor:pointer;" title="Click to inspect model attributes">
          <div class="biz-card-head">
            <span class="biz-tag biz-tag-agent">🧠 AI Deliberation (${escapeHtml(s.gen_ai_request_model || 'LLM')})</span>
            <div class="biz-chips">
              <span class="biz-chip">⏱️ ${s.duration_ms} ms</span>
              <span class="biz-chip">${s.gen_ai_total_tokens} tokens</span>
              <span class="biz-chip">$${Number(s.gen_ai_cost_usd || 0).toFixed(5)}</span>
            </div>
          </div>
          <div class="biz-body">${escapeHtml(bodyText)}</div>
        </div>
      `);
    }
  });

  // Final Output Card
  let finalCompletion = rootSpan.completion_payload;
  try {
    const fp = JSON.parse(finalCompletion);
    if (typeof fp === "string") finalCompletion = fp;
  } catch (_) {}

  if (finalCompletion && finalCompletion.trim() !== '""' && finalCompletion.trim() !== "") {
    cards.push(`
      <div class="biz-chat-card">
        <div class="biz-card-head">
          <span class="biz-tag biz-tag-output">🎯 Final Agent Deliverable</span>
          <span style="font-size:0.75rem; color:var(--color-success); font-weight:700;">✓ Completed in ${totalMs} ms</span>
        </div>
        <div class="biz-body resolution">${escapeHtml(finalCompletion)}</div>
      </div>
    `);
  }

  canvas.innerHTML = scorecardHtml + `<div class="biz-card-stream">${cards.join("")}</div>`;
}

function exportActiveTraceCapsule() {
  if (!activeTraceId) return;
  const url = currentDb 
    ? `/api/traces/${activeTraceId}/export-html?db=${encodeURIComponent(currentDb)}` 
    : `/api/traces/${activeTraceId}/export-html`;
  
  const link = document.createElement("a");
  link.href = url;
  link.download = `${activeTraceId}.ntrace.html`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
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

  // Smart ruler ticks with automatic unit scaling (µs vs ms vs s)
  let tickFmt;
  if (totalDurationMs < 0.1) {
    tickFmt = val => `${(val * 1000).toFixed(0)} µs`;
  } else if (totalDurationMs < 10) {
    tickFmt = val => `${val.toFixed(2)} ms`;
  } else if (totalDurationMs < 1000) {
    tickFmt = val => `${val.toFixed(1)} ms`;
  } else {
    tickFmt = val => `${(val / 1000).toFixed(2)} s`;
  }

  // Waterfall timeline ruler header
  const rulerHtml = `
    <div class="waterfall-header-ruler">
      <div class="ruler-title-col">Span / Operation Hierarchy</div>
      <div class="ruler-ticks-col">
        <span>0</span>
        <span>${tickFmt(totalDurationMs * 0.25)}</span>
        <span>${tickFmt(totalDurationMs * 0.50)}</span>
        <span>${tickFmt(totalDurationMs * 0.75)}</span>
        <span>${tickFmt(totalDurationMs)}</span>
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

// ==========================================================================
// Poster Audience Perspective Toggle (Layman vs. Technical)
// ==========================================================================

function togglePosterMode(mode) {
  const pLayman = document.getElementById("posterLayman");
  const pTech = document.getElementById("posterTech");
  const btnL = document.getElementById("toggleLaymanBtn");
  const btnT = document.getElementById("toggleTechBtn");
  if (!pLayman || !pTech) return;

  if (mode === "layman") {
    pLayman.style.display = "flex";
    pTech.style.display = "none";
    if (btnL && btnT) {
      btnL.style.background = "var(--accent-primary)";
      btnL.style.color = "#ffffff";
      btnT.style.background = "transparent";
      btnT.style.color = "var(--text-muted)";
    }
  } else {
    pLayman.style.display = "none";
    pTech.style.display = "flex";
    if (btnL && btnT) {
      btnT.style.background = "var(--accent-primary)";
      btnT.style.color = "#ffffff";
      btnL.style.background = "transparent";
      btnL.style.color = "var(--text-muted)";
    }
  }
}

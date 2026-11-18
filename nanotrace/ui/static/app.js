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
let currentReplaySpanId = null;
let lastForkedTraceId = null;

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
  const tabRegressionBtn = document.getElementById("tabRegressionBtn");
  const tabPromptBtn = document.getElementById("tabPromptBtn");
  const tabSafetyBtn = document.getElementById("tabSafetyBtn");
  const tabFleetBtn = document.getElementById("tabFleetBtn");
  const viewTraces = document.getElementById("viewTraces");
  const viewGuide = document.getElementById("viewGuide");
  const viewRegression = document.getElementById("viewRegression");
  const viewPromptStudio = document.getElementById("viewPromptStudio");
  const viewSafety = document.getElementById("viewSafety");
  const viewFleet = document.getElementById("viewFleet");

  [tabTracesBtn, tabGuideBtn, tabRegressionBtn, tabPromptBtn, tabSafetyBtn, tabFleetBtn].forEach(b => b && b.classList.remove("active"));
  [viewTraces, viewGuide, viewRegression, viewPromptStudio, viewSafety, viewFleet].forEach(v => v && v.classList.remove("active"));

  if (viewName === "traces") {
    if (tabTracesBtn) tabTracesBtn.classList.add("active");
    if (viewTraces) viewTraces.classList.add("active");
  } else if (viewName === "guide") {
    if (tabGuideBtn) tabGuideBtn.classList.add("active");
    if (viewGuide) viewGuide.classList.add("active");
  } else if (viewName === "regression") {
    if (tabRegressionBtn) tabRegressionBtn.classList.add("active");
    if (viewRegression) viewRegression.classList.add("active");
    loadGoldenDatasets();
    loadRegressionRuns();
  } else if (viewName === "prompt") {
    if (tabPromptBtn) tabPromptBtn.classList.add("active");
    if (viewPromptStudio) viewPromptStudio.classList.add("active");
    loadPromptStudio();
  } else if (viewName === "safety") {
    if (tabSafetyBtn) tabSafetyBtn.classList.add("active");
    if (viewSafety) viewSafety.classList.add("active");
    if (currentSafetyTab === "redteam") {
      loadRedTeamScans();
    } else {
      loadRAGRadar();
    }
  } else if (viewName === "fleet") {
    if (tabFleetBtn) tabFleetBtn.classList.add("active");
    if (viewFleet) viewFleet.classList.add("active");
    if (currentFleetTab === "topology") {
      loadTopologyAnalysis();
    } else {
      loadFleetOverview();
    }
  }
}

// ==========================================================================
// Data Loading (Stats & Traces)
// ==========================================================================

async function loadDashboard() {
  await Promise.all([loadStats(), loadTraces(), loadShieldStats(), loadFeedbackStats()]);
}

async function loadShieldStats() {
  try {
    const url = currentDb ? `/api/shield/stats?db=${encodeURIComponent(currentDb)}` : "/api/shield/stats";
    const res = await fetch(url);
    const data = await res.json();
    if (!data) return;

    const loopsEl = document.getElementById("shieldLoopsCount");
    const savedEl = document.getElementById("shieldSavedUsd");
    const badgeEl = document.getElementById("shieldStatusBadge");

    if (loopsEl) loopsEl.innerText = `🔄 ${data.loops_intercepted || 0} Runaway Loops Intercepted`;
    if (savedEl) savedEl.innerText = `💰 $${Number(data.estimated_spend_saved_usd || 0).toFixed(2)} Spend Saved`;
    if (badgeEl) {
      if (data.total_tripped > 0) {
        badgeEl.className = "shield-badge alert";
        badgeEl.innerText = `● ${data.total_tripped} BREACHES INTERCEPTED`;
      } else {
        badgeEl.className = "shield-badge ok";
        badgeEl.innerText = "● ACTIVE & MONITORING";
      }
    }
  } catch (err) {
    console.debug("Failed to load shield stats", err);
  }
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
      <div class="biz-body">${escapeHtml(sanitizeBase64ForDisplay(initialPrompt))}</div>
    </div>
  `);

  // Intermediate Action Cards
  spans.forEach(s => {
    if (s.span_id === rootSpan.span_id && spans.length > 1) return;

    const isShieldTripped = s.attributes_json && (
      s.attributes_json.includes('"nanotrace.shield.tripped": true') || 
      s.attributes_json.includes('"nanotrace.shield.tripped":true')
    );

    if (isShieldTripped) {
      cards.push(`
        <div class="biz-chat-card" style="border: 1.5px solid var(--color-error); background: rgba(239, 68, 68, 0.06);">
          <div class="biz-card-head">
            <span class="biz-tag" style="color:var(--color-error); font-weight:800;">🛡️ NanoShield Active Circuit Breaker Intercepted</span>
            <span style="font-size:0.75rem; color:var(--color-error); font-weight:700;">HALTED IN-PROCESS (&lt; 1 µs)</span>
          </div>
          <div class="biz-body" style="border-left: 4px solid var(--color-error);">
            <strong>${escapeHtml(s.status_message || 'Circuit breaker tripped.')}</strong>
            <p style="margin-top:6px; font-size:0.8rem; color:var(--text-muted); line-height:1.4;">
              NanoShield actively intercepted runaway execution at this node before API bills or runaway recursion escalated.
            </p>
          </div>
        </div>
      `);
      return;
    }

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
          <div class="biz-body">${escapeHtml(sanitizeBase64ForDisplay(bodyText))}</div>
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
          <div class="biz-body">${escapeHtml(sanitizeBase64ForDisplay(bodyText))}</div>
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
        <div class="biz-body resolution">${escapeHtml(sanitizeBase64ForDisplay(finalCompletion))}</div>
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
          <button class="btn-fork-waterfall" onclick="event.stopPropagation(); openTimeTravelModal('${s.span_id}')" title="Time-Travel: Fork from this node">🔀 Fork</button>
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
  document.getElementById("drawerPrompt").innerText = sanitizeBase64ForDisplay(promptText) || "(No input recorded)";

  let compText = span.completion_payload;
  try { compText = JSON.stringify(JSON.parse(span.completion_payload), null, 2); } catch (_) {}
  document.getElementById("drawerCompletion").innerText = sanitizeBase64ForDisplay(compText) || "(No completion recorded)";

  // Phase 4: Multi-Modal Media Detection in Drawer
  const pMedia = extractClientMedia(span.prompt_payload);
  const cMedia = extractClientMedia(span.completion_payload);
  const allMedia = [...pMedia, ...cMedia];
  const gallery = document.getElementById("drawerMediaGallery");
  const mediaBadge = document.getElementById("drawerMediaBadge");

  if (gallery) {
    if (allMedia.length > 0) {
      if (mediaBadge) {
        mediaBadge.innerText = allMedia.length;
        mediaBadge.style.display = "inline";
      }
      gallery.innerHTML = allMedia.map((m, idx) => `
        <div class="media-card" onclick="openMediaLightbox('${encodeURIComponent(m.url)}', '${escapeHtml(m.label)}', '${m.mime}')">
          ${m.type === 'image' 
            ? `<img src="${m.url}" class="media-thumb" alt="Artifact">` 
            : `<div class="media-thumb" style="display:flex;align-items:center;justify-content:center;background:#1e293b;font-size:1.8rem;">🎵</div>`}
          <div class="media-card-info">
            <span class="media-card-label">${escapeHtml(m.label)}</span>
            <span class="media-card-sub">${m.type.toUpperCase()} • Click to Zoom</span>
          </div>
        </div>
      `).join("");
    } else {
      if (mediaBadge) mediaBadge.style.display = "none";
      gallery.innerHTML = `<div style="color:var(--text-muted); font-size:0.8rem; padding:20px; text-align:center;">No visual or audio media detected in this execution span.</div>`;
    }
  }

  // Phase 4: Feedback state check
  checkSpanFeedbackState(span.trace_id, span.span_id);

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
  } else if (tabName === "media") {
    document.querySelectorAll(".drawer-tab")[2].classList.add("active");
    document.getElementById("dtab-media").classList.add("active");
  } else if (tabName === "otel") {
    document.querySelectorAll(".drawer-tab")[3].classList.add("active");
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

// ==========================================================================
// Time-Travel Agent Debugger & Replay Engine
// ==========================================================================

async function openTimeTravelModal(spanId) {
  currentReplaySpanId = spanId;
  const modal = document.getElementById("replayModalOverlay");
  const diffBox = document.getElementById("replayDiffBox");
  if (!modal) return;

  if (diffBox) diffBox.style.display = "none";

  const span = activeTraceSpans.find(s => s.span_id === spanId);
  const nodeTitle = span ? span.name : "Span " + spanId.slice(0, 8);
  const nameEl = document.getElementById("replayNodeName");
  if (nameEl) nameEl.innerText = `Fork & Replay: ${nodeTitle}`;

  // Fetch lineage context
  try {
    const url = currentDb ? `/api/replay/${spanId}/context?db=${encodeURIComponent(currentDb)}` : `/api/replay/${spanId}/context`;
    const res = await fetch(url);
    const ctx = await res.json();

    // Populate lineage chips
    const chipsEl = document.getElementById("replayLineageChips");
    if (chipsEl) {
      if (ctx.ancestors && ctx.ancestors.length > 0) {
        chipsEl.innerHTML = ctx.ancestors.map(a => `<span class="lineage-chip">${escapeHtml(a.name)}</span> → `).join("") + 
          `<span class="lineage-chip" style="font-weight:700; color:var(--accent-primary);">${escapeHtml(nodeTitle)}</span>`;
      } else {
        chipsEl.innerHTML = `<span class="lineage-chip" style="font-weight:700; color:var(--accent-primary);">Root: ${escapeHtml(nodeTitle)}</span>`;
      }
    }

    // Populate prompt input
    let pText = span ? span.prompt_payload : "";
    try {
      const parsed = JSON.parse(pText);
      if (typeof parsed === "string") pText = parsed;
    } catch (_) {}
    const pInput = document.getElementById("replayPromptInput");
    if (pInput) pInput.value = pText || "";

    // Set model
    const m = (span && span.gen_ai_request_model) ? span.gen_ai_request_model : "gpt-4o-mini";
    const selectEl = document.getElementById("replayModelSelect");
    if (selectEl) {
      const hasOpt = Array.from(selectEl.options).some(o => o.value === m);
      if (hasOpt) selectEl.value = m;
      else selectEl.value = "gpt-4o-mini";
    }
  } catch (err) {
    console.error("Error loading replay context", err);
  }

  modal.classList.add("open");
}

function closeReplayModal(e) {
  if (e && e.target !== document.getElementById("replayModalOverlay")) return;
  const modal = document.getElementById("replayModalOverlay");
  if (modal) modal.classList.remove("open");
  currentReplaySpanId = null;
}

async function executeReplayBranch() {
  if (!currentReplaySpanId) return;

  const btn = document.getElementById("btnExecuteReplay");
  const origBtnText = btn.innerHTML;
  btn.innerHTML = `<span>⏳ Re-executing in-process...</span>`;
  btn.disabled = true;

  const prompt = document.getElementById("replayPromptInput").value;
  const model = document.getElementById("replayModelSelect").value;
  const temp = parseFloat(document.getElementById("replayTempSlider").value) || 0.7;

  try {
    const url = currentDb 
      ? `/api/traces/${activeTraceId}/fork?db=${encodeURIComponent(currentDb)}` 
      : `/api/traces/${activeTraceId}/fork`;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        span_id: currentReplaySpanId,
        prompt: prompt,
        model: model,
        temperature: temp,
      }),
    });

    const forkRes = await res.json();
    lastForkedTraceId = forkRes.forked_trace_id;

    // Render diff results
    const scorecardsEl = document.getElementById("diffScorecards");
    if (scorecardsEl) {
      scorecardsEl.innerHTML = `
        <div class="diff-metric-cell">
          <span class="diff-metric-label">Duration</span>
          <span class="diff-metric-val">${forkRes.original_duration_ms}ms → ${forkRes.forked_duration_ms}ms</span>
        </div>
        <div class="diff-metric-cell">
          <span class="diff-metric-label">Tokens</span>
          <span class="diff-metric-val">${forkRes.original_tokens} → ${forkRes.forked_tokens}</span>
        </div>
        <div class="diff-metric-cell">
          <span class="diff-metric-label">Cost</span>
          <span class="diff-metric-val">$${Number(forkRes.original_cost_usd || 0).toFixed(5)} → $${Number(forkRes.forked_cost_usd || 0).toFixed(5)}</span>
        </div>
        <div class="diff-metric-cell">
          <span class="diff-metric-label">Model</span>
          <span class="diff-metric-val">${escapeHtml(forkRes.model)}</span>
        </div>
      `;
    }

    const origEl = document.getElementById("diffOrigText");
    const forkedEl = document.getElementById("diffForkedText");
    if (origEl) origEl.innerText = forkRes.original_completion || "(Empty original completion)";
    if (forkedEl) forkedEl.innerText = forkRes.forked_completion || "(Forked completion output)";
    
    const diffBox = document.getElementById("replayDiffBox");
    if (diffBox) diffBox.style.display = "block";
  } catch (err) {
    alert("Replay execution failed: " + err.message);
  } finally {
    btn.innerHTML = origBtnText;
    btn.disabled = false;
  }
}

async function switchToForkedTrace() {
  if (!lastForkedTraceId) return;
  const modal = document.getElementById("replayModalOverlay");
  if (modal) modal.classList.remove("open");

  await loadDashboard();
  selectTrace(lastForkedTraceId);
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

// ==========================================================================
// Phase 3: Golden Datasets & Prompt Regression Matrix Client
// ==========================================================================

let activeGoldenDataset = "default";
let currentRegressionResults = [];

async function loadGoldenDatasets() {
  try {
    const url = currentDb ? `/api/golden/datasets?db=${encodeURIComponent(currentDb)}` : `/api/golden/datasets`;
    const res = await fetch(url);
    const datasets = await res.json();
    const select = document.getElementById("regDatasetSelect");
    const badge = document.getElementById("regDatasetCountBadge");
    if (badge) badge.innerText = `${datasets.length} Set${datasets.length === 1 ? '' : 's'}`;

    if (select) {
      if (datasets.length === 0) {
        select.innerHTML = `<option value="default">default (0 cases)</option>`;
      } else {
        select.innerHTML = datasets.map(d => 
          `<option value="${escapeHtml(d.dataset_name)}" ${d.dataset_name === activeGoldenDataset ? 'selected' : ''}>
            ${escapeHtml(d.dataset_name)} (${d.case_count} cases)
          </option>`
        ).join("");
      }
    }
    loadGoldenCases(activeGoldenDataset);
  } catch (err) {
    console.error("Failed loading golden datasets:", err);
  }
}

function onRegressionDatasetChange(datasetName) {
  activeGoldenDataset = datasetName;
  loadGoldenCases(datasetName);
}

async function loadGoldenCases(datasetName) {
  const container = document.getElementById("goldCasesList");
  if (!container) return;
  try {
    const url = currentDb 
      ? `/api/golden/cases?dataset=${encodeURIComponent(datasetName)}&db=${encodeURIComponent(currentDb)}`
      : `/api/golden/cases?dataset=${encodeURIComponent(datasetName)}`;
    const res = await fetch(url);
    const cases = await res.json();

    if (cases.length === 0) {
      container.innerHTML = `
        <div style="padding:24px 16px; text-align:center; color:var(--text-muted); font-size:0.85rem;">
          No golden cases in <strong>${escapeHtml(datasetName)}</strong>.<br><br>
          <span style="font-size:0.78rem;">Open any trace in the waterfall, click on a span, and click <strong>"🌟 Save as Golden"</strong> to curate tests.</span>
        </div>`;
      return;
    }

    container.innerHTML = cases.map(c => `
      <div class="gold-case-card" onclick="selectGoldenCaseForTesting('${c.case_id}')">
        <div class="gold-case-title">${escapeHtml(c.name)}</div>
        <div class="gold-case-prompt">${escapeHtml(c.input_prompt || c.expected_output || 'No prompt preview')}</div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px; font-size:0.72rem; color:var(--text-muted);">
          <span>ID: ${c.case_id.slice(0, 10)}</span>
          <button class="btn btn-replay-inline" style="padding:1px 6px; font-size:0.68rem;" onclick="event.stopPropagation(); deleteGoldenCaseUI('${c.case_id}')">✕ Delete</button>
        </div>
      </div>
    `).join("");
  } catch (err) {
    console.error("Failed loading golden cases:", err);
  }
}

async function saveSelectedSpanAsGoldenCase() {
  if (!selectedSpanId || !activeTraceSpans) {
    alert("Please select a span first!");
    return;
  }
  const span = activeTraceSpans.find(s => s.span_id === selectedSpanId);
  if (!span) return;

  const datasetName = prompt("Enter Golden Dataset name:", activeGoldenDataset || "default");
  if (!datasetName) return;

  const caseName = prompt("Enter descriptive title for this test case:", `Gold: ${span.name}`);
  if (!caseName) return;

  try {
    const url = currentDb ? `/api/golden/save?db=${encodeURIComponent(currentDb)}` : `/api/golden/save`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trace_id: span.trace_id,
        span_id: span.span_id,
        name: caseName,
        dataset_name: datasetName,
      })
    });
    if (!res.ok) throw new Error(await res.text());
    const caseData = await res.json();
    alert(`🌟 Golden test case #${caseData.case_id} saved to dataset '${datasetName}'!`);
    loadGoldenDatasets();
  } catch (err) {
    alert(`Error saving golden test case: ${err.message}`);
  }
}

async function deleteGoldenCaseUI(caseId) {
  if (!confirm(`Delete golden case ${caseId}?`)) return;
  try {
    const url = currentDb ? `/api/golden/cases/${caseId}?db=${encodeURIComponent(currentDb)}` : `/api/golden/cases/${caseId}`;
    await fetch(url, { method: "DELETE" });
    loadGoldenCases(activeGoldenDataset);
  } catch (err) {
    alert(`Failed deleting case: ${err.message}`);
  }
}

async function runRegressionMatrixUI() {
  const btn = document.getElementById("btnRunRegression");
  const badge = document.getElementById("regRunStatusBadge");
  const basePrompt = document.getElementById("regBasePrompt").value;
  const candPrompt = document.getElementById("regCandPrompt").value;
  const baseModel = document.getElementById("regBaseModel").value;
  const candModel = document.getElementById("regCandModel").value;

  if (btn) btn.disabled = true;
  if (badge) {
    badge.innerText = "Running Matrix...";
    badge.style.background = "rgba(59, 130, 246, 0.2)";
    badge.style.color = "var(--accent-primary)";
  }

  try {
    const url = currentDb ? `/api/regression/run?db=${encodeURIComponent(currentDb)}` : `/api/regression/run`;
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataset_name: activeGoldenDataset,
        candidate_name: `Candidate (${candModel})`,
        baseline_name: `Baseline (${baseModel})`,
        candidate_prompt: candPrompt,
        baseline_prompt: basePrompt,
        candidate_model: candModel,
        baseline_model: baseModel,
        fail_under: 0.80,
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Regression run failed");
    }

    const runData = await res.json();
    displayRegressionRun(runData);
    loadRegressionRuns();
  } catch (err) {
    alert(`Regression Run Error: ${err.message}`);
    if (badge) {
      badge.innerText = "Error";
      badge.style.background = "rgba(239, 68, 68, 0.2)";
      badge.style.color = "#ef4444";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

function displayRegressionRun(run) {
  const badge = document.getElementById("regRunStatusBadge");
  if (badge) {
    if (run.passed) {
      badge.innerText = "✅ Quality Gate Passed";
      badge.style.background = "rgba(16, 185, 129, 0.15)";
      badge.style.color = "#10b981";
    } else {
      badge.innerText = "❌ Quality Gate Breached";
      badge.style.background = "rgba(239, 68, 68, 0.15)";
      badge.style.color = "#ef4444";
    }
  }

  // KPIs
  const elPassRate = document.getElementById("kpiRegPassRate");
  const elScoreDelta = document.getElementById("kpiRegScoreDelta");
  const elCostDelta = document.getElementById("kpiRegCostDelta");
  const elDurDelta = document.getElementById("kpiRegDurDelta");
  const elBreakdown = document.getElementById("kpiRegBreakdown");

  if (elPassRate) elPassRate.innerText = `${(run.pass_rate * 100).toFixed(1)}%`;
  if (elScoreDelta) {
    const sDelta = run.score_delta;
    elScoreDelta.innerText = `${sDelta >= 0 ? '+' : ''}${(sDelta * 100).toFixed(1)}%`;
    elScoreDelta.style.color = sDelta >= 0 ? "var(--color-success)" : "var(--color-danger)";
  }
  if (elCostDelta) {
    const cDelta = run.avg_cost_delta_pct;
    elCostDelta.innerText = `${cDelta >= 0 ? '+' : ''}${cDelta.toFixed(1)}%`;
    elCostDelta.style.color = cDelta <= 0 ? "var(--color-success)" : "var(--color-danger)";
  }
  if (elDurDelta) {
    const dDelta = run.avg_duration_delta_pct;
    elDurDelta.innerText = `${dDelta >= 0 ? '+' : ''}${dDelta.toFixed(1)}%`;
  }
  if (elBreakdown) {
    elBreakdown.innerHTML = `<span style="color:var(--color-success);">${run.improved_count} Improved</span> • <span style="color:var(--color-danger);">${run.regressed_count} Regressed</span> • ${run.unchanged_count} Flat`;
  }

  // Table
  currentRegressionResults = run.results || [];
  const tbody = document.getElementById("regressionResultsBody");
  if (!tbody) return;

  if (currentRegressionResults.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">No cases evaluated.</td></tr>`;
    return;
  }

  tbody.innerHTML = currentRegressionResults.map(r => {
    let statusClass = "status-badge-unchanged";
    let icon = "➖";
    if (r.status === "IMPROVED") { statusClass = "status-badge-improved"; icon = "✅"; }
    else if (r.status === "REGRESSED") { statusClass = "status-badge-regressed"; icon = "❌"; }

    return `
      <tr onclick="inspectRegressionCase('${r.case_id}')" style="cursor:pointer;" title="Click to inspect side-by-side completion diff">
        <td style="font-family:monospace; font-size:0.75rem; color:var(--text-muted);">${r.case_id.slice(0, 10)}</td>
        <td style="font-weight:600;">${escapeHtml(r.case_name)}</td>
        <td>${r.baseline_duration_ms}ms ➔ ${r.candidate_duration_ms}ms <span style="font-size:0.72rem; color:var(--text-muted);">(${r.duration_delta_pct > 0 ? '+' : ''}${r.duration_delta_pct}%)</span></td>
        <td>$${r.baseline_cost_usd.toFixed(4)} ➔ $${r.candidate_cost_usd.toFixed(4)} <span style="font-size:0.72rem; color:${r.cost_delta_pct <= 0 ? 'var(--color-success)' : 'var(--color-danger)'};">(${r.cost_delta_pct > 0 ? '+' : ''}${r.cost_delta_pct}%)</span></td>
        <td>${(r.baseline_score * 100).toFixed(0)}% ➔ ${(r.candidate_score * 100).toFixed(0)}% <span style="font-size:0.72rem; color:${r.score_delta >= 0 ? 'var(--color-success)' : 'var(--color-danger)'};">(${r.score_delta >= 0 ? '+' : ''}${(r.score_delta * 100).toFixed(0)}%)</span></td>
        <td><span class="${statusClass}">${icon} ${r.status}</span></td>
      </tr>
    `;
  }).join("");
}

function inspectRegressionCase(caseId) {
  const result = currentRegressionResults.find(r => r.case_id === caseId);
  const diffBox = document.getElementById("regSelectedCaseDiff");
  if (!result || !diffBox) return;

  diffBox.style.display = "block";
  document.getElementById("regDiffCaseTitle").innerText = `Completion Diff: ${result.case_name} (${result.status})`;
  document.getElementById("regDiffBaseText").innerText = result.baseline_output || "(empty baseline output)";
  document.getElementById("regDiffCandText").innerText = result.candidate_output || "(empty candidate output)";
  diffBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function closeRegressionDiff() {
  const diffBox = document.getElementById("regSelectedCaseDiff");
  if (diffBox) diffBox.style.display = "none";
}

async function loadRegressionRuns() {
  const list = document.getElementById("pastRegressionRunsList");
  if (!list) return;
  try {
    const url = currentDb ? `/api/regression/runs?db=${encodeURIComponent(currentDb)}` : `/api/regression/runs`;
    const res = await fetch(url);
    const runs = await res.json();
    if (runs.length === 0) {
      list.innerHTML = `<div style="color:var(--text-muted); font-size:0.78rem;">No past runs found.</div>`;
      return;
    }
    list.innerHTML = runs.map(r => `
      <div style="padding:6px 8px; border-radius:6px; margin-bottom:4px; background:var(--bg-surface); cursor:pointer; display:flex; justify-content:space-between; align-items:center;" onclick="loadAndDisplayRun('${r.run_id}')">
        <div>
          <span style="font-weight:600; color:var(--text-primary);">${escapeHtml(r.dataset_name)}</span>
          <span style="font-size:0.72rem; color:var(--text-muted); display:block;">${r.created_at.slice(0, 16)}</span>
        </div>
        <span class="${r.passed ? 'status-badge-improved' : 'status-badge-regressed'}" style="font-size:0.68rem;">
          ${r.passed ? 'PASS' : 'FAIL'} (${(r.pass_rate * 100).toFixed(0)}%)
        </span>
      </div>
    `).join("");
  } catch (err) {
    console.error("Failed loading regression runs:", err);
  }
}

async function loadAndDisplayRun(runId) {
  try {
    const url = currentDb ? `/api/regression/runs/${runId}?db=${encodeURIComponent(currentDb)}` : `/api/regression/runs/${runId}`;
    const res = await fetch(url);
    const run = await res.json();
    displayRegressionRun(run);
  } catch (err) {
    alert(`Failed to load regression run: ${err.message}`);
  }
}

// ==========================================================================
// Phase 4: Multi-Modal Utilities & Lightbox
// ==========================================================================

let activeLightboxUri = "";

function extractClientMedia(text) {
  if (!text || typeof text !== "string") return [];
  const items = [];
  const dataUriRegex = /(data:(image\/[a-zA-Z0-9\+\-\.]+|audio\/[a-zA-Z0-9\+\-\.]+|application\/pdf);base64,([A-Za-z0-9+/=]+))/gi;
  let match;
  while ((match = dataUriRegex.exec(text)) !== null) {
    const mime = match[2].toLowerCase();
    const size = Math.round(match[3].length * 0.75);
    items.push({
      type: mime.startsWith("image/") ? "image" : (mime.startsWith("audio/") ? "audio" : "document"),
      mime: mime,
      url: match[1],
      size: size,
      label: `${mime.split("/")[1].toUpperCase()} (${(size / 1024).toFixed(1)} KB)`,
    });
  }
  const urlRegex = /(https?:\/\/[^\s"\'<>]+\.(?:png|jpg|jpeg|webp|gif|svg)(?:\?[^\s"\'<>]*)?)/gi;
  while ((match = urlRegex.exec(text)) !== null) {
    if (!match[1].startsWith("data:")) {
      const ext = match[1].split("?")[0].split(".").pop().toLowerCase();
      items.push({
        type: "image",
        mime: "image/" + ext,
        url: match[1],
        size: 0,
        label: `Remote ${ext.toUpperCase()}`,
      });
    }
  }
  return items;
}

function sanitizeBase64ForDisplay(text) {
  if (!text || typeof text !== "string") return "";
  return text.replace(/(data:(image\/[a-zA-Z0-9\+\-\.]+|audio\/[a-zA-Z0-9\+\-\.]+|application\/pdf);base64,([A-Za-z0-9+/=]{100,}))/gi, function(match, full, mime, b64) {
    const sizeKb = ((b64.length * 0.75) / 1024).toFixed(1);
    const icon = mime.includes("image") ? "🖼️" : (mime.includes("audio") ? "🎵" : "📄");
    return `[${icon} Embedded Media: ${mime} (${sizeKb} KB)]`;
  });
}

function openMediaLightbox(urlEncoded, label, mime) {
  const modal = document.getElementById("mediaLightboxModal");
  const img = document.getElementById("lightboxImage");
  const title = document.getElementById("lightboxTitle");
  const meta = document.getElementById("lightboxMeta");
  if (!modal || !img) return;

  activeLightboxUri = decodeURIComponent(urlEncoded);
  img.src = activeLightboxUri;
  if (title) title.innerText = label || "Visual Artifact";
  if (meta) meta.innerText = mime || "Media Preview";
  modal.style.display = "flex";
}

function closeMediaLightbox(e) {
  const modal = document.getElementById("mediaLightboxModal");
  if (modal) modal.style.display = "none";
}

function copyLightboxUri() {
  if (!activeLightboxUri) return;
  navigator.clipboard.writeText(activeLightboxUri).then(() => {
    alert("Copied media URI/URL to clipboard!");
  }).catch(() => {
    alert("Clipboard copy failed.");
  });
}

// ==========================================================================
// Phase 4: Feedback Collector & Trace Association
// ==========================================================================

async function submitSpanFeedback(score) {
  if (!activeTraceId) return;
  const statusSpan = document.getElementById("spanFeedbackStatus");
  const banner = document.getElementById("goldenRecommendBanner");

  try {
    const res = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        trace_id: activeTraceId,
        span_id: selectedSpanId,
        score: score,
        comment: score > 0 ? "Marked helpful in dashboard" : "Flagged in dashboard",
      }),
    });
    if (res.ok) {
      if (statusSpan) {
        statusSpan.innerText = score > 0 ? "✓ Liked" : "✓ Flagged";
        statusSpan.style.color = score > 0 ? "var(--color-success)" : "var(--color-error)";
        statusSpan.style.display = "inline";
      }
      if (banner && score > 0) {
        banner.style.display = "flex";
      }
      loadFeedbackStats();
    }
  } catch (err) {
    console.error("Failed submitting feedback:", err);
  }
}

async function checkSpanFeedbackState(traceId, spanId) {
  const statusSpan = document.getElementById("spanFeedbackStatus");
  const banner = document.getElementById("goldenRecommendBanner");
  if (statusSpan) statusSpan.style.display = "none";
  if (banner) banner.style.display = "none";

  try {
    const res = await fetch(`/api/feedback?trace_id=${encodeURIComponent(traceId)}`);
    const entries = await res.json();
    if (entries.length > 0) {
      const latest = entries[0];
      if (statusSpan) {
        statusSpan.innerText = latest.score > 0 ? "👍 Liked" : "👎 Flagged";
        statusSpan.style.color = latest.score > 0 ? "var(--color-success)" : "var(--color-error)";
        statusSpan.style.display = "inline";
      }
      if (banner && latest.score > 0) {
        banner.style.display = "flex";
      }
    }
  } catch (_) {}
}

async function loadFeedbackStats() {
  const sentEl = document.getElementById("valNetSentiment");
  if (!sentEl) return;
  try {
    const res = await fetch("/api/feedback/stats");
    const data = await res.json();
    if (data.total_feedback > 0) {
      sentEl.innerText = `${data.net_sentiment_pct > 0 ? '+' : ''}${data.net_sentiment_pct}%`;
      sentEl.style.color = data.net_sentiment_pct >= 0 ? "var(--color-success)" : "var(--color-error)";
    } else {
      sentEl.innerText = "--";
    }
  } catch (_) {}
}

// ==========================================================================
// Phase 4: Prompt Studio & Registry Management
// ==========================================================================

let activePromptName = "";
let activePromptData = null;
let allPromptsCache = [];

async function loadPromptStudio() {
  try {
    const url = currentDb ? `/api/prompts?db=${encodeURIComponent(currentDb)}` : "/api/prompts";
    const res = await fetch(url);
    const prompts = await res.json();
    allPromptsCache = prompts;

    const countBadge = document.getElementById("promptRegistryCountBadge");
    if (countBadge) countBadge.innerText = `${prompts.length} Prompt${prompts.length === 1 ? "" : "s"}`;

    renderPromptsList(prompts);

    if (prompts.length > 0 && !activePromptName) {
      selectPrompt(prompts[0].name);
    } else if (prompts.length === 0) {
      createNewPromptForm();
    }
  } catch (err) {
    console.error("Failed loading prompts:", err);
  }
}

function renderPromptsList(prompts) {
  const container = document.getElementById("promptListContainer");
  if (!container) return;

  if (prompts.length === 0) {
    container.innerHTML = `<div style="padding:24px; text-align:center; color:var(--text-muted); font-size:0.8rem;">No prompts registered yet.<br>Click <strong>+ New</strong> to create one.</div>`;
    return;
  }

  container.innerHTML = prompts.map(p => {
    const isProd = p.active_tags && p.active_tags.includes("production");
    const isStaging = p.active_tags && p.active_tags.includes("staging");
    return `
      <div class="prompt-card ${p.name === activePromptName ? 'active' : ''}" onclick="selectPrompt('${escapeHtml(p.name)}')">
        <div class="prompt-card-top">
          <span class="prompt-card-name">${escapeHtml(p.name)}</span>
          <span class="tag-badge ${isProd ? 'prod' : (isStaging ? 'staging' : '')}">${p.latest_version}</span>
        </div>
        <div class="prompt-card-preview">${escapeHtml(p.template_preview || '(empty template)')}</div>
        <div class="prompt-card-tags">
          ${(p.active_tags || []).map(t => `<span class="tag-badge ${t === 'production' ? 'prod' : (t === 'staging' ? 'staging' : '')}">${escapeHtml(t)}</span>`).join("")}
          ${(p.variables || []).map(v => `<span class="var-pill">{{${escapeHtml(v)}}}</span>`).join("")}
        </div>
      </div>
    `;
  }).join("");
}

function filterPromptsList(query) {
  const q = (query || "").toLowerCase();
  const filtered = allPromptsCache.filter(p => 
    p.name.toLowerCase().includes(q) || 
    (p.template_preview && p.template_preview.toLowerCase().includes(q)) ||
    (p.active_tags && p.active_tags.some(t => t.toLowerCase().includes(q)))
  );
  renderPromptsList(filtered);
}

async function selectPrompt(name) {
  activePromptName = name;
  renderPromptsList(allPromptsCache);

  try {
    const url = currentDb ? `/api/prompts/${encodeURIComponent(name)}?db=${encodeURIComponent(currentDb)}` : `/api/prompts/${encodeURIComponent(name)}`;
    const res = await fetch(url);
    const data = await res.json();
    activePromptData = data;

    const p = data.prompt;
    document.getElementById("studioPromptTitle").innerText = p.name;
    document.getElementById("studioVersionBadge").innerText = p.version;
    document.getElementById("promptTemplateTextarea").value = p.template;
    document.getElementById("studioTagsInput").value = (p.tags || []).join(", ");
    document.getElementById("studioAuthorInput").value = p.author || "engineer";

    // Version select dropdown
    const vSelect = document.getElementById("studioVersionSelect");
    if (vSelect && data.versions) {
      vSelect.innerHTML = data.versions.map(v => `
        <option value="${v.version}" ${v.version === p.version ? 'selected' : ''}>
          ${v.version} ${v.tags.length > 0 ? `[${v.tags.join(',')}]` : ''}
        </option>
      `).join("");
    }

    // Tags strip
    const tagStrip = document.getElementById("studioTagBadges");
    if (tagStrip) {
      tagStrip.innerHTML = (p.tags || []).map(t => `
        <span class="tag-badge ${t === 'production' ? 'prod' : (t === 'staging' ? 'staging' : '')}">${escapeHtml(t)}</span>
      `).join("");
    }

    onTemplateInputChange(p.template);
  } catch (err) {
    console.error("Failed loading prompt details:", err);
  }
}

function createNewPromptForm() {
  activePromptName = "new_prompt";
  document.getElementById("studioPromptTitle").innerText = "Create New Prompt";
  document.getElementById("studioVersionBadge").innerText = "v1.0.0";
  document.getElementById("studioVersionSelect").innerHTML = `<option value="v1.0.0">v1.0.0</option>`;
  document.getElementById("promptTemplateTextarea").value = "You are an expert AI assistant. Please assist with {{task}} for {{user}}.";
  document.getElementById("studioTagsInput").value = "dev";
  document.getElementById("studioAuthorInput").value = "engineer";
  document.getElementById("studioTagBadges").innerHTML = `<span class="tag-badge">dev</span>`;

  onTemplateInputChange(document.getElementById("promptTemplateTextarea").value);
}

function onStudioVersionChange(version) {
  if (!activePromptData || !activePromptData.versions) return;
  const target = activePromptData.versions.find(v => v.version === version);
  if (!target) return;

  document.getElementById("studioVersionBadge").innerText = target.version;
  document.getElementById("promptTemplateTextarea").value = target.template;
  document.getElementById("studioTagsInput").value = (target.tags || []).join(", ");
  document.getElementById("studioAuthorInput").value = target.author || "engineer";

  const tagStrip = document.getElementById("studioTagBadges");
  if (tagStrip) {
    tagStrip.innerHTML = (target.tags || []).map(t => `
      <span class="tag-badge ${t === 'production' ? 'prod' : (t === 'staging' ? 'staging' : '')}">${escapeHtml(t)}</span>
    `).join("");
  }

  onTemplateInputChange(target.template);
}

function onTemplateInputChange(templateStr) {
  const varsFound = [];
  const regex = /\{\{([a-zA-Z0-9_]+)\}\}/g;
  let m;
  while ((m = regex.exec(templateStr)) !== null) {
    if (!varsFound.includes(m[1])) varsFound.push(m[1]);
  }

  // Update pills
  const pillBox = document.getElementById("promptVariablePills");
  if (pillBox) {
    pillBox.innerHTML = varsFound.length > 0 
      ? varsFound.map(v => `<span class="var-pill">{{${escapeHtml(v)}}}</span>`).join("")
      : `<span style="font-size:0.7rem; color:var(--text-muted);">None</span>`;
  }

  // Update parameter inputs
  const inputContainer = document.getElementById("sandboxVariableInputs");
  if (inputContainer) {
    if (varsFound.length === 0) {
      inputContainer.innerHTML = `<span style="color:var(--text-muted); font-size:0.75rem;">No variables detected in template.</span>`;
    } else {
      inputContainer.innerHTML = varsFound.map(v => `
        <div style="display:flex; align-items:center; gap:8px;">
          <label style="font-size:0.72rem; font-family:monospace; font-weight:700; width:90px; color:var(--text-muted);">${escapeHtml(v)}:</label>
          <input type="text" class="form-input sandbox-param-input" data-var="${escapeHtml(v)}" placeholder="value for ${escapeHtml(v)}" oninput="compilePromptPreview()" style="font-size:0.75rem; padding:4px 8px; flex:1;">
        </div>
      `).join("");
    }
  }

  compilePromptPreview();
}

function compilePromptPreview() {
  const template = document.getElementById("promptTemplateTextarea").value || "";
  const paramInputs = document.querySelectorAll(".sandbox-param-input");
  const values = {};
  paramInputs.forEach(inp => {
    values[inp.getAttribute("data-var")] = inp.value;
  });

  const compiled = template.replace(/\{\{([a-zA-Z0-9_]+)\}\}/g, (match, varName) => {
    return values[varName] !== undefined && values[varName] !== "" ? values[varName] : match;
  });

  const previewBox = document.getElementById("sandboxCompiledOutput");
  if (previewBox) {
    previewBox.innerText = compiled || "(empty template)";
  }
}

async function saveCurrentPrompt() {
  const name = activePromptName === "new_prompt" ? prompt("Enter prompt name (alphanumeric_snake_case):", "customer_agent") : activePromptName;
  if (!name) return;

  const template = document.getElementById("promptTemplateTextarea").value.trim();
  const tagsRaw = document.getElementById("studioTagsInput").value;
  const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);
  const author = document.getElementById("studioAuthorInput").value.trim() || "engineer";
  let version = document.getElementById("studioVersionSelect").value || "v1.0.0";

  // Auto-increment minor version on save if editing existing
  if (activePromptData && activePromptData.prompt && activePromptData.prompt.template !== template) {
    const parts = version.replace("v", "").split(".");
    if (parts.length === 3) {
      parts[1] = parseInt(parts[1], 10) + 1;
      version = `v${parts.join(".")}`;
    }
  }

  try {
    const url = currentDb ? `/api/prompts?db=${encodeURIComponent(currentDb)}` : "/api/prompts";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        template: template,
        version: version,
        tags: tags,
        author: author,
      }),
    });
    if (res.ok) {
      alert(`Prompt '${name}' (${version}) saved successfully!`);
      activePromptName = name;
      await loadPromptStudio();
      await selectPrompt(name);
    } else {
      const err = await res.json();
      alert(`Error saving prompt: ${err.detail || "Bad Request"}`);
    }
  } catch (err) {
    alert(`Failed to save prompt: ${err.message}`);
  }
}

async function promoteCurrentPrompt(tag = "production") {
  if (!activePromptName || activePromptName === "new_prompt") {
    alert("Please save the prompt first before promoting.");
    return;
  }
  const version = document.getElementById("studioVersionBadge").innerText;

  try {
    const url = currentDb ? `/api/prompts/promote?db=${encodeURIComponent(currentDb)}` : "/api/prompts/promote";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: activePromptName,
        version: version,
        tag: tag,
      }),
    });
    if (res.ok) {
      alert(`Prompt '${activePromptName}' (${version}) successfully promoted to '${tag}'!`);
      await loadPromptStudio();
      await selectPrompt(activePromptName);
    } else {
      const err = await res.json();
      alert(`Error promoting prompt: ${err.detail || "Bad Request"}`);
    }
  } catch (err) {
    alert(`Failed to promote prompt: ${err.message}`);
  }
}

function sendPromptToRegressionMatrix() {
  const template = document.getElementById("promptTemplateTextarea").value;
  if (!template) {
    alert("Please enter prompt template instructions first.");
    return;
  }

  // Switch to regression view
  switchView("regression");

  // Populate candidate prompt
  const candInput = document.getElementById("regCandPrompt");
  if (candInput) {
    candInput.value = template;
    candInput.scrollIntoView({ behavior: "smooth" });
    candInput.focus();
  }
}

// ==========================================================================
// Phase 5: RAG Hallucination Radar & Autonomous Red-Teaming Client
// ==========================================================================

let currentSafetyTab = "radar";
let activeRadarData = null;

function switchSafetyTab(tab) {
  currentSafetyTab = tab;
  const btnRadar = document.getElementById("subtabRadarBtn");
  const btnRedTeam = document.getElementById("subtabRedTeamBtn");
  const panelRadar = document.getElementById("panelRAGRadar");
  const panelRedTeam = document.getElementById("panelRedTeam");
  const actions = document.getElementById("safetySubnavActions");

  if (tab === "radar") {
    if (btnRadar) btnRadar.classList.add("active");
    if (btnRedTeam) btnRedTeam.classList.remove("active");
    if (panelRadar) panelRadar.style.display = "block";
    if (panelRedTeam) panelRedTeam.style.display = "none";
    if (actions) actions.style.display = "flex";
    loadRAGRadar();
  } else {
    if (btnRedTeam) btnRedTeam.classList.add("active");
    if (btnRadar) btnRadar.classList.remove("active");
    if (panelRedTeam) panelRedTeam.style.display = "block";
    if (panelRadar) panelRadar.style.display = "none";
    if (actions) actions.style.display = "none";
    loadRedTeamScans();
  }
}

async function loadRAGRadar() {
  const dbName = typeof currentDb !== "undefined" && currentDb ? currentDb : "";
  const dbParam = dbName ? `?db=${encodeURIComponent(dbName)}` : "";

  try {
    const res = await fetch(`/api/rag/radar${dbParam}`);
    if (!res.ok) return;
    const data = await res.json();
    activeRadarData = data;

    // Update KPI cards
    const kpiTotal = document.getElementById("ragKpiTotal");
    const kpiMean = document.getElementById("ragKpiMeanSim");
    const kpiVoid = document.getElementById("ragKpiVoidRate");
    const kpiVoidCount = document.getElementById("ragKpiVoidCount");
    const voidBadge = document.getElementById("radarVoidBadge");

    if (kpiTotal) kpiTotal.innerText = data.total_queries;
    if (kpiMean) kpiMean.innerText = Number(data.mean_similarity || 0).toFixed(3);
    if (kpiVoid) {
      kpiVoid.innerText = `${data.void_rate_pct}%`;
      kpiVoid.style.color = data.void_rate_pct < 10 ? "var(--color-success)" : (data.void_rate_pct < 25 ? "var(--color-warning)" : "var(--color-danger)");
    }
    if (kpiVoidCount) kpiVoidCount.innerText = `${data.semantic_void_count} voids detected (< 0.55 similarity)`;
    if (voidBadge) voidBadge.innerText = `${data.semantic_void_count} Void${data.semantic_void_count === 1 ? '' : 's'}`;

    renderRadarPoints(data.radar_points || []);
    renderRadarVoids(data.void_queries || []);
  } catch (err) {
    console.error("Failed to load RAG Radar:", err);
  }
}

function renderRadarPoints(points) {
  const group = document.getElementById("radarPointsGroup");
  if (!group) return;

  if (!points || points.length === 0) {
    group.innerHTML = `<text x="0" y="5" text-anchor="middle" font-size="7" fill="var(--text-muted)">No RAG queries recorded yet</text>`;
    return;
  }

  const tooltip = document.getElementById("radarTooltip");

  group.innerHTML = points.map((p, idx) => {
    const isVoid = p.point_type === "void";
    const r = isVoid ? 3.8 : 2.6;
    const fill = isVoid ? "#ef4444" : "#3b82f6";
    const cssClass = isVoid ? "radar-pt pt-void" : "radar-pt";

    return `
      <circle class="${cssClass}" cx="${p.x}" cy="${p.y}" r="${r}" fill="${fill}"
              data-idx="${idx}"
              onmouseenter="showRadarTooltip(event, ${idx})"
              onmouseleave="hideRadarTooltip()"></circle>
    `;
  }).join("");
}

function showRadarTooltip(event, idx) {
  if (!activeRadarData || !activeRadarData.radar_points) return;
  const pt = activeRadarData.radar_points[idx];
  if (!pt) return;

  const tooltip = document.getElementById("radarTooltip");
  if (!tooltip) return;

  const isVoid = pt.point_type === "void";
  tooltip.innerHTML = `
    <div style="font-weight:700; margin-bottom:3px; color:${isVoid ? '#ef4444' : 'var(--text-primary)'}">
      ${isVoid ? '🚨 Semantic Void Outlier' : '🔍 Grounded Query'}
    </div>
    <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">${escapeHtml(pt.text_snippet)}</div>
    <div style="display:flex; justify-content:space-between; font-size:0.68rem; font-family:monospace;">
      <span>Similarity: <strong>${pt.similarity.toFixed(3)}</strong></span>
      <span style="color:${isVoid ? '#ef4444' : '#10b981'}">${isVoid ? 'High Hallucination Risk' : 'Grounded Context'}</span>
    </div>
  `;

  tooltip.style.display = "block";
  tooltip.style.left = "14px";
  tooltip.style.top = "14px";
}

function hideRadarTooltip() {
  const tooltip = document.getElementById("radarTooltip");
  if (tooltip) tooltip.style.display = "none";
}

function renderRadarVoids(voids) {
  const container = document.getElementById("radarVoidsListContainer");
  if (!container) return;

  if (!voids || voids.length === 0) {
    container.innerHTML = `
      <div style="padding:24px; text-align:center; color:var(--text-muted); font-size:0.8rem;">
        ✅ Zero semantic voids detected! All queries matched relevant context chunks.
      </div>
    `;
    return;
  }

  container.innerHTML = voids.map(v => `
    <div class="radar-void-row">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:0.75rem; font-weight:700; color:#ef4444;">🚨 Void: ${escapeHtml(v.query_text.substring(0, 40))}...</span>
        <span style="font-size:0.7rem; font-family:monospace; background:rgba(239, 68, 68, 0.15); color:#ef4444; padding:2px 6px; border-radius:4px; font-weight:700;">
          Sim: ${v.mean_similarity.toFixed(3)}
        </span>
      </div>
      <span style="font-size:0.7rem; color:var(--text-muted);">
        Query: "${escapeHtml(v.query_text)}"
      </span>
      ${v.trace_id ? `
        <div style="margin-top:2px;">
          <a href="#" onclick="selectTrace('${v.trace_id}'); switchView('traces'); return false;" style="font-size:0.68rem; color:var(--accent-primary); text-decoration:none;">
            Inspect Trace Telemetry →
          </a>
        </div>
      ` : ''}
    </div>
  `).join("");
}

async function scanRAGSpansUI() {
  const btn = document.getElementById("btnScanRAG");
  if (btn) btn.innerText = "Scanning Spans...";
  const dbName = typeof currentDb !== "undefined" && currentDb ? currentDb : "";
  const dbParam = dbName ? `?db=${encodeURIComponent(dbName)}` : "";

  try {
    const res = await fetch(`/api/rag/scan${dbParam}`, { method: "POST" });
    const data = await res.json();
    alert(`Scanned stored spans and indexed ${data.scanned_count} retrieval operations into RAG Radar!`);
    await loadRAGRadar();
  } catch (err) {
    alert(`Failed to scan RAG spans: ${err.message}`);
  } finally {
    if (btn) btn.innerText = "🔄 Scan Spans for RAG";
  }
}

// --------------------------------------------------------------------------
// Red-Teaming Client Functions
// --------------------------------------------------------------------------

async function loadRedTeamScans() {
  const dbName = typeof currentDb !== "undefined" && currentDb ? currentDb : "";
  const dbParam = dbName ? `?db=${encodeURIComponent(dbName)}` : "";

  try {
    const res = await fetch(`/api/security/latest${dbParam}`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.status === "ok" && data.scorecard) {
      renderSecurityScorecard(data.scorecard);
    }
  } catch (err) {
    console.error("Failed to load latest security scan:", err);
  }
}

async function runRedTeamUI() {
  const targetName = document.getElementById("rtTargetInput").value || "Production Agent";
  const promptOverride = document.getElementById("rtPromptInput").value || "";
  const simSelect = document.getElementById("rtSimSelect").value || "safe";
  const btn = document.getElementById("btnRunRedTeam");

  // Threat types
  const types = [];
  if (document.getElementById("chkAtkInjection")?.checked) types.push("prompt_injection");
  if (document.getElementById("chkAtkJailbreak")?.checked) types.push("jailbreak");
  if (document.getElementById("chkAtkPII")?.checked) types.push("pii_extraction");
  if (document.getElementById("chkAtkLoop")?.checked) types.push("loop_bomb");
  if (document.getElementById("chkAtkFlood")?.checked) types.push("context_flood");
  if (document.getElementById("chkAtkHallucination")?.checked) types.push("hallucination_trap");

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>⏳ Simulating ${types.length * 2} Adversarial Vectors...</span>`;
  }

  const dbName = typeof currentDb !== "undefined" && currentDb ? currentDb : "";
  const dbParam = dbName ? `?db=${encodeURIComponent(dbName)}` : "";

  try {
    const res = await fetch(`/api/security/run${dbParam}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target_name: targetName,
        prompt_override: promptOverride,
        attack_types: types,
        model_simulate: simSelect,
      })
    });

    if (!res.ok) {
      const err = await res.json();
      alert(`Red-team scan failed: ${err.detail || "Server error"}`);
      return;
    }

    const card = await res.json();
    renderSecurityScorecard(card);
  } catch (err) {
    alert(`Failed to execute red-team suite: ${err.message}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span>⚔️ Launch Adversarial Red-Team Suite</span>`;
    }
  }
}

function renderSecurityScorecard(card) {
  const gradeCircle = document.getElementById("rtGradeCircle");
  const targetDisp = document.getElementById("rtTargetDisplay");
  const resilienceDisp = document.getElementById("rtResilienceDisplay");
  const bar = document.getElementById("rtResilienceBar");
  const atkCount = document.getElementById("rtAttacksCountDisplay");
  const breachesCount = document.getElementById("rtBreachesCountDisplay");
  const scanDate = document.getElementById("rtScanDate");
  const tableBody = document.getElementById("rtResultsTableBody");

  if (targetDisp) targetDisp.innerText = card.target_name || "Agent Target";
  if (resilienceDisp) resilienceDisp.innerText = `${card.resilience_pct.toFixed(1)}%`;
  if (scanDate) scanDate.innerText = `Scanned at ${card.created_at ? card.created_at.substring(11, 19) + ' UTC' : 'recently'}`;
  if (atkCount) atkCount.innerText = `${card.total_attacks} attacks evaluated`;
  if (breachesCount) breachesCount.innerText = `${card.breaches_detected} breaches detected`;

  // Color mapping
  let color = "#10b981";
  if (card.security_grade === "B") color = "#f59e0b";
  else if (card.security_grade === "C") color = "#ea580c";
  else if (card.security_grade === "F") color = "#ef4444";

  if (gradeCircle) {
    gradeCircle.innerText = card.security_grade;
    gradeCircle.style.background = color;
    gradeCircle.style.boxShadow = `0 4px 10px ${color}55`;
  }
  if (bar) {
    bar.style.width = `${card.resilience_pct}%`;
    bar.style.background = color;
  }
  if (resilienceDisp) resilienceDisp.style.color = color;

  // Render Table Rows
  if (tableBody) {
    if (!card.results || card.results.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:18px; color:var(--text-muted);">No attack outcomes recorded.</td></tr>`;
      return;
    }

    tableBody.innerHTML = card.results.map(r => {
      const isPass = r.passed_robustness;
      const verdictBadge = isPass 
        ? `<span class="status-badge-improved" style="font-size:0.68rem;">✓ DEFENDED</span>` 
        : `<span class="status-badge-regressed" style="font-size:0.68rem;">❌ BREACH</span>`;
      
      const defenseLabel = r.guardrail_tripped 
        ? `🛡️ ${escapeHtml(r.guardrail_tripped)}` 
        : (isPass ? `Safe Model Refusal` : `<span style="color:#ef4444;">Vulnerable Target</span>`);

      return `
        <tr>
          <td>
            <div style="font-weight:700; color:var(--text-primary);">${escapeHtml(r.name)}</div>
            <div style="font-size:0.68rem; color:var(--text-muted); font-family:monospace; margin-top:2px;">${escapeHtml(r.prompt_sent.substring(0, 50))}...</div>
          </td>
          <td>
            <span style="font-size:0.7rem; font-family:monospace; color:var(--text-muted);">${escapeHtml(r.attack_type)}</span>
          </td>
          <td>
            <div style="font-size:0.72rem;">${defenseLabel}</div>
            <div style="font-size:0.65rem; color:var(--text-muted);">${escapeHtml(r.interception_reason || '')}</div>
          </td>
          <td style="text-align:center;">${verdictBadge}</td>
        </tr>
      `;
    }).join("");
  }
}

// ==========================================================================
// Phase 6: NanoFleet Multi-Node Sync & Swarm Topology Optimizer
// ==========================================================================

let currentFleetTab = "hub";
let activeTopologyTraceId = null;

function switchFleetTab(tab) {
  currentFleetTab = tab;
  const hubBtn = document.getElementById("fleetSubNavHub");
  const topoBtn = document.getElementById("fleetSubNavTopology");
  const hubPanel = document.getElementById("panelFleetHub");
  const topoPanel = document.getElementById("panelFleetTopology");

  if (tab === "hub") {
    if (hubBtn) hubBtn.classList.add("active");
    if (topoBtn) topoBtn.classList.remove("active");
    if (hubPanel) { hubPanel.style.display = "block"; hubPanel.classList.add("active"); }
    if (topoPanel) { topoPanel.style.display = "none"; topoPanel.classList.remove("active"); }
    loadFleetOverview();
  } else {
    if (topoBtn) topoBtn.classList.add("active");
    if (hubBtn) hubBtn.classList.remove("active");
    if (hubPanel) { hubPanel.style.display = "none"; hubPanel.classList.remove("active"); }
    if (topoPanel) { topoPanel.style.display = "block"; topoPanel.classList.add("active"); }
    populateTopologyTraceSelect();
    loadTopologyAnalysis();
  }
}

async function loadFleetOverview() {
  try {
    const url = currentDb ? `/api/fleet/overview?db=${encodeURIComponent(currentDb)}` : "/api/fleet/overview";
    const res = await fetch(url);
    if (!res.ok) return;
    const data = await res.json();

    const totalNodesEl = document.getElementById("valFleetTotalNodes");
    const activeNodesEl = document.getElementById("valFleetActiveNodes");
    const aggSpansEl = document.getElementById("valFleetAggSpans");
    const lastSyncBadge = document.getElementById("fleetLastSyncBadge");
    const nodesGrid = document.getElementById("fleetNodesGrid");

    if (totalNodesEl) totalNodesEl.innerText = data.total_nodes || 0;
    if (activeNodesEl) activeNodesEl.innerText = data.active_nodes || 0;
    if (aggSpansEl) aggSpansEl.innerText = Number(data.total_spans_aggregated || data.aggregated_spans || 0).toLocaleString();

    if (lastSyncBadge) {
      if (data.last_sync_time && data.last_sync_time !== "No sync executed") {
        lastSyncBadge.innerText = `Last Sync: ${data.last_sync_time}`;
      } else {
        lastSyncBadge.innerText = "Last Sync: Ready";
      }
    }

    if (nodesGrid) {
      if (!data.nodes || data.nodes.length === 0) {
        nodesGrid.innerHTML = `
          <div style="padding:28px; text-align:center; color:var(--text-muted); font-size:0.8rem; grid-column:1/-1; background:var(--bg-card); border-radius:8px; border:1px dashed var(--border-color);">
            No distributed fleet nodes registered yet. Click <strong>Export Snapshot</strong> or <strong>Ingest Fleet Parquet</strong> below to synchronize distributed agent nodes.
          </div>
        `;
        return;
      }

      nodesGrid.innerHTML = data.nodes.map(node => {
        const isOnline = node.status === "active";
        const syncStr = node.last_sync_at || 'Never';
        const uriDisp = node.target_uri ? node.target_uri.split('/').slice(-2).join('/') : 'local-lakehouse';

        return `
          <div class="fleet-node-card">
            <div class="fleet-node-header">
              <span class="fleet-node-title">🖥️ ${escapeHtml(node.node_id)}</span>
              <span class="fleet-node-badge ${isOnline ? 'badge-active' : 'badge-syncing'}">
                ${isOnline ? '● ACTIVE' : '○ IDLE'}
              </span>
            </div>
            <div style="display:flex; flex-direction:column; gap:4px; font-size:0.74rem;">
              <div style="display:flex; justify-content:space-between; color:var(--text-secondary);">
                <span>Hostname / Host:</span>
                <span style="font-family:monospace; color:var(--text-primary); font-size:0.7rem;">${escapeHtml(node.hostname || 'localhost')} (${escapeHtml(node.ip_address || '127.0.0.1')})</span>
              </div>
              <div style="display:flex; justify-content:space-between; color:var(--text-secondary);">
                <span>Target URI:</span>
                <span style="font-family:monospace; color:var(--text-primary); font-size:0.7rem;" title="${escapeHtml(node.target_uri || '')}">${escapeHtml(uriDisp)}</span>
              </div>
              <div style="display:flex; justify-content:space-between; color:var(--text-secondary);">
                <span>Ingested Spans:</span>
                <strong style="color:var(--text-primary);">${Number(node.spans_synced || 0).toLocaleString()}</strong>
              </div>
              <div style="display:flex; justify-content:space-between; color:var(--text-secondary);">
                <span>Last Sync:</span>
                <span>${escapeHtml(syncStr)}</span>
              </div>
            </div>
          </div>
        `;
      }).join("");
    }
  } catch (err) {
    console.error("Failed to load fleet overview:", err);
  }
}

async function exportFleetSnapshotUI() {
  const targetDirInput = document.getElementById("fleetTargetInput");
  const targetDir = targetDirInput ? targetDirInput.value.trim() : "./.traces/fleet_sync";
  const badge = document.getElementById("fleetLastSyncBadge");

  if (badge) badge.innerText = "Exporting compressed Parquet snapshot...";

  try {
    const url = currentDb ? `/api/fleet/sync?db=${encodeURIComponent(currentDb)}` : "/api/fleet/sync";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "export", target_dir: targetDir })
    });
    const data = await res.json();
    if (res.ok) {
      const filesCount = data.files_written ? data.files_written.length : 1;
      if (badge) badge.innerText = `Exported ${data.spans_exported} spans (${filesCount} Parquet file) in ${data.elapsed_ms}ms`;
      loadFleetOverview();
    } else {
      if (badge) badge.innerText = `Export error: ${data.detail || 'failed'}`;
    }
  } catch (err) {
    console.error("Export snapshot failed:", err);
    if (badge) badge.innerText = `Export failed: ${err.message}`;
  }
}

async function importFleetSnapshotsUI() {
  const targetDirInput = document.getElementById("fleetTargetInput");
  const targetDir = targetDirInput ? targetDirInput.value.trim() : "./.traces/fleet_sync";
  const badge = document.getElementById("fleetLastSyncBadge");

  if (badge) badge.innerText = "Ingesting Parquet snapshots into Lakehouse...";

  try {
    const url = currentDb ? `/api/fleet/sync?db=${encodeURIComponent(currentDb)}` : "/api/fleet/sync";
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: "import", target_dir: targetDir })
    });
    const data = await res.json();
    if (res.ok) {
      if (badge) badge.innerText = `Ingested ${data.spans_imported} spans from Parquet snapshots`;
      loadFleetOverview();
      loadDashboard();
    } else {
      if (badge) badge.innerText = `Import error: ${data.detail || 'failed'}`;
    }
  } catch (err) {
    console.error("Import snapshots failed:", err);
    if (badge) badge.innerText = `Import failed: ${err.message}`;
  }
}

async function populateTopologyTraceSelect() {
  const sel = document.getElementById("topoTraceSelect");
  if (!sel) return;

  try {
    let traceList = (typeof traces !== "undefined" && Array.isArray(traces) && traces.length > 0) ? traces : [];
    if (traceList.length === 0) {
      const url = currentDb ? `/api/traces?db=${encodeURIComponent(currentDb)}` : "/api/traces";
      const res = await fetch(url);
      if (res.ok) {
        traceList = await res.json();
      }
    }

    const currentVal = sel.value;
    sel.innerHTML = `<option value="">Latest Execution Trace</option>` + traceList.map(t => {
      const label = `${t.trace_id.substring(0, 8)}... (${escapeHtml(t.root_span_name || 'Workflow')}) - ${t.span_count} spans`;
      return `<option value="${escapeHtml(t.trace_id)}">${label}</option>`;
    }).join("");

    if (currentVal) sel.value = currentVal;
  } catch (err) {
    console.error("Error populating topology trace select:", err);
  }
}

function onTopologyTraceChange() {
  const sel = document.getElementById("topoTraceSelect");
  const traceId = sel ? sel.value : "";
  loadTopologyAnalysis(traceId);
}

function refreshTopologyUI() {
  const sel = document.getElementById("topoTraceSelect");
  const traceId = sel ? sel.value : "";
  loadTopologyAnalysis(traceId);
}

async function loadTopologyAnalysis(traceId) {
  try {
    let url = traceId 
      ? `/api/topology/trace/${encodeURIComponent(traceId)}` 
      : `/api/topology/latest`;
    if (currentDb) {
      url += (url.includes('?') ? '&' : '?') + `db=${encodeURIComponent(currentDb)}`;
    }

    const res = await fetch(url);
    if (!res.ok) return;
    const analysis = await res.json();

    const stepsVal = document.getElementById("topoStepsVal");
    const agentsVal = document.getElementById("topoAgentsVal");
    const critVal = document.getElementById("topoCritVal");
    const overheadVal = document.getElementById("topoOverheadVal");

    if (stepsVal) stepsVal.innerText = analysis.total_steps || 0;
    if (agentsVal) agentsVal.innerText = analysis.total_agents || analysis.agent_count || 0;
    const critLatency = analysis.critical_path_ms ?? analysis.critical_path_latency_ms ?? 0;
    if (critVal) critVal.innerText = `${critLatency.toFixed(1)} ms`;
    if (overheadVal) overheadVal.innerText = `${(analysis.communication_overhead_pct || 0).toFixed(1)}%`;

    renderTopologyDAG(analysis);
    renderTopologyRecs(analysis.recommendations || []);
  } catch (err) {
    console.error("Failed to load topology analysis:", err);
  }
}

function renderTopologyDAG(analysis) {
  const edgesGroup = document.getElementById("topologyEdgesGroup");
  const nodesGroup = document.getElementById("topologyNodesGroup");
  if (!edgesGroup || !nodesGroup) return;

  edgesGroup.innerHTML = "";
  nodesGroup.innerHTML = "";

  const nodes = analysis.nodes || [];
  const edges = analysis.edges || [];

  if (nodes.length === 0) {
    nodesGroup.innerHTML = `
      <text x="350" y="210" text-anchor="middle" fill="var(--text-muted)" font-size="13">
        No execution nodes found for this trace. Select a trace with agent/tool spans.
      </text>
    `;
    return;
  }

  // Build DAG parent relationships from edges
  const nodeMap = new Map();
  nodes.forEach(n => nodeMap.set(n.id, n));

  const incomingEdges = new Map();
  nodes.forEach(n => incomingEdges.set(n.id, []));
  edges.forEach(e => {
    if (incomingEdges.has(e.target)) {
      incomingEdges.get(e.target).push(e.source);
    }
  });

  const levels = new Map();
  // Find roots (nodes with 0 incoming edges from valid nodes)
  nodes.forEach(n => {
    const parents = (incomingEdges.get(n.id) || []).filter(pid => nodeMap.has(pid));
    if (parents.length === 0) {
      levels.set(n.id, 0);
    }
  });

  // Assign BFS levels
  let changed = true;
  let iterations = 0;
  while (changed && iterations < 20) {
    changed = false;
    iterations++;
    nodes.forEach(n => {
      const parents = (incomingEdges.get(n.id) || []).filter(pid => nodeMap.has(pid));
      if (parents.length > 0) {
        let maxPL = 0;
        parents.forEach(pid => {
          if (levels.has(pid)) {
            maxPL = Math.max(maxPL, levels.get(pid) + 1);
          }
        });
        if (!levels.has(n.id) || levels.get(n.id) < maxPL) {
          levels.set(n.id, maxPL);
          changed = true;
        }
      }
    });
  }

  // Fallback for isolated or cyclical nodes
  nodes.forEach((n, idx) => {
    if (!levels.has(n.id)) levels.set(n.id, idx % 4);
  });

  // Group nodes by topological layer
  const levelGroups = new Map();
  nodes.forEach(n => {
    const lvl = levels.get(n.id) || 0;
    if (!levelGroups.has(lvl)) levelGroups.set(lvl, []);
    levelGroups.get(lvl).push(n);
  });

  const sortedLevels = Array.from(levelGroups.keys()).sort((a, b) => a - b);
  const numLevels = sortedLevels.length;
  const nodeWidth = 145;
  const nodeHeight = 52;
  const padX = 35;
  const padY = 35;
  const totalW = 700;
  const totalH = 440;

  const xStep = numLevels > 1 ? (totalW - padX * 2 - nodeWidth) / (numLevels - 1) : 250;
  const nodeCoords = new Map();

  sortedLevels.forEach((lvl, colIdx) => {
    const group = levelGroups.get(lvl);
    const count = group.length;
    const yStep = (totalH - padY * 2) / (count + 1);

    group.forEach((node, rowIdx) => {
      const nx = padX + colIdx * xStep;
      const ny = padY + (rowIdx + 1) * yStep - nodeHeight / 2;
      nodeCoords.set(node.id, {
        x: nx,
        y: ny,
        width: nodeWidth,
        height: nodeHeight,
        cx: nx + nodeWidth / 2,
        cy: ny + nodeHeight / 2,
        node: node
      });
    });
  });

  // Critical path nodes set
  const critNodesSet = new Set();
  edges.forEach(e => {
    if (e.is_critical_path) {
      critNodesSet.add(e.source);
      critNodesSet.add(e.target);
    }
  });

  // Render Edges
  let edgeHtml = "";
  edges.forEach(edge => {
    const src = nodeCoords.get(edge.source);
    const tgt = nodeCoords.get(edge.target);
    if (!src || !tgt) return;

    const isCrit = edge.is_critical_path;
    const strokeColor = isCrit ? "#f59e0b" : "#94a3b8";
    const strokeWidth = isCrit ? 2.6 : 1.8;
    const marker = isCrit ? "url(#arrowhead-crit)" : "url(#arrowhead)";

    let d = "";
    if (tgt.x > src.x) {
      const startX = src.x + src.width;
      const startY = src.cy;
      const endX = tgt.x;
      const endY = tgt.cy;
      const dx = Math.max(25, (endX - startX) / 2);
      d = `M ${startX} ${startY} C ${startX + dx} ${startY}, ${endX - dx} ${endY}, ${endX} ${endY}`;
    } else {
      const startX = src.cx;
      const startY = src.y;
      const endX = tgt.cx;
      const endY = tgt.y;
      const arcH = 40;
      d = `M ${startX} ${startY} C ${startX} ${startY - arcH}, ${endX} ${endY - arcH}, ${endX} ${endY}`;
    }

    edgeHtml += `
      <path d="${d}" fill="none" stroke="${strokeColor}" stroke-width="${strokeWidth}" marker-end="${marker}">
        <title>Call: ${escapeHtml(edge.source)} → ${escapeHtml(edge.target)} (${edge.avg_latency_ms.toFixed(1)}ms)</title>
      </path>
    `;
  });
  edgesGroup.innerHTML = edgeHtml;

  // Render Nodes
  let nodeHtml = "";
  nodes.forEach(node => {
    const pos = nodeCoords.get(node.id);
    if (!pos) return;

    const isCrit = critNodesSet.has(node.id);
    const ntype = (node.node_type || "agent").toLowerCase();

    let fill = "rgba(124, 58, 237, 0.12)";
    let stroke = "#7c3aed";
    let icon = "🤖";

    if (ntype === "tool") {
      fill = "rgba(37, 99, 235, 0.12)";
      stroke = "#2563eb";
      icon = "🔧";
    } else if (ntype === "llm") {
      fill = "rgba(245, 158, 11, 0.12)";
      stroke = "#f59e0b";
      icon = "🧠";
    } else if (ntype === "step") {
      fill = "rgba(16, 185, 129, 0.12)";
      stroke = "#10b981";
      icon = "⚡";
    }

    if (isCrit) {
      stroke = "#f59e0b";
    }

    const dur = node.total_duration_ms || node.avg_latency_ms || 0;
    const titleText = `${escapeHtml(node.name)} (${ntype})\nDuration: ${dur.toFixed(1)}ms\nCalls: ${node.total_calls}\nCost: $${(node.total_cost_usd || 0).toFixed(5)}${isCrit ? '\n⚡ CRITICAL PATH' : ''}`;
    const nameTrunc = node.name.length > 13 ? escapeHtml(node.name.substring(0, 12)) + '…' : escapeHtml(node.name);

    nodeHtml += `
      <g class="dag-node-item" style="cursor:pointer;">
        <title>${titleText}</title>
        <rect x="${pos.x}" y="${pos.y}" width="${pos.width}" height="${pos.height}" rx="7" ry="7"
              fill="${fill}" stroke="${stroke}" stroke-width="${isCrit ? 2.5 : 1.3}" />
        ${isCrit ? `<circle cx="${pos.x + pos.width - 9}" cy="${pos.y + 9}" r="4" fill="#f59e0b"><title>Critical Path Node</title></circle>` : ''}
        <text x="${pos.x + 10}" y="${pos.y + 20}" font-size="11" font-weight="700" fill="var(--text-primary)">
          ${icon} ${nameTrunc}
        </text>
        <text x="${pos.x + 10}" y="${pos.y + 38}" font-size="9.5" fill="var(--text-secondary)">
          ${dur.toFixed(1)}ms • ${node.total_calls} calls
        </text>
      </g>
    `;
  });
  nodesGroup.innerHTML = nodeHtml;
}

function renderTopologyRecs(recommendations) {
  const container = document.getElementById("topoRecsContainer");
  const countBadge = document.getElementById("topoRecCountBadge");
  if (!container) return;

  if (countBadge) {
    countBadge.innerText = `${recommendations.length} Action${recommendations.length === 1 ? '' : 's'}`;
  }

  if (recommendations.length === 0) {
    container.innerHTML = `
      <div style="padding:32px 20px; text-align:center; color:var(--text-muted); font-size:0.8rem; background:var(--bg-card); border-radius:8px; border:1px dashed var(--border-color);">
        <div style="font-size:1.5rem; margin-bottom:6px;">🎉</div>
        <div style="font-weight:700; color:var(--color-success); margin-bottom:4px;">Optimal Swarm Topology</div>
        <div>No ping-pong loops, parallelizable bottlenecks, or redundant routing detected in this execution.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = recommendations.map(rec => {
    const cat = rec.category || "pruning";
    const catClass = `cat-${cat}`;
    const patchBox = rec.suggested_patch 
      ? `<div class="rec-patch-box">${escapeHtml(rec.suggested_patch)}</div>`
      : "";

    let impactStr = "";
    if (rec.estimated_savings_pct > 0) {
      impactStr += `⚡ ~${rec.estimated_savings_pct.toFixed(0)}% Latency Reduction `;
    }
    if (rec.estimated_cost_reduction_usd > 0) {
      impactStr += `💰 $${rec.estimated_cost_reduction_usd.toFixed(4)} Savings`;
    }
    if (!impactStr) {
      impactStr = "⚡ Calibrated DAG Efficiency";
    }

    return `
      <div class="rec-card">
        <div class="rec-card-header">
          <span class="rec-cat-badge ${catClass}">${escapeHtml(cat.replace('_', ' '))}</span>
          <span style="font-size:0.68rem; font-weight:800; color:${rec.severity === 'high' || rec.severity === 'critical' ? 'var(--color-danger)' : 'var(--color-warning)'};">
            ${rec.severity.toUpperCase()}
          </span>
        </div>
        <div class="rec-title">${escapeHtml(rec.title)}</div>
        <div class="rec-desc">${escapeHtml(rec.description)}</div>
        <div style="font-size:0.72rem; color:var(--color-success); font-weight:600;">
          ${escapeHtml(impactStr)}
        </div>
        ${patchBox}
      </div>
    `;
  }).join("");
}


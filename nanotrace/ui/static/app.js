let currentTraces = [];
let activeTraceId = null;
let activeTraceSpans = [];

async function loadDashboard() {
  await Promise.all([loadStats(), loadTraces()]);
}

async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();
    document.getElementById("valTotalTraces").innerText = data.total_traces || 0;
    document.getElementById("valTotalSpans").innerText = data.total_spans || 0;
    document.getElementById("valTotalTokens").innerText = Number(data.total_tokens || 0).toLocaleString();
    document.getElementById("valTotalCost").innerText = "$" + Number(data.total_cost_usd || 0).toFixed(4);
    document.getElementById("valP50").innerText = (data.p50_duration_ms || 0) + " ms";
    document.getElementById("valErrorRate").innerText = (data.error_rate_pct || 0) + "%";
  } catch (err) {
    console.error("Failed to load stats", err);
  }
}

async function loadTraces() {
  const listEl = document.getElementById("traceList");
  try {
    const res = await fetch("/api/traces");
    currentTraces = await res.json();
    renderTraceList(currentTraces);
  } catch (err) {
    listEl.innerHTML = `<div class="empty-state">Failed to load traces from DuckDB.</div>`;
  }
}

function renderTraceList(traces) {
  const listEl = document.getElementById("traceList");
  if (!traces || traces.length === 0) {
    listEl.innerHTML = `<div class="empty-state">No traces logged yet.<br>Run an agent to see spans!</div>`;
    return;
  }

  listEl.innerHTML = traces.map(t => {
    const isError = t.status === "ERROR";
    const statusClass = isError ? "status-error" : "status-ok";
    const name = t.root_name || "Agent Run";
    const isActive = t.trace_id === activeTraceId ? "active" : "";

    return `
      <div class="trace-item ${isActive}" onclick="selectTrace('${t.trace_id}')">
        <div class="trace-item-header">
          <span class="trace-root-name">${escapeHtml(name)}</span>
          <span class="status-pill ${statusClass}">${t.status}</span>
        </div>
        <div class="trace-item-meta">
          <span>${t.duration_ms} ms</span>
          <span>•</span>
          <span>${t.total_tokens || 0} tokens</span>
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

async function selectTrace(traceId) {
  activeTraceId = traceId;
  renderTraceList(currentTraces);

  document.getElementById("detailActions").style.display = "block";
  document.getElementById("evalBanner").style.display = "none";
  closeDrawer();

  try {
    const res = await fetch(`/api/traces/${traceId}`);
    activeTraceSpans = await res.json();

    const rootSpan = activeTraceSpans.find(s => !s.parent_span_id) || activeTraceSpans[0];
    document.getElementById("activeTraceTitle").innerText = rootSpan ? rootSpan.name : "Trace: " + traceId.slice(0, 8);
    document.getElementById("activeTraceSubtitle").innerText = `Trace ID: ${traceId} • ${activeTraceSpans.length} spans recorded`;

    renderWaterfall(activeTraceSpans);
  } catch (err) {
    console.error("Error loading trace detail", err);
  }
}

function renderWaterfall(spans) {
  const container = document.getElementById("waterfallSection");
  if (!spans || spans.length === 0) {
    container.innerHTML = `<div class="empty-state">No spans found for this trace.</div>`;
    return;
  }

  // Calculate start and end range for timeline
  const minStart = Math.min(...spans.map(s => Number(s.start_time_ns)));
  const maxEnd = Math.max(...spans.map(s => Number(s.end_time_ns)));
  const totalDurationNs = Math.max(1, maxEnd - minStart);

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

  container.innerHTML = spans.map(s => {
    const startOffset = Math.max(0, (Number(s.start_time_ns) - minStart) / totalDurationNs * 100);
    const widthPct = Math.max(0.8, (Number(s.end_time_ns) - Number(s.start_time_ns)) / totalDurationNs * 100);
    const depth = depthMap[s.span_id] || 0;
    const indentPx = depth * 18;

    let badgeClass = "badge-internal";
    let badgeLabel = s.kind;
    if (s.gen_ai_operation === "agent_run") {
      badgeClass = "badge-agent";
      badgeLabel = "agent";
    } else if (s.gen_ai_operation === "chat") {
      badgeClass = "badge-chat";
      badgeLabel = s.gen_ai_request_model || "llm";
    } else if (s.gen_ai_operation === "execute_tool" || s.gen_ai_tool_name) {
      badgeClass = "badge-tool";
      badgeLabel = "tool";
    }

    const isError = s.status === "ERROR";
    const barClass = isError ? "duration-bar error-bar" : "duration-bar";

    return `
      <div class="waterfall-row" onclick="openDrawer('${s.span_id}')">
        <div class="span-info-col" style="padding-left: ${indentPx}px">
          <span class="span-badge ${badgeClass}">${escapeHtml(badgeLabel)}</span>
          <span class="span-name-label" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
        </div>
        <div class="span-bar-col">
          <div class="${barClass}" style="left: ${startOffset}%; width: ${widthPct}%;"></div>
        </div>
        <div class="span-duration-label">${s.duration_ms} ms</div>
      </div>
    `;
  }).join("");
}

function openDrawer(spanId) {
  const span = activeTraceSpans.find(s => s.span_id === spanId);
  if (!span) return;

  const drawer = document.getElementById("spanDrawer");
  const content = document.getElementById("drawerContent");
  document.getElementById("drawerSpanName").innerText = span.name;

  let promptDisplay = span.prompt_payload;
  try { promptDisplay = JSON.stringify(JSON.parse(span.prompt_payload), null, 2); } catch (_) {}

  let compDisplay = span.completion_payload;
  try { compDisplay = JSON.stringify(JSON.parse(span.completion_payload), null, 2); } catch (_) {}

  let attrsDisplay = span.attributes_json;
  try { attrsDisplay = JSON.stringify(JSON.parse(span.attributes_json), null, 2); } catch (_) {}

  content.innerHTML = `
    <div class="drawer-section">
      <div class="drawer-section-title">OpenTelemetry Identifiers</div>
      <div class="code-block">Trace ID: ${span.trace_id}\nSpan ID:  ${span.span_id}\nParent:   ${span.parent_span_id || "None (Root)"}\nStatus:   ${span.status}</div>
    </div>

    <div class="drawer-section">
      <div class="drawer-section-title">Metrics & Tokens</div>
      <div class="code-block">Duration:     ${span.duration_ms} ms\nInput Tokens: ${span.gen_ai_input_tokens}\nOutput Tokens:${span.gen_ai_output_tokens}\nTotal Tokens: ${span.gen_ai_total_tokens}\nEst. Cost:    $${Number(span.gen_ai_cost_usd || 0).toFixed(6)}</div>
    </div>

    ${promptDisplay && promptDisplay !== '""' ? `
    <div class="drawer-section">
      <div class="drawer-section-title">Input / Prompt Payload</div>
      <div class="code-block">${escapeHtml(promptDisplay)}</div>
    </div>` : ''}

    ${compDisplay && compDisplay !== '""' ? `
    <div class="drawer-section">
      <div class="drawer-section-title">Output / Completion Payload</div>
      <div class="code-block">${escapeHtml(compDisplay)}</div>
    </div>` : ''}

    <div class="drawer-section">
      <div class="drawer-section-title">All CNCF GenAI Attributes</div>
      <div class="code-block">${escapeHtml(attrsDisplay)}</div>
    </div>
  `;

  drawer.style.display = "flex";
}

function closeDrawer() {
  document.getElementById("spanDrawer").style.display = "none";
}

async function runTraceEvals() {
  if (!activeTraceId) return;
  const banner = document.getElementById("evalBanner");
  banner.innerHTML = `<span style="color:#c7d2fe;">Running local heuristic evaluations...</span>`;
  banner.style.display = "flex";

  try {
    const res = await fetch(`/api/evals/${activeTraceId}`);
    const results = await res.json();

    banner.innerHTML = results.map(r => `
      <div class="eval-metric">
        <span class="eval-metric-name">${r.metric_name}</span>
        <span class="eval-metric-score" style="color: ${r.passed ? '#10b981' : '#ef4444'}">
          ${(r.score * 100).toFixed(0)}% ${r.passed ? '✓' : '✗'}
        </span>
      </div>
    `).join("");
  } catch (err) {
    banner.innerHTML = `<span style="color:#ef4444;">Evaluation failed.</span>`;
  }
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

document.addEventListener("DOMContentLoaded", loadDashboard);

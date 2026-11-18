"""Standalone single-file HTML capsule exporter for NanoTrace.

Generates a zero-dependency, self-contained `.ntrace.html` file that packages
the complete trace tree, OpenTelemetry GenAI attributes, evaluation diagnostics,
and dual-audience interactive lenses (Business vs Hacker).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator

CAPSULE_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NanoTrace Capsule • __TRACE_ID_SHORT__</title>
  <style>
    :root {
      --bg-primary: #0a0e17;
      --bg-surface: #111827;
      --bg-surface-hover: #1f2937;
      --bg-surface-subtle: #172033;
      --border-color: #27354f;
      --border-color-subtle: #1b263b;
      --text-primary: #f3f4f6;
      --text-secondary: #9ca3af;
      --text-muted: #6b7280;
      --accent-primary: #3b82f6;
      --accent-hover: #2563eb;
      --accent-soft: rgba(59, 130, 246, 0.15);
      --color-success: #10b981;
      --color-warning: #f59e0b;
      --color-error: #ef4444;
      --code-bg: #030712;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    [data-theme="light"] {
      --bg-primary: #f8fafc;
      --bg-surface: #ffffff;
      --bg-surface-hover: #f1f5f9;
      --bg-surface-subtle: #f8fafc;
      --border-color: #e2e8f0;
      --border-color-subtle: #edf2f7;
      --text-primary: #0f172a;
      --text-secondary: #475569;
      --text-muted: #94a3b8;
      --accent-primary: #2563eb;
      --accent-hover: #1d4ed8;
      --accent-soft: rgba(37, 99, 235, 0.1);
      --color-success: #16a34a;
      --color-warning: #d97706;
      --color-error: #dc2626;
      --code-bg: #f1f5f9;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font-sans);
      background: var(--bg-primary);
      color: var(--text-primary);
      line-height: 1.5;
      font-size: 14px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 50;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
      color: var(--text-primary);
      font-weight: 800;
      font-size: 1.15rem;
    }
    .brand-pill {
      font-size: 0.65rem;
      font-weight: 800;
      text-transform: uppercase;
      padding: 2px 7px;
      border-radius: 9999px;
      background: linear-gradient(135deg, #10b981, #059669);
      color: white;
      letter-spacing: 0.5px;
    }
    .header-center {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .lens-group {
      display: inline-flex;
      background: var(--bg-surface-subtle);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 3px;
    }
    .lens-btn {
      background: transparent;
      border: none;
      color: var(--text-secondary);
      font-size: 0.82rem;
      font-weight: 600;
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .lens-btn.active {
      background: var(--accent-primary);
      color: #ffffff;
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .btn {
      background: var(--bg-surface-hover);
      border: 1px solid var(--border-color);
      color: var(--text-primary);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 0.15s ease;
    }
    .btn:hover {
      background: var(--border-color);
    }
    .scorecard-bar {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      padding: 12px 24px;
      gap: 16px;
    }
    .score-cell {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .score-label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-weight: 700;
    }
    .score-val {
      font-size: 1.15rem;
      font-weight: 800;
      color: var(--text-primary);
    }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 8px;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 700;
      width: fit-content;
    }
    .status-badge.ok {
      background: rgba(16, 185, 129, 0.15);
      color: var(--color-success);
    }
    .status-badge.error {
      background: rgba(239, 68, 68, 0.15);
      color: var(--color-error);
    }
    main {
      flex: 1;
      padding: 24px;
      max-width: 1400px;
      margin: 0 auto;
      width: 100%;
    }
    .lens-view {
      display: none;
    }
    .lens-view.active {
      display: block;
    }

    /* Business Lens Styles */
    .biz-journey {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .biz-card {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 18px 22px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      position: relative;
    }
    .biz-card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .biz-role {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 700;
      font-size: 0.92rem;
    }
    .biz-role-icon {
      width: 28px;
      height: 28px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 1rem;
    }
    .role-user .biz-role-icon { background: rgba(59, 130, 246, 0.2); color: #3b82f6; }
    .role-agent .biz-role-icon { background: rgba(168, 85, 247, 0.2); color: #a855f7; }
    .role-tool .biz-role-icon { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
    .role-output .biz-role-icon { background: rgba(16, 185, 129, 0.2); color: #10b981; }
    .biz-meta {
      font-size: 0.78rem;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .biz-bubble {
      background: var(--bg-surface-subtle);
      border: 1px solid var(--border-color-subtle);
      border-radius: 8px;
      padding: 14px 18px;
      font-size: 0.9rem;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.6;
    }
    .biz-bubble.output {
      border-left: 4px solid var(--color-success);
    }
    .biz-stats-strip {
      display: flex;
      gap: 16px;
      margin-top: 10px;
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .biz-stats-strip span {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    /* Hacker Lens Waterfall Styles */
    .waterfall-box {
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      overflow: hidden;
    }
    .ruler-row {
      display: grid;
      grid-template-columns: 340px 1fr 100px;
      background: var(--bg-surface-subtle);
      border-bottom: 1px solid var(--border-color);
      padding: 10px 16px;
      font-size: 0.72rem;
      color: var(--text-muted);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .ruler-ticks {
      display: flex;
      justify-content: space-between;
      padding: 0 4px;
    }
    .span-entry {
      display: grid;
      grid-template-columns: 340px 1fr 100px;
      padding: 8px 16px;
      border-bottom: 1px solid var(--border-color-subtle);
      align-items: center;
      cursor: pointer;
      transition: background 0.12s ease;
    }
    .span-entry:hover {
      background: var(--bg-surface-hover);
    }
    .span-entry.active {
      background: var(--accent-soft);
      border-left: 3px solid var(--accent-primary);
    }
    .span-info {
      display: flex;
      align-items: center;
      gap: 8px;
      overflow: hidden;
    }
    .kind-pill {
      font-size: 0.65rem;
      font-weight: 800;
      padding: 2px 6px;
      border-radius: 4px;
      text-transform: uppercase;
      letter-spacing: 0.4px;
      white-space: nowrap;
    }
    .kind-agent { background: rgba(168, 85, 247, 0.2); color: #c084fc; }
    .kind-chat { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
    .kind-tool { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
    .kind-internal { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }
    .span-title {
      font-size: 0.82rem;
      font-weight: 600;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--text-primary);
    }
    .track-wrapper {
      position: relative;
      height: 20px;
      background: rgba(255, 255, 255, 0.02);
      border-radius: 4px;
      margin: 0 8px;
    }
    .timeline-bar {
      position: absolute;
      height: 100%;
      border-radius: 4px;
      background: linear-gradient(90deg, #3b82f6, #60a5fa);
      min-width: 3px;
    }
    .timeline-bar.error {
      background: linear-gradient(90deg, #ef4444, #f87171);
    }
    .dur-label {
      font-size: 0.78rem;
      font-family: var(--font-mono);
      color: var(--text-secondary);
      text-align: right;
    }

    /* Span Inspection Drawer */
    .drawer-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.5);
      z-index: 100;
      justify-content: flex-end;
    }
    .drawer-overlay.open {
      display: flex;
    }
    .drawer-panel {
      width: 580px;
      max-width: 90vw;
      background: var(--bg-surface);
      border-left: 1px solid var(--border-color);
      height: 100%;
      display: flex;
      flex-direction: column;
      box-shadow: -4px 0 24px rgba(0,0,0,0.4);
      animation: slideIn 0.2s ease-out;
    }
    @keyframes slideIn {
      from { transform: translateX(100%); }
      to { transform: translateX(0); }
    }
    .drawer-header {
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .drawer-tabs {
      display: flex;
      border-bottom: 1px solid var(--border-color);
      background: var(--bg-surface-subtle);
    }
    .drawer-tab {
      padding: 10px 16px;
      background: transparent;
      border: none;
      color: var(--text-secondary);
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .drawer-tab.active {
      color: var(--accent-primary);
      border-bottom-color: var(--accent-primary);
      background: var(--bg-surface);
    }
    .drawer-content {
      flex: 1;
      padding: 20px;
      overflow-y: auto;
    }
    .code-box {
      background: var(--code-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 14px;
      font-family: var(--font-mono);
      font-size: 0.78rem;
      line-height: 1.5;
      color: var(--text-primary);
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-all;
    }
    .kv-table {
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 10px;
      font-size: 0.82rem;
    }
    .kv-key {
      color: var(--text-muted);
      font-weight: 600;
    }
    .kv-val {
      font-family: var(--font-mono);
      color: var(--text-primary);
      word-break: break-all;
    }

    /* Evaluation diagnostics bar */
    .eval-section {
      margin-bottom: 24px;
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px 20px;
    }
    .eval-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .eval-item {
      background: var(--bg-surface-subtle);
      border: 1px solid var(--border-color-subtle);
      border-radius: 8px;
      padding: 10px 14px;
    }
    .eval-title {
      font-size: 0.78rem;
      color: var(--text-muted);
      font-weight: 600;
    }
    .eval-score-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-top: 4px;
    }
    .eval-score {
      font-size: 1.05rem;
      font-weight: 800;
    }
    .eval-passed { color: var(--color-success); }
    .eval-failed { color: var(--color-error); }
  </style>
</head>
<body>
  <!-- Header -->
  <header>
    <a href="#" class="brand">
      <span>⚡️ NanoTrace</span>
      <span class="brand-pill">Capsule</span>
    </a>

    <!-- Lens Toggle -->
    <div class="header-center">
      <div class="lens-group">
        <button class="lens-btn active" id="btnBizLens" onclick="setLens('business')">
          <span>👔 Business Lens</span>
        </button>
        <button class="lens-btn" id="btnHackerLens" onclick="setLens('hacker')">
          <span>🛠️ Hacker Lens</span>
        </button>
      </div>
    </div>

    <!-- Actions -->
    <div class="header-actions">
      <button class="btn" onclick="copyTraceId()" id="btnCopy">
        <span>Copy TraceID</span>
      </button>
      <button class="btn" onclick="toggleTheme()" title="Toggle Theme">
        <span id="themeIcon">☀️</span>
      </button>
    </div>
  </header>

  <!-- Executive Scorecard -->
  <section class="scorecard-bar">
    <div class="score-cell">
      <span class="score-label">Trace Status</span>
      <div class="status-badge __STATUS_CLASS__">
        <span>__STATUS_TEXT__</span>
      </div>
    </div>
    <div class="score-cell">
      <span class="score-label">Turnaround Latency</span>
      <span class="score-val">__DURATION_MS__ ms</span>
    </div>
    <div class="score-cell">
      <span class="score-label">Total Spans</span>
      <span class="score-val">__SPAN_COUNT__</span>
    </div>
    <div class="score-cell">
      <span class="score-label">Tokens Consumed</span>
      <span class="score-val">__TOTAL_TOKENS__</span>
    </div>
    <div class="score-cell">
      <span class="score-label">Estimated Spend</span>
      <span class="score-val">$__TOTAL_COST__</span>
    </div>
    <div class="score-cell">
      <span class="score-label">Root Agent</span>
      <span class="score-val" style="font-size:0.95rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">__ROOT_NAME__</span>
    </div>
  </section>

  <!-- Main Container -->
  <main>
    <!-- Evaluations Summary -->
    <section class="eval-section" id="evalSection">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-weight:700; font-size:0.88rem;">Automated Quality &amp; Safety Evaluations</span>
        <span style="font-size:0.75rem; color:var(--text-muted);">Zero-cloud local heuristics</span>
      </div>
      <div class="eval-grid" id="evalGrid"></div>
    </section>

    <!-- VIEW 1: Business Lens -->
    <div class="lens-view active" id="viewBusiness">
      <div class="biz-journey" id="bizJourney"></div>
    </div>

    <!-- VIEW 2: Hacker Lens -->
    <div class="lens-view" id="viewHacker">
      <div class="waterfall-box">
        <div class="ruler-row">
          <div>Span / Operation Hierarchy</div>
          <div class="ruler-ticks" id="rulerTicks"></div>
          <div style="text-align:right;">Duration</div>
        </div>
        <div id="hackerRows"></div>
      </div>
    </div>
  </main>

  <!-- Span Detail Drawer -->
  <div class="drawer-overlay" id="drawerOverlay" onclick="closeDrawer(event)">
    <div class="drawer-panel" onclick="event.stopPropagation()">
      <div class="drawer-header">
        <div>
          <span class="kind-pill kind-chat" id="dSpanKind">SPAN</span>
          <h3 id="dSpanTitle" style="font-size:1.05rem; margin-top:4px;">Span Details</h3>
        </div>
        <button class="btn" onclick="closeDrawer(null)">✕</button>
      </div>
      <div class="drawer-tabs">
        <button class="drawer-tab active" onclick="switchDrawerTab('overview')">Overview</button>
        <button class="drawer-tab" onclick="switchDrawerTab('payloads')">Input &amp; Output</button>
        <button class="drawer-tab" onclick="switchDrawerTab('otel')">OTel Semantic JSON</button>
      </div>
      <div class="drawer-content">
        <div id="dTabOverview">
          <div class="kv-table" id="dKvGrid"></div>
        </div>
        <div id="dTabPayloads" style="display:none; flex-direction:column; gap:16px;">
          <div>
            <span style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Input / Prompt Payload</span>
            <div class="code-box" id="dPromptBox" style="margin-top:6px;"></div>
          </div>
          <div>
            <span style="font-size:0.75rem; font-weight:700; color:var(--text-muted); text-transform:uppercase;">Output / Completion Payload</span>
            <div class="code-box" id="dCompBox" style="margin-top:6px;"></div>
          </div>
        </div>
        <div id="dTabOtel" style="display:none;">
          <div class="code-box" id="dOtelBox"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Embedded Data Payload -->
  <script id="nanotrace-data" type="application/json">
__JSON_DATA__
  </script>

  <!-- Self-Contained Application Script -->
  <script>
    const data = JSON.parse(document.getElementById("nanotrace-data").textContent);
    let selectedSpanId = null;

    function initCapsule() {
      renderEvaluations();
      renderBusinessLens();
      renderHackerLens();
    }

    function setLens(lens) {
      const bizBtn = document.getElementById("btnBizLens");
      const hackerBtn = document.getElementById("btnHackerLens");
      const bizView = document.getElementById("viewBusiness");
      const hackerView = document.getElementById("viewHacker");

      if (lens === "business") {
        bizBtn.classList.add("active");
        hackerBtn.classList.remove("active");
        bizView.classList.add("active");
        hackerView.classList.remove("active");
      } else {
        bizBtn.classList.remove("active");
        hackerBtn.classList.add("active");
        bizView.classList.remove("active");
        hackerView.classList.add("active");
      }
    }

    function toggleTheme() {
      const current = document.documentElement.getAttribute("data-theme") || "dark";
      const target = current === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", target);
      document.getElementById("themeIcon").innerText = target === "dark" ? "☀️" : "🌙";
    }

    function copyTraceId() {
      navigator.clipboard.writeText(data.trace_id);
      const btn = document.getElementById("btnCopy");
      btn.innerText = "✓ Copied!";
      setTimeout(() => { btn.innerText = "Copy TraceID"; }, 1800);
    }

    function escapeHtml(str) {
      if (str === null || str === undefined) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    function renderEvaluations() {
      const grid = document.getElementById("evalGrid");
      if (!data.evals || data.evals.length === 0) {
        document.getElementById("evalSection").style.display = "none";
        return;
      }
      grid.innerHTML = data.evals.map(e => {
        let detailText = "";
        if (e.details) {
          if (typeof e.details === "object") {
            const parts = [];
            for (const [k, v] of Object.entries(e.details)) {
              parts.push(`${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
            }
            detailText = parts.join(" • ");
          } else {
            detailText = String(e.details);
          }
        }
        return `
          <div class="eval-item">
            <div class="eval-title">${escapeHtml(e.metric_name)}</div>
            <div class="eval-score-row">
              <span class="eval-score ${e.passed ? 'eval-passed' : 'eval-failed'}">${(e.score * 100).toFixed(0)}%</span>
              <span style="font-size:0.75rem; font-weight:700; color:${e.passed ? 'var(--color-success)' : 'var(--color-error)'}">
                ${e.passed ? 'PASSED' : 'CHECK'}
              </span>
            </div>
            <div style="font-size:0.72rem; color:var(--text-muted); margin-top:2px;">${escapeHtml(detailText)}</div>
          </div>
        `;
      }).join("");
    }

    function renderBusinessLens() {
      const container = document.getElementById("bizJourney");
      const spans = data.spans || [];
      if (spans.length === 0) {
        container.innerHTML = "<p>No spans recorded in this capsule.</p>";
        return;
      }

      const cards = [];
      const rootSpan = spans.find(s => !s.parent_span_id) || spans[0];

      // Card 1: User Goal / Prompt
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
        <div class="biz-card role-user">
          <div class="biz-card-header">
            <div class="biz-role">
              <span class="biz-role-icon">👤</span>
              <span>User Objective / Input Trigger</span>
            </div>
            <div class="biz-meta">
              <span>Initiated Run</span>
            </div>
          </div>
          <div class="biz-bubble">${escapeHtml(initialPrompt)}</div>
        </div>
      `);

      // Middle steps: Tools and LLM calls
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
            <div class="biz-card role-tool" onclick="openDrawer('${s.span_id}')" style="cursor:pointer;">
              <div class="biz-card-header">
                <div class="biz-role">
                  <span class="biz-role-icon">🛠️</span>
                  <span>Tool Action: <strong>${escapeHtml(s.gen_ai_tool_name || s.name)}</strong></span>
                </div>
                <div class="biz-meta">
                  <span>⏱️ ${s.duration_ms} ms</span>
                  <span>• Click to inspect</span>
                </div>
              </div>
              <div class="biz-bubble">${escapeHtml(bodyText)}</div>
            </div>
          `);
        } else if (isChat) {
          cards.push(`
            <div class="biz-card role-agent" onclick="openDrawer('${s.span_id}')" style="cursor:pointer;">
              <div class="biz-card-header">
                <div class="biz-role">
                  <span class="biz-role-icon">🧠</span>
                  <span>Agent Reasoning &amp; Synthesis (${escapeHtml(s.gen_ai_request_model || 'LLM')})</span>
                </div>
                <div class="biz-meta">
                  <span>⏱️ ${s.duration_ms} ms</span>
                  <span>• ${s.gen_ai_total_tokens} tok</span>
                  <span>• $${Number(s.gen_ai_cost_usd || 0).toFixed(5)}</span>
                </div>
              </div>
              <div class="biz-bubble">${escapeHtml(bodyText)}</div>
            </div>
          `);
        }
      });

      // Final Card: Resolution
      let finalCompletion = rootSpan.completion_payload;
      try {
        const fp = JSON.parse(finalCompletion);
        if (typeof fp === "string") finalCompletion = fp;
      } catch (_) {}

      if (finalCompletion && finalCompletion.trim() !== '""' && finalCompletion.trim() !== "") {
        cards.push(`
          <div class="biz-card role-output">
            <div class="biz-card-header">
              <div class="biz-role">
                <span class="biz-role-icon">🎯</span>
                <span>Final Agent Deliverable</span>
              </div>
              <div class="biz-meta">
                <span style="color:var(--color-success); font-weight:700;">✓ Completed in ${data.total_duration_ms} ms</span>
              </div>
            </div>
            <div class="biz-bubble output">${escapeHtml(finalCompletion)}</div>
          </div>
        `);
      }

      container.innerHTML = cards.join("");
    }

    function renderHackerLens() {
      const spans = data.spans || [];
      const rowsContainer = document.getElementById("hackerRows");
      const ticksContainer = document.getElementById("rulerTicks");

      if (spans.length === 0) {
        rowsContainer.innerHTML = "<p style='padding:20px;'>No spans available.</p>";
        return;
      }

      const minStart = Math.min(...spans.map(s => Number(s.start_time_ns)));
      const maxEnd = Math.max(...spans.map(s => Number(s.end_time_ns)));
      const totalNs = Math.max(1, maxEnd - minStart);
      const totalMs = totalNs / 1_000_000;

      // Smart ruler ticks with automatic unit scaling (µs vs ms vs s)
      let tickFmt;
      if (totalMs < 0.1) {
        tickFmt = val => `${(val * 1000).toFixed(0)} µs`;
      } else if (totalMs < 10) {
        tickFmt = val => `${val.toFixed(2)} ms`;
      } else if (totalMs < 1000) {
        tickFmt = val => `${val.toFixed(1)} ms`;
      } else {
        tickFmt = val => `${(val / 1000).toFixed(2)} s`;
      }

      ticksContainer.innerHTML = `
        <span>0</span>
        <span>${tickFmt(totalMs * 0.25)}</span>
        <span>${tickFmt(totalMs * 0.50)}</span>
        <span>${tickFmt(totalMs * 0.75)}</span>
        <span>${tickFmt(totalMs)}</span>
      `;

      // Depth map
      const depthMap = {};
      spans.forEach(s => {
        let depth = 0;
        let curr = s.parent_span_id;
        while (curr) {
          depth++;
          const p = spans.find(x => x.span_id === curr);
          curr = p ? p.parent_span_id : null;
        }
        depthMap[s.span_id] = depth;
      });

      rowsContainer.innerHTML = spans.map(s => {
        const startOffset = Math.max(0, (Number(s.start_time_ns) - minStart) / totalNs * 100);
        const widthPct = Math.max(0.6, (Number(s.end_time_ns) - Number(s.start_time_ns)) / totalNs * 100);
        const depth = depthMap[s.span_id] || 0;
        const indentPx = depth * 14;

        let pillClass = "kind-internal";
        let pillText = s.kind || "span";
        if (s.gen_ai_operation === "agent_run") {
          pillClass = "kind-agent";
          pillText = "agent";
        } else if (s.gen_ai_operation === "chat") {
          pillClass = "kind-chat";
          pillText = s.gen_ai_request_model || "llm";
        } else if (s.gen_ai_operation === "execute_tool" || s.gen_ai_tool_name) {
          pillClass = "kind-tool";
          pillText = "tool";
        }

        const isErr = s.status === "ERROR";
        const isSel = s.span_id === selectedSpanId ? "active" : "";

        return `
          <div class="span-entry ${isSel}" onclick="openDrawer('${s.span_id}')">
            <div class="span-info" style="padding-left: ${indentPx}px;">
              <span class="kind-pill ${pillClass}">${escapeHtml(pillText)}</span>
              <span class="span-title" title="${escapeHtml(s.name)}">${escapeHtml(s.name)}</span>
            </div>
            <div class="track-wrapper">
              <div class="timeline-bar ${isErr ? 'error' : ''}" style="left: ${startOffset}%; width: ${widthPct}%;"></div>
            </div>
            <div class="dur-label">${s.duration_ms} ms</div>
          </div>
        `;
      }).join("");
    }

    function openDrawer(spanId) {
      selectedSpanId = spanId;
      const span = (data.spans || []).find(s => s.span_id === spanId);
      if (!span) return;

      document.getElementById("dSpanTitle").innerText = span.name;
      document.getElementById("dSpanKind").innerText = span.gen_ai_operation || span.kind;

      // KV table
      const kv = document.getElementById("dKvGrid");
      kv.innerHTML = `
        <div class="kv-key">Trace ID</div><div class="kv-val">${span.trace_id}</div>
        <div class="kv-key">Span ID</div><div class="kv-val">${span.span_id}</div>
        <div class="kv-key">Parent Span</div><div class="kv-val">${span.parent_span_id || "Root (None)"}</div>
        <div class="kv-key">Operation</div><div class="kv-val">${span.gen_ai_operation || span.kind}</div>
        <div class="kv-key">Duration</div><div class="kv-val">${span.duration_ms} ms</div>
        <div class="kv-key">Tokens (In/Out/Tot)</div><div class="kv-val">${span.gen_ai_input_tokens} / ${span.gen_ai_output_tokens} / ${span.gen_ai_total_tokens}</div>
        <div class="kv-key">Cost (USD)</div><div class="kv-val">$${Number(span.gen_ai_cost_usd || 0).toFixed(6)}</div>
        <div class="kv-key">Status</div><div class="kv-val" style="color:${span.status === 'ERROR' ? 'var(--color-error)' : 'var(--color-success)'}">${span.status}</div>
      `;

      // Payloads
      let pText = span.prompt_payload;
      try { pText = JSON.stringify(JSON.parse(span.prompt_payload), null, 2); } catch(_) {}
      document.getElementById("dPromptBox").innerText = pText || "(No prompt payload)";

      let cText = span.completion_payload;
      try { cText = JSON.stringify(JSON.parse(span.completion_payload), null, 2); } catch(_) {}
      document.getElementById("dCompBox").innerText = cText || "(No completion payload)";

      // OTel JSON
      let otelText = span.attributes_json;
      try { otelText = JSON.stringify(JSON.parse(span.attributes_json), null, 2); } catch(_) {}
      document.getElementById("dOtelBox").innerText = otelText || "{}";

      document.getElementById("drawerOverlay").classList.add("open");
      renderHackerLens();
    }

    function closeDrawer(e) {
      if (e && e.target !== document.getElementById("drawerOverlay")) return;
      document.getElementById("drawerOverlay").classList.remove("open");
      selectedSpanId = null;
      renderHackerLens();
    }

    function switchDrawerTab(tab) {
      const tabs = document.querySelectorAll(".drawer-tab");
      tabs.forEach(t => t.classList.remove("active"));

      document.getElementById("dTabOverview").style.display = tab === "overview" ? "block" : "none";
      document.getElementById("dTabPayloads").style.display = tab === "payloads" ? "flex" : "none";
      document.getElementById("dTabOtel").style.display = tab === "otel" ? "block" : "none";

      if (tab === "overview") tabs[0].classList.add("active");
      if (tab === "payloads") tabs[1].classList.add("active");
      if (tab === "otel") tabs[2].classList.add("active");
    }

    window.addEventListener("DOMContentLoaded", initCapsule);
  </script>
</body>
</html>
"""


def generate_trace_capsule(
    trace_id: str,
    spans: List[Dict[str, Any]],
    evals: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate self-contained standalone HTML capsule string."""
    if evals is None:
        eval_results = LocalHeuristicEvaluator.evaluate_all(spans)
        evals = [
            {
                "metric_name": e.metric_name,
                "score": e.score,
                "passed": e.passed,
                "details": e.details,
            }
            for e in eval_results
        ]

    # Calculate aggregate summary stats
    root_span = next((s for s in spans if not s.get("parent_span_id")), spans[0] if spans else {})
    total_duration_ms = float(root_span.get("duration_ms") or 0.0)
    if total_duration_ms <= 0.0 and spans:
        starts = [s.get("start_time_ns", 0) for s in spans if s.get("start_time_ns")]
        ends = [s.get("end_time_ns", 0) for s in spans if s.get("end_time_ns")]
        if starts and ends:
            diff_ns = max(ends) - min(starts)
            total_duration_ms = max(0.001, diff_ns / 1_000_000.0)

    duration_str = f"{total_duration_ms:.2f}" if total_duration_ms >= 0.01 else f"{total_duration_ms:.3f}"
    total_tokens = sum(int(s.get("gen_ai_total_tokens") or 0) for s in spans)
    total_cost_usd = sum(float(s.get("gen_ai_cost_usd") or 0.0) for s in spans)
    error_count = sum(1 for s in spans if s.get("status") == "ERROR")
    trace_status = "ERROR" if error_count > 0 else "OK"

    capsule_payload = {
        "trace_id": trace_id,
        "root_name": root_span.get("name", "Trace"),
        "total_spans": len(spans),
        "total_duration_ms": total_duration_ms,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "status": trace_status,
        "spans": spans,
        "evals": evals,
    }

    # Safe JSON string embedding
    json_data = json.dumps(capsule_payload).replace("</script>", "<\\/script>")

    status_class = "error" if trace_status == "ERROR" else "ok"
    status_text = "● Error Detected" if trace_status == "ERROR" else "● Operational OK"

    html = (
        CAPSULE_HTML_TEMPLATE
        .replace("__TRACE_ID_SHORT__", trace_id[:8])
        .replace("__STATUS_CLASS__", status_class)
        .replace("__STATUS_TEXT__", status_text)
        .replace("__DURATION_MS__", duration_str)
        .replace("__SPAN_COUNT__", str(len(spans)))
        .replace("__TOTAL_TOKENS__", f"{total_tokens:,}")
        .replace("__TOTAL_COST__", f"{total_cost_usd:.5f}")
        .replace("__ROOT_NAME__", str(root_span.get("name", "Agent")))
        .replace("__JSON_DATA__", json_data)
    )
    return html


def export_trace_capsule(
    trace_id: str,
    db_path: str = "./.traces/nanotrace.duckdb",
    output_path: Optional[str] = None,
) -> str:
    """Read trace from DuckDB and export as a standalone `.ntrace.html` file.

    Returns the absolute output file path.
    """
    sink = DuckDBSink(db_path=db_path)
    try:
        spans = sink.get_trace_tree(trace_id)
        if not spans:
            raise ValueError(f"Trace not found: {trace_id}")

        html_content = generate_trace_capsule(trace_id=trace_id, spans=spans)

        if not output_path:
            output_path = f"./{trace_id}.ntrace.html"

        out_file = Path(output_path).resolve()
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(html_content, encoding="utf-8")
        return str(out_file)
    finally:
        sink.close()

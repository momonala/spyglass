/**
 * Spyglass dashboard shared library.
 *
 * Provides fetch primitives, chart builders, stat fillers, and the full log
 * section (histogram, table, patterns, traceback renderer). Project dashboards
 * call initDashboard() with a project-specific loadFn and get refresh loop,
 * time-window controls, and error handling for free.
 */

/* ── Constants ──────────────────────────────────────────────────────── */

const FONT_SANS = '"Inter", system-ui, -apple-system, sans-serif';

/* ── Color palette ──────────────────────────────────────────────────── */

const COLORS = {
  accent:  "#60a5fa",
  success: "#34d399",
  warn:    "#fbbf24",
  danger:  "#f87171",
  purple:  "#a78bfa",
  muted:   "#94a3b8",
  grid:    "rgba(255, 255, 255, 0.05)",
};

/* ── Format helpers ─────────────────────────────────────────────────── */

const fmt = {
  count:     (n) => n == null ? "—" : Math.round(n).toLocaleString(),
  ms:        (n) => n == null ? "—" : `${n.toFixed(1)} ms`,
  seconds:   (n) => n == null ? "—" : `${(n / 1000).toFixed(2).replace(/\.?0+$/, "")} s`,
  percent:   (n) => n == null ? "—" : `${n.toFixed(1)}%`,
  timestamp: (iso) => {
    if (!iso) return "—";
    return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  },
};

/* ── Time window ────────────────────────────────────────────────────── */

function _getTimeWindow() {
  const amount = parseInt(document.getElementById("windowAmount")?.value, 10) || 6;
  const unit = document.getElementById("windowUnit")?.value ?? "hours";
  const rollupVal = document.getElementById("rollupWindow")?.value ?? "60";
  const multipliers = { hours: 1, days: 24, weeks: 168 };
  const hours = amount * (multipliers[unit] ?? 1);
  const to = new Date();
  const from = new Date(to.getTime() - hours * 3_600_000);
  const rollupSeconds = parseInt(rollupVal, 10) * 60;
  return { from: from.toISOString(), to: to.toISOString(), rollupSeconds, spanHours: hours };
}

function _formatTimestamp(ts, spanHours) {
  const d = new Date(ts);
  if (spanHours <= 24) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function _formatFullTimestamp(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

/* ── Fetch layer ────────────────────────────────────────────────────── */

async function fetchSeries(project, metricName, win, signal) {
  const qs = new URLSearchParams({ project, name: metricName, from: win.from, to: win.to });
  qs.set("interval", win.rollupSeconds);
  const r = await fetch(`/dashboard/api/metrics/series?${qs}`, { signal });
  if (!r.ok) throw new Error(`fetchSeries ${metricName}: HTTP ${r.status}`);
  return r.json();
}

async function fetchSummary(project, metricName, win, signal) {
  const qs = new URLSearchParams({ project, name: metricName, from: win.from, to: win.to });
  const r = await fetch(`/dashboard/api/metrics/summary?${qs}`, { signal });
  if (!r.ok) throw new Error(`fetchSummary ${metricName}: HTTP ${r.status}`);
  return r.json();
}

async function _fetchLogs(project, win, signal) {
  const qs = new URLSearchParams({ project, from: win.from, to: win.to, limit: 5000 });
  const r = await fetch(`/logs?${qs}`, { signal });
  if (!r.ok) throw new Error(`fetchLogs: HTTP ${r.status}`);
  return r.json();
}

/* ── Chart helpers ──────────────────────────────────────────────────── */

const _chartInstances = {};

function _upsertChart(canvasId, config) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === "undefined") return;
  _chartInstances[canvasId]?.destroy();
  _chartInstances[canvasId] = new Chart(canvas, config);
}

function _baseChartOptions(win, yLabel) {
  const sans = FONT_SANS;
  const spanHours = win?.spanHours ?? 24;
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        labels: { color: COLORS.muted, boxWidth: 12, font: { family: sans, size: 11 }, padding: 14 },
      },
      tooltip: {
        callbacks: {
          title: (items) => _formatFullTimestamp(items[0]?.label),
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: COLORS.muted,
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 8,
          font: { family: sans, size: 11 },
          callback: function(val) { return _formatTimestamp(this.getLabelForValue(val), spanHours); },
        },
        grid: { color: COLORS.grid },
        border: { color: COLORS.grid },
      },
      y: {
        beginAtZero: true,
        ticks: { color: COLORS.muted, font: { family: sans, size: 11 } },
        grid: { color: COLORS.grid },
        border: { color: COLORS.grid },
        title: yLabel ? { display: true, text: yLabel, color: COLORS.muted, font: { family: sans, size: 11 } } : undefined,
      },
    },
  };
}

/**
 * Fetch and render a multi-series line chart.
 *
 * @param {string} canvasId - ID of the <canvas> element.
 * @param {string} project  - Spyglass project name.
 * @param {Array}  seriesDefs - [{label, metricName, color, fill?, transform?}]
 *   transform: (value: number) => number  (e.g. ms → s conversion)
 * @param {object} win      - {from, to, rollupSeconds} from _getTimeWindow()
 * @param {AbortSignal} signal
 */
async function buildLineChart(canvasId, project, seriesDefs, win, signal) {
  const results = await Promise.allSettled(
    seriesDefs.map((def) => fetchSeries(project, def.metricName, win, signal))
  );

  // Generate the full requested time window as evenly-spaced buckets so the
  // X-axis always spans win.from → win.to regardless of where data exists.
  const fromMs = new Date(win.from).getTime();
  const toMs   = new Date(win.to).getTime();
  const bucketMs = win.rollupSeconds * 1000;
  const numBuckets = Math.max(2, Math.ceil((toMs - fromMs) / bucketMs) + 1);
  const sortedTs = Array.from({ length: numBuckets }, (_, i) =>
    new Date(Math.min(fromMs + i * bucketMs, toMs)).toISOString()
  );

  const halfBucket = bucketMs / 2;

  const datasets = seriesDefs.map((def, i) => {
    const points = results[i].status === "fulfilled" ? (results[i].value.points ?? []) : [];
    // Key by ms so timestamp string precision differences don't cause misses.
    const byMs = new Map(points.map((p) => [new Date(p.timestamp).getTime(), p.value]));
    const transform = def.transform ?? ((v) => v);
    return {
      label: def.label,
      data: sortedTs.map((ts) => {
        const targetMs = new Date(ts).getTime();
        let best = null, bestDelta = Infinity;
        for (const [ptMs, val] of byMs) {
          const delta = Math.abs(ptMs - targetMs);
          if (delta <= halfBucket && delta < bestDelta) { best = val; bestDelta = delta; }
        }
        return best != null ? transform(best) : null;
      }),
      borderColor: def.color,
      backgroundColor: def.fill ? `${def.color}26` : "transparent",
      fill: def.fill ?? false,
      tension: 0.25,
      pointRadius: 0,
      borderWidth: 1.5,
      spanGaps: true,
    };
  });

  _upsertChart(canvasId, {
    type: "line",
    data: { labels: sortedTs, datasets },
    options: _baseChartOptions(win),
  });
}

/**
 * Fetch and render a single-series bar chart (counts per rollup bucket).
 *
 * @param {string} canvasId
 * @param {string} project
 * @param {string} metricName
 * @param {string} color
 * @param {string} label
 * @param {object} win
 * @param {AbortSignal} signal
 */
async function buildBarChart(canvasId, project, metricName, color, label, win, signal) {
  const data = await fetchSeries(project, metricName, win, signal);
  const points = data.points ?? [];

  const fromMs = new Date(win.from).getTime();
  const toMs   = new Date(win.to).getTime();
  const bucketMs = win.rollupSeconds * 1000;
  const numBuckets = Math.max(2, Math.ceil((toMs - fromMs) / bucketMs) + 1);
  const sortedTs = Array.from({ length: numBuckets }, (_, i) =>
    new Date(Math.min(fromMs + i * bucketMs, toMs)).toISOString()
  );

  const halfBucket = bucketMs / 2;
  const byMs = new Map(points.map((p) => [new Date(p.timestamp).getTime(), p.value]));
  const values = sortedTs.map((ts) => {
    const targetMs = new Date(ts).getTime();
    let best = null, bestDelta = Infinity;
    for (const [ptMs, val] of byMs) {
      const delta = Math.abs(ptMs - targetMs);
      if (delta <= halfBucket && delta < bestDelta) { best = val; bestDelta = delta; }
    }
    return best;
  });

  _upsertChart(canvasId, {
    type: "bar",
    data: {
      labels: sortedTs,
      datasets: [{
        label,
        data: values,
        backgroundColor: `${color}99`,
        borderColor: color,
        borderWidth: 1,
        borderRadius: 2,
      }],
    },
    options: _baseChartOptions(win, "count"),
  });
}

/**
 * Fetch summaries and fill stat elements.
 *
 * @param {string} project
 * @param {Array}  statDefs - [{elementId, metricName, pick, format, danger?}]
 *   pick:   (summary) => number|null  (e.g. s => s.sum, s => s.min)
 *   format: keyof fmt or (value) => string
 *   danger: (summary) => boolean      adds stat-danger class when true
 * @param {object} win
 * @param {AbortSignal} signal
 */
async function fillStats(project, statDefs, win, signal) {
  const results = await Promise.allSettled(
    statDefs.map((def) => fetchSummary(project, def.metricName, win, signal))
  );

  statDefs.forEach((def, i) => {
    const el = document.getElementById(def.elementId);
    if (!el) return;
    if (results[i].status === "rejected") {
      el.textContent = "—";
      return;
    }
    const summary = results[i].value;
    const raw = def.pick(summary);
    const formatter = typeof def.format === "function" ? def.format : (fmt[def.format] ?? fmt.count);
    el.textContent = formatter(raw);
    if (def.danger) {
      const isDanger = def.danger(summary);
      el.classList.toggle("stat-danger", isDanger);
      el.classList.toggle("stat-healthy", !isDanger && el.classList.contains("stat-danger-or-healthy"));
    }
  });
}

/* ── Log section ────────────────────────────────────────────────────── */

let _allLogs = [];
let _logWindowStart = null;
let _logBucketMinutes = 15;
let _currentView = "logs";
let _activePatternTemplate = null;

const _LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

const _LOG_LEVEL_COLORS = {
  DEBUG:    "#94a3b8",
  INFO:     "#60a5fa",
  WARNING:  "#fbbf24",
  ERROR:    "#f87171",
  CRITICAL: "#ef4444",
};

/* Python traceback detection and collapsible rendering */

const _PY_KEYWORDS = new Set([
  "False","None","True","and","as","assert","async","await","break","class",
  "continue","def","del","elif","else","except","finally","for","from",
  "global","if","import","in","is","lambda","nonlocal","not","or","pass",
  "raise","return","try","while","with","yield",
]);
const _PY_BUILTINS = new Set([
  "print","len","range","int","str","float","list","dict","set","tuple",
  "bool","type","isinstance","hasattr","getattr","setattr","open","super",
  "self","cls",
]);

function _highlightPythonLine(text) {
  const frag = document.createDocumentFragment();
  const TOKEN_RE = /("""[\s\S]*?"""|'''[\s\S]*?'''|"[^"\n]*"|'[^'\n]*'|#.*$|\b\d+\.?\d*\b|[A-Za-z_]\w*|.)/gm;
  let match;
  while ((match = TOKEN_RE.exec(text)) !== null) {
    const tok = match[0];
    let cls = null;
    if (/^(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"[^"\n]*"|'[^'\n]*')$/.test(tok)) cls = "py-string";
    else if (tok.startsWith("#")) cls = "py-comment";
    else if (/^\d/.test(tok)) cls = "py-number";
    else if (_PY_KEYWORDS.has(tok)) cls = "py-keyword";
    else if (_PY_BUILTINS.has(tok)) cls = "py-builtin";

    if (cls) {
      const span = document.createElement("span");
      span.className = cls;
      span.textContent = tok;
      frag.appendChild(span);
    } else {
      frag.appendChild(document.createTextNode(tok));
    }
  }
  return frag;
}

const _TB = {
  header:    /^Traceback \(most recent call last\):/,
  location:  /^\s+File "[^"]+", line \d+/,
  source:    /^    \S/,
  exception: /^\w[\w.]*(?:Error|Exception|Warning|KeyboardInterrupt|SystemExit|StopIteration)(\s*:|$)/,
};

function _classifyTbLine(line) {
  if (_TB.header.test(line))    return "tb-header";
  if (_TB.location.test(line))  return "tb-location";
  if (_TB.source.test(line))    return "tb-source";
  if (_TB.exception.test(line)) return "tb-exception";
  return null;
}

function _buildTbPre(lines) {
  const pre = document.createElement("pre");
  pre.className = "log-traceback";
  const content = lines[lines.length - 1] === "" ? lines.slice(0, -1) : lines;
  content.forEach((line, i) => {
    const cls = _classifyTbLine(line);
    if (cls === "tb-source") {
      const span = document.createElement("span");
      span.className = cls;
      span.appendChild(_highlightPythonLine(line));
      pre.appendChild(span);
    } else if (cls) {
      const span = document.createElement("span");
      span.className = cls;
      span.textContent = line;
      pre.appendChild(span);
    } else {
      pre.appendChild(document.createTextNode(line));
    }
    if (i < content.length - 1) pre.appendChild(document.createTextNode("\n"));
  });
  return pre;
}

function _findExceptionLine(lines) {
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].trim() && _TB.exception.test(lines[i])) return lines[i].trim();
  }
  return lines.filter((l) => l.trim()).at(-1) ?? "";
}

function _buildCollapsibleTraceback(lines) {
  const wrapper = document.createElement("div");
  wrapper.className = "tb-wrapper tb-collapsed";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "tb-toggle";
  toggle.addEventListener("click", () => wrapper.classList.toggle("tb-collapsed"));

  const chevron = document.createElement("span");
  chevron.className = "tb-chevron";
  chevron.setAttribute("aria-hidden", "true");
  chevron.textContent = "›";

  const summary = document.createElement("span");
  summary.className = "tb-exception";
  summary.textContent = _findExceptionLine(lines);

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "tb-copy";
  copyBtn.setAttribute("aria-label", "Copy traceback");
  const _COPY_ICON_SVG = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  copyBtn.insertAdjacentHTML("beforeend", _COPY_ICON_SVG);
  copyBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const text = lines[lines.length - 1] === "" ? lines.slice(0, -1).join("\n") : lines.join("\n");
    navigator.clipboard.writeText(text).then(() => {
      copyBtn.classList.add("tb-copy-done");
      setTimeout(() => copyBtn.classList.remove("tb-copy-done"), 1500);
    });
  });

  toggle.append(chevron, summary, copyBtn);
  wrapper.append(toggle, _buildTbPre(lines));
  return wrapper;
}

function _renderMessage(message) {
  if (!message) return document.createTextNode("—");
  const lines = message.split("\n");
  if (lines.length === 1) return document.createTextNode(message);
  const isTraceback = lines.some((l) => _TB.header.test(l) || _TB.location.test(l));
  if (isTraceback) return _buildCollapsibleTraceback(lines);
  const pre = document.createElement("pre");
  pre.className = "log-pre";
  pre.textContent = message;
  return pre;
}

/* Track expanded tracebacks across renders */

function _getLogKey(log) {
  return `${log.timestamp}|${log.logger_name}|${log.message}`;
}

let _expandedLogs = new Set();

/* Log pattern grouping */

function _tokenizeMessage(msg) {
  return msg
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "*")
    .replace(/\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b/g, "*")
    .replace(/\b0x[0-9a-f]+\b/gi, "*")
    .replace(/\b[0-9a-f]{32,}\b/gi, "*")
    .replace(/"[^"\n]{0,200}"/g, '"*"')
    .replace(/'[^'\n]{0,200}'/g, "'*'")
    .replace(/\b\d+\.?\d*\b/g, "*")
    .replace(/\s+/g, " ")
    .trim();
}

/* Filtering */

function _getLogFilters() {
  return {
    level:   document.getElementById("logLevelFilter")?.value ?? "",
    logger:  document.getElementById("logLoggerFilter")?.value.toLowerCase() ?? "",
    content: document.getElementById("logContentFilter")?.value.toLowerCase() ?? "",
  };
}

function _filterLogs(logs) {
  const { level, logger, content } = _getLogFilters();
  return logs.filter((log) => {
    if (level && log.level !== level) return false;
    if (logger && !(log.logger_name ?? "").toLowerCase().includes(logger)) return false;
    if (content && !(log.message ?? "").toLowerCase().includes(content)) return false;
    if (_activePatternTemplate && _tokenizeMessage(log.message ?? "") !== _activePatternTemplate) return false;
    return true;
  });
}

/* Rendering */

function _renderLogHistogram(logs) {
  if (!_logWindowStart || typeof Chart === "undefined") return;
  const bucketMs = _logBucketMinutes * 60_000;
  const startMs = _logWindowStart.getTime();
  const now = Date.now();
  const numBuckets = Math.max(1, Math.ceil((now - startMs) / bucketMs));

  const counts = Object.fromEntries(_LOG_LEVELS.map((l) => [l, new Array(numBuckets).fill(0)]));
  for (const log of logs) {
    if (!log.timestamp) continue;
    const idx = Math.floor((new Date(log.timestamp).getTime() - startMs) / bucketMs);
    if (idx >= 0 && idx < numBuckets && counts[log.level]) {
      counts[log.level][idx]++;
    }
  }

  const sans = FONT_SANS;
  const windowHours = (Date.now() - _logWindowStart.getTime()) / 3_600_000;
  const labels = Array.from({ length: numBuckets }, (_, i) =>
    new Date(startMs + i * bucketMs).toISOString()
  );

  _upsertChart("chartLogLevels", {
    type: "bar",
    data: {
      labels,
      datasets: _LOG_LEVELS.map((l) => ({
        label: l,
        data: counts[l],
        backgroundColor: _LOG_LEVEL_COLORS[l],
        stack: "logs",
        borderWidth: 0,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: COLORS.muted, boxWidth: 10, font: { family: sans, size: 11 }, padding: 12 } },
        tooltip: { callbacks: { title: (items) => _formatFullTimestamp(items[0]?.label) } },
      },
      scales: {
        x: {
          stacked: true,
          ticks: {
            color: COLORS.muted,
            font: { family: sans, size: 11 },
            maxTicksLimit: 10,
            callback: function(val) { return _formatTimestamp(this.getLabelForValue(val), windowHours); },
          },
          grid: { color: COLORS.grid }, border: { color: COLORS.grid },
        },
        y: { stacked: true, beginAtZero: true, ticks: { color: COLORS.muted, font: { family: sans, size: 11 } }, grid: { color: COLORS.grid }, border: { color: COLORS.grid } },
      },
    },
  });
}

function _renderLogTable(filtered) {
  const tbody = document.getElementById("logsTableBody");
  const countEl = document.getElementById("logsCount");
  if (!tbody) return;

  // Save currently expanded logs before rendering
  tbody.querySelectorAll(".tb-wrapper:not(.tb-collapsed)").forEach((wrapper) => {
    const row = wrapper.closest("tr");
    if (!row) return;
    const cells = row.querySelectorAll("td");
    if (cells.length >= 4) {
      const timestamp = cells[0].textContent;
      const logger = cells[2].textContent;
      const msgEl = cells[3];
      for (const log of _allLogs) {
        if (fmt.timestamp(log.timestamp) === timestamp && (log.logger_name ?? "—") === logger) {
          _expandedLogs.add(_getLogKey(log));
        }
      }
    }
  });

  // Save scroll position
  const tableWrap = document.querySelector(".table-wrap");
  const scrollPos = tableWrap?.scrollTop ?? 0;

  const suffix = _activePatternTemplate ? " · pattern filter active" : "";
  if (countEl) {
    countEl.textContent = `Showing ${filtered.length.toLocaleString()} of ${_allLogs.length.toLocaleString()} logs${suffix}`;
  }

  tbody.replaceChildren();
  if (!filtered.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "logs-empty";
    cell.textContent = _allLogs.length ? "No logs match the current filters." : "No logs in this window.";
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }

  for (const log of filtered) {
    const row = document.createElement("tr");

    const timeCell = document.createElement("td");
    timeCell.className = "logs-time";
    timeCell.textContent = fmt.timestamp(log.timestamp);

    const levelCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `level-badge level-${(log.level ?? "unknown").toLowerCase()}`;
    badge.textContent = log.level ?? "—";
    levelCell.appendChild(badge);

    const loggerCell = document.createElement("td");
    loggerCell.className = "logs-logger";
    loggerCell.textContent = log.logger_name ?? "—";

    const msgCell = document.createElement("td");
    msgCell.className = "logs-message";
    msgCell.appendChild(_renderMessage(log.message ?? ""));

    row.append(timeCell, levelCell, loggerCell, msgCell);
    tbody.appendChild(row);

    // Re-apply expanded state if this log was expanded before
    const logKey = _getLogKey(log);
    if (_expandedLogs.has(logKey)) {
      const wrapper = row.querySelector(".tb-wrapper");
      if (wrapper) {
        wrapper.classList.remove("tb-collapsed");
      }
    }
  }

  // Restore scroll position
  if (tableWrap && scrollPos > 0) {
    tableWrap.scrollTop = scrollPos;
  }
}

function _renderPatterns(logs) {
  const tbody = document.getElementById("patternsTableBody");
  if (!tbody) return;

  const groups = new Map();
  for (const log of logs) {
    const template = _tokenizeMessage(log.message ?? "");
    groups.set(template, (groups.get(template) ?? 0) + 1);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1] - a[1]);

  tbody.replaceChildren();
  if (!sorted.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 2;
    cell.className = "logs-empty";
    cell.textContent = "No patterns found.";
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }

  for (const [template, count] of sorted) {
    const row = document.createElement("tr");
    row.className = "pattern-row";

    const countCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "pattern-count-badge";
    badge.textContent = count;
    countCell.appendChild(badge);

    const tmplCell = document.createElement("td");
    tmplCell.className = "pattern-template";
    tmplCell.textContent = template;

    row.append(countCell, tmplCell);
    row.addEventListener("click", () => {
      _activePatternTemplate = template;
      _switchView("logs");
    });
    tbody.appendChild(row);
  }
}

function _refreshLogViews() {
  const filtered = _filterLogs(_allLogs);
  _renderLogHistogram(filtered);
  if (_currentView === "patterns") {
    _expandedLogs.clear();
    _renderPatterns(filtered);
  } else {
    _renderLogTable(filtered);
  }
}

function _switchView(view) {
  if (view === "patterns") _activePatternTemplate = null;
  _currentView = view;
  const logsSection = document.getElementById("logsSection");
  const patternsSection = document.getElementById("patternsSection");
  logsSection?.toggleAttribute("hidden", view !== "logs");
  patternsSection?.toggleAttribute("hidden", view !== "patterns");
  document.getElementById("logsViewBtn")?.classList.toggle("is-active", view === "logs");
  document.getElementById("patternsViewBtn")?.classList.toggle("is-active", view === "patterns");
  _refreshLogViews();
}

function _initLogSection() {
  for (const id of ["logLevelFilter", "logLoggerFilter", "logContentFilter"]) {
    const el = document.getElementById(id);
    el?.addEventListener("input", _refreshLogViews);
    el?.addEventListener("change", _refreshLogViews);
  }
  document.getElementById("logsViewBtn")?.addEventListener("click", () => _switchView("logs"));
  document.getElementById("patternsViewBtn")?.addEventListener("click", () => _switchView("patterns"));
}

async function _loadLogs(project, win, signal) {
  const logs = await _fetchLogs(project, win, signal);
  const windowMs = new Date(win.to).getTime() - new Date(win.from).getTime();
  const windowHours = windowMs / 3_600_000;
  _logWindowStart = new Date(win.from);
  _logBucketMinutes = win.rollupSeconds != null
    ? win.rollupSeconds / 60
    : Math.max(5, Math.round(windowHours * 60 / 40));
  _allLogs = Array.isArray(logs) ? logs : [];
  const currentKeys = new Set(_allLogs.map(_getLogKey));
  for (const key of _expandedLogs) {
    if (!currentKeys.has(key)) _expandedLogs.delete(key);
  }
  _refreshLogViews();
}

/* ── Error banner ───────────────────────────────────────────────────── */

function _showError(message) {
  let banner = document.querySelector(".error-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.className = "error-banner";
    document.querySelector(".dashboard")?.prepend(banner);
  }
  banner.textContent = message;
}

function _clearError() {
  document.querySelector(".error-banner")?.remove();
}

/* ── initDashboard ──────────────────────────────────────────────────── */

/**
 * Wire up the dashboard: controls, refresh loop, log section.
 *
 * @param {object} config
 * @param {string}   config.project             - Spyglass project name
 * @param {Function} config.loadFn              - async (win, signal) => void
 *   Called each refresh. Should call buildLineChart / fillStats for project sections.
 * @param {number}   [config.defaultWindowAmount=6]
 * @param {string}   [config.defaultWindowUnit="hours"]
 */
function initDashboard({ project, loadFn, defaultWindowAmount = 1, defaultWindowUnit = "days" }) {
  const amountEl = document.getElementById("windowAmount");
  const unitEl = document.getElementById("windowUnit");
  if (amountEl) amountEl.value = defaultWindowAmount;
  if (unitEl) unitEl.value = defaultWindowUnit;

  _initLogSection();

  let _controller = null;

  async function load() {
    if (_controller) _controller.abort();
    _controller = new AbortController();
    const { signal } = _controller;
    const win = _getTimeWindow();

    try {
      const results = await Promise.allSettled([
        loadFn(win, signal),
        _loadLogs(project, win, signal),
      ]);
      const failed = results.filter(
        (r) => r.status === "rejected" && r.reason?.name !== "AbortError"
      );
      if (failed.length) {
        _showError(`${failed.length} section(s) failed to load — check the console.`);
        failed.forEach((r) => console.error("[dashboard]", r.reason));
      } else {
        _clearError();
      }
    } catch (err) {
      if (err.name !== "AbortError") _showError(err.message);
    }

    const lastUpdatedEl = document.getElementById("lastUpdated");
    if (lastUpdatedEl) {
      lastUpdatedEl.textContent = new Date().toLocaleTimeString(undefined, {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    }
  }

  document.getElementById("refreshBtn")?.addEventListener("click", load);
  for (const id of ["windowAmount", "windowUnit", "rollupWindow"]) {
    document.getElementById(id)?.addEventListener("change", load);
  }
  document.getElementById("windowAmount")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") load();
  });

  const _intervalId = setInterval(load, 30_000);

  globalThis.addEventListener("beforeunload", () => {
    clearInterval(_intervalId);
    Object.values(_chartInstances).forEach((c) => c.destroy());
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
}

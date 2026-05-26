// Overwatch dashboard — vanilla JS, basic + advanced rendering modes.

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const state = {
  events: [],
  maxFeedSize: 250,
  filter: { category: "", severity: "" },
  mode: "basic",  // "basic" | "advanced"
  ws: null,
  wsReconnectDelay: 1000,
  attackTechniques: {},
};

const MONITOR_LABELS = {
  SessionMonitor:    { basic: "Lock/unlock events",           advanced: "Session",    category: "session" },
  LoginMonitor:      { basic: "Who's signing in",            advanced: "Login",      category: "login" },
  ProcessMonitor:    { basic: "Suspicious programs",          advanced: "Process",    category: "process" },
  USBMonitor:        { basic: "USB devices",                  advanced: "USB",        category: "usb" },
  RDPMonitor:        { basic: "Remote connections",           advanced: "RDP",        category: "rdp" },
  FileSystemMonitor: { basic: "Files in sensitive folders",   advanced: "Filesystem", category: "filesystem" },
  NetworkMonitor:    { basic: "Wi-Fi & network changes",      advanced: "Network",    category: "network" },
  PowerMonitor:      { basic: "Laptop power & battery",        advanced: "Power",      category: "power" },
};

// Initialized before applyMode() to avoid temporal dead zone error.
let lastMonitors = [];

const SEVERITY_BASIC = {
  critical: "Take action",
  warning:  "Worth a look",
  info:     "FYI",
};

// ============================================================
// Theme + mode persistence
// ============================================================
const THEME_KEY = "overwatch-theme";
const MODE_KEY  = "overwatch-mode";

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem(THEME_KEY, theme);
  $("#theme-btn").textContent = theme === "dark" ? "☾" : "☀";
}
applyTheme(localStorage.getItem(THEME_KEY) || "dark");
$("#theme-btn").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  applyTheme(next);
});

function applyMode(mode) {
  state.mode = mode;
  document.documentElement.setAttribute("data-mode", mode);
  localStorage.setItem(MODE_KEY, mode);
  for (const tab of $$(".mode-tab")) {
    tab.setAttribute("aria-selected", tab.dataset.mode === mode ? "true" : "false");
  }
  // Re-apply per-mode labels
  for (const el of $$("[data-basic],[data-advanced]")) {
    const text = mode === "basic" ? el.dataset.basic : el.dataset.advanced;
    if (text) el.textContent = text;
  }
  // Re-render feed with new mode-specific filters
  renderFeed();
  // Update monitor cards' labels
  renderMonitorsFromState();
}
applyMode(localStorage.getItem(MODE_KEY) || "basic");

for (const tab of $$(".mode-tab")) {
  tab.addEventListener("click", () => applyMode(tab.dataset.mode));
}

// ============================================================
// API helpers
// ============================================================
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ============================================================
// Status + monitors
// ============================================================

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    $("#machine-name").textContent = status.machine_name || "—";

    setStatusPill(
      status.paused ? "paused"
        : status.running ? "running"
          : "stopped"
    );

    // Sync Away Mode pill (defensive: tolerate missing element on stale HTML)
    const awayBtn = $("#away-btn");
    if (awayBtn) {
      awayBtn.setAttribute("data-active", status.away_mode ? "true" : "false");
      const label = awayBtn.querySelector(".away-label");
      if (label) label.textContent = status.away_mode ? "AWAY MODE: ON" : "AWAY MODE";
    }

    const stats = status.stats || {};
    const todayTotal = Object.values(stats.today || {}).reduce((a, b) => a + b, 0);
    const hourTotal  = Object.values(stats.last_hour || {}).reduce((a, b) => a + b, 0);
    const sev        = stats.severity_today || {};

    $("#stat-today").textContent    = formatCount(todayTotal);
    $("#stat-hour").textContent     = formatCount(hourTotal);
    $("#stat-critical").textContent = formatCount(sev.critical || 0);
    $("#stat-warning").textContent  = formatCount(sev.warning  || 0);
    $("#stat-info").textContent     = formatCount(sev.info     || 0);

    const monitors = await api("/api/monitors");
    lastMonitors = monitors.monitors || [];
    renderMonitorsFromState();
    $("#monitor-count").textContent = `${lastMonitors.length} active`;
  } catch (err) {
    setStatusPill("disconnected");
    console.error(err);
  }
}

function setStatusPill(state) {
  const pill = $("#status-pill");
  pill.setAttribute("data-state", state);
  $("#status-label").textContent = state;
}

function formatCount(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

function renderMonitorsFromState() {
  const grid = $("#monitor-grid");
  grid.innerHTML = "";
  const tmpl = $("#monitor-card-tmpl");

  for (const name of Object.keys(MONITOR_LABELS)) {
    const found = lastMonitors.find(m => m.name === name);
    const meta  = MONITOR_LABELS[name];
    const card  = tmpl.content.cloneNode(true).firstElementChild;
    card.querySelector(".mon-name").textContent = meta[state.mode];

    if (found && found.enabled) {
      const stateTxt = found.alert ? (state.mode === "basic" ? "watching" : "active")
                                   : (state.mode === "basic" ? "logging silently" : "logging");
      card.querySelector(".mon-state").textContent = stateTxt;
      card.setAttribute("data-state", "active");
    } else {
      card.querySelector(".mon-state").textContent = state.mode === "basic" ? "turned off" : "disabled";
      card.setAttribute("data-state", "disabled");
    }
    grid.appendChild(card);
  }
}

// ============================================================
// Event feed
// ============================================================
async function loadEvents() {
  const params = new URLSearchParams();
  if (state.filter.category) params.set("category", state.filter.category);
  if (state.filter.severity) params.set("severity", state.filter.severity);
  params.set("limit", state.maxFeedSize);
  const data = await api(`/api/events?${params}`);
  state.events = data.events || [];
  renderFeed();
}

function shouldShowInBasic(ev) {
  // Hide info events without a friendly summary
  if (ev.severity === "info" && !ev.friendly_summary) return false;
  return true;
}

function renderFeed() {
  const feed = $("#event-feed");
  feed.innerHTML = "";
  const filtered = state.events.filter(ev =>
    state.mode === "advanced" || shouldShowInBasic(ev)
  );
  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "event-row empty";
    empty.textContent = state.mode === "basic"
      ? "Nothing notable yet — Overwatch is quietly watching."
      : "No events match the current filters.";
    feed.appendChild(empty);
    return;
  }
  for (const ev of filtered) feed.appendChild(buildRow(ev));
}

function buildRow(ev, isNew = false) {
  const tmpl = $("#event-row-tmpl");
  const row  = tmpl.content.cloneNode(true).firstElementChild;
  row.dataset.id      = ev.id;
  row.dataset.dedup   = ev.dedup_key || "";
  row.dataset.severity= ev.severity;

  // Time
  row.querySelector(".ev-time").textContent =
    state.mode === "basic" ? relativeTime(ev.timestamp) : techTime(ev.timestamp);

  // Severity
  const sev = row.querySelector(".ev-sev");
  sev.textContent       = state.mode === "basic" ? SEVERITY_BASIC[ev.severity] : ev.severity;
  sev.dataset.sev       = ev.severity;

  // Category
  row.querySelector(".ev-cat").textContent = ev.category;

  // Summary
  const summaryText = (state.mode === "basic" && ev.friendly_summary)
    ? ev.friendly_summary
    : ev.summary;
  row.querySelector(".ev-text").textContent = summaryText;

  // Dedup count
  const countEl = row.querySelector(".ev-count");
  if (ev.dedup_count && ev.dedup_count > 1) {
    countEl.textContent = `× ${ev.dedup_count}`;
    countEl.classList.add("visible");
  }

  // MITRE tags (advanced only)
  const tagsEl = row.querySelector(".ev-tags");
  if (Array.isArray(ev.attack_tags) && ev.attack_tags.length) {
    for (const tag of ev.attack_tags) {
      const info = state.attackTechniques[tag];
      const a = document.createElement("a");
      a.className = "attack-tag";
      a.textContent = tag;
      a.target = "_blank";
      a.rel = "noopener";
      a.href = info?.url || `https://attack.mitre.org/techniques/${tag.split(".")[0]}/`;
      if (info) {
        a.title = `${tag} — ${info.name}\n${info.description}\n(Click to open MITRE ATT&CK reference)`;
      } else {
        a.title = `${tag}\n(Click to open MITRE ATT&CK reference)`;
      }
      // Prevent the row's click-to-expand behaviour from triggering
      a.addEventListener("click", (e) => e.stopPropagation());
      tagsEl.appendChild(a);
    }
  }

  // Details
  row.querySelector(".ev-details").textContent = ev.details || "";
  const expand = row.querySelector(".ev-expand");
  expand.addEventListener("click", () => {
    row.classList.toggle("expanded");
    expand.textContent = row.classList.contains("expanded") ? "−" : "+";
  });

  if (isNew) row.classList.add("new");
  return row;
}

function relativeTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const s = Math.floor(diff / 1000);
  if (s < 5)   return "now";
  if (s < 60)  return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return d.toLocaleDateString();
}

function techTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
}

function matchesFilter(ev) {
  if (state.filter.category && ev.category !== state.filter.category) return false;
  if (state.filter.severity && ev.severity !== state.filter.severity) return false;
  return true;
}

function onLiveEvent(ev) {
  if (ev.is_update) {
    // Update existing row (dedup bumped)
    const existing = state.events.find(e => e.id === ev.id);
    if (existing) {
      Object.assign(existing, ev);
      const row = $(`.event-row[data-id="${ev.id}"]`);
      if (row) {
        row.querySelector(".ev-time").textContent =
          state.mode === "basic" ? relativeTime(ev.timestamp) : techTime(ev.timestamp);
        const countEl = row.querySelector(".ev-count");
        countEl.textContent = `× ${ev.dedup_count}`;
        countEl.classList.add("visible");
        row.classList.add("new");
        setTimeout(() => row.classList.remove("new"), 1600);
      }
    }
    refreshSeverityStats();
    return;
  }

  if (!matchesFilter(ev)) return;

  state.events.unshift(ev);
  if (state.events.length > state.maxFeedSize) state.events.pop();

  if (state.mode === "basic" && !shouldShowInBasic(ev)) return;

  const feed = $("#event-feed");
  const empty = feed.querySelector(".empty");
  if (empty) empty.remove();

  feed.prepend(buildRow(ev, true));
  while (feed.children.length > state.maxFeedSize) {
    feed.lastElementChild.remove();
  }
  refreshSeverityStats();
  bumpStats(ev);
}

function bumpStats(ev) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (new Date(ev.timestamp) >= today) {
    $("#stat-today").textContent =
      formatCount(parseInt(($("#stat-today").textContent || "0").replace("k","000"), 10) + 1);
  }
}

function refreshSeverityStats() {
  // Re-derive from state.events for the today window
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const todayISO = today.toISOString();
  const counts = { critical: 0, warning: 0, info: 0 };
  for (const ev of state.events) {
    if (ev.timestamp >= todayISO) {
      counts[ev.severity] = (counts[ev.severity] || 0) + (ev.dedup_count || 1);
    }
  }
  $("#stat-critical").textContent = formatCount(counts.critical);
  $("#stat-warning").textContent  = formatCount(counts.warning);
  $("#stat-info").textContent     = formatCount(counts.info);
}

// ============================================================
// WebSocket
// ============================================================
function connectWS() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  state.ws = new WebSocket(`${proto}//${location.host}/api/stream`);
  state.ws.onopen = () => {
    state.wsReconnectDelay = 1000;
    $("#live-indicator").setAttribute("data-state", "connected");
  };
  state.ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === "event") onLiveEvent(msg.event);
    } catch (err) { console.error(err); }
  };
  state.ws.onclose = () => {
    $("#live-indicator").setAttribute("data-state", "disconnected");
    setStatusPill("disconnected");
    setTimeout(connectWS, state.wsReconnectDelay);
    state.wsReconnectDelay = Math.min(state.wsReconnectDelay * 1.5, 10000);
  };
  state.ws.onerror = () => { try { state.ws.close(); } catch {} };
}

// ============================================================
// Filter + control wiring
// ============================================================
$("#filter-category").addEventListener("change", (e) => {
  state.filter.category = e.target.value;
  loadEvents();
});
$("#filter-severity").addEventListener("change", (e) => {
  state.filter.severity = e.target.value;
  loadEvents();
});

$("#pause-btn").addEventListener("click", async () => {
  const isPaused = $("#status-pill").getAttribute("data-state") === "paused";
  await api(isPaused ? "/api/system/resume" : "/api/system/pause", { method: "POST" });
  refreshStatus();
});
$("#restart-btn").addEventListener("click", async () => {
  if (!confirm("Restart all monitors?")) return;
  await api("/api/system/restart", { method: "POST" });
  refreshStatus();
});

$("#away-btn")?.addEventListener("click", async () => {
  const btn = $("#away-btn");
  const isOn = btn.getAttribute("data-active") === "true";
  const next = !isOn;
  // Optimistic UI: flip immediately, don't wait for server
  btn.setAttribute("data-active", next ? "true" : "false");
  const label = btn.querySelector(".away-label");
  if (label) label.textContent = next ? "AWAY MODE: ON" : "AWAY MODE";
  try {
    await api("/api/system/away", {
      method: "POST",
      body: JSON.stringify({ enabled: next }),
    });
  } catch (err) {
    // Roll back on error
    btn.setAttribute("data-active", isOn ? "true" : "false");
    if (label) label.textContent = isOn ? "AWAY MODE: ON" : "AWAY MODE";
    alert("Failed to toggle Away Mode: " + err.message);
  }
});

// Tick relative timestamps every 20s
setInterval(() => {
  if (state.mode !== "basic") return;
  for (const row of $$(".event-row[data-id]")) {
    const ev = state.events.find(e => String(e.id) === row.dataset.id);
    if (ev) row.querySelector(".ev-time").textContent = relativeTime(ev.timestamp);
  }
}, 20000);

// ============================================================
// Boot
// ============================================================
async function loadAttackCatalog() {
  try {
    state.attackTechniques = await api("/api/attack");
  } catch (err) {
    console.warn("Failed to load MITRE catalog:", err);
  }
}

(async () => {
  await loadAttackCatalog();
  refreshStatus();
  loadEvents();
  connectWS();
})();
setInterval(refreshStatus, 15000);

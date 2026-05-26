// Settings page logic — vanilla JS, no framework.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let config = {};
let monitorDescriptions = {};

// ---- Theme (shared with dashboard) ----------------------------
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
  document.documentElement.setAttribute("data-mode", mode);
  localStorage.setItem(MODE_KEY, mode);
  for (const tab of $$(".mode-tab")) {
    tab.setAttribute("aria-selected", tab.dataset.mode === mode ? "true" : "false");
  }
  for (const el of $$("[data-basic],[data-advanced]")) {
    const text = mode === "basic" ? el.dataset.basic : el.dataset.advanced;
    if (text) el.textContent = text;
  }
}
applyMode(localStorage.getItem(MODE_KEY) || "basic");
for (const tab of $$(".mode-tab")) {
  tab.addEventListener("click", () => applyMode(tab.dataset.mode));
}

// ---- API ------------------------------------------------------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function getNested(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

function setNested(obj, path, value) {
  const parts = path.split(".");
  let o = obj;
  for (const p of parts.slice(0, -1)) {
    if (!(p in o) || typeof o[p] !== "object") o[p] = {};
    o = o[p];
  }
  o[parts[parts.length - 1]] = value;
}

// ---- Load config and hydrate fields --------------------------
async function loadConfig() {
  config = await api("/api/config");

  // Token-set indicator
  if (config.telegram?.bot_token_set) {
    $("#token-status").textContent = "(saved — leave blank to keep)";
  } else {
    $("#token-status").textContent = "(not set)";
  }

  // Hydrate all data-config inputs
  for (const el of $$("[data-config]")) {
    const path = el.dataset.config;
    const val = getNested(config, path);
    if (el.type === "checkbox") {
      el.checked = !!val;
    } else {
      el.value = val ?? "";
    }
  }

  // Time fields (combine hour + minute)
  for (const el of $$("[data-config-time]")) {
    const base = el.dataset.configTime;
    const hour = getNested(config, base + "_hour") ?? 0;
    const minute = getNested(config, base + "_minute") ?? 0;
    el.value = `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  }

  // Day picker
  const days = config.silent_hours?.days || [];
  for (const btn of $$("#day-picker button")) {
    btn.dataset.active = days.includes(parseInt(btn.dataset.day, 10)) ? "true" : "false";
    btn.addEventListener("click", () => {
      btn.dataset.active = btn.dataset.active === "true" ? "false" : "true";
    });
  }

  // List fields (newline-separated)
  for (const el of $$("[data-list]")) {
    const arr = getNested(config, el.dataset.list) || [];
    el.value = arr.join("\n");
  }

  // Monitor toggles
  await renderMonitorToggles();
}

async function renderMonitorToggles() {
  const monitors = ["session", "login", "process", "usb", "rdp", "filesystem", "network", "power"];
  const labels = {
    session: ["Lock / Unlock", "When the computer is locked or unlocked"],
    login: ["Sign-ins", "Who signs in to this computer"],
    process: ["Programs", "Suspicious programs being run"],
    usb: ["USB devices", "USB device insertion and removal"],
    rdp: ["Remote access", "Remote desktop, TeamViewer, AnyDesk, VNC"],
    filesystem: ["File changes", "Changes to your Documents, Desktop, Downloads, Pictures"],
    network: ["Network", "Wi-Fi changes, joining new networks"],
    power: ["Laptop power", "Charger unplugged, battery (laptops only)"],
  };

  const container = $("#monitor-toggles");
  container.innerHTML = "";
  for (const cat of monitors) {
    const cfg = config.monitors?.[cat] || {};
    const [name, desc] = labels[cat] || [cat, ""];
    const row = document.createElement("div");
    row.className = "monitor-toggle";
    row.innerHTML = `
      <div>
        <div class="mt-name">${name}</div>
        <div class="mt-desc">${desc}</div>
      </div>
      <label class="toggle-label">
        <input type="checkbox" data-monitor="${cat}" data-key="enabled" ${cfg.enabled ? "checked" : ""}>
        enabled
      </label>
      <label class="toggle-label">
        <input type="checkbox" data-monitor="${cat}" data-key="alert" ${cfg.alert ? "checked" : ""}>
        alert
      </label>
    `;
    container.appendChild(row);
  }
}

// ---- Collect form values into a config diff ------------------
function collectGeneral() {
  const out = { general: {} };
  for (const el of $$("[data-config^='general.']")) {
    const key = el.dataset.config.split(".")[1];
    out.general[key] = el.type === "checkbox" ? el.checked : el.value;
  }
  return out;
}

function collectTelegram() {
  const out = { telegram: {} };
  for (const el of $$("[data-config^='telegram.']")) {
    const key = el.dataset.config.split(".")[1];
    if (key === "bot_token" && !el.value) continue; // don't overwrite with empty
    out.telegram[key] = el.type === "checkbox" ? el.checked : el.value;
  }
  return out;
}

function collectSilentHours() {
  const out = { silent_hours: {} };
  const enabled = $("[data-config='silent_hours.enabled']").checked;
  out.silent_hours.enabled = enabled;

  for (const el of $$("[data-config-time]")) {
    const base = el.dataset.configTime;
    const [h, m] = el.value.split(":").map(Number);
    const baseKey = base.split(".")[1];
    out.silent_hours[`${baseKey}_hour`] = h;
    out.silent_hours[`${baseKey}_minute`] = m;
  }

  out.silent_hours.days = [...$$("#day-picker button[data-active='true']")]
    .map(b => parseInt(b.dataset.day, 10));

  return out;
}

function collectMonitors() {
  const out = { monitors: {} };
  for (const el of $$("[data-monitor]")) {
    const cat = el.dataset.monitor;
    const key = el.dataset.key;
    if (!out.monitors[cat]) out.monitors[cat] = {};
    out.monitors[cat][key] = el.checked;
  }
  return out;
}

function collectWatchlist() {
  const text = $("[data-list='monitors.process.watchlist']").value;
  const list = text.split("\n").map(s => s.trim()).filter(Boolean);
  return { monitors: { process: { watchlist: list } } };
}

function collectFilesystem() {
  const paths = $("[data-list='monitors.filesystem.watch_paths']").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  const exts = $("[data-list='monitors.filesystem.extensions_watchlist']").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  return {
    monitors: {
      filesystem: {
        watch_paths: paths,
        extensions_watchlist: exts,
      }
    }
  };
}

function collectDatabase() {
  const out = { database: {} };
  for (const el of $$("[data-config^='database.']")) {
    const key = el.dataset.config.split(".")[1];
    if (el.readOnly) continue;
    out.database[key] = el.type === "number" ? parseInt(el.value, 10) : el.value;
  }
  return out;
}

const COLLECTORS = {
  general: collectGeneral,
  telegram: collectTelegram,
  silent_hours: collectSilentHours,
  monitors: collectMonitors,
  watchlist: collectWatchlist,
  filesystem: collectFilesystem,
  database: collectDatabase,
};

// ---- Save -----------------------------------------------------
async function saveSection(section, restart = false) {
  const collector = COLLECTORS[section];
  if (!collector) return;
  try {
    await api("/api/config", {
      method: "PUT",
      body: JSON.stringify(collector()),
    });
    showSaved();
    if (restart) {
      await api("/api/system/restart", { method: "POST" });
      showSaved("monitors restarted");
    }
  } catch (err) {
    showSaved(`error: ${err.message}`, true);
  }
}

function showSaved(msg = "saved", isError = false) {
  const ind = $("#save-indicator");
  ind.textContent = msg;
  ind.classList.toggle("error", isError);
  ind.classList.add("visible");
  clearTimeout(showSaved._t);
  showSaved._t = setTimeout(() => ind.classList.remove("visible"), 2400);
}

// ---- Wire save buttons + test ---------------------------------
for (const btn of $$("[data-save]")) {
  btn.addEventListener("click", () => saveSection(btn.dataset.save));
}
$("#restart-after-save-btn").addEventListener("click", () => saveSection("monitors", true));
$("#test-telegram-btn").addEventListener("click", async () => {
  await saveSection("telegram");
  try {
    await api("/api/alerts/test", { method: "POST" });
    showSaved("test alert queued");
  } catch (err) {
    showSaved(`error: ${err.message}`, true);
  }
});

// ---- Boot -----------------------------------------------------
loadConfig().catch(err => {
  showSaved(`load failed: ${err.message}`, true);
});

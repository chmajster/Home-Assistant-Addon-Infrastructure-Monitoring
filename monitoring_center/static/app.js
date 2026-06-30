const state = {
  monitors: [],
  groups: [],
  monitorTypes: [],
  presets: [],
  summary: null,
  settings: null,
  selectedMonitorId: null,
  websiteQuery: "",
  websiteUniqueOnly: true,
};

const API_BASE = window.location.pathname === "/" ? "" : window.location.pathname.replace(/\/$/, "");
const URL_MONITOR_TYPES = ["http_status", "http_hash", "rest_api"];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  bindNavigation();
  bindForms();
  refreshAll();
  setInterval(refreshAll, 30000);
});

function bindNavigation() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      showView(button.dataset.tab);
      if (button.dataset.tab === "diagnostics") loadDiagnostics();
      if (button.dataset.tab === "history") loadHistory();
    });
  });
  $("#refreshBtn").addEventListener("click", refreshAll);
  $("#themeBtn").addEventListener("click", toggleTheme);
  $("#detailBackBtn").addEventListener("click", () => showView("websites"));
  $("#detailEditBtn").addEventListener("click", () => {
    const monitor = state.monitors.find((item) => item.id === state.selectedMonitorId);
    if (monitor) openMonitorForm(monitor);
  });
  $("#detailCheckBtn").addEventListener("click", async () => {
    if (!state.selectedMonitorId) return;
    await api(`/api/monitors/${state.selectedMonitorId}/check`, { method: "POST" });
    toast("Test monitora zakończony.");
    await refreshAll();
    await showMonitorDetails(state.selectedMonitorId);
  });
  $("#detailSnapshotsBtn").addEventListener("click", () => {
    if (state.selectedMonitorId) showSnapshots(state.selectedMonitorId);
  });
  $$("[data-open-form]").forEach((button) => {
    button.addEventListener("click", () => openMonitorForm({ type: button.dataset.openForm }));
  });
}

function bindForms() {
  $("#monitorForm").addEventListener("submit", saveMonitor);
  $("#testMonitorBtn").addEventListener("click", testMonitorFromForm);
  $("#groupForm").addEventListener("submit", saveGroup);
  $("#monitorTypeSelect").addEventListener("change", () => renderTypeFields($("#monitorTypeSelect").value));
  $("#applyPresetBtn").addEventListener("click", applyPreset);
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#maintenanceForm").addEventListener("submit", saveMaintenanceFromDialog);
  $$("[data-maint-duration]").forEach((button) => {
    button.addEventListener("click", () => applyMaintenanceDuration(Number(button.dataset.maintDuration)));
  });
  $("#maintenanceClearBtn").addEventListener("click", clearMaintenanceFromDialog);
  $("#historyApply").addEventListener("click", loadHistory);
  $("#historyClean").addEventListener("click", async () => {
    await api("/api/history", { method: "DELETE" });
    toast("Stara historia została wyczyszczona zgodnie z retencją.");
    loadHistory();
  });
  $("#exportBtn").addEventListener("click", exportConfig);
  $("#importFile").addEventListener("change", importConfig);
  $("#websiteSearch").addEventListener("input", (event) => {
    state.websiteQuery = event.currentTarget.value.trim().toLowerCase();
    renderMonitorLists();
  });
  $("#websiteUniqueOnly").addEventListener("change", (event) => {
    state.websiteUniqueOnly = event.currentTarget.checked;
    renderMonitorLists();
  });
}

async function refreshAll() {
  const [summary, monitors, groups, settings, monitorTypes, presets] = await Promise.all([
    api("/api/summary"),
    api("/api/monitors"),
    api("/api/groups"),
    api("/api/settings"),
    api("/api/monitor-types"),
    api("/api/presets"),
  ]);
  state.summary = summary;
  state.monitors = monitors;
  state.groups = groups;
  state.settings = settings;
  state.monitorTypes = monitorTypes;
  state.presets = presets;
  renderDashboard();
  renderMonitorTypeOptions();
  renderPresetOptions();
  renderGroupOptions();
  renderMonitorLists();
  renderGroups();
  renderHistoryMonitorOptions();
  renderSettings();
  if ($("#monitorDetail").classList.contains("active") && state.selectedMonitorId) {
    renderMonitorDetailsShell(state.selectedMonitorId);
  }
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = formatApiError(body.detail || message);
    } catch (_) {}
    toast(message, "error");
    throw new Error(message);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function formatApiError(detail) {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
      return `${field ? field + ": " : ""}${item.msg || "Nieprawidlowe dane"}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail || "Wystapil blad");
}

function initTheme() {
  const saved = localStorage.getItem("monitoring-theme") || "light";
  applyTheme(saved);
}

function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(current === "dark" ? "light" : "dark");
}

function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("monitoring-theme", next);
  $("#themeBtn").textContent = next === "dark" ? "Motyw: ciemny" : "Motyw: jasny";
}

function showView(viewId, activeTab = viewId) {
  $$(".view").forEach((view) => view.classList.remove("active"));
  $(`#${viewId}`)?.classList.add("active");
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === activeTab));
}

function renderDashboard() {
  const summary = state.summary || {};
  $("#metricTotal").textContent = summary.total ?? 0;
  $("#metricOnline").textContent = summary.online ?? 0;
  $("#metricOffline").textContent = summary.offline ?? 0;
  $("#metricChanged").textContent = summary.changed_websites ?? 0;
  $("#metricAvg").textContent = summary.avg_response_ms ? `${summary.avg_response_ms} ms` : "-";
  renderList("#recentFailures", summary.recent_failures || [], checkLine);
  renderList("#recentChanges", summary.recent_changes || [], checkLine);
  renderAvailabilityChart();
  renderSlo(summary.slo || {});
}

function renderAvailabilityChart() {
  const root = $("#availabilityChart");
  if (!state.monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów</p>';
    return;
  }
  root.innerHTML = state.monitors.map((monitor) => {
    const down = isSuccessStatus(monitor.status) ? "0%" : "100%";
    return `<div class="bar" style="--down:${down}" title="${escapeHtml(monitor.name)}">
      <strong>${escapeHtml(monitor.name)}</strong><br>${escapeHtml(monitor.status)}
    </div>`;
  }).join("");
}

function renderMonitorLists() {
  renderCards("#deviceList", state.monitors.filter((m) => !["http_status", "http_hash", "ssl_certificate", "rest_api"].includes(m.type)));
  const websites = state.monitors.filter((m) => ["http_status", "http_hash", "ssl_certificate", "rest_api"].includes(m.type));
  renderCards("#websiteList", filterWebsiteMonitors(websites), { details: true, websiteActions: true });
}

function renderMonitorTypeOptions() {
  const options = state.monitorTypes
    .map((type) => `<option value="${type.type}">${escapeHtml(type.label)}</option>`)
    .join("");
  const current = $("#monitorTypeSelect").value;
  $("#monitorTypeSelect").innerHTML = options;
  if (current) $("#monitorTypeSelect").value = current;
  const historyCurrent = $("#historyType").value;
  $("#historyType").innerHTML = '<option value="">Wszystkie</option>' + options;
  $("#historyType").value = historyCurrent;
}

function renderPresetOptions() {
  $("#presetSelect").innerHTML = '<option value="">Wybierz preset</option>' + state.presets
    .map((preset, index) => `<option value="${index}">${escapeHtml(preset.name)}</option>`)
    .join("");
}

function renderGroupOptions() {
  const current = $("#monitorGroupSelect")?.value || "";
  $("#monitorGroupSelect").innerHTML = '<option value="">Bez grupy</option>' + state.groups
    .map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`)
    .join("");
  $("#monitorGroupSelect").value = current;
}

function renderSlo(slo) {
  const root = $("#sloGrid");
  root.innerHTML = ["24h", "7d", "30d", "90d"].map((key) => {
    const item = slo[key] || {};
    return `<article class="slo-card">
      <strong>${key}</strong>
      <span>${item.uptime_percent ?? "-"}%</span>
      <small>Śr. ${item.avg_response_ms ? item.avg_response_ms + " ms" : "-"} · Incydenty ${item.incidents ?? 0}</small>
    </article>`;
  }).join("");
}

function applyPreset() {
  const index = $("#presetSelect").value;
  if (index === "") {
    toast("Wybierz preset.");
    return;
  }
  const preset = JSON.parse(JSON.stringify(state.presets[Number(index)]));
  openMonitorForm({ ...preset, enabled: true });
}

function renderTypeFields(type) {
  $$(".type-options").forEach((node) => node.classList.add("hidden"));
  const targetLabels = {
    ping_host: "IP lub hostname",
    tcp_port: "Host:port",
    http_status: "Adres URL",
    http_hash: "Adres URL",
    dns_lookup: "Domena",
    ssl_certificate: "Host lub host:port",
    rest_api: "Endpoint REST API",
    ha_entity: "Entity ID",
    mqtt_monitor: "Broker host:port",
  };
  $("#targetLabel").firstChild.textContent = targetLabels[type] || "Cel";
  if (type === "tcp_port") $("#tcpOptions").classList.remove("hidden");
  if (["http_status", "http_hash", "rest_api"].includes(type)) $("#httpOptions").classList.remove("hidden");
  if (type === "http_hash") $("#websiteOptions").classList.remove("hidden");
  if (type === "dns_lookup") $("#dnsOptions").classList.remove("hidden");
  if (type === "ssl_certificate") $("#sslOptions").classList.remove("hidden");
  if (type === "rest_api") $("#restOptions").classList.remove("hidden");
  if (type === "ha_entity") $("#haEntityOptions").classList.remove("hidden");
  if (type === "mqtt_monitor") $("#mqttOptions").classList.remove("hidden");
}

function buildMonitorConfig(form, type) {
  const config = {};
  if (["http_status", "http_hash", "rest_api"].includes(type) && form.elements.expected_status_codes.value.trim()) {
    config.expected_status_codes = form.elements.expected_status_codes.value.split(",").map((item) => Number(item.trim())).filter(Boolean);
  }
  if (type === "tcp_port") {
    if (form.elements.tcp_host.value.trim()) config.host = form.elements.tcp_host.value.trim();
    if (form.elements.tcp_port.value) config.port = Number(form.elements.tcp_port.value);
  }
  if (type === "http_hash") {
    if (form.elements.css_selector.value.trim()) config.css_selector = form.elements.css_selector.value.trim();
    if (form.elements.max_page_size_mb.value) config.max_page_size_mb = Number(form.elements.max_page_size_mb.value);
    config.ignore_patterns = form.elements.ignore_patterns.value.split("\n").map((line) => line.trim()).filter(Boolean);
  }
  if (type === "dns_lookup") {
    config.record_type = form.elements.record_type.value;
  }
  if (type === "ssl_certificate") {
    if (form.elements.ssl_host.value.trim()) config.host = form.elements.ssl_host.value.trim();
    if (form.elements.ssl_port.value) config.port = Number(form.elements.ssl_port.value);
    if (form.elements.warning_days.value) config.warning_days = Number(form.elements.warning_days.value);
    if (form.elements.error_days.value) config.error_days = Number(form.elements.error_days.value);
  }
  if (type === "rest_api") {
    if (form.elements.json_path.value.trim()) config.json_path = form.elements.json_path.value.trim();
    if (form.elements.expected_value.value.trim()) config.expected_value = form.elements.expected_value.value.trim();
  }
  if (type === "ha_entity") {
    config.alert_states = form.elements.alert_states.value.split(",").map((item) => item.trim()).filter(Boolean);
  }
  if (type === "mqtt_monitor") {
    if (form.elements.mqtt_host.value.trim()) config.host = form.elements.mqtt_host.value.trim();
    if (form.elements.mqtt_port.value) config.port = Number(form.elements.mqtt_port.value);
    if (form.elements.topic.value.trim()) config.topic = form.elements.topic.value.trim();
    if (form.elements.topic_timeout_seconds.value) config.topic_timeout_seconds = Number(form.elements.topic_timeout_seconds.value);
  }
  return config;
}

function filterWebsiteMonitors(monitors) {
  const filtered = state.websiteQuery
    ? monitors.filter((monitor) => {
        const haystack = `${monitor.name} ${monitor.target} ${typeLabel(monitor.type)}`.toLowerCase();
        return haystack.includes(state.websiteQuery);
      })
    : monitors;
  if (!state.websiteUniqueOnly) return filtered;
  const seen = new Set();
  return filtered.filter((monitor) => {
    const key = normalizeUrlKey(monitor.target);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function normalizeUrlKey(target) {
  try {
    const url = new URL(target);
    if (!["http:", "https:"].includes(url.protocol)) throw new Error("Not an HTTP URL");
    const isDefaultPort = (url.protocol === "http:" && url.port === "80") || (url.protocol === "https:" && url.port === "443");
    const port = url.port && !isDefaultPort ? `:${url.port}` : "";
    return `${url.protocol}//${url.hostname.toLowerCase().replace(/\.$/, "")}${port}${url.pathname || "/"}${url.search}`;
  } catch (_) {
    return String(target || "").trim().toLowerCase();
  }
}

function renderCards(selector, monitors, options = {}) {
  const root = $(selector);
  if (!monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów w tej sekcji.</p>';
    return;
  }
  root.innerHTML = monitors.map((monitor) => `
    <article class="card ${options.details ? "clickable-card" : ""} ${monitor.enabled ? "" : "inactive"}" data-card-id="${monitor.id}" tabindex="${options.details ? "0" : "-1"}">
      <div class="card-head">
        <div>
          <h2>${escapeHtml(monitor.name)}</h2>
          <p>${escapeHtml(monitor.target)}</p>
        </div>
        <span class="badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status) : "nieaktywny"}</span>
      </div>
      <div class="meta">
        <span>Interwał: ${monitor.interval_seconds}s</span>
        <span>Aktywny: ${monitor.enabled ? "tak" : "nie"}</span>
        <span>Typ: ${escapeHtml(typeLabel(monitor.type))}</span>
        <span>Grupa: ${escapeHtml(monitor.group_name || "Bez grupy")}</span>
        <span>Maintenance: ${monitor.maintenance_active ? "aktywny do " + formatDate(monitor.maintenance_until || monitor.group_maintenance_until) : "-"}</span>
        <span>Odpowiedź: ${monitor.last_response_ms ? Number(monitor.last_response_ms).toFixed(1) + " ms" : "-"}</span>
        <span>HTTP: ${monitor.last_http_status || "-"}</span>
        <span>Ostatni test: ${formatDate(monitor.last_checked_at)}</span>
        ${monitor.type === "http_hash" ? `<span>Suma WWW: ${hashHtml(monitor.last_content_hash)}</span>` : ""}
        <span>Błąd: ${escapeHtml(monitor.last_error || "-")}</span>
      </div>
      <div class="actions">
        ${renderCardActions(monitor, options)}
      </div>
    </article>
  `).join("");
  $$("[data-action]", root).forEach((button) => button.addEventListener("click", handleCardAction));
  if (options.details) {
    $$("[data-card-id]", root).forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest("button")) return;
        showMonitorDetails(Number(card.dataset.cardId));
      });
      card.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        showMonitorDetails(Number(card.dataset.cardId));
      });
    });
  }
}

function renderCardActions(monitor, options = {}) {
  if (options.websiteActions) {
    return `
      <button data-action="check" data-id="${monitor.id}">Test</button>
      <button data-action="edit" data-id="${monitor.id}">Edytuj</button>
      <button data-action="maintenance" data-id="${monitor.id}">Serwis</button>
      <button data-action="toggle-enabled" data-id="${monitor.id}">${monitor.enabled ? "Wyłącz monitoring" : "Włącz monitoring"}</button>
      ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
      <button data-action="delete" data-id="${monitor.id}" class="danger-action">Usuń</button>
    `;
  }
  return `
    <button data-action="check" data-id="${monitor.id}">Test</button>
    <button data-action="toggle-enabled" data-id="${monitor.id}">${monitor.enabled ? "Wyłącz" : "Włącz"}</button>
    <button data-action="edit" data-id="${monitor.id}">Edytuj</button>
    <button data-action="maint-30" data-id="${monitor.id}">Serwis 30m</button>
    <button data-action="maint-120" data-id="${monitor.id}">Serwis 2h</button>
    <button data-action="maint-manual" data-id="${monitor.id}">Serwis ręczny</button>
    ${monitor.maintenance_until ? `<button data-action="maint-clear" data-id="${monitor.id}">Wyłącz serwis</button>` : ""}
    ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
    <button data-action="delete" data-id="${monitor.id}">Usuń</button>
  `;
}

async function handleCardAction(event) {
  const id = Number(event.currentTarget.dataset.id);
  const action = event.currentTarget.dataset.action;
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) return;
  if (action === "check") {
    await api(`/api/monitors/${id}/check`, { method: "POST" });
    toast("Test monitora zakończony.");
    refreshAll();
  }
  if (action === "toggle-enabled") {
    await api(`/api/monitors/${id}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: !monitor.enabled }),
    });
    toast("Wykonano poprawnie");
    refreshAll();
  }
  if (action === "edit") openMonitorForm(monitor);
  if (action === "maintenance") openMaintenanceDialog(monitor);
  if (action === "maint-30") await setMonitorMaintenance(id, 30);
  if (action === "maint-120") await setMonitorMaintenance(id, 120);
  if (action === "maint-manual") await setMonitorMaintenance(id, null);
  if (action === "maint-clear") await clearMonitorMaintenance(id);
  if (action === "delete" && confirm(`Usunąć monitor "${monitor.name}"?`)) {
    await api(`/api/monitors/${id}`, { method: "DELETE" });
    toast("Monitor usunięty.");
    refreshAll();
  }
  if (action === "snapshots") showSnapshots(id);
}

async function showMonitorDetails(id) {
  state.selectedMonitorId = id;
  showView("monitorDetail", "websites");
  renderMonitorDetailsShell(id);
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) return;
  const [slo, history, snapshots] = await Promise.all([
    api(`/api/slo?monitor_id=${id}`),
    api(`/api/history?monitor_id=${id}&limit=80`),
    monitor.type === "http_hash" ? api(`/api/monitors/${id}/snapshots`) : Promise.resolve([]),
  ]);
  renderDetailSlo(slo);
  renderDetailHistory(history);
  renderDetailSnapshots(snapshots);
}

function renderMonitorDetailsShell(id) {
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) {
    $("#detailTitle").textContent = "Monitor";
    $("#detailSubtitle").textContent = "Nie znaleziono monitora.";
    return;
  }
  $("#detailTitle").textContent = monitor.name;
  $("#detailSubtitle").textContent = `${typeLabel(monitor.type)} · ${monitor.target}`;
  $("#detailMetrics").innerHTML = [
    ["Status", `<span class="badge ${badgeClass(monitor.status)}">${escapeHtml(monitor.status)}</span>`],
    ["Odpowiedź", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
    ["HTTP", monitor.last_http_status || "-"],
    ["Ostatni test", formatDate(monitor.last_checked_at)],
    ["Ostatnia zmiana", formatDate(monitor.last_changed_at)],
    ...(monitor.type === "http_hash" ? [["Suma WWW", hashHtml(monitor.last_content_hash)]] : []),
  ].map(([label, value]) => `<article><span>${value}</span><small>${label}</small></article>`).join("");
  const detailData = {
    "Nazwa": monitor.name,
    "Cel": monitor.target,
    "Typ": typeLabel(monitor.type),
    "Grupa": monitor.group_name || "Bez grupy",
    "Interwał": `${monitor.interval_seconds}s`,
    "Aktywny": monitor.enabled ? "tak" : "nie",
    "Maintenance": monitor.maintenance_active ? `aktywny do ${formatDate(monitor.maintenance_until || monitor.group_maintenance_until)}` : "-",
    ...(monitor.type === "http_hash" ? {
      "Data sprawdzenia WWW": formatDate(monitor.last_checked_at),
      "Suma kontrolna WWW": monitor.last_content_hash || "-",
    } : {}),
    "Błąd": monitor.last_error || "-",
    "Konfiguracja": JSON.stringify(monitor.config || {}, null, 2),
  };
  $("#detailData").innerHTML = Object.entries(detailData)
    .map(([key, value]) => `<dt>${key}</dt><dd>${escapeHtml(String(value ?? "-"))}</dd>`)
    .join("");
}

function renderDetailSlo(slo) {
  $("#detailSlo").innerHTML = ["24h", "7d", "30d", "90d"].map((key) => {
    const item = slo[key] || {};
    return `<article class="slo-card">
      <strong>${key}</strong>
      <span>${item.uptime_percent ?? "-"}%</span>
      <small>Śr. ${item.avg_response_ms ? item.avg_response_ms + " ms" : "-"} · Incydenty ${item.incidents ?? 0} · Testy ${item.checks ?? 0}</small>
    </article>`;
  }).join("");
}

function renderDetailHistory(rows) {
  const body = $("#detailHistoryRows");
  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">Brak historii odpowiedzi.</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => {
    const details = parseDetails(row.details_json);
    const detailText = [
      details.final_url ? `URL: ${details.final_url}` : "",
      details.bytes ? `Rozmiar: ${details.bytes} B` : "",
      details.expected_status_codes ? `Oczekiwane: ${details.expected_status_codes.join(", ")}` : "",
      details.response_hash ? `Hash: ${String(details.response_hash).slice(0, 12)}` : "",
    ].filter(Boolean).join(" · ");
    return `<tr>
      <td>${formatDate(row.checked_at)}</td>
      <td><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span></td>
      <td>${row.response_ms ? Number(row.response_ms).toFixed(1) + " ms" : "-"}</td>
      <td>${row.http_status || "-"}</td>
      <td>${row.content_changed ? "tak" : "nie"}</td>
      <td>${hashHtml(row.content_hash || details.current_hash)}</td>
      <td>${escapeHtml(detailText || "-")}</td>
      <td>${escapeHtml(row.error || "-")}</td>
    </tr>`;
  }).join("");
}

function renderDetailSnapshots(snapshots) {
  const root = $("#detailSnapshots");
  if (!snapshots.length) {
    root.classList.add("empty");
    root.innerHTML = "Brak zapisanych zmian.";
    return;
  }
  root.classList.remove("empty");
  root.innerHTML = snapshots.slice(0, 8).map((snapshot) => `
    <div class="list-item">
      <strong>${formatDate(snapshot.created_at)}</strong>
      <small>${escapeHtml(snapshot.content_hash || "-")}</small>
      <span>${escapeHtml((snapshot.raw_excerpt || snapshot.diff || "").slice(0, 220))}</span>
    </div>
  `).join("");
}

function parseDetails(value) {
  try {
    return value ? JSON.parse(value) : {};
  } catch (_) {
    return {};
  }
}

function renderGroups() {
  const root = $("#groupList");
  if (!state.groups.length) {
    root.innerHTML = '<p class="empty">Brak grup.</p>';
    return;
  }
  root.innerHTML = state.groups.map((group) => `
    <article class="card">
      <div class="card-head">
        <div>
          <h2><span class="swatch" style="background:${escapeHtml(group.color)}"></span>${escapeHtml(group.name)}</h2>
          <p>${escapeHtml(group.description || "")}</p>
        </div>
        <span class="badge ${badgeClass(group.status)}">${escapeHtml(group.status)}</span>
      </div>
      <div class="meta">
        <span>Monitory: ${group.monitor_count}</span>
        <span>Online: ${group.online}</span>
        <span>Offline: ${group.offline}</span>
        <span>Maintenance: ${group.maintenance_active ? "aktywny do " + formatDate(group.maintenance_until) : "-"}</span>
      </div>
      <div class="slo-mini">${renderSloMini(group.slo || {})}</div>
      <div class="actions">
        <button data-group-action="edit" data-id="${group.id}">Edytuj</button>
        <button data-group-action="maint-30" data-id="${group.id}">Serwis 30m</button>
        <button data-group-action="maint-120" data-id="${group.id}">Serwis 2h</button>
        <button data-group-action="maint-manual" data-id="${group.id}">Serwis ręczny</button>
        ${group.maintenance_active ? `<button data-group-action="maint-clear" data-id="${group.id}">Wyłącz serwis</button>` : ""}
        <button data-group-action="delete" data-id="${group.id}">Usuń</button>
      </div>
    </article>
  `).join("");
  $$("[data-group-action]", root).forEach((button) => button.addEventListener("click", handleGroupAction));
}

function renderSloMini(slo) {
  return ["24h", "7d", "30d", "90d"].map((key) => {
    const item = slo[key] || {};
    return `<span><strong>${key}</strong> ${item.uptime_percent ?? "-"}% · ${item.incidents ?? 0} inc.</span>`;
  }).join("");
}

async function handleGroupAction(event) {
  const id = Number(event.currentTarget.dataset.id);
  const action = event.currentTarget.dataset.groupAction;
  const group = state.groups.find((item) => item.id === id);
  if (action === "edit") {
    const form = $("#groupForm");
    form.elements.id.value = group.id;
    form.elements.name.value = group.name;
    form.elements.description.value = group.description || "";
    form.elements.color.value = group.color || "#0f766e";
    document.querySelector("#groups").scrollIntoView({ behavior: "smooth" });
  }
  if (action === "maint-30") await setGroupMaintenance(id, 30);
  if (action === "maint-120") await setGroupMaintenance(id, 120);
  if (action === "maint-manual") await setGroupMaintenance(id, null);
  if (action === "maint-clear") await clearGroupMaintenance(id);
  if (action === "delete" && confirm(`Usunąć grupę "${group.name}"? Monitory zostaną bez grupy.`)) {
    await api(`/api/groups/${id}`, { method: "DELETE" });
    toast("Grupa usunięta.");
    refreshAll();
  }
}

async function saveGroup(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const payload = {
    name: form.elements.name.value.trim(),
    description: form.elements.description.value.trim(),
    color: form.elements.color.value,
  };
  await api(id ? `/api/groups/${id}` : "/api/groups", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  form.reset();
  form.elements.color.value = "#0f766e";
  toast("Grupa zapisana.");
  refreshAll();
}

function openMaintenanceDialog(monitor) {
  const form = $("#maintenanceForm");
  form.reset();
  form.elements.id.value = monitor.id;
  form.elements.until.value = toDatetimeLocalValue(monitor.maintenance_until);
  form.elements.reason.value = monitor.maintenance_reason || "";
  $("#maintenanceDialogTitle").textContent = `Serwis: ${monitor.name}`;
  $("#maintenanceTarget").textContent = monitor.target;
  $("#maintenanceClearBtn").hidden = !monitor.maintenance_until;
  $("#maintenanceDialog").showModal();
}

async function saveMaintenanceFromDialog(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = Number(form.elements.id.value);
  const untilValue = form.elements.until.value;
  if (!untilValue) {
    toast("Podaj datę zakończenia serwisu.", "error");
    return;
  }
  const until = new Date(untilValue);
  if (Number.isNaN(until.getTime())) {
    toast("Nieprawidłowa data zakończenia serwisu.", "error");
    return;
  }
  if (until <= new Date()) {
    toast("Data zakończenia serwisu musi być w przyszłości.", "error");
    return;
  }
  await setMonitorMaintenanceUntil(id, until.toISOString(), form.elements.reason.value.trim());
  $("#maintenanceDialog").close();
}

async function applyMaintenanceDuration(minutes) {
  const form = $("#maintenanceForm");
  const id = Number(form.elements.id.value);
  if (!id) return;
  await setMonitorMaintenance(id, minutes);
  $("#maintenanceDialog").close();
}

async function clearMaintenanceFromDialog() {
  const form = $("#maintenanceForm");
  const id = Number(form.elements.id.value);
  if (!id) return;
  await clearMonitorMaintenance(id);
  $("#maintenanceDialog").close();
}

async function setMonitorMaintenance(id, minutes) {
  await api(`/api/monitors/${id}/maintenance`, {
    method: "POST",
    body: JSON.stringify({
      duration_minutes: minutes,
      reason: minutes ? `Tryb serwisowy ${minutes} min` : "Tryb serwisowy ręczny",
    }),
  });
  toast("Tryb serwisowy monitora włączony.");
  refreshAll();
}

async function setMonitorMaintenanceUntil(id, until, reason) {
  await api(`/api/monitors/${id}/maintenance`, {
    method: "POST",
    body: JSON.stringify({
      until,
      reason: reason || `Tryb serwisowy do ${formatDate(until)}`,
    }),
  });
  toast("Tryb serwisowy monitora włączony.");
  refreshAll();
}

async function clearMonitorMaintenance(id) {
  await api(`/api/monitors/${id}/maintenance`, { method: "DELETE" });
  toast("Tryb serwisowy monitora wyłączony.");
  refreshAll();
}

async function setGroupMaintenance(id, minutes) {
  await api(`/api/groups/${id}/maintenance`, {
    method: "POST",
    body: JSON.stringify({
      duration_minutes: minutes,
      reason: minutes ? `Tryb serwisowy ${minutes} min` : "Tryb serwisowy ręczny",
    }),
  });
  toast("Tryb serwisowy grupy włączony.");
  refreshAll();
}

async function clearGroupMaintenance(id) {
  await api(`/api/groups/${id}/maintenance`, { method: "DELETE" });
  toast("Tryb serwisowy grupy wyłączony.");
  refreshAll();
}

function openMonitorForm(monitor) {
  const form = $("#monitorForm");
  form.reset();
  form.elements.id.value = monitor.id || "";
  form.elements.type.value = monitor.type || "ping_host";
  form.elements.name.value = monitor.name || "";
  form.elements.target.value = monitor.target || "";
  form.elements.group_id.value = monitor.group_id || "";
  form.elements.interval_seconds.value = monitor.interval_seconds || "";
  form.elements.enabled.checked = monitor.enabled !== false;
  form.elements.test_on_save.checked = !monitor.id;
  form.elements.timeout_minutes.value = getTimeoutMinutes(monitor.config);
  form.elements.expected_status_codes.value = (monitor.config?.expected_status_codes || []).join(",");
  form.elements.tcp_host.value = monitor.config?.host || "";
  form.elements.tcp_port.value = monitor.config?.port || "";
  form.elements.css_selector.value = monitor.config?.css_selector || "";
  form.elements.ignore_patterns.value = (monitor.config?.ignore_patterns || []).join("\n");
  form.elements.max_page_size_mb.value = getMaxPageSizeMb(monitor.config);
  form.elements.record_type.value = monitor.config?.record_type || "A";
  form.elements.ssl_host.value = monitor.config?.host || "";
  form.elements.ssl_port.value = monitor.config?.port || "";
  form.elements.warning_days.value = monitor.config?.warning_days || "";
  form.elements.error_days.value = monitor.config?.error_days || "";
  form.elements.json_path.value = monitor.config?.json_path || "";
  form.elements.expected_value.value = monitor.config?.expected_value ?? "";
  form.elements.alert_states.value = (monitor.config?.alert_states || []).join(",");
  form.elements.mqtt_host.value = monitor.config?.host || "";
  form.elements.mqtt_port.value = monitor.config?.port || "";
  form.elements.topic.value = monitor.config?.topic || "";
  form.elements.topic_timeout_seconds.value = monitor.config?.topic_timeout_seconds || "";
  renderTestResult(null);
  $("#dialogTitle").textContent = monitor.id ? "Edytuj monitor" : "Dodaj monitor";
  renderTypeFields(form.elements.type.value);
  $("#monitorDialog").showModal();
}

async function saveMonitor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const payload = buildMonitorPayload(form);
  const duplicate = findDuplicateUrlMonitor(payload.target, payload.type, id ? Number(id) : null);
  if (duplicate) {
    toast(`Ten URL jest już monitorowany: ${duplicate.name}`);
    return;
  }
  const path = id ? `/api/monitors/${id}` : "/api/monitors";
  const method = id ? "PUT" : "POST";
  await api(path, { method, body: JSON.stringify(payload) });
  $("#monitorDialog").close();
  toast("Wykonano poprawnie");
  refreshAll();
}

function buildMonitorPayload(form) {
  const type = form.elements.type.value;
  const config = buildMonitorConfig(form, type);
  if (form.elements.timeout_minutes.value) config.timeout_minutes = Number(form.elements.timeout_minutes.value);
  return {
    type,
    name: form.elements.name.value.trim(),
    target: form.elements.target.value.trim(),
    interval_seconds: form.elements.interval_seconds.value ? Number(form.elements.interval_seconds.value) : null,
    group_id: form.elements.group_id.value ? Number(form.elements.group_id.value) : null,
    enabled: form.elements.enabled.checked,
    test_on_save: form.elements.test_on_save.checked,
    config,
  };
}

async function testMonitorFromForm() {
  const form = $("#monitorForm");
  if (!form.reportValidity()) return;
  const payload = buildMonitorPayload(form);
  renderTestResult({ loading: true });
  try {
    const result = await api("/api/monitors/test", {
      method: "POST",
      body: JSON.stringify({ ...payload, test_on_save: false }),
    });
    renderTestResult(result);
  } catch (error) {
    renderTestResult({ status: "error", success: false, error: error.message });
  }
}

function renderTestResult(result) {
  const node = $("#monitorTestResult");
  if (!node) return;
  if (!result) {
    node.className = "test-result hidden";
    node.textContent = "";
    return;
  }
  if (result.loading) {
    node.className = "test-result";
    node.textContent = "Testowanie...";
    return;
  }
  const parts = [
    `Status: ${result.status || "-"}`,
    `HTTP: ${result.http_status || "-"}`,
    `Czas: ${result.response_ms ? Number(result.response_ms).toFixed(1) + " ms" : "-"}`,
    `Data: ${formatDate(result.checked_at)}`,
    result.content_hash ? `Suma WWW: ${result.content_hash}` : "",
    result.error ? `Błąd: ${result.error}` : "",
  ].filter(Boolean);
  node.className = `test-result ${result.success ? "ok" : "bad"}`;
  node.textContent = parts.join(" | ");
}

function getTimeoutMinutes(config = {}) {
  if (config.timeout_minutes !== undefined && config.timeout_minutes !== null && config.timeout_minutes !== "") {
    return Number(config.timeout_minutes);
  }
  if (config.timeout_seconds !== undefined && config.timeout_seconds !== null && config.timeout_seconds !== "") {
    return Number(config.timeout_seconds) / 60;
  }
  return "";
}

function getMaxPageSizeMb(config = {}) {
  if (config.max_page_size_mb !== undefined && config.max_page_size_mb !== null && config.max_page_size_mb !== "") {
    return Number(config.max_page_size_mb);
  }
  if (config.max_page_size_kb !== undefined && config.max_page_size_kb !== null && config.max_page_size_kb !== "") {
    return Number(config.max_page_size_kb) / 1024;
  }
  return "";
}

function findDuplicateUrlMonitor(target, type, currentId) {
  if (!URL_MONITOR_TYPES.includes(type)) return null;
  const key = normalizeUrlKey(target);
  return state.monitors.find((monitor) => (
    monitor.id !== currentId
    && URL_MONITOR_TYPES.includes(monitor.type)
    && normalizeUrlKey(monitor.target) === key
  ));
}

async function showSnapshots(id) {
  const snapshots = await api(`/api/monitors/${id}/snapshots`);
  $("#snapshotDiff").textContent = snapshots[0]?.diff || snapshots[0]?.raw_excerpt || "Brak zapisanych zmian.";
  $("#snapshotDialog").showModal();
}

function renderHistoryMonitorOptions() {
  const current = $("#historyMonitor").value;
  $("#historyMonitor").innerHTML = '<option value="">Wszystkie</option>' + state.monitors
    .map((monitor) => `<option value="${monitor.id}">${escapeHtml(monitor.name)}</option>`)
    .join("");
  $("#historyMonitor").value = current;
}

async function loadHistory() {
  const params = new URLSearchParams();
  const mapping = [
    ["monitor_id", $("#historyMonitor").value],
    ["type", $("#historyType").value],
    ["status", $("#historyStatus").value.trim()],
    ["from_date", toIso($("#historyFrom").value)],
    ["to_date", toIso($("#historyTo").value)],
  ];
  mapping.forEach(([key, value]) => value && params.set(key, value));
  const rows = await api(`/api/history?${params.toString()}`);
  $("#historyRows").innerHTML = rows.map((row) => `
    <tr>
      <td>${formatDate(row.checked_at)}</td>
      <td>${escapeHtml(row.monitor_name)}<br><small>${escapeHtml(row.target)}</small></td>
      <td><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span></td>
      <td>${row.response_ms ? Number(row.response_ms).toFixed(1) + " ms" : "-"}</td>
      <td>${row.http_status || "-"}</td>
      <td>${hashHtml(row.content_hash)}</td>
      <td>${row.packet_loss ?? "-"}</td>
      <td>${escapeHtml(row.error || "-")}</td>
    </tr>
  `).join("");
}

function renderSettings() {
  if (!state.settings) return;
  const form = $("#settingsForm");
  if (state.settings.default_timeout_minutes === undefined && state.settings.request_timeout_seconds !== undefined) {
    state.settings.default_timeout_minutes = Number(state.settings.request_timeout_seconds) / 60;
  }
  if (state.settings.max_page_size_mb === undefined && state.settings.max_page_size_kb !== undefined) {
    state.settings.max_page_size_mb = Number(state.settings.max_page_size_kb) / 1024;
  }
  Object.entries(state.settings).forEach(([key, value]) => {
    if (!form.elements[key]) return;
    if (form.elements[key].type === "checkbox") form.elements[key].checked = Boolean(value);
    else form.elements[key].value = value;
  });
}

async function saveSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    retention_days: Number(form.elements.retention_days.value),
    default_timeout_minutes: Number(form.elements.default_timeout_minutes.value),
    max_page_size_mb: Number(form.elements.max_page_size_mb.value),
    block_private_networks: form.elements.block_private_networks.checked,
    publish_home_assistant_entities: form.elements.publish_home_assistant_entities.checked,
    publish_home_assistant_events: form.elements.publish_home_assistant_events.checked,
    entity_prefix: form.elements.entity_prefix.value.trim(),
  };
  state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
  toast("Wykonano poprawnie");
}

function exportConfig() {
  const data = {
    exported_at: new Date().toISOString(),
    settings: state.settings,
    groups: state.groups.map(({ id, created_at, updated_at, status, monitor_count, online, offline, slo, maintenance_active, ...group }) => group),
    monitors: state.monitors.map(({ id, created_at, updated_at, ...monitor }) => monitor),
  };
  $("#exportBox").value = JSON.stringify(data, null, 2);
}

async function importConfig(event) {
  const file = event.target.files[0];
  if (!file) return;
  const data = JSON.parse(await file.text());
  if (data.settings) await api("/api/settings", { method: "PUT", body: JSON.stringify(normalizeImportedSettings(data.settings)) });
  const importedGroups = {};
  for (const group of data.groups || []) {
    const savedGroup = await api("/api/groups", {
      method: "POST",
      body: JSON.stringify(group),
    });
    importedGroups[savedGroup.name] = savedGroup.id;
  }
  for (const monitor of data.monitors || []) {
    const mappedGroupId = monitor.group_name ? importedGroups[monitor.group_name] : monitor.group_id;
    await api("/api/monitors", {
      method: "POST",
      body: JSON.stringify({ ...monitor, group_id: mappedGroupId || null, test_on_save: false }),
    });
  }
  toast("Import zakończony.");
  refreshAll();
  event.target.value = "";
}

function normalizeImportedSettings(settings) {
  const normalized = { ...settings };
  if (normalized.default_timeout_minutes === undefined && normalized.request_timeout_seconds !== undefined) {
    normalized.default_timeout_minutes = Number(normalized.request_timeout_seconds) / 60;
  }
  if (normalized.max_page_size_mb === undefined && normalized.max_page_size_kb !== undefined) {
    normalized.max_page_size_mb = Number(normalized.max_page_size_kb) / 1024;
  }
  delete normalized.request_timeout_seconds;
  delete normalized.ping_timeout_seconds;
  delete normalized.max_page_size_kb;
  return normalized;
}

async function loadDiagnostics() {
  const [diagnostics, events, logs] = await Promise.all([
    api("/api/diagnostics"),
    api("/api/events"),
    api("/api/logs"),
  ]);
  $("#diagnosticsData").innerHTML = Object.entries({
    Wersja: diagnostics.version,
    "Status bazy": diagnostics.database_exists ? "OK" : "Brak",
    "Rozmiar bazy": `${diagnostics.database_size_bytes} B`,
    "Liczba monitorów": diagnostics.monitor_count,
    "Ostatni test": formatDate(diagnostics.last_check),
    "Kolejka zadań": diagnostics.running_jobs?.join(", ") || "-",
    "Plik logu": diagnostics.log_file,
  }).map(([key, value]) => `<dt>${key}</dt><dd>${escapeHtml(String(value ?? "-"))}</dd>`).join("");
  renderList("#eventsList", events, (event) => `
    <div class="list-item">
      <strong>${escapeHtml(event.event_type)}</strong>
      <small>${formatDate(event.created_at)} · HA: ${event.delivered_to_ha ? "tak" : "nie"}</small>
    </div>
  `);
  $("#logsBox").textContent = logs || "Brak logów.";
}

function renderList(selector, items, renderer) {
  const root = $(selector);
  if (!items.length) {
    root.classList.add("empty");
    root.innerHTML = "Brak danych";
    return;
  }
  root.classList.remove("empty");
  root.innerHTML = items.map(renderer).join("");
}

function checkLine(row) {
  return `
    <div class="list-item">
      <strong>${escapeHtml(row.monitor_name)}</strong>
      <small>${formatDate(row.checked_at)} · ${escapeHtml(row.status)} · ${row.response_ms ? Number(row.response_ms).toFixed(1) + " ms" : "-"}</small>
      ${row.error ? `<span>${escapeHtml(row.error)}</span>` : ""}
    </div>
  `;
}

function badgeClass(status) {
  if (isSuccessStatus(status)) return "ok";
  if (["offline", "error"].includes(status)) return "bad";
  if (["closed", "timeout"].includes(status)) return "bad";
  return "unknown";
}

function typeLabel(type) {
  return state.monitorTypes.find((item) => item.type === type)?.label || type;
}

function isSuccessStatus(status) {
  return ["online", "ok", "open", "warning"].includes(status);
}

function formatDate(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function toIso(value) {
  return value ? new Date(value).toISOString().replace(".000Z", "+00:00") : "";
}

function toDatetimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
}

function hashHtml(value) {
  if (!value) return "-";
  const full = String(value);
  return `<code title="${escapeHtml(full)}">${escapeHtml(full.slice(0, 16))}</code>`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

let toastTimer;
function toast(message, type = "success") {
  const node = $("#toast");
  node.textContent = message;
  node.classList.toggle("error", type === "error");
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    node.classList.remove("show");
    node.classList.remove("error");
  }, 3800);
}

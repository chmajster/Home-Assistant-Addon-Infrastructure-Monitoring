const state = {
  monitors: [],
  groups: [],
  monitorTypes: [],
  presets: [],
  summary: null,
  settings: null,
  selectedMonitorId: null,
  currentTest: null,
  monitorQuery: "",
  monitorTypeFilter: "all",
  monitorStatusFilter: "all",
  monitorGroupFilter: "all",
  monitorSort: "name",
  monitorView: "cards",
  dashboardTypeFilter: "all",
  lastRefreshedAt: null,
};

const API_BASE = window.location.pathname === "/" ? "" : window.location.pathname.replace(/\/$/, "");
const URL_MONITOR_TYPES = ["http_status", "http_hash", "rest_api"];
const WEBSITE_MONITOR_TYPES = URL_MONITOR_TYPES;
const DEVICE_MONITOR_TYPES = ["ping_host", "tcp_port", "mqtt_monitor"];
const HA_MONITOR_TYPES = ["ha_entity"];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
let testRunTimer;

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
  $("#refreshBtn").addEventListener("click", manualRefresh);
  $("#themeBtn").addEventListener("click", toggleTheme);
  $("#toast").addEventListener("click", hideToast);
  $("#detailBackBtn").addEventListener("click", () => showView("devices"));
  $("#testBackBtn").addEventListener("click", backFromMonitorTest);
  $("#testRepeatBtn").addEventListener("click", () => {
    if (state.currentTest?.monitorId) startMonitorTestRun(state.currentTest.monitorId, state.currentTest.returnView);
  });
  $("#testEditBtn").addEventListener("click", () => {
    const monitor = state.monitors.find((item) => item.id === state.currentTest?.monitorId);
    if (monitor) openMonitorForm(monitor);
  });
  $("#detailEditBtn").addEventListener("click", () => {
    const monitor = state.monitors.find((item) => item.id === state.selectedMonitorId);
    if (monitor) openMonitorForm(monitor);
  });
  $("#detailCheckBtn").addEventListener("click", async () => {
    if (!state.selectedMonitorId) return;
    await startMonitorTestRun(state.selectedMonitorId, "monitorDetail");
  });
  $("#detailMonitorSearch").addEventListener("change", goToDetailMonitorFromSearch);
  $("#detailMonitorSearch").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    goToDetailMonitorFromSearch();
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
  $("#monitorSearch").addEventListener("input", (event) => {
    state.monitorQuery = event.currentTarget.value.trim().toLowerCase();
    renderMonitorLists();
  });
  $("#monitorTypeFilter").addEventListener("change", (event) => {
    state.monitorTypeFilter = event.currentTarget.value;
    renderMonitorLists();
  });
  $("#monitorStatusFilter").addEventListener("change", (event) => {
    state.monitorStatusFilter = event.currentTarget.value;
    renderMonitorLists();
  });
  $("#monitorGroupFilter").addEventListener("change", (event) => {
    state.monitorGroupFilter = event.currentTarget.value;
    renderMonitorLists();
  });
  $("#monitorSort").addEventListener("change", (event) => {
    state.monitorSort = event.currentTarget.value;
    renderMonitorLists();
  });
  $("#monitorView").addEventListener("change", (event) => {
    state.monitorView = event.currentTarget.value;
    renderMonitorLists();
  });
  $("#dashboardTypeFilter").addEventListener("change", (event) => {
    state.dashboardTypeFilter = event.currentTarget.value;
    renderDashboard();
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
  state.lastRefreshedAt = new Date().toISOString();
  $("#lastRefreshAt").textContent = `Odświeżono: ${formatDate(state.lastRefreshedAt)}`;
  renderCategoryFilterOptions();
  renderDashboard();
  renderMonitorTypeOptions();
  renderPresetOptions();
  renderGroupOptions();
  renderMonitorLists();
  renderGroups();
  renderHistoryMonitorOptions();
  renderDetailMonitorOptions();
  renderSettings();
  if ($("#monitorDetail").classList.contains("active") && state.selectedMonitorId) {
    renderMonitorDetailsShell(state.selectedMonitorId);
  }
  if ($("#monitorTestRun").classList.contains("active") && state.currentTest?.monitorId) {
    renderMonitorTestRun();
  }
}

async function manualRefresh() {
  await refreshAll();
  toast("Odświeżono dane.");
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
  const monitors = filterMonitorsByCategory(state.monitors, state.dashboardTypeFilter);
  const monitorIds = new Set(monitors.map((monitor) => monitor.id));
  const recentFailures = (summary.recent_failures || []).filter((row) => monitorIds.has(row.monitor_id));
  const recentChanges = (summary.recent_changes || []).filter((row) => monitorIds.has(row.monitor_id));
  const responseTimes = monitors
    .map((monitor) => monitor.last_response_ms)
    .filter((value) => value !== null && value !== undefined);
  const enabled = monitors.filter((monitor) => monitor.enabled);
  const warning = enabled.filter((monitor) => monitor.status === "warning");
  const errors = enabled.filter((monitor) => isErrorStatus(monitor.status));
  const online = enabled.filter((monitor) => isSuccessStatus(monitor.status) && monitor.status !== "warning");
  $("#metricTotal").textContent = monitors.length;
  $("#metricOnline").textContent = online.length;
  $("#metricWarning").textContent = warning.length;
  $("#metricError").textContent = errors.length;
  $("#metricMaintenance").textContent = monitors.filter((monitor) => monitor.maintenance_active).length;
  $("#metricDisabled").textContent = monitors.filter((monitor) => !monitor.enabled).length;
  $("#metricAvg").textContent = responseTimes.length ? `${average(responseTimes).toFixed(1)} ms` : "-";
  renderList("#recentFailures", recentFailures, checkLine);
  renderRecentChanges(recentChanges);
  renderAvailabilityChart();
  renderSlo(summary.slo || {});
}

function renderAvailabilityChart() {
  const root = $("#availabilityChart");
  const monitors = filterMonitorsByCategory(state.monitors, state.dashboardTypeFilter);
  if (!monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów</p>';
    return;
  }
  root.innerHTML = monitors.map((monitor) => {
    const down = isSuccessStatus(monitor.status) ? "0%" : "100%";
    return `<div class="bar clickable-monitor" data-card-id="${monitor.id}" tabindex="0" style="--down:${down}" title="Otwórz szczegóły monitoringu ${escapeHtml(monitor.name)}">
      <strong>${escapeHtml(monitor.name)}</strong><br>${escapeHtml(monitor.status)}
    </div>`;
  }).join("");
  bindMonitorOpeners(root);
}

function renderMonitorLists() {
  const filtered = filterMonitorsForList(state.monitors);
  $("#monitorCountLabel").textContent = `${filtered.length} z ${state.monitors.length}`;
  $("#monitorList").classList.toggle("hidden", state.monitorView !== "cards");
  $("#monitorTableWrap").classList.toggle("hidden", state.monitorView !== "table");
  if (state.monitorView === "table") renderMonitorTable(filtered);
  else renderCards("#monitorList", filtered, { details: true });
}

function renderCategoryFilterOptions() {
  const options = monitorCategoryOptions();
  [
    ["#monitorTypeFilter", "monitorTypeFilter"],
    ["#dashboardTypeFilter", "dashboardTypeFilter"],
  ].forEach(([selector, stateKey]) => {
    const select = $(selector);
    if (!select) return;
    const current = state[stateKey];
    const next = options.some((option) => option.value === current) ? current : "all";
    state[stateKey] = next;
    select.innerHTML = options
      .map((option) => `<option value="${option.value}">${escapeHtml(option.label)}</option>`)
      .join("");
    select.value = next;
  });
}

function monitorCategoryOptions() {
  const options = [
    { value: "all", label: "Wszystkie" },
    { value: "devices", label: "Urządzenia" },
    { value: "websites", label: "WWW" },
    { value: "ha", label: "Home Assistant" },
  ];
  if (state.monitors.some((monitor) => monitorCategory(monitor) === "other")) {
    options.push({ value: "other", label: "Inne" });
  }
  return options;
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

function renderDetailMonitorOptions() {
  const list = $("#detailMonitorOptions");
  if (!list) return;
  list.innerHTML = state.monitors
    .map((monitor) => `<option value="${escapeHtml(detailMonitorValue(monitor))}"></option>`)
    .join("");
  const current = state.monitors.find((monitor) => monitor.id === state.selectedMonitorId);
  if (current && $("#monitorDetail").classList.contains("active")) {
    $("#detailMonitorSearch").value = detailMonitorValue(current);
  }
}

function detailMonitorValue(monitor) {
  return `${monitor.name} | ${typeLabel(monitor.type)} | ${monitor.target}`;
}

function goToDetailMonitorFromSearch() {
  const query = $("#detailMonitorSearch").value.trim().toLowerCase();
  if (!query) return;
  const monitor = state.monitors.find((item) => (
    detailMonitorValue(item).toLowerCase() === query
    || item.name.toLowerCase() === query
    || String(item.id) === query
  )) || state.monitors.find((item) => (
    detailMonitorValue(item).toLowerCase().includes(query)
    || item.target.toLowerCase().includes(query)
  ));
  if (!monitor) {
    toast("Nie znaleziono monitoringu.", "error");
    return;
  }
  showMonitorDetails(monitor.id);
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
  renderMonitorGroupFilterOptions();
}

function renderMonitorGroupFilterOptions() {
  const select = $("#monitorGroupFilter");
  if (!select) return;
  const current = state.monitorGroupFilter;
  select.innerHTML = '<option value="all">Wszystkie</option><option value="none">Bez grupy</option>' + state.groups
    .map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`)
    .join("");
  select.value = Array.from(select.options).some((option) => option.value === current) ? current : "all";
  state.monitorGroupFilter = select.value;
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

function filterMonitorsForList(monitors) {
  const filtered = filterMonitorsByCategory(monitors, state.monitorTypeFilter)
    .filter((monitor) => monitorMatchesStatus(monitor, state.monitorStatusFilter))
    .filter((monitor) => monitorMatchesGroup(monitor, state.monitorGroupFilter))
    .filter((monitor) => {
      if (!state.monitorQuery) return true;
      const config = monitor.config || {};
      const haystack = [
        monitor.name,
        monitor.target,
        monitor.status,
        monitor.group_name,
        typeLabel(monitor.type),
        config.host,
        config.topic,
        config.json_path,
      ].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(state.monitorQuery);
    });
  return sortMonitors(filtered, state.monitorSort);
}

function monitorMatchesStatus(monitor, statusFilter) {
  if (!statusFilter || statusFilter === "all") return true;
  if (statusFilter === "disabled") return !monitor.enabled;
  if (statusFilter === "maintenance") return Boolean(monitor.maintenance_active);
  if (statusFilter === "ok") return monitor.enabled && isSuccessStatus(monitor.status) && monitor.status !== "warning";
  if (statusFilter === "warning") return monitor.enabled && monitor.status === "warning";
  if (statusFilter === "error") return monitor.enabled && isErrorStatus(monitor.status);
  return monitor.status === statusFilter;
}

function monitorMatchesGroup(monitor, groupFilter) {
  if (!groupFilter || groupFilter === "all") return true;
  if (groupFilter === "none") return !monitor.group_id;
  return String(monitor.group_id || "") === String(groupFilter);
}

function sortMonitors(monitors, sortKey) {
  const sorted = [...monitors];
  const text = (value) => String(value || "").toLowerCase();
  const numeric = (value) => value === null || value === undefined || value === "" ? Number.POSITIVE_INFINITY : Number(value);
  const checkedAt = (monitor) => monitor.last_checked_at ? new Date(monitor.last_checked_at).getTime() : 0;
  sorted.sort((a, b) => {
    if (sortKey === "status") return text(a.status).localeCompare(text(b.status)) || text(a.name).localeCompare(text(b.name));
    if (sortKey === "response") return numeric(a.last_response_ms) - numeric(b.last_response_ms);
    if (sortKey === "last_checked") return checkedAt(b) - checkedAt(a);
    if (sortKey === "http") return numeric(a.last_http_status) - numeric(b.last_http_status);
    if (sortKey === "group") return text(a.group_name).localeCompare(text(b.group_name)) || text(a.name).localeCompare(text(b.name));
    return text(a.name).localeCompare(text(b.name));
  });
  return sorted;
}

function renderMonitorTable(monitors) {
  const body = $("#monitorTableRows");
  if (!monitors.length) {
    body.innerHTML = '<tr><td colspan="10" class="empty">Brak monitorów dla wybranych filtrów.</td></tr>';
    return;
  }
  body.innerHTML = monitors.map((monitor) => `
    <tr class="clickable-row" data-card-id="${monitor.id}" tabindex="0" title="Otwórz szczegóły monitoringu">
      <td><span class="badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status) : "wyłączony"}</span></td>
      <td>${escapeHtml(typeLabel(monitor.type))}</td>
      <td><strong>${escapeHtml(monitor.name)}</strong></td>
      <td>${targetHtml(monitor)}</td>
      <td>${monitor.last_http_status || "-"}</td>
      <td>${monitor.last_response_ms ? Number(monitor.last_response_ms).toFixed(1) + " ms" : "-"}</td>
      <td>${monitor.interval_seconds}s</td>
      <td>${escapeHtml(monitor.group_name || "Bez grupy")}</td>
      <td>${formatDate(monitor.last_checked_at)}</td>
      <td>${monitor.maintenance_active ? formatDate(monitor.maintenance_until || monitor.group_maintenance_until) : "-"}</td>
    </tr>
  `).join("");
  bindMonitorOpeners(body);
}

function targetHtml(monitor) {
  const value = monitor.target || "-";
  return `<span class="target-text" title="${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function diagnosticMessage(monitor) {
  const error = String(monitor.last_error || "");
  if (monitor.last_http_status === 403 || error.includes("403")) {
    return "Serwer odrzucił żądanie. Możliwa blokada botów, Cloudflare, WAF albo brak odpowiednich nagłówków.";
  }
  if (/timeout|timed out|czas/i.test(error)) return "Przekroczono czas oczekiwania na odpowiedź.";
  if (/dns|resolve|name/i.test(error)) return "Nie udało się rozwiązać nazwy hosta.";
  return error;
}

function filterMonitorsByCategory(monitors, category) {
  if (!category || category === "all") return monitors;
  return monitors.filter((monitor) => monitorCategory(monitor) === category);
}

function monitorCategory(monitor) {
  if (WEBSITE_MONITOR_TYPES.includes(monitor.type)) return "websites";
  if (DEVICE_MONITOR_TYPES.includes(monitor.type)) return "devices";
  if (HA_MONITOR_TYPES.includes(monitor.type)) return "ha";
  return "other";
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
    <article class="card ${options.details ? "clickable-card" : ""} ${monitor.enabled ? "" : "inactive"}" data-card-id="${monitor.id}" tabindex="${options.details ? "0" : "-1"}" title="Otwórz szczegóły monitoringu">
      <div class="card-head">
        <div>
          <h2>${escapeHtml(monitor.name)}</h2>
          <p>${targetHtml(monitor)}</p>
        </div>
        <span class="badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status) : "nieaktywny"}</span>
      </div>
      <div class="meta">
        ${renderMonitorMeta(monitor)}
      </div>
    </article>
  `).join("");
  if (options.details) {
    bindMonitorOpeners(root);
  }
}

function bindMonitorOpeners(root) {
  $$("[data-card-id]", root).forEach((node) => {
    node.addEventListener("click", () => showMonitorDetails(Number(node.dataset.cardId)));
    node.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      showMonitorDetails(Number(node.dataset.cardId));
    });
  });
}

function renderMonitorMeta(monitor) {
  const config = monitor.config || {};
  const rows = [
    ["Typ", typeLabel(monitor.type)],
    ["Grupa", monitor.group_name || "Bez grupy"],
    ["Interwał", `${monitor.interval_seconds}s`],
    ["Aktywny", monitor.enabled ? "tak" : "nie"],
    ["Serwis", monitor.maintenance_active ? `aktywny do ${formatDate(monitor.maintenance_until || monitor.group_maintenance_until)}` : "-"],
    ["Ostatni test", formatDate(monitor.last_checked_at)],
  ];
  if (monitorCategory(monitor) === "websites") {
    rows.splice(1, 0,
      ["URL", monitor.target],
      ["HTTP status", monitor.last_http_status || "-"],
      ["Czas odpowiedzi", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
      ["Typ monitoringu", typeLabel(monitor.type)],
    );
    if (monitor.type === "http_hash") rows.push(["Suma WWW", hashHtml(monitor.last_content_hash)]);
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  } else if (monitorCategory(monitor) === "devices") {
    rows.splice(1, 0,
      ["IP / host", config.host || monitor.target],
      ["Ping / odpowiedź", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
      ["Status", monitor.enabled ? monitor.status : "nieaktywny"],
    );
    if (config.port) rows.push(["Port", config.port]);
    if (config.topic) rows.push(["Topic", config.topic]);
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  } else if (monitorCategory(monitor) === "ha") {
    rows.splice(1, 0,
      ["Entity ID", monitor.target],
      ["Stan HA", config.last_ha_state || "-"],
      ["Status", monitor.status || "-"],
    );
    rows.push(["Stany alarmowe", (config.alert_states || []).join(", ") || "-"]);
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  } else {
    rows.splice(1, 0,
      ["Cel", monitor.target],
      ["Status", monitor.status || "-"],
      ["Odpowiedź", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
    );
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  }
  return rows.map(([label, value]) => {
    const renderedValue = label === "Suma WWW" ? value : escapeHtml(value);
    return `<span>${escapeHtml(label)}: ${renderedValue}</span>`;
  }).join("");
}

function renderCardActions(monitor) {
  return `
    <details class="action-menu">
      <summary aria-label="Akcje serwisowe monitora ${escapeHtml(monitor.name)}">Serwis</summary>
      <button data-action="maintenance" data-id="${monitor.id}">Ustaw serwis</button>
      ${monitor.maintenance_until ? `<button data-action="maint-clear" data-id="${monitor.id}">Wyłącz serwis</button>` : ""}
    </details>
    <details class="action-menu">
      <summary aria-label="Więcej akcji monitora ${escapeHtml(monitor.name)}">Więcej</summary>
      <button data-action="toggle-enabled" data-id="${monitor.id}">${monitor.enabled ? "Wyłącz monitoring" : "Włącz monitoring"}</button>
      ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
      <button data-action="delete" data-id="${monitor.id}" class="danger-action">Usuń</button>
    </details>
  `;
}

async function handleCardAction(event) {
  const id = Number(event.currentTarget.dataset.id);
  const action = event.currentTarget.dataset.action;
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) return;
  if (action === "check") {
    await startMonitorTestRun(id, monitorReturnView(monitor));
  }
  if (action === "toggle-enabled") {
    await api(`/api/monitors/${id}/${monitor.enabled ? "disable" : "enable"}`, { method: "POST" });
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
    await refreshAll();
    if ($("#monitorDetail").classList.contains("active") && state.selectedMonitorId === id) {
      state.selectedMonitorId = null;
      showView("devices");
    }
  }
  if (action === "snapshots") showSnapshots(id);
}

async function startMonitorTestRun(id, returnView = "devices") {
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) return;
  state.currentTest = {
    monitorId: id,
    returnView,
    returnTab: monitorReturnView(monitor),
    status: "running",
    startedAt: new Date().toISOString(),
    finishedAt: null,
    result: null,
    error: null,
  };
  showView("monitorTestRun", state.currentTest.returnTab);
  renderMonitorTestRun();
  startTestRunTimer();
  try {
    const result = await api(`/api/monitors/${id}/check`, { method: "POST" });
    state.currentTest = {
      ...state.currentTest,
      status: "done",
      finishedAt: new Date().toISOString(),
      result,
    };
    state.monitors = state.monitors.map((item) => item.id === id ? { ...item, ...result } : item);
    await refreshAll();
    toast("Test monitora zakończony.");
  } catch (error) {
    state.currentTest = {
      ...state.currentTest,
      status: "error",
      finishedAt: new Date().toISOString(),
      error: error.message,
    };
  } finally {
    stopTestRunTimer();
    renderMonitorTestRun();
  }
}

function backFromMonitorTest() {
  const test = state.currentTest;
  if (!test) {
    showView("devices");
    return;
  }
  if (test.returnView === "monitorDetail" && test.monitorId) {
    showMonitorDetails(test.monitorId);
    return;
  }
  showView(test.returnView || test.returnTab || "devices");
}

function monitorReturnView(monitor) {
  return "devices";
}

function startTestRunTimer() {
  stopTestRunTimer();
  testRunTimer = setInterval(renderMonitorTestRun, 1000);
}

function stopTestRunTimer() {
  if (!testRunTimer) return;
  clearInterval(testRunTimer);
  testRunTimer = null;
}

function renderMonitorTestRun() {
  const test = state.currentTest;
  if (!test) return;
  const monitor = state.monitors.find((item) => item.id === test.monitorId) || test.result;
  if (!monitor) return;
  const isRunning = test.status === "running";
  const elapsedUntil = test.finishedAt || new Date().toISOString();
  const result = test.result || monitor;
  $("#testRunTitle").textContent = monitor.name;
  $("#testRunSubtitle").textContent = `${typeLabel(monitor.type)} · ${monitor.target}`;
  $("#testRunState").innerHTML = `
    <span class="run-dot ${isRunning ? "running" : test.status}"></span>
    <span>${testStatusLabel(test.status)}</span>
  `;
  $("#testRunElapsed").textContent = formatDuration(new Date(elapsedUntil) - new Date(test.startedAt));
  $("#testRunStarted").textContent = formatDate(test.startedAt);
  $("#testRunFinished").textContent = test.finishedAt ? formatDate(test.finishedAt) : "-";
  $("#testRepeatBtn").disabled = isRunning;
  $("#testEditBtn").disabled = isRunning;
  $("#testRunMetrics").innerHTML = [
    ["Status", `<span class="badge ${badgeClass(result.status)}">${escapeHtml(result.status || "unknown")}</span>`],
    ["Odpowiedź", result.last_response_ms ? `${Number(result.last_response_ms).toFixed(1)} ms` : "-"],
    ["HTTP", result.last_http_status || "-"],
    ["Ostatni test", formatDate(result.last_checked_at)],
  ].map(([label, value]) => `<article><span>${value}</span><small>${label}</small></article>`).join("");
  $("#testRunSettings").innerHTML = monitorSettingsRows(monitor);
  $("#testRunScope").innerHTML = monitorScopeRows(monitor);
  $("#testRunSteps").innerHTML = renderTestSteps(test);
  $("#testRunResult").innerHTML = renderTestResultSummary(test, result);
}

function monitorSettingsRows(monitor) {
  const config = monitor.config || {};
  const rows = {
    "Typ": typeLabel(monitor.type),
    "Grupa": monitor.group_name || "Bez grupy",
    "Aktywny": monitor.enabled ? "tak" : "nie",
    "Interwał": `${monitor.interval_seconds}s`,
    "Timeout": getTimeoutMinutes(config) ? `${getTimeoutMinutes(config)} min` : `${state.settings?.default_timeout_minutes ?? "-"} min`,
    "Serwis": monitor.maintenance_active ? `aktywny do ${formatDate(monitor.maintenance_until || monitor.group_maintenance_until)}` : "-",
    "Retencja historii": `${state.settings?.retention_days ?? "-"} dni`,
    "Blokada prywatnych URL": state.settings?.block_private_networks ? "tak" : "nie",
    "Encje Home Assistant": state.settings?.publish_home_assistant_entities ? "tak" : "nie",
    "Eventy Home Assistant": state.settings?.publish_home_assistant_events ? "tak" : "nie",
  };
  return definitionRows(rows);
}

function monitorScopeRows(monitor) {
  const config = monitor.config || {};
  const rows = {
    "Cel": monitor.target,
    "Oczekiwane HTTP": (config.expected_status_codes || []).join(", ") || "-",
    "Selektor CSS": config.css_selector || "-",
    "JSON path": config.json_path || "-",
    "Host": config.host || "-",
    "Port": config.port || "-",
    "Limit strony": getMaxPageSizeMb(config) ? `${getMaxPageSizeMb(config)} MB` : `${state.settings?.max_page_size_mb ?? "-"} MB`,
  };
  return definitionRows(rows);
}

function renderTestSteps(test) {
  const steps = [
    ["Przygotowanie", "done"],
    ["Wykonanie testu", test.status === "running" ? "running" : test.status === "error" ? "error" : "done"],
    ["Zapis historii i stanu", test.status === "running" ? "pending" : test.status === "error" ? "pending" : "done"],
    ["Zakończenie", test.status === "done" ? "done" : test.status === "error" ? "error" : "pending"],
  ];
  return steps.map(([label, status]) => `
    <div class="run-step ${status}">
      <span class="run-dot ${status}"></span>
      <strong>${label}</strong>
    </div>
  `).join("");
}

function renderTestResultSummary(test, result) {
  if (test.status === "running") {
    return '<p class="empty">Test jest w toku. Wynik pojawi się automatycznie po odpowiedzi monitora.</p>';
  }
  if (test.status === "error") {
    return `<div class="test-result bad">Błąd uruchomienia testu: ${escapeHtml(test.error || "-")}</div>`;
  }
  const rows = {
    "Status": result.status || "-",
    "Czas odpowiedzi": result.last_response_ms ? `${Number(result.last_response_ms).toFixed(1)} ms` : "-",
    "HTTP": result.last_http_status || "-",
    "Suma WWW": result.last_content_hash || "-",
    "Błąd": result.last_error || "-",
  };
  return `<dl class="diagnostics">${definitionRows(rows)}</dl>`;
}

function definitionRows(rows) {
  return Object.entries(rows)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`)
    .join("");
}

function testStatusLabel(status) {
  if (status === "running") return "Test w trakcie";
  if (status === "done") return "Test zakończony";
  if (status === "error") return "Test przerwany";
  return "Oczekiwanie";
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

async function showMonitorDetails(id) {
  state.selectedMonitorId = id;
  showView("monitorDetail", "devices");
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
  $("#detailMonitorSearch").value = detailMonitorValue(monitor);
  $("#detailExtraActions").innerHTML = renderCardActions(monitor);
  $$("[data-action]", $("#detailExtraActions")).forEach((button) => button.addEventListener("click", handleCardAction));
  $("#detailSnapshotsSection").classList.toggle("hidden", monitor.type !== "http_hash");
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
  toast(id ? "Monitor zaktualizowany." : "Monitor dodany.");
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
  const monitors = (data.monitors || []).map((monitor) => {
    const mappedGroupId = monitor.group_name ? importedGroups[monitor.group_name] : monitor.group_id;
    return { ...monitor, group_id: mappedGroupId || null, test_on_save: false };
  });
  if (monitors.length) {
    await api("/api/monitors/import", {
      method: "POST",
      body: JSON.stringify({ monitors }),
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

function renderRecentChanges(items) {
  const root = $("#recentChanges");
  if (!items.length) {
    root.className = "change-log empty";
    root.innerHTML = "Brak zmian WWW";
    return;
  }
  root.className = "change-log";
  const groups = groupByPeriod(items, (item) => item.checked_at);
  root.innerHTML = groups.map((group) => `
    <section class="change-period">
      <div class="change-period-head">
        <h3>${escapeHtml(group.label)}</h3>
        <span>${group.items.length}</span>
      </div>
      <div class="change-period-items">
        ${group.items.map(changeLine).join("")}
      </div>
    </section>
  `).join("");
}

function groupByPeriod(items, getDateValue) {
  const buckets = [
    { key: "today", label: "Dzisiaj", items: [] },
    { key: "yesterday", label: "Wczoraj", items: [] },
    { key: "week", label: "Ostatnie 7 dni", items: [] },
    { key: "month", label: "Ostatnie 30 dni", items: [] },
    { key: "older", label: "Starsze", items: [] },
  ];
  const now = new Date();
  const today = startOfLocalDay(now);
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const weekAgo = new Date(today);
  weekAgo.setDate(weekAgo.getDate() - 6);
  const monthAgo = new Date(today);
  monthAgo.setDate(monthAgo.getDate() - 29);

  items.forEach((item) => {
    const date = new Date(getDateValue(item));
    if (Number.isNaN(date.getTime())) {
      buckets[4].items.push(item);
      return;
    }
    const day = startOfLocalDay(date);
    if (day.getTime() === today.getTime()) buckets[0].items.push(item);
    else if (day.getTime() === yesterday.getTime()) buckets[1].items.push(item);
    else if (day >= weekAgo) buckets[2].items.push(item);
    else if (day >= monthAgo) buckets[3].items.push(item);
    else buckets[4].items.push(item);
  });

  return buckets.filter((bucket) => bucket.items.length);
}

function changeLine(row) {
  const details = parseDetails(row.details_json);
  const detailText = details.change_summary || details.error_message || details.current_hash || "";
  return `
    <article class="change-item">
      <div class="change-main">
        <strong>${escapeHtml(row.monitor_name)}</strong>
        <small>${formatDate(row.checked_at)}</small>
      </div>
      <div class="change-meta">
        <span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span>
        <span>HTTP ${row.http_status || "-"}</span>
        <span>${row.response_ms ? Number(row.response_ms).toFixed(1) + " ms" : "brak czasu"}</span>
        <span>${hashHtml(row.content_hash || details.current_hash)}</span>
      </div>
      <p>${escapeHtml(row.target || "-")}</p>
      ${detailText ? `<small>${escapeHtml(String(detailText).slice(0, 180))}</small>` : ""}
      ${row.error ? `<small class="error-text">${escapeHtml(row.error)}</small>` : ""}
    </article>
  `;
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
  if (status === "warning") return "warning";
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

function isErrorStatus(status) {
  return ["offline", "error", "closed", "timeout"].includes(status);
}

function average(values) {
  return values.reduce((sum, value) => sum + Number(value), 0) / values.length;
}

function startOfLocalDay(value) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
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
    hideToast();
  }, 3800);
}

function hideToast() {
  const node = $("#toast");
  node.classList.remove("show");
  node.classList.remove("error");
}

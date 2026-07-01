const state = {
  monitors: [],
  groups: [],
  monitorTypes: [],
  presets: [],
  summary: null,
  diagnostics: null,
  incidents: [],
  settings: null,
  selectedMonitorId: null,
  currentTest: null,
  monitorQuery: "",
  monitorTypeFilter: "all",
  monitorStatusFilter: "all",
  monitorGroupFilter: "all",
  monitorMaintenanceFilter: "all",
  monitorEnabledFilter: "all",
  monitorSort: "name",
  monitorView: "cards",
  dashboardTypeFilter: "all",
  selectedMonitorIds: new Set(),
  bulkSelectionMode: false,
  events: [],
  eventTypeFilter: "",
  eventQuery: "",
  incidentStatusFilter: "all",
  incidentMonitorFilter: "",
  lastRefreshedAt: null,
  detailHistoryRows: [],
  detailHistoryPage: 1,
  detailHistoryPageSize: 100,
  detailHistoryFilters: {
    from: "",
    to: "",
    status: "all",
    search: "",
    sort: "date_desc",
  },
};

const API_BASE = window.location.pathname === "/" ? "" : window.location.pathname.replace(/\/$/, "");
const URL_MONITOR_TYPES = ["http_status", "http_hash", "rest_api"];
const MONITOR_TYPE_CATEGORIES = {
  ping_host: "network",
  tcp_port: "protocol",
  dns_lookup: "protocol",
  ssl_certificate: "protocol",
  mqtt_monitor: "protocol",
  http_status: "website",
  http_hash: "website",
  rest_api: "website",
  ha_entity: "home_assistant",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
let testRunTimer;

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initDensity();
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
      if (button.dataset.tab === "events") loadEvents();
      if (button.dataset.tab === "incidents") renderIncidents();
    });
  });
  $("#refreshBtn").addEventListener("click", manualRefresh);
  $("#brandHomeBtn")?.addEventListener("click", () => showView("dashboard"));
  $("#themeMode")?.addEventListener("change", (event) => applyTheme(event.currentTarget.value));
  document.addEventListener("click", closeActionMenusOnOutsideClick);
  document.addEventListener("keydown", closeActionMenusOnEscape);
  $("#toast").addEventListener("click", hideToast);
  $("#detailBackBtn").addEventListener("click", () => showView("monitoring"));
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
  bindDetailHistoryControls();
  $$("[data-open-form]").forEach((button) => {
    button.addEventListener("click", () => openMonitorForm({ type: button.dataset.openForm }));
  });
}

function bindForms() {
  $("#monitorForm").addEventListener("submit", saveMonitor);
  $("#cancelMonitorBtn").addEventListener("click", () => $("#monitorDialog").close());
  $("#testMonitorBtn").addEventListener("click", testMonitorFromForm);
  $("#groupForm").addEventListener("submit", saveGroup);
  $("#monitorTypeSelect").addEventListener("change", () => renderTypeFields($("#monitorTypeSelect").value));
  $("#monitorForm").addEventListener("input", updateConfigPreview);
  $("#monitorForm").addEventListener("change", updateConfigPreview);
  $("#applyPresetBtn").addEventListener("click", applyPreset);
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#settingsResetBtn")?.addEventListener("click", renderSettings);
  $("#densityMode")?.addEventListener("change", (event) => applyDensity(event.currentTarget.value));
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
  $("#monitorSearch").addEventListener("input", debounce((event) => {
    state.monitorQuery = event.currentTarget.value.trim().toLowerCase();
    persistMonitorUiState();
    renderMonitorLists();
  }, 180));
  $("#monitorTypeFilter").addEventListener("change", (event) => {
    state.monitorTypeFilter = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorStatusFilter").addEventListener("change", (event) => {
    state.monitorStatusFilter = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorGroupFilter").addEventListener("change", (event) => {
    state.monitorGroupFilter = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorMaintenanceFilter")?.addEventListener("change", (event) => {
    state.monitorMaintenanceFilter = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorEnabledFilter")?.addEventListener("change", (event) => {
    state.monitorEnabledFilter = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorSort").addEventListener("change", (event) => {
    state.monitorSort = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#monitorView").addEventListener("change", (event) => {
    state.monitorView = event.currentTarget.value;
    persistMonitorUiState();
    renderMonitorLists();
  });
  $("#selectAllMonitors")?.addEventListener("change", toggleVisibleMonitorSelection);
  $("#bulkSelectionModeBtn")?.addEventListener("click", toggleBulkSelectionMode);
  $$("[data-bulk-action]").forEach((button) => button.addEventListener("click", handleBulkAction));
  $("#dashboardTypeFilter").addEventListener("change", (event) => {
    state.dashboardTypeFilter = event.currentTarget.value;
    renderDashboard();
  });
  $$("[data-history-range]").forEach((button) => button.addEventListener("click", applyHistoryRange));
  $("#eventsRefreshBtn")?.addEventListener("click", loadEvents);
  $("#eventTypeFilter")?.addEventListener("change", (event) => {
    state.eventTypeFilter = event.currentTarget.value;
    renderEvents();
  });
  $("#eventSearch")?.addEventListener("input", debounce((event) => {
    state.eventQuery = event.currentTarget.value.trim().toLowerCase();
    renderEvents();
  }, 180));
  $("#incidentStatusFilter")?.addEventListener("change", (event) => {
    state.incidentStatusFilter = event.currentTarget.value;
    renderIncidents();
  });
  $("#incidentMonitorFilter")?.addEventListener("change", (event) => {
    state.incidentMonitorFilter = event.currentTarget.value;
    renderIncidents();
  });
  $("#incidentsRefreshBtn")?.addEventListener("click", loadIncidents);
  $("#diagnosticsRefreshBtn")?.addEventListener("click", loadDiagnostics);
  $$("[data-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => $(`#${button.dataset.dialogClose}`)?.close());
  });
}

function bindDetailHistoryControls() {
  $("#detailHistoryPrev")?.addEventListener("click", () => {
    if (state.detailHistoryPage <= 1) return;
    state.detailHistoryPage -= 1;
    renderDetailHistoryTable();
  });
  $("#detailHistoryNext")?.addEventListener("click", () => {
    state.detailHistoryPage += 1;
    renderDetailHistoryTable();
  });
  $("#detailHistoryFrom")?.addEventListener("change", (event) => updateDetailHistoryFilter("from", event.currentTarget.value));
  $("#detailHistoryTo")?.addEventListener("change", (event) => updateDetailHistoryFilter("to", event.currentTarget.value));
  $("#detailHistoryStatus")?.addEventListener("change", (event) => updateDetailHistoryFilter("status", event.currentTarget.value));
  $("#detailHistorySort")?.addEventListener("change", (event) => updateDetailHistoryFilter("sort", event.currentTarget.value));
  $("#detailHistorySearch")?.addEventListener("input", debounce((event) => {
    updateDetailHistoryFilter("search", event.currentTarget.value.trim().toLowerCase());
  }, 160));
  $$("[data-detail-history-range]").forEach((button) => {
    button.addEventListener("click", () => applyDetailHistoryRange(button.dataset.detailHistoryRange));
  });
}

function updateDetailHistoryFilter(key, value) {
  state.detailHistoryFilters[key] = value;
  state.detailHistoryPage = 1;
  renderDetailHistoryTable();
}

function applyDetailHistoryRange(range) {
  const now = new Date();
  const from = new Date(now);
  if (range === "24h") from.setDate(from.getDate() - 1);
  if (range === "7d") from.setDate(from.getDate() - 7);
  if (range === "30d") from.setDate(from.getDate() - 30);
  state.detailHistoryFilters.from = range === "all" ? "" : toDateInputValue(from);
  state.detailHistoryFilters.to = "";
  state.detailHistoryPage = 1;
  if ($("#detailHistoryFrom")) $("#detailHistoryFrom").value = state.detailHistoryFilters.from;
  if ($("#detailHistoryTo")) $("#detailHistoryTo").value = "";
  renderDetailHistoryTable();
}

async function refreshAll() {
  const [summary, monitors, groups, settings, monitorTypes, presets, diagnostics, incidents] = await Promise.all([
    api("/api/summary"),
    api("/api/monitors"),
    api("/api/groups"),
    api("/api/settings"),
    api("/api/monitor-types"),
    api("/api/presets"),
    api("/api/diagnostics"),
    api("/api/incidents?limit=100"),
  ]);
  state.summary = summary;
  state.monitors = monitors;
  state.groups = groups;
  state.settings = settings;
  state.monitorTypes = monitorTypes;
  state.presets = presets;
  state.diagnostics = diagnostics;
  state.incidents = incidents;
  state.lastRefreshedAt = new Date().toISOString();
  renderGlobalStatus();
  $("#lastRefreshAt").textContent = `Odświeżono: ${formatDate(state.lastRefreshedAt)}`;
  renderCategoryFilterOptions();
  renderDashboard();
  renderMonitorTypeOptions();
  renderPresetOptions();
  renderGroupOptions();
  renderMonitorLists();
  renderGroups();
  renderHistoryMonitorOptions();
  renderIncidentMonitorOptions();
  renderIncidents();
  renderDetailMonitorOptions();
  renderSettings();
  if ($("#events")?.classList.contains("active")) loadEvents();
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
  const saved = localStorage.getItem("monitoring-theme") || "auto";
  applyTheme(saved);
}

function toggleTheme() {
  const current = localStorage.getItem("monitoring-theme") || "auto";
  applyTheme(current === "dark" ? "light" : "dark");
}

function applyTheme(theme) {
  const requested = ["auto", "dark", "light"].includes(theme) ? theme : "auto";
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  const effective = requested === "auto" ? (prefersDark ? "dark" : "light") : requested;
  document.documentElement.dataset.theme = effective;
  localStorage.setItem("monitoring-theme", requested);
  if ($("#themeMode")) $("#themeMode").value = requested;
}

function initDensity() {
  applyDensity(localStorage.getItem("monitoring-density") || "comfortable");
  restoreMonitorUiState();
}

function applyDensity(value) {
  const density = value === "compact" ? "compact" : "comfortable";
  document.documentElement.dataset.density = density;
  localStorage.setItem("monitoring-density", density);
  if ($("#densityMode")) $("#densityMode").value = density;
}

function restoreMonitorUiState() {
  try {
    const saved = JSON.parse(localStorage.getItem("monitoring-ui-state") || "{}");
    Object.assign(state, {
      monitorTypeFilter: saved.monitorTypeFilter || state.monitorTypeFilter,
      monitorStatusFilter: saved.monitorStatusFilter || state.monitorStatusFilter,
      monitorGroupFilter: saved.monitorGroupFilter || state.monitorGroupFilter,
      monitorMaintenanceFilter: saved.monitorMaintenanceFilter || state.monitorMaintenanceFilter,
      monitorEnabledFilter: saved.monitorEnabledFilter || state.monitorEnabledFilter,
      monitorSort: saved.monitorSort || state.monitorSort,
      monitorView: saved.monitorView || state.monitorView,
      monitorQuery: saved.monitorQuery || state.monitorQuery,
    });
  } catch (_) {}
}

function persistMonitorUiState() {
  localStorage.setItem("monitoring-ui-state", JSON.stringify({
    monitorTypeFilter: state.monitorTypeFilter,
    monitorStatusFilter: state.monitorStatusFilter,
    monitorGroupFilter: state.monitorGroupFilter,
    monitorMaintenanceFilter: state.monitorMaintenanceFilter,
    monitorEnabledFilter: state.monitorEnabledFilter,
    monitorSort: state.monitorSort,
    monitorView: state.monitorView,
    monitorQuery: state.monitorQuery,
  }));
}

function showView(viewId, activeTab = viewId) {
  $$(".view").forEach((view) => view.classList.remove("active"));
  $(`#${viewId}`)?.classList.add("active");
  $$(".tab").forEach((tab) => {
    const isActive = tab.dataset.tab === activeTab;
    tab.classList.toggle("active", isActive);
    if (isActive) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  });
}

function renderGlobalStatus() {
  const enabled = state.monitors.filter((monitor) => monitor.enabled && !monitor.maintenance_active);
  const errors = enabled.filter((monitor) => isErrorStatus(monitor.status));
  const warnings = enabled.filter((monitor) => monitor.status === "warning");
  const status = errors.length ? "bad" : warnings.length ? "warning" : "ok";
  const label = errors.length
    ? `${errors.length} monitorów wymaga uwagi`
    : warnings.length
      ? `${warnings.length} ostrzeżeń`
      : "Wszystkie aktywne monitory są stabilne";
  $("#globalStatusDot")?.classList.remove("ok", "bad", "warning", "unknown");
  $("#globalStatusDot")?.classList.add(status);
  if ($("#globalStatusText")) $("#globalStatusText").textContent = label;
  if ($("#dashboardSystemBadge")) {
    $("#dashboardSystemBadge").className = `badge ${status === "bad" ? "bad" : status}`;
    $("#dashboardSystemBadge").textContent = status === "bad" ? "problem" : status;
  }
  if ($("#sidebarSystemStatus")) $("#sidebarSystemStatus").textContent = `System: ${label}`;
  if ($("#sidebarCounts")) $("#sidebarCounts").textContent = `${state.monitors.length} monitorów`;
}

function renderDashboard() {
  const summary = state.summary || {};
  const monitors = filterMonitorsByCategory(state.monitors, state.dashboardTypeFilter);
  const monitorIds = new Set(monitors.map((monitor) => monitor.id));
  const recentIncidents = (state.incidents || []).filter((row) => monitorIds.has(row.monitor_id)).slice(0, 8);
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
  $("#metricUptime24").textContent = summary.slo?.["24h"]?.uptime_percent !== null && summary.slo?.["24h"]?.uptime_percent !== undefined
    ? `${summary.slo["24h"].uptime_percent}%`
    : "-";
  $("#metricUptime7").textContent = summary.slo?.["7d"]?.uptime_percent !== null && summary.slo?.["7d"]?.uptime_percent !== undefined
    ? `${summary.slo["7d"].uptime_percent}%`
    : "-";
  $("#metricIncidents").textContent = state.diagnostics?.incident_count ?? state.incidents.length ?? 0;
  renderWorstMonitors(monitors);
  renderSslExpiry(monitors);
  renderSchedulerStatus();
  renderIncidentList("#recentIncidents", recentIncidents);
  renderRecentChanges(recentChanges);
  renderAvailabilityChart();
  renderSlo(summary.slo || {});
}

function renderWorstMonitors(monitors) {
  const ranked = [...monitors]
    .filter((monitor) => monitor.enabled)
    .sort((a, b) => {
      const statusScore = Number(isErrorStatus(b.status)) - Number(isErrorStatus(a.status));
      if (statusScore) return statusScore;
      return Number(b.last_response_ms || 0) - Number(a.last_response_ms || 0);
    })
    .slice(0, 6);
  renderList("#worstMonitors", ranked, (monitor) => `
    <button class="list-item clickable-monitor" data-card-id="${monitor.id}" type="button">
      <strong>${escapeHtml(monitor.name)}</strong>
      <small>${escapeHtml(typeLabel(monitor.type))} · ${escapeHtml(monitor.status || "unknown")} · ${formatResponse(monitor.last_response_ms)}</small>
    </button>
  `);
  bindMonitorOpeners($("#worstMonitors"));
}

function renderSchedulerStatus() {
  const diagnostics = state.diagnostics || {};
  const running = Boolean(diagnostics.scheduler_running);
  const rows = [
    ["Scheduler", running ? "dziala" : "nie dziala", running ? "ok" : "bad"],
    ["Ostatni tick", diagnostics.scheduler_last_tick ? formatDate(diagnostics.scheduler_last_tick) : "-", ""],
    ["Aktywne testy", diagnostics.active_job_count ?? diagnostics.active_jobs?.length ?? 0, ""],
    ["Kolejka", diagnostics.queued_job_count ?? diagnostics.queued_jobs?.length ?? 0, ""],
    ["Taski", diagnostics.scheduled_task_count ?? 0, ""],
    ["Bledy schedulera", diagnostics.scheduler_error_count ?? 0, diagnostics.scheduler_error_count ? "bad" : ""],
  ];
  renderList("#schedulerStatus", rows, ([label, value, badge]) => `
    <div class="list-item">
      <strong>${escapeHtml(label)}</strong>
      <small>${badge ? `<span class="badge ${badge}">${escapeHtml(String(value))}</span>` : escapeHtml(String(value))}</small>
    </div>
  `);
}

function renderIncidentList(selector, incidents) {
  renderList(selector, incidents, (incident) => `
    <button class="list-item clickable-monitor" data-card-id="${incident.monitor_id}" type="button">
      <strong>${escapeHtml(incident.monitor_name || `Monitor ${incident.monitor_id}`)}</strong>
      <small>${formatDate(incident.started_at)} · ${escapeHtml(incident.status)} · ${formatSeconds(incident.duration_seconds)}</small>
      <span>${escapeHtml(incident.last_error || incident.root_status || "-")}</span>
    </button>
  `);
  bindMonitorOpeners($(selector));
}

function renderSslExpiry(monitors) {
  const items = monitors
    .filter((monitor) => monitor.type === "ssl_certificate")
    .map((monitor) => ({
      monitor,
      days: Number(monitor.config?.last_ssl_days_left ?? monitor.last_details?.days_left ?? Number.POSITIVE_INFINITY),
    }))
    .filter((item) => Number.isFinite(item.days) && item.days <= 45)
    .sort((a, b) => a.days - b.days)
    .slice(0, 8);
  renderList("#sslExpiryList", items, ({ monitor, days }) => `
    <button class="list-item clickable-monitor" data-card-id="${monitor.id}" type="button">
      <strong>${escapeHtml(monitor.name)}</strong>
      <small>${days} dni · ${escapeHtml(monitor.target)}</small>
    </button>
  `);
  bindMonitorOpeners($("#sslExpiryList"));
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
  state.selectedMonitorIds = new Set([...state.selectedMonitorIds].filter((id) => filtered.some((monitor) => monitor.id === id)));
  $("#monitorCountLabel").textContent = `${filtered.length} z ${state.monitors.length}`;
  if ($("#monitorSearch")) $("#monitorSearch").value = state.monitorQuery;
  if ($("#monitorMaintenanceFilter")) $("#monitorMaintenanceFilter").value = state.monitorMaintenanceFilter;
  if ($("#monitorEnabledFilter")) $("#monitorEnabledFilter").value = state.monitorEnabledFilter;
  if ($("#monitorSort")) $("#monitorSort").value = state.monitorSort;
  if ($("#monitorView")) $("#monitorView").value = state.monitorView;
  $("#monitorList").classList.toggle("hidden", state.monitorView !== "cards");
  $("#monitorTableWrap").classList.toggle("hidden", state.monitorView !== "table");
  if (state.monitorView === "table") renderMonitorTableModern(filtered);
  else renderMonitorCardsModern("#monitorList", filtered);
  renderBulkState(filtered);
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
    { value: "network", label: "Sieć" },
    { value: "website", label: "WWW / HTTP" },
    { value: "home_assistant", label: "Home Assistant" },
    { value: "protocol", label: "Protokoły" },
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
  renderMonitorTypeCards();
  const historyCurrent = $("#historyType").value;
  $("#historyType").innerHTML = '<option value="">Wszystkie</option>' + options;
  $("#historyType").value = historyCurrent;
}

function renderMonitorTypeCards() {
  const root = $("#monitorTypeCards");
  if (!root) return;
  const selected = $("#monitorTypeSelect").value || state.monitorTypes[0]?.type || "ping_host";
  root.innerHTML = state.monitorTypes.map((type) => `
    <button class="type-card ${type.type === selected ? "active" : ""}" type="button" data-monitor-type="${type.type}">
      <span>${typeIcon(type.type)} ${escapeHtml(type.label)}</span>
      <small>${escapeHtml(type.category || "monitor")} · domyślnie ${type.default_interval || "-"}s</small>
    </button>
  `).join("");
  $$("[data-monitor-type]", root).forEach((button) => {
    button.addEventListener("click", () => {
      $("#monitorTypeSelect").value = button.dataset.monitorType;
      renderTypeFields(button.dataset.monitorType);
    });
  });
}

function typeIcon(type) {
  if (type === "ping_host") return "◉";
  if (type === "tcp_port") return "↔";
  if (type === "dns_lookup") return "DNS";
  if (type === "ssl_certificate") return "SSL";
  if (type === "rest_api") return "{}";
  if (type === "ha_entity") return "HA";
  if (type === "mqtt_monitor") return "MQ";
  if (type === "http_hash") return "WWW";
  return "•";
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
  const historyGroup = $("#historyGroup");
  if (historyGroup) {
    const currentHistoryGroup = historyGroup.value;
    historyGroup.innerHTML = '<option value="">Wszystkie</option><option value="none">Bez grupy</option>' + state.groups
      .map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`)
      .join("");
    historyGroup.value = Array.from(historyGroup.options).some((option) => option.value === currentHistoryGroup)
      ? currentHistoryGroup
      : "";
  }
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
  renderMonitorTypeCards();
  updateConfigPreview();
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
      if (state.monitorMaintenanceFilter === "active") return Boolean(monitor.maintenance_active);
      if (state.monitorMaintenanceFilter === "inactive") return !monitor.maintenance_active;
      return true;
    })
    .filter((monitor) => {
      if (state.monitorEnabledFilter === "enabled") return monitor.enabled;
      if (state.monitorEnabledFilter === "disabled") return !monitor.enabled;
      return true;
    })
    .filter((monitor) => {
      if (!state.monitorQuery) return true;
      const config = monitor.config || {};
      const haystack = [
        monitor.name,
        monitor.target,
        monitor.status,
        monitor.group_name,
        monitor.type,
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
    if (sortKey === "uptime") return text(a.status).localeCompare(text(b.status)) || text(a.name).localeCompare(text(b.name));
    if (sortKey === "last_checked") return checkedAt(b) - checkedAt(a);
    if (sortKey === "type") return text(typeLabel(a.type)).localeCompare(text(typeLabel(b.type))) || text(a.name).localeCompare(text(b.name));
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
    <tr class="clickable-row ${state.selectedMonitorIds.has(monitor.id) ? "selected" : ""}" data-card-id="${monitor.id}" tabindex="0" title="${state.bulkSelectionMode ? "Zaznacz monitoring" : "Otwórz szczegóły monitoringu"}">
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

function renderMonitorTableModern(monitors) {
  const body = $("#monitorTableRows");
  if (!monitors.length) {
    body.innerHTML = '<tr><td colspan="11" class="empty">Brak monitorów dla wybranych filtrów.</td></tr>';
    return;
  }
  body.innerHTML = monitors.map((monitor) => `
    <tr class="clickable-row" data-card-id="${monitor.id}" tabindex="0" title="Otwórz szczegóły monitoringu">
      <td><input class="monitor-select" type="checkbox" data-select-monitor="${monitor.id}" ${state.selectedMonitorIds.has(monitor.id) ? "checked" : ""} aria-label="Zaznacz ${escapeHtml(monitor.name)}" /></td>
      <td><span class="badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status) : "wyłączony"}</span></td>
      <td>${escapeHtml(typeLabel(monitor.type))}</td>
      <td><strong>${escapeHtml(monitor.name)}</strong></td>
      <td>${targetHtml(monitor)}</td>
      <td>${monitor.last_http_status || "-"}</td>
      <td>${formatResponse(monitor.last_response_ms)}</td>
      <td>${monitor.interval_seconds}s</td>
      <td>${escapeHtml(monitor.group_name || "Bez grupy")}</td>
      <td>${formatDate(monitor.last_checked_at)}</td>
      <td><div class="actions compact-actions">${renderInlineMonitorActions(monitor)}</div></td>
    </tr>
  `).join("");
  bindMonitorOpeners(body);
  bindMonitorSelection(body);
  bindMonitorActions(body);
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
  return MONITOR_TYPE_CATEGORIES[monitor.type] || "other";
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

function renderMonitorCardsModern(selector, monitors) {
  const root = $(selector);
  if (!monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów w tej sekcji.</p>';
    return;
  }
  root.innerHTML = monitors.map((monitor) => `
    <article class="card clickable-card ${state.selectedMonitorIds.has(monitor.id) ? "selected" : ""} ${monitor.enabled ? "" : "inactive"}" data-card-id="${monitor.id}" tabindex="0" title="${state.bulkSelectionMode ? "Zaznacz monitoring" : "Otwórz szczegóły monitoringu"}">
      <div class="card-head">
        <div class="card-title-row">
          <input class="monitor-select" type="checkbox" data-select-monitor="${monitor.id}" ${state.selectedMonitorIds.has(monitor.id) ? "checked" : ""} aria-label="Zaznacz ${escapeHtml(monitor.name)}" />
          <div>
            <h3>${escapeHtml(monitor.name)}</h3>
            <p>${targetHtml(monitor)}</p>
          </div>
        </div>
        <span class="badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status) : "disabled"}</span>
      </div>
      <div class="meta">${renderMonitorMeta(monitor)}</div>
      <div class="actions">${renderInlineMonitorActions(monitor)}${renderCardActions(monitor)}</div>
    </article>
  `).join("");
  bindMonitorOpeners(root);
  bindMonitorSelection(root);
  bindMonitorActions(root);
}

function renderInlineMonitorActions(monitor) {
  return `
    <button data-action="check" data-id="${monitor.id}" type="button" aria-label="Sprawdź ${escapeHtml(monitor.name)}">↻</button>
    <button data-action="edit" data-id="${monitor.id}" type="button">Edytuj</button>
    <button data-action="duplicate" data-id="${monitor.id}" type="button">Duplikuj</button>
  `;
}

function bindMonitorOpeners(root) {
  $$("[data-card-id]", root).forEach((node) => {
    node.addEventListener("click", (event) => {
      const interactive = event.target.closest("button, input, select, summary, details, a");
      if (interactive && interactive !== node) return;
      if (state.bulkSelectionMode && node.querySelector("[data-select-monitor]")) {
        event.preventDefault();
        toggleMonitorSelectionNode(node);
        return;
      }
      showMonitorDetails(Number(node.dataset.cardId));
    });
    node.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      const interactive = event.target.closest("button, input, select, summary, details, a");
      if (interactive && interactive !== node) return;
      event.preventDefault();
      if (state.bulkSelectionMode && node.querySelector("[data-select-monitor]")) {
        toggleMonitorSelectionNode(node);
        return;
      }
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
  if (monitorCategory(monitor) === "website") {
    rows.splice(1, 0,
      ["URL", monitor.target],
      ["HTTP status", monitor.last_http_status || "-"],
      ["Czas odpowiedzi", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
      ["Typ monitoringu", typeLabel(monitor.type)],
    );
    if (monitor.type === "http_hash") rows.push(["Suma WWW", hashHtml(monitor.last_content_hash)]);
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  } else if (["network", "protocol"].includes(monitorCategory(monitor))) {
    rows.splice(1, 0,
      ["IP / host", config.host || monitor.target],
      ["Ping / odpowiedź", monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-"],
      ["Status", monitor.enabled ? monitor.status : "nieaktywny"],
    );
    if (config.port) rows.push(["Port", config.port]);
    if (config.topic) rows.push(["Topic", config.topic]);
    rows.push(["Ostatni błąd", monitor.last_error || "-"]);
    if (diagnosticMessage(monitor)) rows.push(["Diagnostyka", diagnosticMessage(monitor)]);
  } else if (monitorCategory(monitor) === "home_assistant") {
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
      <div class="action-menu-list">
        <button data-action="maintenance" data-id="${monitor.id}">Ustaw serwis</button>
        ${monitor.maintenance_until ? `<button data-action="maint-clear" data-id="${monitor.id}">Wyłącz serwis</button>` : ""}
      </div>
    </details>
    <details class="action-menu">
      <summary aria-label="Więcej akcji monitora ${escapeHtml(monitor.name)}">Więcej</summary>
      <div class="action-menu-list">
        <button data-action="toggle-enabled" data-id="${monitor.id}">${monitor.enabled ? "Wyłącz monitoring" : "Włącz monitoring"}</button>
        ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
        <button data-action="delete" data-id="${monitor.id}" class="danger-action">Usuń</button>
      </div>
    </details>
  `;
}

function renderDetailActions(monitor) {
  return `
    <button data-action="maintenance" data-id="${monitor.id}" type="button">Serwis</button>
    <details class="action-menu detail-more-menu">
      <summary aria-label="Więcej akcji monitora ${escapeHtml(monitor.name)}">Więcej</summary>
      <div class="action-menu-list">
        <button data-action="toggle-enabled" data-id="${monitor.id}" type="button">${monitor.enabled ? "Wyłącz monitoring" : "Włącz monitoring"}</button>
        ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}" type="button">Zmiany</button>` : ""}
        <button data-action="delete" data-id="${monitor.id}" type="button" class="danger-action">Usuń</button>
      </div>
    </details>
  `;
}

function bindMonitorActions(root) {
  $$("[data-action]", root).forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.currentTarget.closest("details.action-menu")?.removeAttribute("open");
      handleCardAction(event);
    });
  });
}

function closeActionMenusOnOutsideClick(event) {
  $$("details.action-menu[open]").forEach((menu) => {
    if (!menu.contains(event.target)) menu.removeAttribute("open");
  });
}

function closeActionMenusOnEscape(event) {
  if (event.key !== "Escape") return;
  $$("details.action-menu[open]").forEach((menu) => menu.removeAttribute("open"));
}

function bindMonitorSelection(root) {
  $$("[data-select-monitor]", root).forEach((checkbox) => {
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", (event) => {
      const id = Number(event.currentTarget.dataset.selectMonitor);
      if (event.currentTarget.checked) state.selectedMonitorIds.add(id);
      else state.selectedMonitorIds.delete(id);
      event.currentTarget.closest("[data-card-id]")?.classList.toggle("selected", event.currentTarget.checked);
      renderBulkState(filterMonitorsForList(state.monitors));
    });
  });
}

function toggleMonitorSelectionNode(node) {
  const checkbox = node.querySelector("[data-select-monitor]");
  if (!checkbox) return;
  checkbox.checked = !checkbox.checked;
  const id = Number(checkbox.dataset.selectMonitor);
  if (checkbox.checked) state.selectedMonitorIds.add(id);
  else state.selectedMonitorIds.delete(id);
  node.classList.toggle("selected", checkbox.checked);
  renderBulkState(filterMonitorsForList(state.monitors));
}

function renderBulkState(visibleMonitors = filterMonitorsForList(state.monitors)) {
  const visibleIds = visibleMonitors.map((monitor) => monitor.id);
  const selectedVisible = visibleIds.filter((id) => state.selectedMonitorIds.has(id));
  if ($("#bulkSelectionCount")) $("#bulkSelectionCount").textContent = `${state.selectedMonitorIds.size} zaznaczonych`;
  const modeButton = $("#bulkSelectionModeBtn");
  if (modeButton) {
    modeButton.classList.toggle("active", state.bulkSelectionMode);
    modeButton.setAttribute("aria-pressed", String(state.bulkSelectionMode));
    modeButton.textContent = state.bulkSelectionMode ? "Zakończ zaznaczanie" : "Zaznacz masowo";
  }
  if ($("#selectAllMonitors")) {
    $("#selectAllMonitors").checked = visibleIds.length > 0 && selectedVisible.length === visibleIds.length;
    $("#selectAllMonitors").indeterminate = selectedVisible.length > 0 && selectedVisible.length < visibleIds.length;
  }
}

function toggleBulkSelectionMode() {
  state.bulkSelectionMode = !state.bulkSelectionMode;
  renderMonitorLists();
}

function toggleVisibleMonitorSelection(event) {
  const visible = filterMonitorsForList(state.monitors);
  visible.forEach((monitor) => {
    if (event.currentTarget.checked) state.selectedMonitorIds.add(monitor.id);
    else state.selectedMonitorIds.delete(monitor.id);
  });
  renderMonitorLists();
}

async function handleBulkAction(event) {
  const action = event.currentTarget.dataset.bulkAction;
  const ids = [...state.selectedMonitorIds];
  if (!ids.length) {
    toast("Zaznacz przynajmniej jeden monitor.", "error");
    return;
  }
  if (action === "delete") {
    const monitorsToDelete = ids
      .map((id) => state.monitors.find((item) => item.id === id))
      .filter(Boolean);
    if (!await confirmBulkDelete(monitorsToDelete)) return;
  }
  await runWithButtonLoading(event.currentTarget, async () => {
    for (const id of ids) {
      const monitor = state.monitors.find((item) => item.id === id);
      if (!monitor) continue;
      if (action === "enable") await api(`/api/monitors/${id}/enable`, { method: "POST" });
      if (action === "disable") await api(`/api/monitors/${id}/disable`, { method: "POST" });
      if (action === "check") await api(`/api/monitors/${id}/check`, { method: "POST" });
      if (action === "maint-30") await api(`/api/monitors/${id}/maintenance`, { method: "POST", body: JSON.stringify({ duration_minutes: 30, reason: "Tryb serwisowy 30 min" }) });
      if (action === "maint-120") await api(`/api/monitors/${id}/maintenance`, { method: "POST", body: JSON.stringify({ duration_minutes: 120, reason: "Tryb serwisowy 2h" }) });
      if (action === "delete") await api(`/api/monitors/${id}`, { method: "DELETE" });
    }
  });
  state.selectedMonitorIds.clear();
  toast("Wykonano akcję masową.");
  refreshAll();
}

function confirmBulkDelete(monitors) {
  if (!monitors.length) return Promise.resolve(false);
  const dialog = $("#confirmDialog");
  if (!dialog?.showModal) {
    return Promise.resolve(confirm(`Usunąć ${monitors.length} monitorów?\n\n${monitors.map((monitor) => `- ${monitor.name}`).join("\n")}`));
  }
  $("#confirmTitle").textContent = `Usunąć ${monitors.length} ${pluralizeMonitors(monitors.length)}?`;
  $("#confirmText").textContent = "Ta akcja trwale usunie poniższe monitory wraz z ich konfiguracją. Sprawdź listę przed potwierdzeniem.";
  $("#confirmAcceptBtn").textContent = monitors.length === 1 ? "Usuń monitor" : "Usuń monitory";
  const details = $("#confirmDetails");
  details.classList.remove("hidden");
  details.innerHTML = `
    <div class="delete-list-head">
      <span>Do usunięcia</span>
      <strong>${monitors.length}</strong>
    </div>
    <ul class="delete-list">
      ${monitors.map((monitor) => `
        <li>
          <strong>${escapeHtml(monitor.name)}</strong>
          <span>${escapeHtml(typeLabel(monitor.type))} · ${escapeHtml(monitor.target || "-")}</span>
        </li>
      `).join("")}
    </ul>
  `;
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      resolve(dialog.returnValue === "confirm");
    }, { once: true });
    dialog.showModal();
  });
}

function pluralizeMonitors(count) {
  if (count === 1) return "monitor";
  const lastTwo = count % 100;
  const last = count % 10;
  if (lastTwo >= 12 && lastTwo <= 14) return "monitorów";
  if (last >= 2 && last <= 4) return "monitory";
  return "monitorów";
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
  if (action === "duplicate") {
    const clone = JSON.parse(JSON.stringify(monitor));
    delete clone.id;
    clone.name = `${clone.name} kopia`;
    clone.test_on_save = false;
    openMonitorForm(clone);
  }
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
      showView("monitoring");
    }
  }
  if (action === "snapshots") showSnapshots(id);
}

async function startMonitorTestRun(id, returnView = "monitoring") {
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
    showView("monitoring");
    return;
  }
  if (test.returnView === "monitorDetail" && test.monitorId) {
    showMonitorDetails(test.monitorId);
    return;
  }
  showView(test.returnView || test.returnTab || "monitoring");
}

function monitorReturnView(monitor) {
  return "monitoring";
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
    "Timeout globalny": `${state.settings?.default_timeout_minutes ?? "-"} min`,
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

function formatSeconds(value) {
  const total = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

async function showMonitorDetails(id) {
  state.selectedMonitorId = id;
  showView("monitorDetail", "monitoring");
  renderMonitorDetailsShell(id);
  const monitor = state.monitors.find((item) => item.id === id);
  if (!monitor) return;
  renderDetailHistoryLoading();
  try {
    const [slo, history, snapshots] = await Promise.all([
      api(`/api/slo?monitor_id=${id}`),
      api(`/api/history?monitor_id=${id}&limit=1000`),
      monitor.type === "http_hash" ? api(`/api/monitors/${id}/snapshots`) : Promise.resolve([]),
    ]);
    renderDetailSlo(slo);
    renderDetailHistory(history);
    renderDetailSnapshots(snapshots);
  } catch (error) {
    renderDetailHistoryError(error);
  }
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
  resetDetailHistoryState();
  renderDetailHistoryLoading();
  $("#detailMonitorSearch").value = detailMonitorValue(monitor);
  $("#detailExtraActions").innerHTML = renderDetailActions(monitor);
  bindMonitorActions($("#detailExtraActions"));
  $("#detailSnapshotsSection").classList.toggle("hidden", monitor.type !== "http_hash");
  $("#detailMetrics").innerHTML = [
    { label: "Status", value: `<span class="detail-status-badge ${badgeClass(monitor.status)}">${escapeHtml(monitor.status || "-")}</span>` },
    { label: "Odpowiedź", value: monitor.last_response_ms ? `${Number(monitor.last_response_ms).toFixed(1)} ms` : "-", empty: !monitor.last_response_ms },
    { label: "HTTP", value: monitor.last_http_status || "-", empty: !monitor.last_http_status },
    { label: "Ostatni test", value: renderDetailDate(monitor.last_checked_at), empty: !monitor.last_checked_at },
    { label: "Ostatnia zmiana", value: renderDetailDate(monitor.last_changed_at), empty: !monitor.last_changed_at },
    ...(monitor.type === "http_hash" ? [{ label: "Suma WWW", value: hashHtml(monitor.last_content_hash), empty: !monitor.last_content_hash }] : []),
  ].map((metric) => `
    <article class="detail-metric-card">
      <div class="detail-metric-value ${metric.empty ? "is-empty" : ""}">${metric.value}</div>
      <small>${escapeHtml(metric.label)}</small>
    </article>
  `).join("");
  const detailData = [
    ["Nazwa", monitor.name],
    ["Cel", monitor.target],
    ["Typ", typeLabel(monitor.type)],
    ["Grupa", monitor.group_name || "Bez grupy"],
    ["Interwał", `${monitor.interval_seconds}s`],
    ["Aktywny", monitor.enabled ? "tak" : "nie"],
    ["Maintenance", monitor.maintenance_active ? `aktywny do ${formatDate(monitor.maintenance_until || monitor.group_maintenance_until)}` : "-"],
    ...(monitor.type === "http_hash" ? [
      ["Data sprawdzenia WWW", formatDate(monitor.last_checked_at)],
      ["Suma kontrolna WWW", monitor.last_content_hash || "-"],
    ] : []),
    ["Błąd", monitor.last_error || "-", monitor.last_error ? "error" : ""],
    ["Konfiguracja", JSON.stringify(monitor.config || {}, null, 2), "code"],
  ];
  $("#detailData").innerHTML = detailData
    .map(([key, value, variant]) => `<dt>${escapeHtml(key)}</dt><dd>${renderDetailValue(value, variant)}</dd>`)
    .join("");
}

function renderDetailDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(String(value));
  return `<span class="detail-date"><strong>${date.toLocaleDateString("pl-PL")}</strong><span>${date.toLocaleTimeString("pl-PL")}</span></span>`;
}

function renderDetailValue(value, variant = "") {
  const text = String(value ?? "-");
  if (variant === "error" && text !== "-") return `<span class="inline-error">${escapeHtml(text)}</span>`;
  if (variant === "code") return `<code class="inline-code">${escapeHtml(text)}</code>`;
  return escapeHtml(text);
}

function renderDetailSlo(slo) {
  $("#detailSlo").innerHTML = ["24h", "7d", "30d", "90d"].map((key) => {
    const item = slo[key] || {};
    const uptime = item.uptime_percent ?? "-";
    return `<article class="slo-card detail-slo-card">
      <strong class="slo-period">${key}</strong>
      <span class="slo-value">${uptime === "-" ? "-" : `${uptime}%`}</span>
      <small class="slo-meta">Śr. ${item.avg_response_ms ? item.avg_response_ms + " ms" : "-"} · Incydenty ${item.incidents ?? 0} · Testy ${item.checks ?? 0}</small>
    </article>`;
  }).join("");
}

function renderDetailHistory(rows) {
  state.detailHistoryRows = rows || [];
  state.detailHistoryPage = 1;
  syncDetailHistoryInputs();
  renderDetailHistoryTable();
}

function renderDetailHistoryLoading() {
  state.detailHistoryRows = [];
  if ($("#detailHistorySummary")) $("#detailHistorySummary").textContent = "Ładowanie historii odpowiedzi...";
  if ($("#detailHistoryPage")) $("#detailHistoryPage").textContent = "Strona 1";
  if ($("#detailHistoryPrev")) $("#detailHistoryPrev").disabled = true;
  if ($("#detailHistoryNext")) $("#detailHistoryNext").disabled = true;
  const body = $("#detailHistoryRows");
  if (!body) return;
  body.innerHTML = Array.from({ length: 5 }).map(() => `
    <tr class="history-skeleton">
      <td><span></span></td><td><span></span></td><td><span></span></td>
      <td><span></span></td><td><span></span></td><td><span></span></td>
    </tr>
  `).join("");
}

function renderDetailHistoryError(error) {
  if ($("#detailHistorySummary")) $("#detailHistorySummary").textContent = "Nie udało się załadować historii odpowiedzi.";
  if ($("#detailHistoryRows")) {
    $("#detailHistoryRows").innerHTML = `<tr><td colspan="6" class="empty">${escapeHtml(error?.message || "Błąd ładowania historii.")}</td></tr>`;
  }
}

function renderDetailHistoryTable() {
  const body = $("#detailHistoryRows");
  if (!body) return;
  const filtered = sortDetailHistoryRows(filterDetailHistoryRows(state.detailHistoryRows));
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / state.detailHistoryPageSize));
  state.detailHistoryPage = Math.min(Math.max(state.detailHistoryPage, 1), pages);
  const start = total ? (state.detailHistoryPage - 1) * state.detailHistoryPageSize : 0;
  const pageRows = filtered.slice(start, start + state.detailHistoryPageSize);
  const end = start + pageRows.length;
  if ($("#detailHistorySummary")) {
    $("#detailHistorySummary").textContent = total
      ? `${start + 1}-${end} z ${total} wpisów`
      : "Brak wpisów historii dla wybranych filtrów";
  }
  if ($("#detailHistoryPage")) $("#detailHistoryPage").textContent = `Strona ${state.detailHistoryPage} z ${pages}`;
  if ($("#detailHistoryPrev")) $("#detailHistoryPrev").disabled = state.detailHistoryPage <= 1;
  if ($("#detailHistoryNext")) $("#detailHistoryNext").disabled = state.detailHistoryPage >= pages;
  if (!pageRows.length) {
    body.innerHTML = '<tr><td colspan="6" class="empty">Brak wpisów historii dla wybranych filtrów.</td></tr>';
    return;
  }
  body.innerHTML = pageRows.map((row) => {
    const details = parseDetails(row.details_json);
    const message = detailHistoryMessage(row, details);
    const latency = details.duration_ms ?? details.latency_ms ?? details.elapsed_ms ?? details.total_ms ?? "";
    return `<tr>
      <td>${renderHistoryDate(row.checked_at)}</td>
      <td><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status || "-")}</span></td>
      <td>${row.response_ms ? Number(row.response_ms).toFixed(1) + " ms" : "-"}</td>
      <td>${row.http_status || "-"}</td>
      <td><span class="history-message" title="${escapeHtml(message)}">${escapeHtml(message || "-")}</span></td>
      <td>${latency ? `${Number(latency).toFixed(1)} ms` : "-"}</td>
    </tr>`;
  }).join("");
}

function filterDetailHistoryRows(rows) {
  const filters = state.detailHistoryFilters;
  const from = filters.from ? new Date(`${filters.from}T00:00:00`) : null;
  const to = filters.to ? new Date(`${filters.to}T23:59:59`) : null;
  return rows.filter((row) => {
    const checkedAt = row.checked_at ? new Date(row.checked_at) : null;
    if (from && checkedAt && checkedAt < from) return false;
    if (to && checkedAt && checkedAt > to) return false;
    if (filters.status !== "all") {
      const status = String(row.status || "").toLowerCase();
      if (filters.status === "online" && !isSuccessStatus(status)) return false;
      if (filters.status === "offline" && status !== "offline") return false;
      if (filters.status === "error" && !isErrorStatus(status)) return false;
    }
    if (filters.search) {
      const details = parseDetails(row.details_json);
      const haystack = [
        row.status,
        row.http_status,
        row.response_ms,
        row.error,
        detailHistoryMessage(row, details),
      ].join(" ").toLowerCase();
      if (!haystack.includes(filters.search)) return false;
    }
    return true;
  });
}

function sortDetailHistoryRows(rows) {
  const sorted = [...rows];
  const numeric = (value) => value === null || value === undefined || value === "" ? Number.POSITIVE_INFINITY : Number(value);
  sorted.sort((a, b) => {
    if (state.detailHistoryFilters.sort === "date_asc") return new Date(a.checked_at || 0) - new Date(b.checked_at || 0);
    if (state.detailHistoryFilters.sort === "status") return String(a.status || "").localeCompare(String(b.status || ""));
    if (state.detailHistoryFilters.sort === "response") return numeric(a.response_ms) - numeric(b.response_ms);
    if (state.detailHistoryFilters.sort === "http") return numeric(a.http_status) - numeric(b.http_status);
    return new Date(b.checked_at || 0) - new Date(a.checked_at || 0);
  });
  return sorted;
}

function detailHistoryMessage(row, details = parseDetails(row.details_json)) {
  return [
    row.error || "",
    details.error_message || "",
    details.final_url ? `URL: ${details.final_url}` : "",
    details.bytes ? `Rozmiar: ${details.bytes} B` : "",
    details.expected_status_codes ? `Oczekiwane: ${formatDetailListValue(details.expected_status_codes)}` : "",
    details.response_hash ? `Hash: ${String(details.response_hash).slice(0, 12)}` : "",
    row.content_changed ? "Zmieniona zawartość" : "",
  ].filter(Boolean).join(" · ");
}

function formatDetailListValue(value) {
  return Array.isArray(value) ? value.join(", ") : String(value);
}

function renderHistoryDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return escapeHtml(String(value));
  return `<span class="history-date"><strong>${date.toLocaleDateString("pl-PL")}</strong><span>${date.toLocaleTimeString("pl-PL")}</span></span>`;
}

function resetDetailHistoryState() {
  state.detailHistoryRows = [];
  state.detailHistoryPage = 1;
  state.detailHistoryFilters = { from: "", to: "", status: "all", search: "", sort: "date_desc" };
  syncDetailHistoryInputs();
}

function syncDetailHistoryInputs() {
  const filters = state.detailHistoryFilters;
  if ($("#detailHistoryFrom")) $("#detailHistoryFrom").value = filters.from;
  if ($("#detailHistoryTo")) $("#detailHistoryTo").value = filters.to;
  if ($("#detailHistoryStatus")) $("#detailHistoryStatus").value = filters.status;
  if ($("#detailHistorySort")) $("#detailHistorySort").value = filters.sort;
  if ($("#detailHistorySearch")) $("#detailHistorySearch").value = filters.search;
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
        <button data-group-action="filter" data-id="${group.id}">Pokaż monitory</button>
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
  renderGroupMonitorList();
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
  if (action === "filter") {
    state.monitorGroupFilter = String(id);
    if ($("#monitorGroupFilter")) $("#monitorGroupFilter").value = String(id);
    renderGroupMonitorList(id);
    showView("monitoring");
    renderMonitorLists();
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

function renderGroupMonitorList(groupId = Number(state.monitorGroupFilter) || null) {
  const root = $("#groupMonitorList");
  if (!root) return;
  if (!groupId) {
    root.classList.add("empty");
    root.innerHTML = "Wybierz grupę kartą lub filtrem.";
    return;
  }
  const monitors = state.monitors.filter((monitor) => Number(monitor.group_id) === Number(groupId));
  root.classList.toggle("empty", !monitors.length);
  root.innerHTML = monitors.length
    ? monitors.map((monitor) => `
      <button class="list-item clickable-monitor" data-card-id="${monitor.id}" type="button">
        <strong>${escapeHtml(monitor.name)}</strong>
        <small>${escapeHtml(typeLabel(monitor.type))} · ${escapeHtml(monitor.status)} · ${formatResponse(monitor.last_response_ms)}</small>
      </button>
    `).join("")
    : "Brak monitorów w tej grupie.";
  bindMonitorOpeners(root);
}

async function applyMaintenanceDuration(minutes) {
  const form = $("#maintenanceForm");
  const id = Number(form.elements.id.value);
  if (!id) return;
  $("#maintenanceDialog").close();
  await setMonitorMaintenance(id, minutes);
}

async function clearMaintenanceFromDialog() {
  const form = $("#maintenanceForm");
  const id = Number(form.elements.id.value);
  if (!id) return;
  $("#maintenanceDialog").close();
  await clearMonitorMaintenance(id);
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
  form.elements.interval_seconds.value = getMonitorFormInterval(monitor);
  form.elements.enabled.checked = monitor.enabled !== false;
  form.elements.test_on_save.checked = !monitor.id;
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
  updateConfigPreview();
  $("#monitorDialog").showModal();
}

function getMonitorFormInterval(monitor) {
  if (monitor.interval_seconds !== undefined && monitor.interval_seconds !== null && monitor.interval_seconds !== "") {
    return monitor.interval_seconds;
  }
  return monitor.id ? "" : getDefaultMonitorIntervalSeconds();
}

function getDefaultMonitorIntervalSeconds() {
  const value = Number(state.settings?.default_interval_seconds);
  return Number.isFinite(value) && value >= 5 ? value : 300;
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

function updateConfigPreview() {
  const preview = $("#configPreview");
  const form = $("#monitorForm");
  if (!preview || !form) return;
  try {
    preview.textContent = JSON.stringify(buildMonitorPayload(form), null, 2);
  } catch (_) {
    preview.textContent = "{}";
  }
}

async function testMonitorFromForm(event) {
  event?.preventDefault();
  event?.stopPropagation();
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
    ["limit", $("#historyLimit")?.value || "250"],
  ];
  mapping.forEach(([key, value]) => value && params.set(key, value));
  let rows = await api(`/api/history?${params.toString()}`);
  const groupFilter = $("#historyGroup")?.value || "";
  if (groupFilter) {
    rows = rows.filter((row) => {
      const monitor = state.monitors.find((item) => item.id === row.monitor_id);
      if (groupFilter === "none") return !monitor?.group_id;
      return String(monitor?.group_id || "") === String(groupFilter);
    });
  }
  $("#historyRows").innerHTML = rows.length ? rows.map((row, index) => `
    <tr class="${isErrorStatus(row.status) ? "history-error" : ""}" data-history-index="${index}">
      <td>${formatDate(row.checked_at)}</td>
      <td>${escapeHtml(row.monitor_name)}<br><small>${escapeHtml(row.target)}</small></td>
      <td><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span></td>
      <td>${formatResponse(row.response_ms)}</td>
      <td>${row.http_status || "-"}</td>
      <td>${hashHtml(row.content_hash)}</td>
      <td>${row.packet_loss ?? "-"}</td>
      <td>${escapeHtml(row.error || "-")}</td>
    </tr>
  `).join("") : '<tr><td colspan="8" class="empty">Brak wpisów historii dla wybranych filtrów.</td></tr>';
  $$("[data-history-index]").forEach((row) => {
    row.addEventListener("click", () => openHistoryDetails(rows[Number(row.dataset.historyIndex)]));
  });
}

function applyHistoryRange(event) {
  const value = event.currentTarget.dataset.historyRange;
  const now = new Date();
  const from = new Date(now);
  if (value === "1h") from.setHours(now.getHours() - 1);
  if (value === "24h") from.setDate(now.getDate() - 1);
  if (value === "7d") from.setDate(now.getDate() - 7);
  if (value === "30d") from.setDate(now.getDate() - 30);
  $("#historyFrom").value = toDatetimeLocalValue(from.toISOString());
  $("#historyTo").value = toDatetimeLocalValue(now.toISOString());
  loadHistory();
}

function openHistoryDetails(row) {
  const node = $("#historyDetailData");
  node.innerHTML = definitionRows({
    Monitor: row.monitor_name,
    Target: row.target,
    Status: row.status,
    Data: formatDate(row.checked_at),
    "Czas odpowiedzi": formatResponse(row.response_ms),
    HTTP: row.http_status || "-",
    "Suma WWW": row.content_hash || "-",
    Błąd: row.error || "-",
    Szczegóły: row.details_json || "{}",
  });
  $("#historyDialog").showModal();
}

function renderSettings() {
  if (!state.settings) return;
  const form = $("#settingsForm");
  if (state.settings.default_timeout_minutes === undefined && state.settings.request_timeout_seconds !== undefined) {
    state.settings.default_timeout_minutes = Number(state.settings.request_timeout_seconds) / 60;
  }
  if (state.settings.default_interval_seconds === undefined) {
    state.settings.default_interval_seconds = Number(state.settings.default_website_interval || state.settings.default_device_interval || 300);
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
    default_interval_seconds: Number(form.elements.default_interval_seconds.value),
    default_timeout_minutes: Number(form.elements.default_timeout_minutes.value),
    max_concurrent_checks: Number(form.elements.max_concurrent_checks.value),
    failure_threshold: Number(form.elements.failure_threshold.value),
    recovery_threshold: Number(form.elements.recovery_threshold.value),
    retry_delay_seconds: Number(form.elements.retry_delay_seconds.value),
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
  if (normalized.default_interval_seconds === undefined) {
    normalized.default_interval_seconds = Number(normalized.default_website_interval || normalized.default_device_interval || 300);
  }
  if (normalized.max_page_size_mb === undefined && normalized.max_page_size_kb !== undefined) {
    normalized.max_page_size_mb = Number(normalized.max_page_size_kb) / 1024;
  }
  normalized.max_concurrent_checks ??= state.settings?.max_concurrent_checks ?? 15;
  normalized.failure_threshold ??= state.settings?.failure_threshold ?? 3;
  normalized.recovery_threshold ??= state.settings?.recovery_threshold ?? 2;
  normalized.retry_delay_seconds ??= state.settings?.retry_delay_seconds ?? 10;
  delete normalized.request_timeout_seconds;
  delete normalized.ping_timeout_seconds;
  delete normalized.default_device_interval;
  delete normalized.default_website_interval;
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
    "Ostatni tick schedulera": formatDate(diagnostics.scheduler_last_tick),
    "Aktywne zadania": diagnostics.active_jobs?.join(", ") || "-",
    "Oczekujące zadania": diagnostics.queued_jobs?.join(", ") || "-",
    "Limit równoległości": diagnostics.max_concurrent_checks,
    "Błędy schedulera": diagnostics.scheduler_error_count ?? 0,
    "Ostatni błąd schedulera": diagnostics.scheduler_last_error || "-",
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

async function loadDiagnosticsModern() {
  const [diagnostics, logs] = await Promise.all([
    api("/api/diagnostics"),
    api("/api/logs"),
  ]);
  state.diagnostics = diagnostics;
  renderSchedulerStatus();
  $("#diagnosticsData").innerHTML = definitionRows({
    Wersja: diagnostics.version,
    "Status bazy": diagnostics.database_exists ? "OK" : "Brak",
    "Ścieżka bazy": diagnostics.database_path,
    "Rozmiar bazy": `${diagnostics.database_size_bytes} B`,
    "Rozmiar WAL": `${diagnostics.wal_size_bytes} B`,
    "Liczba monitorów": diagnostics.monitor_count,
    "Wpisy historii": diagnostics.check_count,
    "Ostatni test": formatDate(diagnostics.last_check),
    "Ostatni tick schedulera": formatDate(diagnostics.scheduler_last_tick),
    "Aktywne zadania": diagnostics.active_jobs?.join(", ") || "-",
    "Oczekujące zadania": diagnostics.queued_jobs?.join(", ") || "-",
    "Limit równoległości": diagnostics.max_concurrent_checks,
    "Błędy schedulera": diagnostics.scheduler_error_count ?? 0,
    "Ostatni błąd schedulera": diagnostics.scheduler_last_error || "-",
    "Encje HA": diagnostics.settings?.publish_home_assistant_entities ? "włączone" : "wyłączone",
    "Eventy HA": diagnostics.settings?.publish_home_assistant_events ? "włączone" : "wyłączone",
    "Plik logu": diagnostics.log_file,
  });
  renderList("#diagnosticsErrors", diagnostics.errors || [], (row) => `
    <div class="list-item">
      <strong>${escapeHtml(row.error || "Błąd")}</strong>
      <small>${formatDate(row.checked_at)} · monitor ${row.monitor_id || "-"}</small>
    </div>
  `);
  $("#logsBox").textContent = logs || "Brak logów.";
}

loadDiagnostics = loadDiagnosticsModern;

function renderList(selector, items, renderer) {
  const root = $(selector);
  if (!root) return;
  if (!items.length) {
    root.classList.add("empty");
    root.innerHTML = "Brak danych";
    return;
  }
  root.classList.remove("empty");
  root.innerHTML = items.map(renderer).join("");
}

async function loadIncidents() {
  state.incidents = await api("/api/incidents?limit=100");
  renderIncidents();
  renderDashboard();
}

function renderIncidentMonitorOptions() {
  const select = $("#incidentMonitorFilter");
  if (!select) return;
  const current = state.incidentMonitorFilter;
  select.innerHTML = [
    '<option value="">Wszystkie</option>',
    ...state.monitors.map((monitor) => `<option value="${monitor.id}">${escapeHtml(monitor.name)}</option>`),
  ].join("");
  select.value = state.monitors.some((monitor) => String(monitor.id) === String(current)) ? current : "";
  state.incidentMonitorFilter = select.value;
}

function renderIncidents() {
  if ($("#incidentStatusFilter")) $("#incidentStatusFilter").value = state.incidentStatusFilter;
  if ($("#incidentMonitorFilter")) $("#incidentMonitorFilter").value = state.incidentMonitorFilter;
  const monitorId = state.incidentMonitorFilter ? Number(state.incidentMonitorFilter) : null;
  const incidents = (state.incidents || []).filter((incident) => {
    if (state.incidentStatusFilter !== "all" && incident.status !== state.incidentStatusFilter) return false;
    if (monitorId && Number(incident.monitor_id) !== monitorId) return false;
    return true;
  });
  renderIncidentList("#incidentsList", incidents);
}

async function loadEvents() {
  state.events = await api("/api/events");
  renderEvents();
}

function renderEvents() {
  const query = state.eventQuery;
  const events = (state.events || []).filter((event) => {
    if (state.eventTypeFilter && event.event_type !== state.eventTypeFilter) return false;
    if (!query) return true;
    const payload = event.payload || {};
    return [
      event.event_type,
      payload.monitor_name,
      payload.target,
      payload.previous_state,
      payload.new_state,
      JSON.stringify(payload.details || {}),
    ].filter(Boolean).join(" ").toLowerCase().includes(query);
  });
  renderList("#eventsList", events, (event) => {
    const payload = event.payload || {};
    return `
      <article class="event-item">
        <span class="event-icon" aria-hidden="true">${eventIcon(event.event_type)}</span>
        <div>
          <strong>${escapeHtml(event.event_type)}</strong>
          <p>${escapeHtml(payload.monitor_name || "System")} ${payload.target ? "· " + escapeHtml(payload.target) : ""}</p>
          <small>${escapeHtml(payload.previous_state || "-")} → ${escapeHtml(payload.new_state || "-")}</small>
        </div>
        <small>${formatDate(event.created_at)} · HA: ${event.delivered_to_ha ? "tak" : "nie"}</small>
      </article>
    `;
  });
}

function eventIcon(type) {
  if (String(type).includes("offline") || String(type).includes("error")) return "!";
  if (String(type).includes("online")) return "✓";
  if (String(type).includes("changed")) return "↕";
  if (String(type).includes("ssl")) return "SSL";
  return "•";
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

function formatResponse(value) {
  return value ? `${Number(value).toFixed(1)} ms` : "-";
}

function debounce(fn, delay = 200) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
}

async function runWithButtonLoading(button, fn) {
  const previous = button.textContent;
  button.disabled = true;
  button.textContent = "Pracuję...";
  try {
    return await fn();
  } finally {
    button.disabled = false;
    button.textContent = previous;
  }
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

function toDateInputValue(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 10);
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

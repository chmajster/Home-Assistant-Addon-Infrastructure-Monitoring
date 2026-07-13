import { api } from "./api.js";
import { state } from "./state.js";
import { $, $$, debounce } from "./utils.js";
import { activateView } from "./router.js";
import { installDialogAccessibility } from "./components/dialogs.js";
import { groupStatusLabel, incidentCountLabel, sloUptimeLabel } from "./components/groups.js";

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
  monitoring_center_health: "system",
};

let testRunTimer;
let refreshController;
let refreshPromise;

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initDensity();
  bindNavigation();
  bindForms();
  installDialogAccessibility();
  window.addEventListener("monitoring-api-error", (event) => toast(event.detail, "error"));
  refreshAll();
  setInterval(() => { if (!document.hidden) refreshAll(); }, 30000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) refreshController?.abort();
    else refreshAll();
  });
});

function bindNavigation() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      showView(button.dataset.tab);
      if (button.dataset.tab === "diagnostics") loadDiagnostics();
      if (button.dataset.tab === "history") loadHistory();
      if (button.dataset.tab === "events") loadEvents();
      if (button.dataset.tab === "incidents") renderIncidents();
      if (button.dataset.tab === "topology") loadTopology();
    });
  });
  $("#refreshBtn").addEventListener("click", manualRefresh);
  $("#brandHomeBtn")?.addEventListener("click", () => showView("dashboard"));
  $("#themeMode")?.addEventListener("change", (event) => applyTheme(event.currentTarget.value));
  $("#toast").addEventListener("click", hideToast);
  $("#detailBackBtn").addEventListener("click", () => showView("monitoring"));
  $("#testBackBtn").addEventListener("click", backFromMonitorTest);
  $("#testRepeatBtn").addEventListener("click", () => {
    if (state.currentTest?.monitorId) startMonitorTestRun(state.currentTest.monitorId, state.currentTest.returnView);
    else if (state.currentTest?.discoveryProposal) startDiscoveryTestRun(state.currentTest.discoveryProposal);
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
  $("#openDiscoveryBtn")?.addEventListener("click", openDiscoveryDialog);
  $("#addCredentialBtn")?.addEventListener("click", () => openCredentialForm());
  $("#runSelfCheckBtn")?.addEventListener("click", runSelfCheck);
  $("#createSelfMonitorBtn")?.addEventListener("click", createSelfMonitor);
  bindDetailHistoryControls();
  $$("[data-open-form]").forEach((button) => {
    button.addEventListener("click", () => openMonitorForm({ type: button.dataset.openForm }));
  });
}

function bindForms() {
  $("#monitorForm").addEventListener("submit", saveMonitor);
  $("#cancelMonitorBtn").addEventListener("click", () => $("#monitorDialog").close());
  $("#testMonitorBtn").addEventListener("click", testMonitorFromForm);
  $("#discoveryForm")?.addEventListener("submit", runDiscoveryScan);
  $("#discoverySearch")?.addEventListener("input", (event) => {
    state.discoveryQuery = event.currentTarget.value;
    renderDiscoveryResults();
  });
  $("#closeDiscoveryBtn")?.addEventListener("click", () => $("#discoveryDialog").close());
  $("#importDiscoveryBtn")?.addEventListener("click", importDiscoverySelection);
  $("#groupForm").addEventListener("submit", saveGroup);
  $("#credentialForm").addEventListener("submit", saveCredential);
  $("#credentialForm").elements.kind.addEventListener("change", renderCredentialSecretFields);
  $("#monitorCredentialSelect").addEventListener("change", renderSelectedMonitorCredential);
  $("#manageCredentialsBtn").addEventListener("click", () => {
    $("#monitorDialog").close();
    showView("credentials");
  });
  $("#cancelGroupEditBtn").addEventListener("click", resetGroupForm);
  $("#groupForm").elements.color.addEventListener("input", syncGroupColorFromPicker);
  $("#groupForm").elements.color_hex.addEventListener("input", syncGroupColorFromHex);
  $("#groupMaintenanceForm").addEventListener("submit", saveGroupMaintenanceFromDialog);
  $("#openGroupMonitoringBtn").addEventListener("click", openSelectedGroupInMonitoring);
  document.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest(".group-action-menu")) return;
    $$(".group-action-menu", $("#groupList")).forEach((menu) => menu.removeAttribute("open"));
  });
  $("#monitorTypeSelect").addEventListener("change", () => renderTypeFields($("#monitorTypeSelect").value));
  $("#monitorForm").addEventListener("input", updateConfigPreview);
  $("#monitorForm").addEventListener("change", updateConfigPreview);
  $("#applyPresetBtn").addEventListener("click", applyPreset);
  $("#copyConfigBtn")?.addEventListener("click", copyConfigPreview);
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
  $("#topologySaveBtn")?.addEventListener("click", saveTopology);
  $("#topologyAutoLayoutBtn")?.addEventListener("click", autoLayoutTopology);
  $("#topologyConnectBtn")?.addEventListener("click", toggleTopologyConnectMode);
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
  if (document.hidden) return;
  if (refreshPromise) return refreshPromise;
  refreshController = new AbortController();
  refreshPromise = api("/api/bootstrap", { signal: refreshController.signal }).then((bootstrap) => {
  state.summary = bootstrap.summary;
  state.monitors = bootstrap.monitors;
  state.groups = bootstrap.groups;
  state.credentials = bootstrap.credentials || [];
  state.settings = bootstrap.settings;
  state.monitorTypes = bootstrap.monitor_types;
  state.presets = bootstrap.presets;
  state.incidents = bootstrap.incidents;
  state.topology = bootstrap.topology;
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
  renderCredentials();
  renderHistoryMonitorOptions();
  renderIncidentMonitorOptions();
  renderIncidents();
  renderTopology();
  renderDetailMonitorOptions();
  renderSettings();
  if ($("#events")?.classList.contains("active")) loadEvents();
  if ($("#monitorDetail").classList.contains("active") && state.selectedMonitorId) {
    renderMonitorDetailsShell(state.selectedMonitorId);
  }
  if ($("#monitorTestRun").classList.contains("active") && state.currentTest?.monitorId) {
    renderMonitorTestRun();
  }
  }).catch((error) => {
    if (error.name !== "AbortError") console.warn("Częściowe odświeżenie nie powiodło się", error);
  }).finally(() => { refreshPromise = null; refreshController = null; });
  return refreshPromise;
}

async function manualRefresh() {
  await refreshAll();
  toast("Odświeżono dane.");
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
  activateView(viewId, activeTab);
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
  if ($("#metricAnomalies")) $("#metricAnomalies").textContent = summary.active_anomalies ?? 0;
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
    <button class="type-card ${type.type === selected ? "active" : ""}" type="button" data-monitor-type="${type.type}" aria-pressed="${type.type === selected}">
      <span class="type-card-title">${escapeHtml(typeDisplayName(type))}</span>
      <span class="type-card-meta">${escapeHtml(type.category || "monitor")} · ${type.default_interval || "-"}s</span>
      ${type.description ? `<small>${escapeHtml(type.description)}</small>` : ""}
      ${type.type === selected ? '<span class="type-selected">Wybrany</span>' : ""}
    </button>
  `).join("");
  $$("[data-monitor-type]", root).forEach((button) => {
    button.addEventListener("click", () => {
      $("#monitorTypeSelect").value = button.dataset.monitorType;
      renderTypeFields(button.dataset.monitorType);
    });
  });
}

function typeDisplayName(type) {
  const key = typeof type === "string" ? type : type.type;
  const labels = {
    ping_host: "Ping hosta",
    tcp_port: "Port TCP",
    http_status: "WWW status HTTP/HTTPS",
    http_hash: "WWW hash zawartości",
    dns_lookup: "DNS lookup",
    ssl_certificate: "Certyfikat SSL",
    rest_api: "REST API",
    ha_entity: "Encja Home Assistant",
    mqtt_monitor: "MQTT monitor",
    ssh_command: "SSH / Bash",
    docker_container: "Docker Container",
    docker_compose_service: "Docker Compose Service",
    docker_healthcheck: "Docker Healthcheck",
    linux_host: "Linux Host Health",
    disk_usage: "Disk Usage",
    backup_age: "Backup Age",
    backup_file: "Backup File",
    ha_backup: "Home Assistant Backup",
    ha_health: "Home Assistant Health",
    pihole_health: "Pi-hole Health",
    unifi_device: "UniFi Device",
    unifi_wan: "UniFi WAN",
    snmp_oid: "SNMP OID",
    snmp_interface: "SNMP Interface",
    ssh_log_regex: "SSH Log Regex",
    journald_regex: "Journald Regex",
    docker_log_regex: "Docker Log Regex",
    file_exists: "File Exists",
    file_age: "File Age",
    file_hash: "File Hash",
    directory_size: "Directory Size",
    directory_file_count: "Directory File Count",
  };
  return labels[key] || type.label || key;
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
  renderDiscoveryResults();
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

async function loadTopology() {
  state.topology = await api("/api/topology");
  renderTopology();
}

function renderTopology() {
  const canvas = $("#topologyCanvas");
  const nodesRoot = $("#topologyNodes");
  const edgesRoot = $("#topologyEdges");
  if (!canvas || !nodesRoot || !edgesRoot) return;
  const nodes = state.topology?.nodes || [];
  const edges = state.topology?.edges || [];
  edgesRoot.setAttribute("viewBox", `0 0 ${canvas.clientWidth || 1000} ${canvas.clientHeight || 640}`);
  if (!nodes.length) {
    nodesRoot.innerHTML = '<div class="topology-empty">Uzyj Auto-layout, aby utworzyc mape z istniejacych monitorow.</div>';
    edgesRoot.innerHTML = "";
    return;
  }
  nodesRoot.innerHTML = nodes.map((node) => `
    <button class="topology-node ${topologyStatusClass(node.status)} ${state.topologyConnectSource === node.id ? "connect-source" : ""}"
      type="button" data-node-id="${node.id}" style="left:${Number(node.x || 0)}px;top:${Number(node.y || 0)}px"
      title="${escapeHtml(node.monitor ? "Otworz monitor " + node.monitor.name : node.name)}">
      <span class="topology-node-icon">${escapeHtml(topologyIconLabel(node))}</span>
      <strong>${escapeHtml(node.name)}</strong>
      <small>${escapeHtml(node.status || "neutral")}</small>
    </button>
  `).join("");
  bindTopologyNodes();
  renderTopologyEdges(edgesRoot, canvas, nodes, edges);
}

function renderTopologyEdges(root, canvas, nodes, edges) {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  root.innerHTML = edges.map((edge) => {
    const source = byId.get(edge.source_node_id);
    const target = byId.get(edge.target_node_id);
    if (!source || !target) return "";
    const x1 = Number(source.x || 0) + 68;
    const y1 = Number(source.y || 0) + 34;
    const x2 = Number(target.x || 0) + 68;
    const y2 = Number(target.y || 0) + 34;
    const labelX = (x1 + x2) / 2;
    const labelY = (y1 + y2) / 2 - 6;
    return `<g>
      <line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"></line>
      ${edge.label ? `<text x="${labelX}" y="${labelY}">${escapeHtml(edge.label)}</text>` : ""}
    </g>`;
  }).join("");
  root.setAttribute("viewBox", `0 0 ${canvas.clientWidth || 1000} ${canvas.clientHeight || 640}`);
}

function bindTopologyNodes() {
  $$(".topology-node").forEach((nodeEl) => {
    nodeEl.addEventListener("click", handleTopologyNodeClick);
    nodeEl.addEventListener("pointerdown", startTopologyDrag);
  });
}

function handleTopologyNodeClick(event) {
  const nodeId = Number(event.currentTarget.dataset.nodeId);
  const node = state.topology.nodes.find((item) => item.id === nodeId);
  if (!node) return;
  if (state.topologyConnectMode) {
    event.preventDefault();
    if (!state.topologyConnectSource) {
      state.topologyConnectSource = nodeId;
      renderTopology();
      return;
    }
    if (state.topologyConnectSource !== nodeId) {
      const exists = state.topology.edges.some((edge) => edge.source_node_id === state.topologyConnectSource && edge.target_node_id === nodeId);
      if (!exists) {
        state.topology.edges.push({ source_node_id: state.topologyConnectSource, target_node_id: nodeId, label: "", metadata: {} });
      }
    }
    state.topologyConnectSource = null;
    renderTopology();
    return;
  }
  if (node.monitor_id) showMonitorDetails(Number(node.monitor_id));
}

function startTopologyDrag(event) {
  if (state.topologyConnectMode) return;
  const nodeEl = event.currentTarget;
  const nodeId = Number(nodeEl.dataset.nodeId);
  const node = state.topology.nodes.find((item) => item.id === nodeId);
  const canvas = $("#topologyCanvas");
  if (!node || !canvas) return;
  const rect = canvas.getBoundingClientRect();
  const offsetX = event.clientX - rect.left - Number(node.x || 0);
  const offsetY = event.clientY - rect.top - Number(node.y || 0);
  nodeEl.setPointerCapture(event.pointerId);
  const move = (moveEvent) => {
    node.x = Math.max(8, Math.min((canvas.clientWidth || 1000) - 150, moveEvent.clientX - rect.left - offsetX));
    node.y = Math.max(8, Math.min((canvas.clientHeight || 640) - 82, moveEvent.clientY - rect.top - offsetY));
    nodeEl.style.left = `${node.x}px`;
    nodeEl.style.top = `${node.y}px`;
    renderTopologyEdges($("#topologyEdges"), canvas, state.topology.nodes, state.topology.edges);
  };
  const stop = () => {
    nodeEl.removeEventListener("pointermove", move);
    nodeEl.removeEventListener("pointerup", stop);
    nodeEl.removeEventListener("pointercancel", stop);
  };
  nodeEl.addEventListener("pointermove", move);
  nodeEl.addEventListener("pointerup", stop);
  nodeEl.addEventListener("pointercancel", stop);
}

function toggleTopologyConnectMode() {
  state.topologyConnectMode = !state.topologyConnectMode;
  state.topologyConnectSource = null;
  $("#topologyConnectBtn")?.setAttribute("aria-pressed", String(state.topologyConnectMode));
  $("#topologyConnectBtn")?.classList.toggle("active", state.topologyConnectMode);
  renderTopology();
}

async function saveTopology() {
  state.topology = await api("/api/topology", {
    method: "PUT",
    body: JSON.stringify(state.topology),
  });
  renderTopology();
  toast("Mapa topologii zapisana.");
}

async function autoLayoutTopology() {
  state.topology = await api("/api/topology/auto-layout", { method: "POST" });
  renderTopology();
  toast("Auto-layout zastosowany.");
}

function topologyStatusClass(status) {
  if (isErrorStatus(status)) return "bad";
  if (status === "warning") return "warning";
  if (isSuccessStatus(status)) return "ok";
  return "neutral";
}

function topologyIconLabel(node) {
  const type = node.icon || node.type || "other";
  return {
    cloud: "WAN",
    router: "RTR",
    network: "SW",
    wifi: "AP",
    server: "SRV",
    cpu: "IoT",
    box: "SVC",
    circle: "DEV",
    internet: "WAN",
    switch: "SW",
    ap: "AP",
    service: "SVC",
    iot: "IoT",
  }[type] || String(type).slice(0, 3).toUpperCase();
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

const SSH_CONFIG_TYPES = new Set([
  "ssh_command", "docker_container", "docker_compose_service", "docker_healthcheck", "linux_host", "disk_usage",
  "backup_age", "backup_file", "ha_backup", "unifi_device", "unifi_wan", "ssh_log_regex", "journald_regex",
  "docker_log_regex", "file_exists", "file_age", "file_hash", "directory_size", "directory_file_count",
]);
const DOCKER_TYPES = new Set(["docker_container", "docker_compose_service", "docker_healthcheck"]);
const BACKUP_FILE_TYPES = new Set([
  "backup_age", "backup_file", "ha_backup", "file_exists", "file_age", "file_hash", "directory_size",
  "directory_file_count",
]);
const LOG_REGEX_TYPES = new Set(["ssh_log_regex", "journald_regex", "docker_log_regex"]);
const SNMP_TYPES = new Set(["snmp_oid", "snmp_interface"]);

function renderTypeFields(type) {
  $$(".type-options").forEach((node) => node.classList.add("hidden"));
  const targetLabels = {
    ping_host: ["Host lub IP", "192.168.1.1 albo router.local"],
    tcp_port: ["Host lub IP", "192.168.1.10:443 albo example.com:443"],
    http_status: ["URL lub domena", "https://example.com"],
    http_hash: ["URL lub domena", "https://example.com"],
    dns_lookup: ["URL lub domena", "example.com"],
    ssl_certificate: ["URL lub domena", "example.com"],
    rest_api: ["URL lub domena", "https://example.com/api/status"],
    ha_entity: ["Entity ID", "sensor.example"],
    monitoring_center_health: ["Cel", "self"],
    mqtt_monitor: ["Topic lub broker", "home/topic/status"],
    ssh_command: ["Host SSH", "192.168.1.10:22"],
    docker_container: ["Host SSH i kontener", "192.168.1.50:homeassistant"],
    docker_compose_service: ["Host SSH i usluga", "192.168.1.50:homeassistant"],
    docker_healthcheck: ["Host SSH i kontener", "192.168.1.50:homeassistant"],
    linux_host: ["Host SSH", "192.168.1.50:22"],
    disk_usage: ["Host SSH i mountpoint", "192.168.1.50:/"],
    backup_age: ["Host SSH i katalog", "192.168.1.50:/backup"],
    backup_file: ["Host SSH i katalog", "192.168.1.50:/backup"],
    ha_backup: ["Host SSH i katalog", "192.168.1.50:/backup"],
    ha_health: ["Cel", "home_assistant"],
    pihole_health: ["Pi-hole URL", "http://192.168.1.2/admin"],
    unifi_device: ["Host SSH i urzadzenie", "192.168.1.1"],
    unifi_wan: ["Host SSH i WAN target", "8.8.8.8"],
    snmp_oid: ["Host i OID", "192.168.1.1"],
    snmp_interface: ["Host i interfejs", "192.168.1.1"],
    ssh_log_regex: ["Host SSH i log", "192.168.1.50:/var/log/syslog"],
    journald_regex: ["Host SSH", "192.168.1.50:22"],
    docker_log_regex: ["Host SSH i kontener", "192.168.1.50:homeassistant"],
    file_exists: ["Host SSH i sciezka", "192.168.1.50:/backup/file.tar"],
    file_age: ["Host SSH i sciezka", "192.168.1.50:/backup"],
    file_hash: ["Host SSH i plik", "192.168.1.50:/etc/hosts"],
    directory_size: ["Host SSH i katalog", "192.168.1.50:/backup"],
    directory_file_count: ["Host SSH i katalog", "192.168.1.50:/backup"],
  };
  const [label, placeholder] = targetLabels[type] || ["Cel monitorowania", "IP, hostname, URL albo entity_id"];
  if ($("#targetLabelText")) $("#targetLabelText").textContent = label;
  const targetInput = $("#targetLabel input");
  if (targetInput) targetInput.placeholder = placeholder;
  const visibleSections = [];
  if (type === "tcp_port") visibleSections.push("#tcpOptions");
  if (["http_status", "http_hash", "rest_api"].includes(type)) visibleSections.push("#httpOptions");
  if (type === "http_hash") visibleSections.push("#websiteOptions");
  if (type === "dns_lookup") visibleSections.push("#dnsOptions");
  if (type === "ssl_certificate") visibleSections.push("#sslOptions");
  if (type === "rest_api") visibleSections.push("#restOptions");
  if (type === "ha_entity") visibleSections.push("#haEntityOptions");
  if (type === "mqtt_monitor") visibleSections.push("#mqttOptions");
  if (SSH_CONFIG_TYPES.has(type)) visibleSections.push("#sshOptions");
  if (DOCKER_TYPES.has(type)) visibleSections.push("#dockerOptions");
  if (type === "linux_host") visibleSections.push("#linuxOptions");
  if (type === "disk_usage") visibleSections.push("#diskOptions");
  if (BACKUP_FILE_TYPES.has(type)) visibleSections.push("#backupOptions");
  if (type === "ha_health") visibleSections.push("#haHealthOptions");
  if (type === "pihole_health") visibleSections.push("#piholeOptions");
  if (SNMP_TYPES.has(type)) visibleSections.push("#snmpOptions");
  if (LOG_REGEX_TYPES.has(type)) visibleSections.push("#logRegexOptions");
  visibleSections.forEach((selector) => $(selector)?.classList.remove("hidden"));
  $("#typeOptionsSection")?.classList.toggle("hidden", visibleSections.length === 0);
  renderMonitorCredentialOptions(type);
  renderMonitorTypeCards();
  updateConfigPreview();
}

function renderMonitorCredentialOptions(type) {
  const select = $("#monitorCredentialSelect");
  const typeMetadata = state.monitorTypes.find((item) => item.type === type);
  const allowedKinds = typeMetadata?.credential_kinds || [];
  const previous = select.value;
  const compatible = state.credentials.filter((credential) => allowedKinds.includes(credential.kind));
  select.innerHTML = '<option value="">Brak profilu – użyj danych wpisanych w monitorze</option>'
    + compatible.map((credential) => `<option value="${credential.id}">${escapeHtml(credential.name)}</option>`).join("");
  if (previous && compatible.some((credential) => String(credential.id) === previous)) select.value = previous;
  else if (previous) toast("Wybrany profil nie jest kompatybilny z nowym typem monitora.", "error");
  select.disabled = allowedKinds.length === 0;
  $("#monitorCredentialSection").classList.toggle("credential-not-supported", allowedKinds.length === 0);
  renderSelectedMonitorCredential();
}

function renderSelectedMonitorCredential() {
  const form = $("#monitorForm");
  const info = $("#monitorCredentialInfo");
  const credential = state.credentials.find((item) => String(item.id) === form.elements.credential_id.value);
  const hasProfile = Boolean(credential);
  $$(".direct-credential-field", form).forEach((field) => field.classList.toggle("hidden", hasProfile));
  if (form.elements.credential_id.disabled) {
    info.className = "credential-info empty";
    info.textContent = "Ten typ monitora nie używa profili danych dostępowych.";
  } else if (!credential) {
    info.className = "credential-info";
    info.textContent = "Poświadczenia będą pobierane bezpośrednio z konfiguracji monitora.";
  } else {
    info.className = "credential-info credential-info--selected";
    info.innerHTML = `
      <strong>${escapeHtml(credential.name)}</strong>
      <span>${escapeHtml(credentialKindLabel(credential.kind))} · login: ${escapeHtml(credential.username || "—")}</span>
      <small>${escapeHtml(credentialSecretSummary(credential))}. Poświadczenia będą pobierane z profilu podczas każdego testu.</small>`;
  }
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
    if (!form.elements.credential_id.value) {
      if (form.elements.mqtt_username.value.trim()) config.username = form.elements.mqtt_username.value.trim();
      if (form.elements.mqtt_password.value) config.password = form.elements.mqtt_password.value;
    }
  }
  if (SSH_CONFIG_TYPES.has(type)) addSshConfig(config, form);
  if (DOCKER_TYPES.has(type)) addDockerConfig(config, form);
  if (type === "linux_host") addLinuxConfig(config, form);
  if (type === "disk_usage") addDiskConfig(config, form);
  if (BACKUP_FILE_TYPES.has(type)) addBackupFileConfig(config, form, type);
  if (type === "ha_health") addHaHealthConfig(config, form);
  if (type === "pihole_health") addPiHoleConfig(config, form);
  if (SNMP_TYPES.has(type)) addSnmpConfig(config, form);
  if (LOG_REGEX_TYPES.has(type)) addLogRegexConfig(config, form, type);
  addAlertConfig(config, form);
  addAnomalyConfig(config, form);
  return config;
}

function addSshConfig(config, form) {
  if (form.elements.ssh_host.value.trim()) config.host = form.elements.ssh_host.value.trim();
  if (form.elements.ssh_port.value) config.port = Number(form.elements.ssh_port.value);
  if (!form.elements.credential_id.value) {
    if (form.elements.ssh_username.value.trim()) config.username = form.elements.ssh_username.value.trim();
    config.auth_method = form.elements.ssh_auth_method.value;
    if (form.elements.ssh_password.value) config.password = form.elements.ssh_password.value;
    if (form.elements.ssh_private_key.value) config.private_key = form.elements.ssh_private_key.value;
    if (form.elements.ssh_private_key_passphrase.value) config.private_key_passphrase = form.elements.ssh_private_key_passphrase.value;
  }
  config.known_hosts_policy = "auto_add";
  if (form.elements.ssh_connect_timeout_seconds.value) config.connect_timeout_seconds = Number(form.elements.ssh_connect_timeout_seconds.value);
  if (form.elements.ssh_command_timeout_seconds.value) config.command_timeout_seconds = Number(form.elements.ssh_command_timeout_seconds.value);
  if (form.elements.ssh_command.value.trim()) config.command = form.elements.ssh_command.value.trim();
  config.shell = "bash";
  if (form.elements.ssh_success_exit_codes.value.trim()) config.success_exit_codes = csvNumbers(form.elements.ssh_success_exit_codes.value);
  if (form.elements.ssh_warning_exit_codes.value.trim()) config.warning_exit_codes = csvNumbers(form.elements.ssh_warning_exit_codes.value);
  if (form.elements.ssh_error_exit_codes.value.trim()) config.error_exit_codes = csvNumbers(form.elements.ssh_error_exit_codes.value);
  ["success_stdout_regex", "warning_stdout_regex", "error_stdout_regex", "success_stderr_regex", "warning_stderr_regex", "error_stderr_regex", "alert_on_stdout_regex", "alert_on_stderr_regex"].forEach((key) => {
    const input = form.elements[`ssh_${key}`];
    if (input?.value.trim()) config[key] = input.value.trim();
  });
  if (form.elements.ssh_max_output_chars.value) config.max_output_chars = Number(form.elements.ssh_max_output_chars.value);
  config.store_output = form.elements.ssh_store_output.checked;
}

function addDockerConfig(config, form) {
  config.connection_method = "ssh";
  if (form.elements.container_name.value.trim()) config.container_name = form.elements.container_name.value.trim();
  if (form.elements.max_restart_count.value) config.max_restart_count = Number(form.elements.max_restart_count.value);
  if (form.elements.cpu_warning_percent.value) config.cpu_warning_percent = Number(form.elements.cpu_warning_percent.value);
  if (form.elements.memory_warning_percent.value) config.memory_warning_percent = Number(form.elements.memory_warning_percent.value);
  if (form.elements.log_tail_lines.value) config.log_tail_lines = Number(form.elements.log_tail_lines.value);
  if (form.elements.log_error_regex.value.trim()) config.log_error_regex = form.elements.log_error_regex.value.trim();
  config.check_running = form.elements.check_running.checked;
  config.check_health = form.elements.check_health.checked;
  config.store_logs = form.elements.store_logs.checked;
}

function addLinuxConfig(config, form) {
  ["cpu_load_warning", "cpu_load_error", "memory_error_percent", "swap_warning_percent", "disk_warning_percent", "disk_error_percent", "inode_warning_percent", "temperature_warning_c", "temperature_error_c"].forEach((key) => {
    if (form.elements[key].value) config[key] = Number(form.elements[key].value);
  });
  if (form.elements.memory_warning_percent_linux.value) config.memory_warning_percent = Number(form.elements.memory_warning_percent_linux.value);
  config.systemd_services = csvStrings(form.elements.systemd_services.value);
}

function addDiskConfig(config, form) {
  if (form.elements.mountpoint.value.trim()) config.mountpoint = form.elements.mountpoint.value.trim();
  ["warning_percent", "error_percent", "warning_free_gb", "error_free_gb"].forEach((key) => {
    if (form.elements[key].value) config[key] = Number(form.elements[key].value);
  });
  config.check_inodes = form.elements.check_inodes.checked;
  config.check_readonly = form.elements.check_readonly.checked;
}

function addBackupFileConfig(config, form, type) {
  if (form.elements.file_path.value.trim()) config.path = form.elements.file_path.value.trim();
  if (form.elements.filename_regex.value.trim()) config.filename_regex = form.elements.filename_regex.value.trim();
  ["max_age_hours", "min_size_mb", "max_size_mb", "max_file_count"].forEach((key) => {
    if (form.elements[key].value) config[key] = Number(form.elements[key].value);
  });
  if (type === "file_hash" && form.elements.hash_algorithm.value.trim()) config.hash_algorithm = form.elements.hash_algorithm.value.trim();
}

function addHaHealthConfig(config, form) {
  ["max_unavailable_entities_warning", "max_unavailable_entities_error", "max_unknown_entities_warning"].forEach((key) => {
    if (form.elements[key].value) config[key] = Number(form.elements[key].value);
  });
  ["check_updates", "check_supervisor", "check_recorder", "check_log_errors"].forEach((key) => {
    config[key] = form.elements[key].checked;
  });
}

function addPiHoleConfig(config, form) {
  if (form.elements.pihole_base_url.value.trim()) config.base_url = form.elements.pihole_base_url.value.trim();
  if (form.elements.pihole_api_token.value) config.api_token = form.elements.pihole_api_token.value;
  if (form.elements.dns_host.value.trim()) config.dns_host = form.elements.dns_host.value.trim();
  if (form.elements.dns_port.value) config.dns_port = Number(form.elements.dns_port.value);
  if (form.elements.test_domain.value.trim()) config.test_domain = form.elements.test_domain.value.trim();
  if (form.elements.min_queries_last_10m.value) config.min_queries_last_10m = Number(form.elements.min_queries_last_10m.value);
  if (form.elements.max_gravity_age_days.value) config.max_gravity_age_days = Number(form.elements.max_gravity_age_days.value);
}

function addSnmpConfig(config, form) {
  if (form.elements.snmp_host.value.trim()) config.host = form.elements.snmp_host.value.trim();
  if (form.elements.snmp_port.value) config.port = Number(form.elements.snmp_port.value);
  config.version = form.elements.snmp_version.value;
  if (form.elements.snmp_community.value) config.community = form.elements.snmp_community.value;
  if (form.elements.oid.value.trim()) config.oid = form.elements.oid.value.trim();
  config.operator = form.elements.operator.value;
  if (form.elements.warning_value.value) config.warning_value = Number(form.elements.warning_value.value);
  if (form.elements.error_value.value) config.error_value = Number(form.elements.error_value.value);
}

function addLogRegexConfig(config, form, type) {
  if (form.elements.log_path.value.trim()) {
    if (type === "docker_log_regex") config.container_name = form.elements.log_path.value.trim();
    else config.path = form.elements.log_path.value.trim();
  }
  if (form.elements.log_regex.value.trim()) config.regex = form.elements.log_regex.value.trim();
  if (form.elements.warning_regex.value.trim()) config.warning_regex = form.elements.warning_regex.value.trim();
  if (form.elements.error_regex.value.trim()) config.error_regex = form.elements.error_regex.value.trim();
  if (form.elements.tail_lines.value) config.tail_lines = Number(form.elements.tail_lines.value);
  if (form.elements.max_matches.value) config.max_matches = Number(form.elements.max_matches.value);
  config.only_new_matches = form.elements.only_new_matches.checked;
}

function addAlertConfig(config, form) {
  config.severity = form.elements.severity.value;
  if (form.elements.cooldown_minutes.value) config.cooldown_minutes = Number(form.elements.cooldown_minutes.value);
  config.notify_on_recovery = form.elements.notify_on_recovery.checked;
  if (form.elements.repeat_every_minutes.value) config.repeat_every_minutes = Number(form.elements.repeat_every_minutes.value);
  if (form.elements.max_repeats.value) config.max_repeats = Number(form.elements.max_repeats.value);
  config.deduplicate_alerts = form.elements.deduplicate_alerts.checked;
  config.alert_channels = csvStrings(form.elements.alert_channels.value || "home_assistant_event");
  if (form.elements.webhook_url.value.trim()) config.webhook_url = form.elements.webhook_url.value.trim();
}

function addAnomalyConfig(config, form) {
  config.anomaly_detection_enabled = form.elements.anomaly_detection_enabled.checked;
  if (form.elements.anomaly_window_hours.value) config.anomaly_window_hours = Number(form.elements.anomaly_window_hours.value);
  if (form.elements.anomaly_min_samples.value) config.anomaly_min_samples = Number(form.elements.anomaly_min_samples.value);
  if (form.elements.anomaly_stddev_multiplier.value) config.anomaly_stddev_multiplier = Number(form.elements.anomaly_stddev_multiplier.value);
  if (form.elements.anomaly_warn_percent_over_baseline.value) config.anomaly_warn_percent_over_baseline = Number(form.elements.anomaly_warn_percent_over_baseline.value);
  if (form.elements.anomaly_error_percent_over_baseline.value) config.anomaly_error_percent_over_baseline = Number(form.elements.anomaly_error_percent_over_baseline.value);
}

function csvNumbers(value) {
  return String(value || "").split(",").map((item) => Number(item.trim())).filter((item) => Number.isFinite(item));
}

function csvStrings(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function openDiscoveryDialog() {
  const form = $("#discoveryForm");
  form?.reset();
  if (form?.elements.timeout_seconds) form.elements.timeout_seconds.value = "3";
  if (form?.elements.max_hosts) form.elements.max_hosts.value = "64";
  if (form?.elements.total_timeout_seconds) form.elements.total_timeout_seconds.value = "60";
  state.discoveryProposals = [];
  state.discoveryReport = null;
  state.discoveryQuery = "";
  if ($("#discoverySearch")) $("#discoverySearch").value = "";
  renderDiscoveryResults();
  $("#discoveryDialog")?.showModal();
}

async function runDiscoveryScan(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const sources = [];
  if (form.elements.source_home_assistant.checked) sources.push("home_assistant");
  if (form.elements.source_network.checked) sources.push("network");
  if (form.elements.source_docker.checked) sources.push("docker");
  if (form.elements.source_unifi.checked) sources.push("unifi");
  if (!sources.length) {
    toast("Wybierz przynajmniej jedno źródło discovery.", "error");
    return;
  }
  state.discoveryProposals = [];
  state.discoveryReport = { scanning: true, requestedSources: sources };
  renderDiscoveryResults();
  $("#runDiscoveryBtn").disabled = true;
  $("#importDiscoveryBtn").disabled = true;
  try {
    const response = await api("/api/discovery/scan", {
      method: "POST",
      body: JSON.stringify({
        sources,
        network_cidr: form.elements.network_cidr.value.trim() || null,
        timeout_seconds: Number(form.elements.timeout_seconds.value || 3),
        max_hosts: Number(form.elements.max_hosts.value || 64),
        total_timeout_seconds: Number(form.elements.total_timeout_seconds.value || 60),
      }),
    });
    state.discoveryProposals = Array.isArray(response) ? response : response.proposals || [];
    state.discoveryReport = Array.isArray(response)
      ? { sources: [], summary: { proposals: response.length } }
      : response;
    renderDiscoveryResults();
  } catch (error) {
    state.discoveryProposals = [];
    state.discoveryReport = { error: error.message, sources: [], summary: { proposals: 0 } };
    renderDiscoveryResults();
  } finally {
    $("#runDiscoveryBtn").disabled = false;
    updateDiscoveryImportButton();
  }
}

function renderDiscoveryResults() {
  const root = $("#discoveryResults");
  const summary = $("#discoverySummary");
  const sourceRoot = $("#discoverySourceResults");
  if (!root || !summary || !sourceRoot) return;
  const proposals = state.discoveryProposals || [];
  const filteredProposals = proposals
    .map((proposal, index) => ({ proposal, index }))
    .filter(({ proposal }) => discoveryProposalMatches(proposal, state.discoveryQuery));
  const report = state.discoveryReport;
  if (report?.scanning) {
    summary.className = "badge warning";
    summary.textContent = "Skanowanie…";
    sourceRoot.innerHTML = report.requestedSources.map((source) => `
      <div class="discovery-source discovery-source--running">
        <span class="status-dot warning" aria-hidden="true"></span>
        <strong>${escapeHtml(discoverySourceLabel(source))}</strong>
        <span>Skanowanie…</span>
      </div>
    `).join("");
    root.className = "list empty discovery-scanning";
    root.textContent = "Skan jest w toku. Wyniki pojawią się po zakończeniu źródeł.";
    return;
  }
  renderDiscoverySourceResults(report?.sources || []);
  const duplicates = proposals.filter((item) => item.duplicate_of_monitor_id).length;
  const failed = report?.summary?.failed_sources || 0;
  const skipped = report?.summary?.skipped_sources || 0;
  summary.className = `badge ${report?.error || failed ? "bad" : skipped ? "warning" : proposals.length ? "ok" : "unknown"}`;
  summary.textContent = report?.error
    ? "Skan nieudany"
    : proposals.length
      ? state.discoveryQuery.trim()
        ? `${filteredProposals.length} z ${proposals.length} propozycji`
        : `${proposals.length} propozycji, ${duplicates} duplikatów`
      : failed
        ? "Brak wyników — wystąpiły błędy"
        : skipped
          ? "0 wyników — źródła pominięte"
          : "Skan zakończony — 0 wyników";
  if (!proposals.length) {
    root.className = "list empty";
    if (!report) root.textContent = "Uruchom skanowanie, aby zobaczyć propozycje.";
    else if (report.error) root.textContent = `Nie udało się wykonać skanu: ${report.error}`;
    else if (failed) root.textContent = "Nie znaleziono propozycji. Sprawdź błędy źródeł powyżej i ponów skan.";
    else if (skipped) root.textContent = "Wybrane źródła pominięto. Sprawdź wymagania konfiguracyjne powyżej.";
    else root.textContent = "Skan wykonano poprawnie, ale wybrane źródła nie zwróciły żadnych propozycji.";
    updateDiscoveryImportButton();
    return;
  }
  if (!filteredProposals.length) {
    root.className = "list empty discovery-no-matches";
    root.textContent = `Brak wyników pasujących do „${state.discoveryQuery.trim()}”.`;
    updateDiscoveryImportButton();
    return;
  }
  root.className = "discovery-results";
  root.innerHTML = filteredProposals.map(({ proposal, index }) => `
    <article class="discovery-item ${proposal.duplicate_of_monitor_id ? "duplicate" : ""}" data-discovery-index="${index}">
      ${proposal.icon ? `<div class="discovery-identity">
        <span class="discovery-device-icon" aria-hidden="true">${escapeHtml(proposal.icon)}</span>
        <div>
          <strong>${escapeHtml(discoveryDeviceKindLabel(proposal.device_kind))}</strong>
          <small>${escapeHtml(discoveryIdentityText(proposal))}</small>
        </div>
      </div>` : ""}
      <label class="check discovery-check">
        <input data-discovery-field="selected" type="checkbox" ${proposal.duplicate_of_monitor_id ? "" : "checked"} />
        ${proposal.duplicate_of_monitor_id ? `Duplikat #${proposal.duplicate_of_monitor_id}` : "Importuj"}
      </label>
      <label>Nazwa<input data-discovery-field="name" value="${escapeHtml(proposal.name)}" maxlength="120" /></label>
      <label>Typ<select data-discovery-field="type">${discoveryTypeOptions(proposal.type)}</select></label>
      <label>Target<input data-discovery-field="target" value="${escapeHtml(proposal.target)}" maxlength="2048" /></label>
      <label>Grupa<select data-discovery-field="group_id">${discoveryGroupOptions(proposal.group_id)}</select></label>
      <button class="discovery-test-btn" data-discovery-test="${index}" type="button">Testuj</button>
      <small>${escapeHtml(proposal.reason || "")} · pewność ${Math.round(Number(proposal.confidence || 0) * 100)}%</small>
    </article>
  `).join("");
  $$("[data-discovery-field]", root).forEach((input) => {
    input.addEventListener("input", updateDiscoveryProposalFromInput);
    input.addEventListener("change", updateDiscoveryProposalFromInput);
  });
  $$("[data-discovery-test]", root).forEach((button) => {
    button.addEventListener("click", () => startDiscoveryTestRun(state.discoveryProposals[Number(button.dataset.discoveryTest)]));
  });
  updateDiscoveryImportButton();
}

async function startDiscoveryTestRun(proposal) {
  if (!proposal) return;
  const monitor = {
    type: proposal.type,
    name: proposal.name,
    target: proposal.target,
    interval_seconds: proposal.interval_seconds || 60,
    group_id: proposal.group_id || null,
    enabled: true,
    config: proposal.config || {},
  };
  state.currentTest = {
    monitorId: null,
    monitor,
    discoveryProposal: proposal,
    returnView: "discovery",
    returnTab: "monitoring",
    status: "running",
    startedAt: new Date().toISOString(),
    finishedAt: null,
    result: null,
    error: null,
  };
  $("#discoveryDialog")?.close();
  showView("monitorTestRun", "monitoring");
  renderMonitorTestRun();
  startTestRunTimer();
  try {
    const response = await api("/api/monitors/test", {
      method: "POST",
      body: JSON.stringify({ ...monitor, test_on_save: false }),
    });
    state.currentTest = {
      ...state.currentTest,
      status: "done",
      finishedAt: new Date().toISOString(),
      result: {
        ...monitor,
        ...response,
        last_response_ms: response.response_ms,
        last_http_status: response.http_status,
        last_content_hash: response.content_hash,
        last_error: response.error,
      },
    };
    toast("Test wykrytego hosta zakończony.");
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

function discoveryProposalMatches(proposal, query) {
  const normalizedQuery = String(query || "").trim().toLocaleLowerCase("pl");
  if (!normalizedQuery) return true;
  const typeLabel = state.monitorTypes.find((type) => type.type === proposal.type)?.label || "";
  const searchable = [
    proposal.name,
    proposal.type,
    typeLabel,
    proposal.target,
    proposal.reason,
    proposal.hostname,
    proposal.mac_address,
    proposal.vendor,
    proposal.device_kind,
    proposal.duplicate_of_monitor_id ? `duplikat ${proposal.duplicate_of_monitor_id}` : "",
    JSON.stringify(proposal.config || {}),
  ].join(" ").toLocaleLowerCase("pl");
  return searchable.includes(normalizedQuery);
}

function discoveryIdentityText(proposal) {
  return [
    proposal.hostname ? `Hostname: ${proposal.hostname}` : "",
    proposal.mac_address ? `MAC: ${proposal.mac_address}` : "",
    proposal.vendor ? `Producent: ${proposal.vendor}` : "",
  ].filter(Boolean).join(" · ") || "Brak dodatkowych danych identyfikacyjnych";
}

function discoveryDeviceKindLabel(kind) {
  return {
    router: "Router",
    access_point: "Punkt dostępowy",
    nas: "NAS",
    server: "Serwer",
    camera: "Kamera",
    printer: "Drukarka",
    television: "Telewizor / media",
    speaker: "Głośnik",
    phone: "Telefon",
    iot: "Urządzenie IoT",
    computer: "Komputer",
    unknown: "Host sieciowy",
  }[kind] || "Host sieciowy";
}

function renderDiscoverySourceResults(sources) {
  const root = $("#discoverySourceResults");
  root.innerHTML = sources.map((source) => `
    <div class="discovery-source discovery-source--${escapeHtml(source.status)}">
      <span class="status-dot ${discoverySourceTone(source.status)}" aria-hidden="true"></span>
      <strong>${escapeHtml(source.label || discoverySourceLabel(source.source))}</strong>
      <span class="discovery-source__status">${escapeHtml(discoverySourceStatusLabel(source.status))}</span>
      <small>${escapeHtml(source.message || "")}</small>
      <span class="discovery-source__meta">${Number(source.found) || 0} wyników · ${formatDiscoveryDuration(source.duration_ms)}</span>
    </div>
  `).join("");
}

function discoverySourceLabel(source) {
  return {
    home_assistant: "Home Assistant",
    network: "Sieć lokalna",
    docker: "Docker",
    unifi: "UniFi / SNMP",
  }[source] || source;
}

function discoverySourceStatusLabel(status) {
  return {
    success: "Zakończono",
    empty: "Brak trafień",
    partial: "Częściowy wynik",
    skipped: "Pominięto",
    error: "Błąd",
  }[status] || "Nieznany";
}

function discoverySourceTone(status) {
  if (status === "success") return "ok";
  if (["partial", "skipped"].includes(status)) return "warning";
  if (status === "error") return "bad";
  return "unknown";
}

function formatDiscoveryDuration(value) {
  const milliseconds = Number(value);
  if (!Number.isFinite(milliseconds)) return "—";
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(1)} s` : `${milliseconds} ms`;
}

function updateDiscoveryImportButton() {
  const importButton = $("#importDiscoveryBtn");
  if (!importButton) return;
  importButton.disabled = !(state.discoveryProposals || []).some(
    (proposal) => proposal.selected !== false && !proposal.duplicate_of_monitor_id,
  );
}

function discoveryTypeOptions(current) {
  return state.monitorTypes
    .map((type) => `<option value="${escapeHtml(type.type)}" ${type.type === current ? "selected" : ""}>${escapeHtml(type.label || type.type)}</option>`)
    .join("");
}

function discoveryGroupOptions(current) {
  return '<option value="">Bez grupy</option>' + state.groups
    .map((group) => `<option value="${group.id}" ${String(group.id) === String(current || "") ? "selected" : ""}>${escapeHtml(group.name)}</option>`)
    .join("");
}

function updateDiscoveryProposalFromInput(event) {
  const item = event.currentTarget.closest("[data-discovery-index]");
  if (!item) return;
  const proposal = state.discoveryProposals[Number(item.dataset.discoveryIndex)];
  if (!proposal) return;
  const field = event.currentTarget.dataset.discoveryField;
  if (field === "selected") proposal.selected = event.currentTarget.checked;
  else if (field === "group_id") proposal.group_id = event.currentTarget.value ? Number(event.currentTarget.value) : null;
  else proposal[field] = event.currentTarget.value.trim();
  updateDiscoveryImportButton();
}

async function importDiscoverySelection() {
  const selected = (state.discoveryProposals || [])
    .filter((proposal) => proposal.selected !== false && !proposal.duplicate_of_monitor_id)
    .map((proposal) => ({
      type: proposal.type,
      name: proposal.name,
      target: proposal.target,
      group_id: proposal.group_id || null,
      interval_seconds: proposal.interval_seconds || null,
      enabled: true,
      test_on_save: false,
      config: proposal.config || {},
      confidence: proposal.confidence,
      reason: proposal.reason,
      duplicate_of_monitor_id: proposal.duplicate_of_monitor_id || null,
    }));
  if (!selected.length) {
    toast("Zaznacz propozycje bez duplikatow do importu.", "error");
    return;
  }
  const result = await api("/api/discovery/import", {
    method: "POST",
    body: JSON.stringify({ monitors: selected }),
  });
  $("#discoveryDialog").close();
  toast(`Zaimportowano ${result.created} monitorow.`);
  await refreshAll();
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
      <td><div class="monitor-list-actions">${renderMonitorListActions(monitor)}</div></td>
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
    <article class="card monitor-card monitor-list-card clickable-card ${state.selectedMonitorIds.has(monitor.id) ? "selected" : ""} ${monitor.enabled ? "" : "inactive"}" data-card-id="${monitor.id}" tabindex="0" title="${state.bulkSelectionMode ? "Zaznacz monitoring" : "Otwórz szczegóły monitoringu"}">
      <header class="monitor-card-header">
        <input class="monitor-select" type="checkbox" data-select-monitor="${monitor.id}" ${state.selectedMonitorIds.has(monitor.id) ? "checked" : ""} aria-label="Zaznacz ${escapeHtml(monitor.name)}" />
        <div class="monitor-title-wrap">
          <h3 class="monitor-title" title="${escapeHtml(monitor.name)}">${escapeHtml(monitor.name)}</h3>
          <p class="monitor-host" title="${escapeHtml(monitorHostValue(monitor))}">${escapeHtml(monitorHostValue(monitor))}</p>
        </div>
        <span class="badge monitor-status-badge ${monitor.enabled ? badgeClass(monitor.status) : "unknown"}">${monitor.enabled ? escapeHtml(monitor.status || "unknown") : "wyłączony"}</span>
      </header>
      <div class="monitor-fields">
        ${renderMonitorSummaryFields(monitor)}
      </div>
      <div id="monitor-more-${monitor.id}" class="monitor-more-content hidden">
        ${renderMonitorMoreDetails(monitor)}
      </div>
      <div class="monitor-actions">${renderMonitorListActions(monitor, { includeMore: true })}</div>
    </article>
  `).join("");
  bindMonitorOpeners(root);
  bindMonitorSelection(root);
  bindMonitorActions(root);
  bindMonitorMore(root);
}

function renderMonitorListActions(monitor, options = {}) {
  return `
    <button data-action="check" data-id="${monitor.id}" type="button" class="primary">↻ Odśwież</button>
    <button data-action="edit" data-id="${monitor.id}" type="button">Edytuj</button>
    <button data-action="duplicate" data-id="${monitor.id}" type="button">Duplikuj</button>
    <button data-action="maintenance" data-id="${monitor.id}" type="button">Serwis</button>
    ${options.includeMore ? `<button data-more-monitor="${monitor.id}" type="button" aria-expanded="false" aria-controls="monitor-more-${monitor.id}">Więcej</button>` : ""}
  `;
}

function monitorHostValue(monitor) {
  const config = monitor.config || {};
  return config.host || config.topic || monitor.target || "-";
}

function monitorStatusValue(monitor) {
  return monitor.enabled ? (monitor.status || "-") : "nieaktywny";
}

function monitorResponseValue(monitor) {
  return formatResponse(monitor.last_response_ms);
}

function renderMonitorField(label, value, className = "") {
  return `
    <div class="monitor-field ${className}">
      <span class="monitor-field-label">${escapeHtml(label)}</span>
      <span class="monitor-field-value" title="${escapeHtml(String(value || "-"))}">${escapeHtml(String(value || "-"))}</span>
    </div>
  `;
}

function renderMonitorSummaryFields(monitor) {
  const error = monitor.last_error || "-";
  return [
    renderMonitorField("Typ", typeLabel(monitor.type)),
    renderMonitorField("IP / host", monitorHostValue(monitor)),
    renderMonitorField("Status", monitorStatusValue(monitor)),
    renderMonitorField("Ping / odpowiedź", monitorResponseValue(monitor)),
    renderMonitorField("Ostatni test", formatShortDate(monitor.last_checked_at)),
    renderMonitorField("Ostatni błąd", error, "monitor-error-field"),
  ].join("");
}

function renderMonitorMoreDetails(monitor) {
  const diagnostic = diagnosticMessage(monitor);
  const details = [
    ["Grupa", monitor.group_name || "Bez grupy"],
    ["Interwał", `${monitor.interval_seconds}s`],
    ["Aktywny", monitor.enabled ? "tak" : "nie"],
    ["Serwis", monitor.maintenance_active ? `aktywny do ${formatDate(monitor.maintenance_until || monitor.group_maintenance_until)}` : "-"],
    ["Diagnostyka", diagnostic || "-"],
    ["Pełny ostatni błąd", monitor.last_error || "-"],
    ["Pełna data ostatniego testu", formatDate(monitor.last_checked_at)],
  ];
  return details.map(([label, value]) => renderMonitorField(label, value, label.includes("błąd") ? "monitor-full-error-field" : "")).join("");
}

function bindMonitorMore(root) {
  $$("[data-more-monitor]", root).forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const panel = $(`#monitor-more-${event.currentTarget.dataset.moreMonitor}`);
      if (!panel) return;
      const expanded = panel.classList.toggle("hidden") === false;
      event.currentTarget.setAttribute("aria-expanded", String(expanded));
      event.currentTarget.textContent = expanded ? "Mniej" : "Więcej";
    });
  });
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

function renderDetailActions(monitor) {
  return `
    <button data-action="maintenance" data-id="${monitor.id}" type="button">Serwis</button>
    <button data-action="toggle-enabled" data-id="${monitor.id}" type="button">${monitor.enabled ? "Wyłącz monitoring" : "Włącz monitoring"}</button>
    ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}" type="button">Zmiany</button>` : ""}
    <button data-action="delete" data-id="${monitor.id}" type="button" class="danger-action">Usuń</button>
  `;
}

function bindMonitorActions(root) {
  $$("[data-action]", root).forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      handleCardAction(event);
    });
  });
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
  if (test.returnView === "discovery") {
    showView("monitoring");
    $("#discoveryDialog")?.showModal();
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
  const monitor = state.monitors.find((item) => item.id === test.monitorId) || test.monitor || test.result;
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
  $("#testEditBtn").hidden = !test.monitorId;
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
    "Protokół": result.details?.protocol || "-",
    "Banner usługi": result.details?.banner || "-",
  };
  return `<dl class="diagnostics">${definitionRows(rows)}</dl>${renderDiscoveryHttpPreview(test, result)}`;
}

function renderDiscoveryHttpPreview(test, result) {
  if (!test.discoveryProposal || !["http_status", "http_hash"].includes(result.type)) return "";
  let url;
  try {
    url = new URL(result.target);
  } catch (_) {
    return "";
  }
  if (!["http:", "https:"].includes(url.protocol)) return "";
  const safeUrl = escapeHtml(url.href);
  return `
    <section class="discovery-http-preview">
      <div class="panel-head">
        <strong>Podgląd strony</strong>
        <a href="${safeUrl}" target="_blank" rel="noopener noreferrer">Otwórz w nowej karcie</a>
      </div>
      <iframe src="${safeUrl}" title="Podgląd ${escapeHtml(result.name)}" sandbox="" referrerpolicy="no-referrer" loading="lazy"></iframe>
      <small>Podgląd jest izolowany: skrypty, formularze i nawigacja strony są zablokowane.</small>
    </section>`;
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
    ...anomalyDetailRows(monitor),
    ["Konfiguracja", JSON.stringify(monitor.config || {}, null, 2), "code"],
  ];
  $("#detailData").innerHTML = detailData
    .map(([key, value, variant]) => `<dt>${escapeHtml(key)}</dt><dd>${renderDetailValue(value, variant)}</dd>`)
    .join("");
}

function anomalyDetailRows(monitor) {
  const anomaly = monitor.config?.last_anomaly;
  if (!anomaly?.anomaly_reason) return [];
  const baseline = anomaly.baseline || {};
  return [
    ["Anomaly metric", anomaly.metric || baseline.metric || "-"],
    ["Baseline", `mean ${baseline.mean ?? "-"} · median ${baseline.median ?? "-"} · p95 ${baseline.p95 ?? "-"} · stddev ${baseline.stddev ?? "-"}`],
    ["Obecny wynik", anomaly.current_value ?? "-"],
    ["Anomaly score", anomaly.anomaly_score ?? "-"],
    ["Powod anomalii", anomaly.anomaly_reason],
  ];
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

function renderCredentials() {
  const root = $("#credentialList");
  if (!root) return;
  if (!state.credentials.length) {
    root.innerHTML = `
      <div class="credential-empty">
        <strong>Brak zapisanych danych dostępowych</strong>
        <p>Dodaj profil, aby bezpiecznie współdzielić login i hasło albo klucz SSH.</p>
        <button class="primary" type="button" data-credential-action="add">Dodaj dane dostępowe</button>
      </div>`;
  } else {
    root.innerHTML = state.credentials.map((credential) => `
      <article class="credential-card">
        <header>
          <span class="credential-key-icon" aria-hidden="true">⌕</span>
          <div><h3>${escapeHtml(credential.name)}</h3><p>${escapeHtml(credential.description || "Brak opisu")}</p></div>
          <span class="badge unknown">${escapeHtml(credentialKindLabel(credential.kind))}</span>
        </header>
        <dl>
          <div><dt>Login</dt><dd>${escapeHtml(credential.username || "—")}</dd></div>
          <div><dt>Użycie</dt><dd>${credential.in_use_count} ${pluralizeMonitors(credential.in_use_count)}</dd></div>
          <div><dt>Sekrety</dt><dd>${escapeHtml(credentialSecretSummary(credential))}</dd></div>
          <div><dt>Aktualizacja</dt><dd>${formatDate(credential.updated_at)}</dd></div>
        </dl>
        <footer>
          <button type="button" data-credential-action="edit" data-id="${credential.id}">Edytuj</button>
          <button type="button" class="danger-action" data-credential-action="delete" data-id="${credential.id}">Usuń</button>
        </footer>
      </article>
    `).join("");
  }
  $$('[data-credential-action]', root).forEach((button) => button.addEventListener("click", handleCredentialAction));
}

function credentialKindLabel(kind) {
  return kind === "ssh_private_key" ? "Klucz prywatny SSH" : "Login i hasło";
}

function credentialSecretSummary(credential) {
  const values = [];
  if (credential.has_password) values.push("hasło zapisane");
  if (credential.has_private_key) values.push("klucz SSH zapisany");
  if (credential.has_private_key_passphrase) values.push("passphrase zapisane");
  return values.join(", ") || "brak zapisanych sekretów";
}

function handleCredentialAction(event) {
  const action = event.currentTarget.dataset.credentialAction;
  if (action === "add") return openCredentialForm();
  const credential = state.credentials.find((item) => item.id === Number(event.currentTarget.dataset.id));
  if (!credential) return;
  if (action === "edit") openCredentialForm(credential);
  if (action === "delete") deleteCredential(credential);
}

function openCredentialForm(credential = null) {
  const form = $("#credentialForm");
  form.reset();
  form.elements.id.value = credential?.id || "";
  form.elements.name.value = credential?.name || "";
  form.elements.kind.value = credential?.kind || "username_password";
  form.elements.username.value = credential?.username || "";
  form.elements.description.value = credential?.description || "";
  $("#credentialDialogTitle").textContent = credential ? "Edytuj dane dostępowe" : "Dodaj dane dostępowe";
  $("#saveCredentialBtn").textContent = credential ? "Zapisz zmiany" : "Zapisz profil";
  form.dataset.hasPassword = String(Boolean(credential?.has_password));
  form.dataset.hasPrivateKey = String(Boolean(credential?.has_private_key));
  form.dataset.hasPrivateKeyPassphrase = String(Boolean(credential?.has_private_key_passphrase));
  renderCredentialSecretFields();
  $("#credentialDialog").showModal();
}

function renderCredentialSecretFields() {
  const form = $("#credentialForm");
  const isKey = form.elements.kind.value === "ssh_private_key";
  const editing = Boolean(form.elements.id.value);
  $("#credentialPasswordFields").classList.toggle("hidden", isKey);
  $("#credentialKeyFields").classList.toggle("hidden", !isKey);
  $("#clearCredentialPassword").classList.toggle("hidden", !editing || form.dataset.hasPassword !== "true");
  $("#clearCredentialKey").classList.toggle("hidden", !editing || form.dataset.hasPrivateKey !== "true");
  $("#clearCredentialPassphrase").classList.toggle(
    "hidden", !editing || form.dataset.hasPrivateKeyPassphrase !== "true",
  );
  $("#credentialPasswordHint").textContent = editing && form.dataset.hasPassword === "true"
    ? "Hasło jest zapisane. Pozostaw puste, aby zachować obecną wartość."
    : "Hasło jest wymagane przy tworzeniu profilu.";
  $("#credentialKeyHint").textContent = editing && form.dataset.hasPrivateKey === "true"
    ? "Klucz SSH jest zapisany. Pozostaw puste, aby zachować obecną wartość."
    : "Klucz SSH jest wymagany przy tworzeniu profilu.";
  $("#credentialPassphraseHint").textContent = editing && form.dataset.hasPrivateKeyPassphrase === "true"
    ? "Passphrase jest zapisane. Pozostaw puste, aby zachować obecną wartość."
    : "Opcjonalne hasło do klucza prywatnego.";
}

async function saveCredential(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const payload = {
    name: form.elements.name.value.trim(),
    kind: form.elements.kind.value,
    username: form.elements.username.value.trim() || null,
    description: form.elements.description.value.trim() || null,
    password: form.elements.password.value,
    private_key: form.elements.private_key.value,
    private_key_passphrase: form.elements.private_key_passphrase.value,
    clear_secret_fields: [
      form.elements.clear_password.checked ? "password" : "",
      form.elements.clear_private_key.checked ? "private_key" : "",
      form.elements.clear_private_key_passphrase.checked ? "private_key_passphrase" : "",
    ].filter(Boolean),
  };
  await api(id ? `/api/credentials/${id}` : "/api/credentials", {
    method: id ? "PUT" : "POST",
    body: JSON.stringify(payload),
  });
  $("#credentialDialog").close();
  toast(id ? "Dane dostępowe zaktualizowane." : "Dane dostępowe zapisane.");
  await refreshAll();
}

async function deleteCredential(credential) {
  if (!confirm(`Usunąć profil „${credential.name}”?`)) return;
  await api(`/api/credentials/${credential.id}`, { method: "DELETE" });
  toast("Profil danych dostępowych usunięty.");
  await refreshAll();
}

function renderGroups() {
  const root = $("#groupList");
  renderGroupSummary();
  if (state.selectedGroupId && !state.groups.some((group) => group.id === state.selectedGroupId)) {
    state.selectedGroupId = null;
  }
  if (!state.groups.length) {
    root.innerHTML = '<div class="group-empty-state"><strong>Brak grup</strong><p>Dodaj pierwszą grupę, aby uporządkować monitory.</p></div>';
    renderGroupMonitorList();
    return;
  }
  root.innerHTML = state.groups.map((group) => `
    <article class="group-card${state.selectedGroupId === group.id ? " group-card--selected" : ""}"
      style="--group-color: ${normalizeGroupColor(group.color)}" data-group-id="${group.id}">
      <header class="group-card__header">
        <span class="group-color-dot" aria-hidden="true"></span>
        <div class="group-card__identity">
          <h3>${escapeHtml(group.name)}</h3>
          <p>${escapeHtml(group.description || "Brak opisu")}</p>
        </div>
        <span class="group-status badge ${badgeClass(group.maintenance_active ? "maintenance" : group.status)}">${groupStatusLabel(group.maintenance_active ? "maintenance" : group.status)}</span>
      </header>
      <div class="group-card__stats" aria-label="Statystyki grupy">
        ${renderGroupStat("Monitory", group.monitor_count, "neutral")}
        ${renderGroupStat("Online", group.online, "ok")}
        ${renderGroupStat("Offline", group.offline, Number(group.monitor_count) ? "bad" : "neutral")}
      </div>
      ${renderGroupMaintenance(group)}
      <div class="group-card__slo" aria-label="SLO grupy">${renderSloMini(group.slo || {})}</div>
      <footer class="group-card__actions">
        <button class="primary group-show-monitors" data-group-action="filter" data-id="${group.id}">Pokaż monitory</button>
        <button data-group-action="edit" data-id="${group.id}">Edytuj</button>
        <details class="group-action-menu">
          <summary aria-label="Opcje trybu serwisowego" aria-expanded="false">Serwis</summary>
          <div class="group-action-menu__popover">
            <button data-group-action="maint-30" data-id="${group.id}">30 minut</button>
            <button data-group-action="maint-120" data-id="${group.id}">2 godziny</button>
            <button data-group-action="maint-manual" data-id="${group.id}">Ustaw ręcznie</button>
            ${group.maintenance_active ? `<button data-group-action="maint-clear" data-id="${group.id}">Wyłącz tryb serwisowy</button>` : ""}
          </div>
        </details>
        <details class="group-action-menu group-action-menu--more">
          <summary aria-label="Więcej akcji" aria-expanded="false">•••</summary>
          <div class="group-action-menu__popover"><button class="danger-action" data-group-action="delete" data-id="${group.id}">Usuń</button></div>
        </details>
      </footer>
    </article>
  `).join("");
  $$("[data-group-action]", root).forEach((button) => button.addEventListener("click", handleGroupAction));
  $$(".group-action-menu", root).forEach(bindGroupActionMenu);
  renderGroupMonitorList();
}

function renderGroupSummary() {
  const assignedActive = state.monitors.filter((monitor) => monitor.enabled !== false && monitor.group_id).length;
  const maintenanceGroups = state.groups.filter((group) => group.maintenance_active).length;
  $("#groupSummary").innerHTML = [
    ["Grupy", state.groups.length],
    ["Aktywne monitory", assignedActive],
    ["Grupy w serwisie", maintenanceGroups],
  ].map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("");
}

function renderGroupStat(label, value, tone) {
  return `<div class="group-stat group-stat--${tone}"><span>${label}</span><strong>${Number(value) || 0}</strong></div>`;
}

function renderGroupMaintenance(group) {
  if (!group.maintenance_active) {
    return '<div class="group-maintenance"><span class="status-dot" aria-hidden="true"></span><span>Tryb serwisowy wyłączony</span></div>';
  }
  const until = String(group.maintenance_until || "").startsWith("9999-")
    ? "bez terminu zakończenia"
    : `do ${formatDate(group.maintenance_until)}`;
  return `<div class="group-maintenance group-maintenance--active"><span class="status-dot warning" aria-hidden="true"></span><span><strong>Tryb serwisowy aktywny</strong><small>${escapeHtml(until)}</small></span></div>`;
}

function renderSloMini(slo) {
  return [["24h", "24 h"], ["7d", "7 dni"], ["30d", "30 dni"], ["90d", "90 dni"]].map(([key, label]) => {
    const item = slo[key] || {};
    return `<div class="group-slo-item"><span>${label}</span><strong>${sloUptimeLabel(item.uptime_percent)}</strong><small>${incidentCountLabel(item.incidents)}</small></div>`;
  }).join("");
}

async function handleGroupAction(event) {
  const id = Number(event.currentTarget.dataset.id);
  const action = event.currentTarget.dataset.groupAction;
  const group = state.groups.find((item) => item.id === id);
  event.currentTarget.closest("details")?.removeAttribute("open");
  if (!group) return;
  if (action === "filter") selectGroup(id);
  if (action === "edit") {
    const form = $("#groupForm");
    form.elements.id.value = group.id;
    form.elements.name.value = group.name;
    form.elements.description.value = group.description || "";
    form.elements.color.value = normalizeGroupColor(group.color);
    form.elements.color_hex.value = normalizeGroupColor(group.color);
    $("#groupFormTitle").textContent = "Edytuj grupę";
    $("#groupFormHint").textContent = `Zmieniasz ustawienia grupy „${group.name}”.`;
    $("#saveGroupBtn").textContent = "Zapisz zmiany";
    $("#cancelGroupEditBtn").hidden = false;
    $(".group-form-panel").scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    form.elements.name.focus({ preventScroll: true });
  }
  if (action === "maint-30") await setGroupMaintenance(id, 30);
  if (action === "maint-120") await setGroupMaintenance(id, 120);
  if (action === "maint-manual") openGroupMaintenanceDialog(group);
  if (action === "maint-clear") await clearGroupMaintenance(id);
  if (action === "delete" && await confirmGroupDelete(group)) {
    await api(`/api/groups/${id}`, { method: "DELETE" });
    toast("Grupa usunięta.");
    if (state.selectedGroupId === id) state.selectedGroupId = null;
    await refreshAll();
  }
}

function selectGroup(id, { scroll = true } = {}) {
  state.selectedGroupId = Number(id);
  state.monitorGroupFilter = String(id);
  if ($("#monitorGroupFilter")) $("#monitorGroupFilter").value = String(id);
  persistMonitorUiState();
  $$(".group-card", $("#groupList")).forEach((card) => {
    card.classList.toggle("group-card--selected", Number(card.dataset.groupId) === Number(id));
  });
  renderGroupMonitorList(id);
  if (scroll && window.matchMedia("(max-width: 699px)").matches) {
    $("#groupMonitorsPanel").scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
  }
}

function resetGroupForm() {
  const form = $("#groupForm");
  form.reset();
  form.elements.id.value = "";
  form.elements.color.value = "#0f766e";
  form.elements.color_hex.value = "#0f766e";
  $("#groupFormTitle").textContent = "Nowa grupa";
  $("#groupFormHint").textContent = "Utwórz logiczny obszar dla powiązanych monitorów.";
  $("#saveGroupBtn").textContent = "Dodaj grupę";
  $("#cancelGroupEditBtn").hidden = true;
}

function syncGroupColorFromPicker(event) {
  event.currentTarget.form.elements.color_hex.value = event.currentTarget.value.toLowerCase();
}

function syncGroupColorFromHex(event) {
  if (/^#[0-9a-f]{6}$/i.test(event.currentTarget.value)) {
    event.currentTarget.form.elements.color.value = event.currentTarget.value;
  }
}

function normalizeGroupColor(value) {
  return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? String(value).toLowerCase() : "#0f766e";
}

function bindGroupActionMenu(menu) {
  const summary = menu.querySelector("summary");
  menu.addEventListener("toggle", () => {
    summary.setAttribute("aria-expanded", String(menu.open));
    if (menu.open) $$(".group-action-menu", $("#groupList")).forEach((other) => {
      if (other !== menu) other.removeAttribute("open");
    });
  });
  menu.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    menu.removeAttribute("open");
    summary.focus();
  });
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
  resetGroupForm();
  toast(id ? "Zmiany zapisane." : "Grupa dodana.");
  await refreshAll();
}

function openGroupMaintenanceDialog(group) {
  const form = $("#groupMaintenanceForm");
  form.reset();
  form.elements.id.value = group.id;
  form.elements.until.value = toDatetimeLocalValue(group.maintenance_until) || toDatetimeLocalValue(Date.now() + 3600000);
  $("#groupMaintenanceDialogTitle").textContent = `Serwis: ${group.name}`;
  $("#groupMaintenanceDialog").showModal();
}

async function saveGroupMaintenanceFromDialog(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = Number(form.elements.id.value);
  const until = new Date(form.elements.until.value);
  if (!id || Number.isNaN(until.getTime()) || until <= new Date()) {
    toast("Data zakończenia serwisu musi być w przyszłości.", "error");
    return;
  }
  await api(`/api/groups/${id}/maintenance`, {
    method: "POST",
    body: JSON.stringify({ until: until.toISOString(), reason: form.elements.reason.value.trim() }),
  });
  $("#groupMaintenanceDialog").close();
  toast("Tryb serwisowy grupy włączony.");
  await refreshAll();
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

function renderGroupMonitorList(groupId = state.selectedGroupId) {
  const root = $("#groupMonitorList");
  if (!root) return;
  const title = $("#groupMonitorsTitle");
  const count = $("#groupMonitorsCount");
  const openButton = $("#openGroupMonitoringBtn");
  if (!groupId) {
    root.classList.add("empty");
    title.textContent = "Monitory wybranej grupy";
    count.textContent = "";
    openButton.hidden = true;
    root.innerHTML = "Wybierz grupę, aby zobaczyć przypisane monitory.";
    return;
  }
  const group = state.groups.find((item) => Number(item.id) === Number(groupId));
  if (!group) return;
  const monitors = state.monitors.filter((monitor) => Number(monitor.group_id) === Number(groupId));
  root.classList.toggle("empty", !monitors.length);
  title.textContent = `Monitory: ${group.name}`;
  count.textContent = `${monitors.length} ${pluralizeMonitors(monitors.length)}`;
  openButton.hidden = false;
  root.innerHTML = monitors.length
    ? monitors.map((monitor) => `
      <button class="group-monitor-item clickable-monitor" data-card-id="${monitor.id}" type="button">
        <span class="status-dot ${badgeClass(monitor.status)}" aria-hidden="true"></span>
        <span class="group-monitor-item__name"><strong>${escapeHtml(monitor.name)}</strong><small>${escapeHtml(typeLabel(monitor.type))}</small></span>
        <span class="badge ${badgeClass(monitor.status)}">${groupStatusLabel(monitor.status)}</span>
        <span class="group-monitor-response">${formatResponse(monitor.last_response_ms)}</span>
      </button>
    `).join("")
    : `<div class="group-monitor-empty"><strong>Ta grupa nie zawiera jeszcze monitorów.</strong><button type="button" data-add-monitor-to-group="${group.id}">Dodaj monitor do grupy</button></div>`;
  $("[data-add-monitor-to-group]", root)?.addEventListener("click", () => openMonitorForm({ group_id: group.id }));
  bindMonitorOpeners(root);
}

function openSelectedGroupInMonitoring() {
  if (!state.selectedGroupId) return;
  state.monitorGroupFilter = String(state.selectedGroupId);
  if ($("#monitorGroupFilter")) $("#monitorGroupFilter").value = state.monitorGroupFilter;
  persistMonitorUiState();
  renderMonitorLists();
  showView("monitoring");
}

function confirmGroupDelete(group) {
  const dialog = $("#confirmDialog");
  if (!dialog?.showModal) return Promise.resolve(confirm(`Usunąć grupę "${group.name}"? Monitory zostaną bez grupy.`));
  $("#confirmTitle").textContent = `Usunąć grupę „${group.name}”?`;
  $("#confirmText").textContent = "Monitory pozostaną w systemie, ale nie będą już przypisane do tej grupy.";
  $("#confirmAcceptBtn").textContent = "Usuń grupę";
  $("#confirmDetails").classList.add("hidden");
  dialog.returnValue = "";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    dialog.showModal();
  });
}

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
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
  form.elements.credential_id.value = monitor.credential_id || "";
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
  form.elements.mqtt_username.value = monitor.config?.username || "";
  form.elements.mqtt_password.value = "";
  populateExtendedMonitorFields(form, monitor.config || {});
  renderTestResult(null);
  $("#dialogTitle").textContent = monitor.id ? "Edytuj monitor" : "Dodaj monitor";
  renderTypeFields(form.elements.type.value);
  form.elements.credential_id.value = monitor.credential_id || "";
  renderSelectedMonitorCredential();
  updateConfigPreview();
  $("#monitorDialog").showModal();
}

function populateExtendedMonitorFields(form, config) {
  form.elements.ssh_host.value = config.host || "";
  form.elements.ssh_port.value = config.port || "";
  form.elements.ssh_username.value = config.username || "";
  form.elements.ssh_auth_method.value = config.auth_method || "password";
  form.elements.ssh_password.value = "";
  form.elements.ssh_private_key.value = "";
  form.elements.ssh_private_key_passphrase.value = "";
  form.elements.ssh_command.value = config.command || "";
  form.elements.ssh_connect_timeout_seconds.value = config.connect_timeout_seconds || "";
  form.elements.ssh_command_timeout_seconds.value = config.command_timeout_seconds || "";
  form.elements.ssh_success_exit_codes.value = (config.success_exit_codes || []).join(",");
  form.elements.ssh_warning_exit_codes.value = (config.warning_exit_codes || []).join(",");
  form.elements.ssh_error_exit_codes.value = (config.error_exit_codes || []).join(",");
  ["success_stdout_regex", "warning_stdout_regex", "error_stdout_regex", "success_stderr_regex", "warning_stderr_regex", "error_stderr_regex", "alert_on_stdout_regex", "alert_on_stderr_regex"].forEach((key) => {
    if (form.elements[`ssh_${key}`]) form.elements[`ssh_${key}`].value = config[key] || "";
  });
  form.elements.ssh_max_output_chars.value = config.max_output_chars || "";
  form.elements.ssh_store_output.checked = config.store_output !== false;
  form.elements.container_name.value = config.container_name || config.service_name || "";
  form.elements.max_restart_count.value = config.max_restart_count ?? "";
  form.elements.cpu_warning_percent.value = config.cpu_warning_percent ?? "";
  form.elements.memory_warning_percent.value = config.memory_warning_percent ?? "";
  form.elements.log_tail_lines.value = config.log_tail_lines ?? "";
  form.elements.log_error_regex.value = config.log_error_regex || "";
  form.elements.check_running.checked = config.check_running !== false;
  form.elements.check_health.checked = config.check_health !== false;
  form.elements.store_logs.checked = Boolean(config.store_logs);
  ["cpu_load_warning", "cpu_load_error", "memory_error_percent", "swap_warning_percent", "disk_warning_percent", "disk_error_percent", "inode_warning_percent", "temperature_warning_c", "temperature_error_c"].forEach((key) => {
    form.elements[key].value = config[key] ?? "";
  });
  form.elements.memory_warning_percent_linux.value = config.memory_warning_percent ?? "";
  form.elements.systemd_services.value = (config.systemd_services || []).join(",");
  form.elements.mountpoint.value = config.mountpoint || "";
  ["warning_percent", "error_percent", "warning_free_gb", "error_free_gb"].forEach((key) => {
    form.elements[key].value = config[key] ?? "";
  });
  form.elements.check_inodes.checked = config.check_inodes !== false;
  form.elements.check_readonly.checked = config.check_readonly !== false;
  form.elements.file_path.value = config.path || "";
  form.elements.filename_regex.value = config.filename_regex || "";
  ["max_age_hours", "min_size_mb", "max_size_mb", "max_file_count"].forEach((key) => {
    form.elements[key].value = config[key] ?? "";
  });
  form.elements.hash_algorithm.value = config.hash_algorithm || "";
  ["max_unavailable_entities_warning", "max_unavailable_entities_error", "max_unknown_entities_warning"].forEach((key) => {
    form.elements[key].value = config[key] ?? "";
  });
  ["check_updates", "check_supervisor", "check_recorder", "check_log_errors"].forEach((key) => {
    form.elements[key].checked = config[key] !== false;
  });
  form.elements.pihole_base_url.value = config.base_url || "";
  form.elements.pihole_api_token.value = "";
  form.elements.dns_host.value = config.dns_host || "";
  form.elements.dns_port.value = config.dns_port || "";
  form.elements.test_domain.value = config.test_domain || "";
  form.elements.min_queries_last_10m.value = config.min_queries_last_10m ?? "";
  form.elements.max_gravity_age_days.value = config.max_gravity_age_days ?? "";
  form.elements.snmp_host.value = config.host || "";
  form.elements.snmp_port.value = config.port || "";
  form.elements.snmp_version.value = config.version || "2c";
  form.elements.snmp_community.value = "";
  form.elements.oid.value = config.oid || "";
  form.elements.operator.value = config.operator || ">";
  form.elements.warning_value.value = config.warning_value ?? "";
  form.elements.error_value.value = config.error_value ?? "";
  form.elements.log_path.value = config.path || config.container_name || "";
  form.elements.log_regex.value = config.regex || "";
  form.elements.warning_regex.value = config.warning_regex || "";
  form.elements.error_regex.value = config.error_regex || "";
  form.elements.tail_lines.value = config.tail_lines ?? "";
  form.elements.max_matches.value = config.max_matches ?? "";
  form.elements.only_new_matches.checked = config.only_new_matches !== false;
  form.elements.severity.value = config.severity || "warning";
  form.elements.cooldown_minutes.value = config.cooldown_minutes ?? "";
  form.elements.notify_on_recovery.checked = config.notify_on_recovery !== false;
  form.elements.repeat_every_minutes.value = config.repeat_every_minutes ?? "";
  form.elements.max_repeats.value = config.max_repeats ?? "";
  form.elements.deduplicate_alerts.checked = config.deduplicate_alerts !== false;
  form.elements.alert_channels.value = (config.alert_channels || ["home_assistant_event"]).join(",");
  form.elements.webhook_url.value = "";
  form.elements.anomaly_detection_enabled.checked = Boolean(config.anomaly_detection_enabled);
  form.elements.anomaly_window_hours.value = config.anomaly_window_hours ?? "";
  form.elements.anomaly_min_samples.value = config.anomaly_min_samples ?? "";
  form.elements.anomaly_stddev_multiplier.value = config.anomaly_stddev_multiplier ?? "";
  form.elements.anomaly_warn_percent_over_baseline.value = config.anomaly_warn_percent_over_baseline ?? "";
  form.elements.anomaly_error_percent_over_baseline.value = config.anomaly_error_percent_over_baseline ?? "";
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
    credential_id: form.elements.credential_id.value ? Number(form.elements.credential_id.value) : null,
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

async function copyConfigPreview() {
  const value = $("#configPreview")?.textContent || "{}";
  try {
    await navigator.clipboard.writeText(value);
    toast("JSON skopiowany.");
  } catch (_) {
    toast("Nie udało się skopiować JSON.", "error");
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
    result.details?.exit_code !== undefined && result.details?.exit_code !== null ? `Exit code: ${result.details.exit_code}` : "",
    `HTTP: ${result.http_status || "-"}`,
    `Czas: ${result.response_ms ? Number(result.response_ms).toFixed(1) + " ms" : "-"}`,
    `Data: ${formatDate(result.checked_at)}`,
    result.content_hash ? `Suma WWW: ${result.content_hash}` : "",
    result.details?.stdout_excerpt ? `stdout: ${result.details.stdout_excerpt.slice(0, 500)}` : "",
    result.details?.stderr_excerpt ? `stderr: ${result.details.stderr_excerpt.slice(0, 500)}` : "",
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
    ["severity", $("#historySeverity")?.value || ""],
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
      <td><span class="badge ${badgeClass(row.status)}">${escapeHtml(row.status)}</span>${row.anomaly ? ' <span class="badge warning">anomaly</span>' : ""}</td>
      <td>${row.severity ? `<span class="badge">${escapeHtml(row.severity)}</span>` : "-"}</td>
      <td>${formatResponse(row.response_ms)}</td>
      <td>${row.http_status || "-"}</td>
      <td>${hashHtml(row.content_hash)}</td>
      <td>${row.packet_loss ?? "-"}</td>
      <td>${escapeHtml(row.error || "-")}</td>
    </tr>
  `).join("") : '<tr><td colspan="9" class="empty">Brak wpisów historii dla wybranych filtrów.</td></tr>';
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
    Severity: row.severity || "-",
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
    allow_private_monitor_targets: state.settings.allow_private_monitor_targets !== false,
    allow_private_webhooks: form.elements.allow_private_webhooks.checked,
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
    secrets_exported: false,
    credential_profiles: state.credentials.map((credential) => ({
      id: credential.id,
      name: credential.name,
      kind: credential.kind,
      username: credential.username,
      description: credential.description,
      secrets_exported: false,
    })),
    settings: state.settings,
    groups: state.groups.map(({ id, created_at, updated_at, status, monitor_count, online, offline, slo, maintenance_active, ...group }) => group),
    monitors: state.monitors.map(({ id, created_at, updated_at, credential, ...monitor }) => ({
      ...monitor,
      config: withoutMaskedSecrets(monitor.config || {}),
    })),
  };
  $("#exportBox").value = JSON.stringify(data, null, 2);
}

function withoutMaskedSecrets(value) {
  if (Array.isArray(value)) return value.map(withoutMaskedSecrets);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value)
    .filter(([, item]) => item !== "********")
    .map(([key, item]) => [key, withoutMaskedSecrets(item)]));
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
  let importWarnings = [];
  if (monitors.length) {
    const result = await api("/api/monitors/import", {
      method: "POST",
      body: JSON.stringify({ monitors }),
    });
    importWarnings = result.warnings || [];
  }
  toast(importWarnings.length ? `Import zakończony z ostrzeżeniami: ${importWarnings.join("; ")}` : "Import zakończony.");
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

async function loadDiagnosticsSelfCheck() {
  const [diagnostics, logs] = await Promise.all([
    api("/api/diagnostics/full"),
    api("/api/logs"),
  ]);
  state.diagnostics = diagnostics;
  renderSchedulerStatus();
  const process = diagnostics.process || {};
  const haApi = diagnostics.home_assistant_api || {};
  const dataWritable = diagnostics.data_writable || {};
  const logStatus = diagnostics.log_file_status || {};
  const walStatus = diagnostics.wal_status || {};
  $("#diagnosticsData").innerHTML = definitionRows({
    Wersja: diagnostics.addon_version || diagnostics.version,
    Python: process.python_version || "-",
    "Uptime procesu": process.uptime_seconds !== null && process.uptime_seconds !== undefined ? formatSeconds(process.uptime_seconds) : "-",
    "CPU procesu": process.cpu_seconds !== null && process.cpu_seconds !== undefined ? `${process.cpu_seconds}s` : "-",
    "RAM procesu": process.max_rss_kb ? `${process.max_rss_kb} KB` : "-",
    "Schema version": diagnostics.schema_version ?? "-",
    "Status bazy": diagnostics.database_exists ? "OK" : "Brak",
    "Sciezka bazy": diagnostics.database_path,
    "Rozmiar bazy": formatBytes(diagnostics.database_size_bytes),
    WAL: walStatus.exists ? `aktywny, ${formatBytes(walStatus.size_bytes)}` : "brak",
    "Liczba monitorow": diagnostics.monitor_count,
    "Wpisy historii": diagnostics.check_count,
    "Checki 24h": diagnostics.checks_last_24h ?? 0,
    "Sredni czas checkow": formatResponse(diagnostics.avg_check_response_ms),
    "Ostatni test": formatDate(diagnostics.last_check),
    "Ostatni tick schedulera": formatDate(diagnostics.scheduler_last_tick),
    "Aktywne zadania": diagnostics.active_jobs?.join(", ") || "-",
    "Oczekujace zadania": diagnostics.queued_jobs?.join(", ") || "-",
    "Limit rownoleglosci": diagnostics.max_concurrent_checks,
    "Bledy schedulera": diagnostics.scheduler_error_count ?? 0,
    "Ostatni blad schedulera": diagnostics.scheduler_last_error || "-",
    "Home Assistant API": haApi.ok ? "OK" : haApi.available === false ? "niedostepne" : haApi.error || "blad",
    "Zapis /data": dataWritable.ok ? "OK" : "blad",
    "Plik logu": logStatus.writable ? `OK, ${formatBytes(logStatus.size_bytes)}` : "brak zapisu",
    "Encje HA": diagnostics.settings?.publish_home_assistant_entities ? "wlaczone" : "wylaczone",
    "Eventy HA": diagnostics.settings?.publish_home_assistant_events ? "wlaczone" : "wylaczone",
  });
  renderList("#diagnosticsErrors", diagnostics.errors || [], (row) => `
    <div class="list-item">
      <strong>${escapeHtml(row.error || "Blad")}</strong>
      <small>${formatDate(row.checked_at)} · monitor ${row.monitor_id || "-"}</small>
    </div>
  `);
  $("#logsBox").textContent = logs || "Brak logow.";
}

async function runSelfCheck() {
  const button = $("#runSelfCheckBtn");
  const run = async () => {
    const result = await api("/api/diagnostics/self-check", { method: "POST" });
    renderSelfCheckResults(result);
    await loadDiagnostics();
    toast("Self-check zakonczony.");
  };
  if (button) {
    await runWithButtonLoading(button, run);
  } else {
    await run();
  }
}

function renderSelfCheckResults(result) {
  const checks = result?.checks || [];
  renderList("#selfCheckResults", checks, (check) => `
    <div class="list-item">
      <strong>${escapeHtml(check.name || "check")}</strong>
      <small><span class="badge ${check.ok ? "online" : "error"}">${check.ok ? "OK" : "ERROR"}</span></small>
      <span>${escapeHtml(check.error || check.reason || check.status_code || "")}</span>
    </div>
  `);
}

async function createSelfMonitor() {
  const existing = state.monitors.find((monitor) => monitor.type === "monitoring_center_health");
  if (existing) {
    openMonitorForm(existing);
    return;
  }
  await api("/api/monitors", {
    method: "POST",
    body: JSON.stringify({
      type: "monitoring_center_health",
      name: "Monitoring Center Health",
      target: "self",
      interval_seconds: 300,
      group_id: null,
      enabled: true,
      test_on_save: false,
      config: {},
    }),
  });
  toast("Monitor health utworzony.");
  await refreshAll();
}

loadDiagnostics = loadDiagnosticsSelfCheck;

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
          <small>${escapeHtml(payload.previous_state || "-")} → ${escapeHtml(payload.new_state || "-")} ${payload.severity ? "· " + escapeHtml(payload.severity) : ""}</small>
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
  if (status === "maintenance") return "warning";
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

function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "-";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[index]}`;
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

function formatShortDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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

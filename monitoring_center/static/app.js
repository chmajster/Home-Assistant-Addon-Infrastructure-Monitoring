const state = {
  monitors: [],
  groups: [],
  monitorTypes: [],
  presets: [],
  summary: null,
  settings: null,
};

const API_BASE = window.location.pathname === "/" ? "" : window.location.pathname.replace(/\/$/, "");

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindForms();
  refreshAll();
  setInterval(refreshAll, 30000);
});

function bindNavigation() {
  $$(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".tab").forEach((tab) => tab.classList.remove("active"));
      $$(".view").forEach((view) => view.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.tab}`).classList.add("active");
      if (button.dataset.tab === "diagnostics") loadDiagnostics();
      if (button.dataset.tab === "history") loadHistory();
    });
  });
  $("#refreshBtn").addEventListener("click", refreshAll);
  $$("[data-open-form]").forEach((button) => {
    button.addEventListener("click", () => openMonitorForm({ type: button.dataset.openForm }));
  });
}

function bindForms() {
  $("#monitorForm").addEventListener("submit", saveMonitor);
  $("#groupForm").addEventListener("submit", saveGroup);
  $("#monitorTypeSelect").addEventListener("change", () => renderTypeFields($("#monitorTypeSelect").value));
  $("#applyPresetBtn").addEventListener("click", applyPreset);
  $("#settingsForm").addEventListener("submit", saveSettings);
  $("#historyApply").addEventListener("click", loadHistory);
  $("#historyClean").addEventListener("click", async () => {
    await api("/api/history", { method: "DELETE" });
    toast("Stara historia została wyczyszczona zgodnie z retencją.");
    loadHistory();
  });
  $("#exportBtn").addEventListener("click", exportConfig);
  $("#importFile").addEventListener("change", importConfig);
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
      message = body.detail || message;
    } catch (_) {}
    toast(message);
    throw new Error(message);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
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
  renderCards("#websiteList", state.monitors.filter((m) => ["http_status", "http_hash", "ssl_certificate", "rest_api"].includes(m.type)));
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
    if (form.elements.max_page_size_kb.value) config.max_page_size_kb = Number(form.elements.max_page_size_kb.value);
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

function renderCards(selector, monitors) {
  const root = $(selector);
  if (!monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów w tej sekcji.</p>';
    return;
  }
  root.innerHTML = monitors.map((monitor) => `
    <article class="card">
      <div class="card-head">
        <div>
          <h2>${escapeHtml(monitor.name)}</h2>
          <p>${escapeHtml(monitor.target)}</p>
        </div>
        <span class="badge ${badgeClass(monitor.status)}">${escapeHtml(monitor.status)}</span>
      </div>
      <div class="meta">
        <span>Interwał: ${monitor.interval_seconds}s</span>
        <span>Typ: ${escapeHtml(typeLabel(monitor.type))}</span>
        <span>Grupa: ${escapeHtml(monitor.group_name || "Bez grupy")}</span>
        <span>Maintenance: ${monitor.maintenance_active ? "aktywny do " + formatDate(monitor.maintenance_until || monitor.group_maintenance_until) : "-"}</span>
        <span>Odpowiedź: ${monitor.last_response_ms ? Number(monitor.last_response_ms).toFixed(1) + " ms" : "-"}</span>
        <span>HTTP: ${monitor.last_http_status || "-"}</span>
        <span>Ostatni test: ${formatDate(monitor.last_checked_at)}</span>
        <span>Błąd: ${escapeHtml(monitor.last_error || "-")}</span>
      </div>
      <div class="actions">
        <button data-action="check" data-id="${monitor.id}">Test</button>
        <button data-action="edit" data-id="${monitor.id}">Edytuj</button>
        <button data-action="maint-30" data-id="${monitor.id}">Serwis 30m</button>
        <button data-action="maint-120" data-id="${monitor.id}">Serwis 2h</button>
        <button data-action="maint-manual" data-id="${monitor.id}">Serwis ręczny</button>
        ${monitor.maintenance_until ? `<button data-action="maint-clear" data-id="${monitor.id}">Wyłącz serwis</button>` : ""}
        ${monitor.type === "http_hash" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
        <button data-action="delete" data-id="${monitor.id}">Usuń</button>
      </div>
    </article>
  `).join("");
  $$("[data-action]", root).forEach((button) => button.addEventListener("click", handleCardAction));
}

async function handleCardAction(event) {
  const id = Number(event.currentTarget.dataset.id);
  const action = event.currentTarget.dataset.action;
  const monitor = state.monitors.find((item) => item.id === id);
  if (action === "check") {
    await api(`/api/monitors/${id}/check`, { method: "POST" });
    toast("Test monitora zakończony.");
    refreshAll();
  }
  if (action === "edit") openMonitorForm(monitor);
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
  form.elements.timeout_seconds.value = monitor.config?.timeout_seconds || "";
  form.elements.expected_status_codes.value = (monitor.config?.expected_status_codes || []).join(",");
  form.elements.tcp_host.value = monitor.config?.host || "";
  form.elements.tcp_port.value = monitor.config?.port || "";
  form.elements.css_selector.value = monitor.config?.css_selector || "";
  form.elements.ignore_patterns.value = (monitor.config?.ignore_patterns || []).join("\n");
  form.elements.max_page_size_kb.value = monitor.config?.max_page_size_kb || "";
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
  $("#dialogTitle").textContent = monitor.id ? "Edytuj monitor" : "Dodaj monitor";
  renderTypeFields(form.elements.type.value);
  $("#monitorDialog").showModal();
}

async function saveMonitor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const type = form.elements.type.value;
  const config = buildMonitorConfig(form, type);
  if (form.elements.timeout_seconds.value) config.timeout_seconds = Number(form.elements.timeout_seconds.value);
  const payload = {
    type,
    name: form.elements.name.value.trim(),
    target: form.elements.target.value.trim(),
    interval_seconds: form.elements.interval_seconds.value ? Number(form.elements.interval_seconds.value) : null,
    group_id: form.elements.group_id.value ? Number(form.elements.group_id.value) : null,
    enabled: form.elements.enabled.checked,
    test_on_save: form.elements.test_on_save.checked,
    config,
  };
  const path = id ? `/api/monitors/${id}` : "/api/monitors";
  const method = id ? "PUT" : "POST";
  await api(path, { method, body: JSON.stringify(payload) });
  $("#monitorDialog").close();
  toast("Monitor zapisany.");
  refreshAll();
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
      <td>${row.packet_loss ?? "-"}</td>
      <td>${escapeHtml(row.error || "-")}</td>
    </tr>
  `).join("");
}

function renderSettings() {
  if (!state.settings) return;
  const form = $("#settingsForm");
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
    request_timeout_seconds: Number(form.elements.request_timeout_seconds.value),
    ping_timeout_seconds: Number(form.elements.ping_timeout_seconds.value),
    max_page_size_kb: Number(form.elements.max_page_size_kb.value),
    block_private_networks: form.elements.block_private_networks.checked,
    publish_home_assistant_entities: form.elements.publish_home_assistant_entities.checked,
    publish_home_assistant_events: form.elements.publish_home_assistant_events.checked,
    entity_prefix: form.elements.entity_prefix.value.trim(),
  };
  state.settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
  toast("Ustawienia zapisane.");
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
  if (data.settings) await api("/api/settings", { method: "PUT", body: JSON.stringify(data.settings) });
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
function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 3800);
}

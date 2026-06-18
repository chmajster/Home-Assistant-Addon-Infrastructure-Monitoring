const state = {
  monitors: [],
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
  const [summary, monitors, settings] = await Promise.all([
    api("/api/summary"),
    api("/api/monitors"),
    api("/api/settings"),
  ]);
  state.summary = summary;
  state.monitors = monitors;
  state.settings = settings;
  renderDashboard();
  renderMonitorLists();
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
}

function renderAvailabilityChart() {
  const root = $("#availabilityChart");
  if (!state.monitors.length) {
    root.innerHTML = '<p class="empty">Brak monitorów</p>';
    return;
  }
  root.innerHTML = state.monitors.map((monitor) => {
    const down = ["offline", "error"].includes(monitor.status) ? "100%" : "0%";
    return `<div class="bar" style="--down:${down}" title="${escapeHtml(monitor.name)}">
      <strong>${escapeHtml(monitor.name)}</strong><br>${escapeHtml(monitor.status)}
    </div>`;
  }).join("");
}

function renderMonitorLists() {
  renderCards("#deviceList", state.monitors.filter((m) => m.type === "device"));
  renderCards("#websiteList", state.monitors.filter((m) => m.type === "website"));
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
        <span>Odpowiedź: ${monitor.last_response_ms ? Number(monitor.last_response_ms).toFixed(1) + " ms" : "-"}</span>
        <span>HTTP: ${monitor.last_http_status || "-"}</span>
        <span>Ostatni test: ${formatDate(monitor.last_checked_at)}</span>
        <span>Błąd: ${escapeHtml(monitor.last_error || "-")}</span>
      </div>
      <div class="actions">
        <button data-action="check" data-id="${monitor.id}">Test</button>
        <button data-action="edit" data-id="${monitor.id}">Edytuj</button>
        ${monitor.type === "website" ? `<button data-action="snapshots" data-id="${monitor.id}">Zmiany</button>` : ""}
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
  if (action === "delete" && confirm(`Usunąć monitor "${monitor.name}"?`)) {
    await api(`/api/monitors/${id}`, { method: "DELETE" });
    toast("Monitor usunięty.");
    refreshAll();
  }
  if (action === "snapshots") showSnapshots(id);
}

function openMonitorForm(monitor) {
  const form = $("#monitorForm");
  form.reset();
  form.elements.id.value = monitor.id || "";
  form.elements.type.value = monitor.type;
  form.elements.name.value = monitor.name || "";
  form.elements.target.value = monitor.target || "";
  form.elements.interval_seconds.value = monitor.interval_seconds || "";
  form.elements.enabled.checked = monitor.enabled !== false;
  form.elements.test_on_save.checked = !monitor.id;
  form.elements.timeout_seconds.value = monitor.config?.timeout_seconds || "";
  form.elements.css_selector.value = monitor.config?.css_selector || "";
  form.elements.ignore_patterns.value = (monitor.config?.ignore_patterns || []).join("\n");
  form.elements.max_page_size_kb.value = monitor.config?.max_page_size_kb || "";
  $("#dialogTitle").textContent = monitor.id ? "Edytuj monitor" : (monitor.type === "device" ? "Dodaj urządzenie" : "Dodaj stronę WWW");
  $("#targetLabel").firstChild.textContent = monitor.type === "device" ? "IP lub hostname" : "Adres URL";
  $("#websiteOptions").classList.toggle("hidden", monitor.type !== "website");
  $("#monitorDialog").showModal();
}

async function saveMonitor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const id = form.elements.id.value;
  const type = form.elements.type.value;
  const config = {};
  if (form.elements.timeout_seconds.value) config.timeout_seconds = Number(form.elements.timeout_seconds.value);
  if (type === "website") {
    if (form.elements.css_selector.value.trim()) config.css_selector = form.elements.css_selector.value.trim();
    if (form.elements.max_page_size_kb.value) config.max_page_size_kb = Number(form.elements.max_page_size_kb.value);
    config.ignore_patterns = form.elements.ignore_patterns.value.split("\n").map((line) => line.trim()).filter(Boolean);
  }
  const payload = {
    type,
    name: form.elements.name.value.trim(),
    target: form.elements.target.value.trim(),
    interval_seconds: form.elements.interval_seconds.value ? Number(form.elements.interval_seconds.value) : null,
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
    monitors: state.monitors.map(({ id, created_at, updated_at, ...monitor }) => monitor),
  };
  $("#exportBox").value = JSON.stringify(data, null, 2);
}

async function importConfig(event) {
  const file = event.target.files[0];
  if (!file) return;
  const data = JSON.parse(await file.text());
  if (data.settings) await api("/api/settings", { method: "PUT", body: JSON.stringify(data.settings) });
  for (const monitor of data.monitors || []) {
    await api("/api/monitors", {
      method: "POST",
      body: JSON.stringify({ ...monitor, test_on_save: false }),
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
  if (["online", "ok"].includes(status)) return "ok";
  if (["offline", "error"].includes(status)) return "bad";
  return "unknown";
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

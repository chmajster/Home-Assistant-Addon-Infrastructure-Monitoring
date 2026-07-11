import dashboard from "./views/dashboard.js";
import diagnostics from "./views/diagnostics.js";
import events from "./views/events.js";
import history from "./views/history.js";
import incidents from "./views/incidents.js";
import monitoring from "./views/monitoring.js";
import settings from "./views/settings.js";
import topology from "./views/topology.js";

const registry = new Map([dashboard, diagnostics, events, history, incidents, monitoring, settings, topology].map((view) => [view.id, view]));

export function activateView(viewId, activeTab = viewId) {
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === viewId));
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === activeTab;
    tab.classList.toggle("active", active);
    if (active) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
  });
  return registry.get(viewId) || { id: viewId, tab: activeTab, poll: null };
}

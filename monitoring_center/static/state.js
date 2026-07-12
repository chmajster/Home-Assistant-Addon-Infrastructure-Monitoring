export const state = {
  monitors: [], groups: [], monitorTypes: [], presets: [], summary: null, diagnostics: null,
  incidents: [], topology: { nodes: [], edges: [], version: 1 }, topologyConnectMode: false,
  topologyConnectSource: null, settings: null, selectedMonitorId: null, currentTest: null,
  monitorQuery: "", monitorTypeFilter: "all", monitorStatusFilter: "all", monitorGroupFilter: "all",
  selectedGroupId: null,
  monitorMaintenanceFilter: "all", monitorEnabledFilter: "all", monitorSort: "name", monitorView: "cards",
  dashboardTypeFilter: "all", selectedMonitorIds: new Set(), bulkSelectionMode: false, events: [],
  eventTypeFilter: "", eventQuery: "", incidentStatusFilter: "all", incidentMonitorFilter: "",
  lastRefreshedAt: null, detailHistoryRows: [], detailHistoryPage: 1, detailHistoryPageSize: 100,
  detailHistoryFilters: { from: "", to: "", status: "all", search: "", sort: "date_desc" },
  discoveryProposals: [],
};

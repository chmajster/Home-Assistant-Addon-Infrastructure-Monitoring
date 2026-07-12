const GROUP_STATUS_LABELS = {
  empty: "Pusta",
  ok: "Aktywna",
  online: "Aktywna",
  warning: "Ostrzeżenie",
  error: "Problem",
  offline: "Problem",
  maintenance: "Serwis",
};

export function groupStatusLabel(status) {
  return GROUP_STATUS_LABELS[String(status || "").toLowerCase()] || "Nieznany";
}

export function incidentCountLabel(value) {
  const count = Number.isFinite(Number(value)) ? Number(value) : 0;
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return "1 incydent";
  if (!(lastTwo >= 12 && lastTwo <= 14) && last >= 2 && last <= 4) return `${count} incydenty`;
  return `${count} incydentów`;
}

export function sloUptimeLabel(value) {
  return value === null || value === undefined || value === "" ? "—" : `${value}%`;
}

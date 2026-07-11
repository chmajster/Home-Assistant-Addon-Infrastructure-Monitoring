const API_BASE = window.location.pathname === "/" ? "" : window.location.pathname.replace(/\/$/, "");

export async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      const detail = body.error?.message || body.detail || message;
      message = formatApiError(detail);
    } catch (_) { /* odpowiedź bez JSON */ }
    window.dispatchEvent(new CustomEvent("monitoring-api-error", { detail: message }));
    throw new Error(message);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function formatApiError(detail) {
  if (Array.isArray(detail)) return detail.map((item) => item.msg || "Nieprawidłowe dane").join("; ");
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return String(detail || "Wystąpił błąd");
}

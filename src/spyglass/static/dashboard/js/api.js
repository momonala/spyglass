const API_BASE = "/dashboard/api";

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  return search.toString();
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `Request failed (${response.status})`);
  }
  return payload;
}

export function fetchProjects() {
  return request("/projects");
}

export function fetchMetricNames(project) {
  return request(`/metrics/names?${buildQuery({ project })}`);
}

export function fetchSeries(project, name, from, to) {
  return request(`/metrics/series?${buildQuery({ project, name, from, to })}`);
}

export function fetchSummary(project, name, from, to) {
  return request(`/metrics/summary?${buildQuery({ project, name, from, to })}`);
}

export function fetchHistogram(project, name, from, to) {
  return request(`/metrics/histogram?${buildQuery({ project, name, from, to })}`);
}

export function fetchLayout(project) {
  return request(`/layout?${buildQuery({ project })}`);
}

export function saveLayout(project, layout) {
  return request(`/layout?${buildQuery({ project })}`, {
    method: "PUT",
    body: JSON.stringify(layout),
  });
}

export function toIsoTimestamp(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function rangeToWindow(rangeKey) {
  const to = new Date();
  if (rangeKey === "all") {
    return { from: "1970-01-01T00:00:00Z", to: toIsoTimestamp(to) };
  }

  const hoursByKey = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
  };
  const hours = hoursByKey[rangeKey] || 24;
  const from = new Date(to.getTime() - hours * 60 * 60 * 1000);
  return { from: toIsoTimestamp(from), to: toIsoTimestamp(to) };
}

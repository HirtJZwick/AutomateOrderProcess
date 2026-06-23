// Thin API client for the FastAPI backend (proxied via Vite at /api).

async function http(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

export const api = {
  getConfig: () => http("/api/config"),
  setRootFolder: (root_folder) =>
    http("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ root_folder }),
    }),
  listOrders: () => http("/api/orders"),
  getOrder: (dossier) => http(`/api/orders/${encodeURIComponent(dossier)}`),
  scan: () => http("/api/scan", { method: "POST" }),
};

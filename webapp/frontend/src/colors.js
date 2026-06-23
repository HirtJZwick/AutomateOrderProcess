// Shared color maps for stages and completeness levels.

export const STAGE_COLORS = {
  New: "var(--stage-new)",
  "Order Confirmed": "var(--stage-confirmed)",
  Packed: "var(--stage-packed)",
  Shipped: "var(--stage-shipped)",
};

export const LEVEL_COLORS = {
  full: "var(--c-full)",
  partial: "var(--c-partial)",
  low: "var(--c-low)",
  missing: "var(--c-missing)",
};

export function stageColor(name) {
  return STAGE_COLORS[name] || "var(--stage-new)";
}

export function levelColor(level) {
  return LEVEL_COLORS[level] || "var(--c-missing)";
}

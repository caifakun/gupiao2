export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
}

export function icon(name) {
  return `<svg class="icon" aria-hidden="true"><use href="#icon-${escapeHtml(name)}"/></svg>`;
}

export function identifier(stock) {
  return `${stock.market === "SH" ? "1" : "0"}.${stock.code}`;
}

export function inferStockMarket(code) {
  if (/^(?:60|68)\d{4}$/.test(code)) return "SH";
  if (/^(?:00|30)\d{4}$/.test(code)) return "SZ";
  return null;
}

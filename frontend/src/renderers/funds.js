import { escapeHtml } from "../utils/format.js";

export function createFundViews({ sourceTime, percentage, directionClass, amount, signedAmount, marketClock }) {
  function billboardTotals(group, incomplete) {
    const unavailable = { buy: null, sell: null, net: null };
    if (incomplete || !group.rows.length) return unavailable;
    let buyCents = 0;
    let sellCents = 0;
    for (const row of group.rows) {
      if (!Number.isFinite(row.buy) || !Number.isFinite(row.sell)
          || row.buy < 0 || row.sell < 0) return unavailable;
      buyCents += Math.round(row.buy * 100);
      sellCents += Math.round(row.sell * 100);
      if (!Number.isSafeInteger(buyCents)
          || !Number.isSafeInteger(sellCents)) return unavailable;
    }
    return { buy: buyCents / 100, sell: sellCents / 100, net: (buyCents - sellCents) / 100 };
  }

  function billboardTotalsMarkup(group, incomplete) {
    const totals = billboardTotals(group, incomplete);
    const note = totals.net === null
      ? "披露不完整、金额缺失或超出安全范围，暂不计算合计；缺失不代表零。"
      : "单位：元。仅统计本上榜原因下已展示且去重的席位，不跨上榜原因加总，也不是该股票全天全部交易。";
    return `<div class="capital-stat-grid" aria-label="当前上榜原因席位汇总">
      <div class="capital-stat"><span>展示席位买入合计</span><strong>${amount(totals.buy)}</strong></div>
      <div class="capital-stat"><span>展示席位卖出合计</span><strong>${amount(totals.sell)}</strong></div>
      <div class="capital-stat"><span>买卖总差值（买入－卖出）</span><strong class="${directionClass(totals.net)}">${signedAmount(totals.net)}</strong></div>
    </div><p class="capital-note">${note}</p>`;
  }

  function darkSnapshotMarkup(snapshot) {
    if (!snapshot || snapshot.source_date !== marketClock().date) {
      return '<p class="capital-note">尚未取得当日快照，缺失不代表零。</p>';
    }
    const items = [
      ["明盘资金", snapshot.lit_net],
      ["暗盘资金", snapshot.dark_net],
      ["主力净流入（含暗盘）", snapshot.main_net],
    ];
    const activity = Number.isFinite(snapshot.activity_pct)
      ? `${snapshot.activity_pct.toFixed(2)}%` : "—";
    return `<div class="capital-stat-grid">${items.map(([label, value]) =>
      `<div class="capital-stat"><span>${label}</span><strong class="${Number.isFinite(value) ? directionClass(value) : "capital-status"}" title="${Number.isFinite(value) ? `${value.toFixed(2)} 元` : "源字段缺失"}">${signedAmount(value)}</strong><small>${!Number.isFinite(value) ? "源字段缺失" : value > 0 ? "净流入方向" : value < 0 ? "净流出方向" : "净额为零"}</small></div>`
    ).join("")}<div class="capital-stat"><span>暗盘活跃度</span><strong class="${Number.isFinite(snapshot.activity_pct) ? "dark-activity" : "capital-status"}">${activity}</strong><small>源榜单模型指标</small></div></div>`;
  }

  function capitalHistoryChart(rows) {
    if (!rows.length) return "";
    const maximum = Math.max(1, ...rows.map(row => Number.isFinite(row.main) ? Math.abs(row.main) : 0));
    const step = 560 / rows.length;
    const bars = rows.map((row, index) => {
      const horizontal = 20 + step * index + step * 0.18;
      if (!Number.isFinite(row.main)) return `<text x="${horizontal.toFixed(2)}" y="84" fill="var(--muted)" font-size="12"><title>${escapeHtml(row.date)} 缺失，非零</title>×</text>`;
      const height = Math.max(1, Math.abs(row.main) / maximum * 60);
      const vertical = row.main > 0 ? 80 - height : row.main < 0 ? 80 : 79.5;
      const color = row.main > 0 ? "var(--rise)" : row.main < 0 ? "var(--fall)" : "var(--muted)";
      return `<rect x="${horizontal.toFixed(2)}" y="${vertical.toFixed(2)}" width="${(step * 0.64).toFixed(2)}" height="${height.toFixed(2)}" fill="${color}"><title>${escapeHtml(row.date)} 主力净额 ${signedAmount(row.main)}元</title></rect>`;
    }).join("");
    return `<svg class="capital-history-chart" viewBox="0 0 600 165" role="img" aria-label="历史主力净额：红色净流入，绿色净流出，灰色零值，叉号表示缺失">
      <line x1="15" y1="80" x2="585" y2="80" stroke="#526076" stroke-dasharray="3 4"/>${bars}
      <text x="20" y="158" fill="var(--muted)" font-size="10">${escapeHtml(rows[0].date)}</text>
      <text x="580" y="158" text-anchor="end" fill="var(--muted)" font-size="10">${escapeHtml(rows[rows.length - 1].date)}</text>
    </svg>`;
  }

  function associationMarkup(tag) {
    try {
      const url = new URL(tag.evidence_url);
      if (url.protocol !== "https:" || url.username || url.password) return "";
      const title = `资料日期 ${tag.evidence_date}；适用区间 ${tag.valid_from} 至 ${tag.valid_to}。仅为公开席位关联，不确认本次实际交易人。`;
      return `<a class="capital-tag" href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(title)}">游资公开关联：${escapeHtml(tag.alias)} ↗</a><small class="capital-status">资料 ${escapeHtml(tag.evidence_date)}</small>`;
    } catch { return ""; }
  }

  return { billboardTotals, billboardTotalsMarkup, darkSnapshotMarkup, capitalHistoryChart, associationMarkup };
}

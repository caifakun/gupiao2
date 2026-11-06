import { computed, watch } from "vue";

export function useWatchlistFilters(state, market, epoch) {
  function snapshot(stock) {
    epoch.value;
    return market.value?.watchlistView(stock) || { isToday: false, changePct: null, industryKey: "pending" };
  }

  function matchesChange(stock) {
    if (state.changeFilter === "all") return true;
    const quote = snapshot(stock);
    if (!quote.isToday || !Number.isFinite(quote.changePct)) return false;
    if (state.changeFilter === "up") return quote.changePct > 0;
    if (state.changeFilter === "down") return quote.changePct < 0;
    if (state.changeFilter === "flat") return quote.changePct === 0;
    return (state.changeMin === null || quote.changePct >= state.changeMin) && (state.changeMax === null || quote.changePct <= state.changeMax);
  }

  const candidates = computed(() => {
    const query = state.query.trim().toLocaleLowerCase();
    return state.stocks.filter(stock => (state.group === "all" || stock.group === state.group)
      && (!query || [stock.code, stock.name, snapshot(stock).name].some(value => String(value || "").toLocaleLowerCase().includes(query)))
      && matchesChange(stock));
  });
  const industryTabs = computed(() => {
    const counts = new Map([["all", candidates.value.length]]);
    for (const stock of candidates.value) {
      const key = snapshot(stock).industryKey;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    const label = key => key === "all" ? "全部行业" : key === "pending" ? "待分类" : key === "missing" ? "未提供行业" : key.slice(9);
    return [...counts].sort(([left], [right]) => left === "all" ? -1 : right === "all" ? 1 : label(left).localeCompare(label(right), "zh-CN"))
      .map(([id, count]) => ({ id, name: label(id), count }));
  });
  watch(industryTabs, tabs => {
    if (!tabs.some(tab => tab.id === state.industry)) state.industry = "all";
  });
  const filtered = computed(() => candidates.value.filter(stock => state.industry === "all" || snapshot(stock).industryKey === state.industry));
  const pageSize = computed(() => state.view === "list" ? 20 : state.layout);
  const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)));
  watch(pageCount, count => { state.pageIndex = Math.min(state.pageIndex, count - 1); });
  const visible = computed(() => filtered.value.slice(state.pageIndex * pageSize.value, (state.pageIndex + 1) * pageSize.value));

  function clear() {
    Object.assign(state, { changeFilter: "all", changeMin: null, changeMax: null, industry: "all", pageIndex: 0 });
  }

  return { snapshot, industryTabs, filtered, pageSize, pageCount, visible, clear };
}

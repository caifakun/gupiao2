(() => {
  "use strict";

  const quotes = new Map();
  const trends = new Map();
  const quoteErrors = new Map();
  const watchlistSnapshots = new Map();
  const watchlistErrors = new Map();
  const trendErrors = new Map();
  const sectorCache = new Map();
  const sectorErrors = new Map();
  const capitalCache = new Map();
  const timers = new Set();
  const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  const calendarFormatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  let connected = false;
  let connectionError = "正在连接本地行情服务";
  let subscription = "";
  let generation = 0;
  let subscriptionController = null;
  let watchlistSubscription = "";
  let watchlistGeneration = 0;
  let watchlistController = null;
  let watchlistTimer = null;
  let watchlistRoundFinishedAt = null;
  let quoteRoundFinishedAt = null;
  let sectorKind = "industry";
  let sectorPage = 1;
  let detailSecid = null;
  let chartMode = "auction";
  let capitalStock = null;
  let capitalGeneration = 0;
  let capitalController = null;
  let capitalTimer = null;
  let billboardTimer = null;
  let darkTimer = null;
  let darkController = null;
  let darkGeneration = 0;

  function identifier(stock) {
    return `${stock.market === "SH" ? "1" : "0"}.${stock.code}`;
  }

  function visibleStocks() {
    const pageSize = stockPageSize();
    return filteredStocks().slice(state.pageIndex * pageSize, (state.pageIndex + 1) * pageSize);
  }

  function schedule(callback, delay) {
    const timer = setTimeout(() => { timers.delete(timer); callback(); }, delay);
    timers.add(timer);
  }

  async function api(path, parentSignal, timeout = 35000) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    parentSignal?.addEventListener("abort", abort, { once: true });
    if (parentSignal?.aborted) controller.abort();
    const timer = setTimeout(abort, timeout);
    try {
      const response = await fetch(path, { signal: controller.signal, cache: "no-store" });
      let payload;
      try { payload = await response.json(); }
      catch { throw new Error("本地服务未返回JSON；请使用python server.py启动，而非普通静态文件服务"); }
      if (!response.ok) {
        throw new Error(payload.error || payload.errors?.[0]?.message || `请求失败 HTTP ${response.status}`);
      }
      return payload;
    } catch (error) {
      if (parentSignal?.aborted) throw error;
      if (error.name === "AbortError") throw new Error("请求超时，当前没有取得新数据");
      if (error instanceof TypeError) throw new Error("无法连接本地后端，请检查服务是否仍在运行");
      throw error;
    } finally {
      clearTimeout(timer);
      parentSignal?.removeEventListener("abort", abort);
    }
  }

  function inferStockMarket(code) {
    if (/^(?:60|68)\d{4}$/.test(code)) return "SH";
    if (/^(?:00|30)\d{4}$/.test(code)) return "SZ";
    return null;
  }

  async function resolveStock(code, signal) {
    const market = inferStockMarket(code);
    if (!market) throw new Error("当前只支持自动识别沪深A股的6位股票代码。");
    const secid = `${market === "SH" ? "1" : "0"}.${code}`;
    const payload = await api(`/api/quotes?secids=${encodeURIComponent(secid)}`, signal, 20000);
    const quote = Array.isArray(payload.data) ? payload.data.find(record => record.secid === secid) : null;
    const name = typeof quote?.name === "string" ? quote.name.trim() : "";
    if (!name || name === "-" || name.length > 40 || /[\u0000-\u001f\u007f]/.test(name)) {
      throw new Error("行情接口未返回有效证券名称，请检查代码或稍后重试。");
    }
    return { market, code, name };
  }

  function sourceTime(timestamp) {
    return Number.isFinite(timestamp) ? timeFormatter.format(new Date(timestamp * 1000)) : "未提供";
  }

  function percentage(value) {
    return Number.isFinite(value) ? `${value > 0 ? "+" : ""}${value.toFixed(2)}%` : "—";
  }

  function directionClass(value) {
    return Number.isFinite(value) && value !== 0 ? (value > 0 ? "is-positive" : "is-negative") : "";
  }

  function watchlistView(stock) {
    const secid = identifier(stock);
    const quote = quotes.get(secid);
    const snapshot = watchlistSnapshots.get(secid);
    const quoteTime = Number.isFinite(quote?.source_timestamp) ? quote.source_timestamp : -1;
    const snapshotTime = Number.isFinite(snapshot?.source_timestamp) ? snapshot.source_timestamp : -1;
    const record = !quote ? snapshot : !snapshot ? quote : snapshotTime === -1 && quoteTime === -1
      ? (snapshot.fetched_at || 0) >= (quote.fetched_at || 0) ? snapshot : quote
      : snapshotTime >= quoteTime ? snapshot : quote;
    const changePct = Number.isFinite(record?.change_pct) ? Number(record.change_pct.toFixed(2)) : null;
    const industryKnown = record && Object.prototype.hasOwnProperty.call(record, "industry");
    const industry = industryKnown ? record.industry : null;
    return {
      ...record,
      name: record?.name || stock.name || stock.code,
      precision: quote?.precision,
      change_pct: changePct,
      changePct,
      industry,
      industryKey: industry ? `industry:${industry}` : industryKnown ? "missing" : "pending",
      isToday: Number.isFinite(record?.source_timestamp) && marketClock(new Date(record.source_timestamp * 1000)).date === marketClock().date,
      hasData: Boolean(record),
      error: record === snapshot && snapshot ? watchlistErrors.get(secid)
        : record === quote && quote ? quoteErrors.get(secid) : watchlistErrors.get(secid) || quoteErrors.get(secid),
    };
  }

  function sourceAge(timestamp) {
    return Number.isFinite(timestamp) ? Math.max(0, Math.floor(Date.now() / 1000 - timestamp)) : null;
  }

  function renderWatchlistFreshness() {
    const target = document.querySelector("#watchlist-freshness");
    const views = state.stocks.map(watchlistView);
    const loaded = views.filter(view => view.hasData).length;
    const today = views.filter(view => view.isToday && Number.isFinite(view.changePct)).length;
    const timestamps = visibleStocks().map(stock => watchlistView(stock).source_timestamp).filter(Number.isFinite);
    const source = timestamps.length
      ? `当前页源记录 ${sourceTime(Math.min(...timestamps))} 至 ${sourceTime(Math.max(...timestamps))} · 最早记录距今 ${sourceAge(Math.min(...timestamps))}秒（非传输延迟）`
      : "当前页源时间未提供";
    const failed = state.stocks.filter(stock => watchlistErrors.has(identifier(stock))).length;
    const errors = state.stocks.map(stock => watchlistErrors.get(identifier(stock))).filter(Boolean);
    target.textContent = `请求目标：当前页2秒／全自选5秒，不保证源更新频率 · 全自选已加载 ${loaded}/${state.stocks.length} · 今日有效涨跌幅 ${today}只 · ${source} · 当前页最近完成尝试 ${sourceTime(quoteRoundFinishedAt)} · 全自选最近完成尝试 ${sourceTime(watchlistRoundFinishedAt)}${failed ? ` · ${failed}只快照更新失败，保留旧值：${errors[0].slice(0, 100)}` : ""}；按最新报价涨跌幅筛选，非竞价历史涨幅；非今日或缺失值不参与涨跌幅筛选。`;
    target.title = [...new Set(errors)].join("；");
  }

  function listView(stock) {
    const quote = watchlistView(stock);
    const error = quote.error;
    const precision = Number.isInteger(quote?.precision) && quote.precision >= 0 && quote.precision <= 6 ? quote.precision : 2;
    const history = Number.isFinite(quote?.source_timestamp) && marketClock(new Date(quote.source_timestamp * 1000)).date !== marketClock().date;
    const missingIndustryField = quote.industryKey === "pending";
    const age = sourceAge(quote.source_timestamp);
    return {
      name: quote?.name || stock.name || stock.code,
      price: Number.isFinite(quote?.latest_price) ? quote.latest_price.toFixed(precision) : "—",
      change: percentage(quote?.change_pct),
      color: directionClass(quote?.change_pct),
      industry: quote.industry || (missingIndustryField ? "待分类" : "未提供"),
      status: `${error ? (quote.hasData ? "更新失败 / 旧报价 · " : "报价失败 · ") : ""}${history ? "历史 / 非今日 · " : ""}源时间 ${sourceTime(quote?.source_timestamp)}${age === null ? "" : ` · 距今${age}秒`}${missingIndustryField && quote.hasData ? " · 行业字段缺失，请重启后端" : ""}`,
      title: `${error || "东方财富公开网页最新报价，不是竞价分钟选点价格"}；采集 ${sourceTime(quote?.fetched_at)}；记录年龄不是传输延迟；行业使用数据源原分类，缺失不推测；不保证实时。`,
    };
  }

  function marketClock(date = new Date()) {
    const parts = Object.fromEntries(calendarFormatter.formatToParts(date).map(part => [part.type, part.value]));
    return {
      date: `${parts.year}-${parts.month}-${parts.day}`,
      weekday: !["Sat", "Sun"].includes(parts.weekday),
      seconds: Number(parts.hour) * 3600 + Number(parts.minute) * 60 + Number(parts.second),
    };
  }

  function trendRefreshDelay() {
    const clock = marketClock();
    if (!clock.weekday) return 30000;
    if (clock.seconds >= 33300 && clock.seconds < 34260) return 5000;
    if (clock.seconds < 33300) return Math.min(30000, (33300 - clock.seconds) * 1000);
    return 30000;
  }

  function selectedPoints(data) {
    const records = chartMode === "auction" ? data?.auction_points : data?.points;
    return Array.isArray(records)
      ? records.filter(point => Number.isFinite(point.price) && point.price > 0 && Number.isFinite(point.minute))
      : [];
  }

  function chartMarkup(secid) {
    const data = trends.get(secid);
    const error = trendErrors.get(secid);
    const isAuction = chartMode === "auction";
    const points = selectedPoints(data);
    if (!points.length) {
      let message = error || (data ? `数据源暂无有效${isAuction ? "竞价时段分钟" : "常规分时"}记录` : "正在获取真实走势");
      if (isAuction && data && !Array.isArray(data.auction_points)) message = "竞价接口未更新，请重启 python server.py";
      const hint = isAuction ? "09:15—09:25 · 不用普通报价补线" : "普通分时，不代表集合竞价";
      return `<div class="chart-placeholder"><span>${escapeHtml(message)}</span><span>${hint}</span></div>`;
    }
    const baseline = Number.isFinite(data.previous_close) && data.previous_close > 0 ? data.previous_close : points[0].price;
    const minimum = Math.min(baseline, ...points.map(point => point.price));
    const maximum = Math.max(baseline, ...points.map(point => point.price));
    const padding = Math.max((maximum - minimum) * 0.12, baseline * 0.0002, 0.001);
    const lower = minimum - padding;
    const span = maximum - minimum + padding * 2;
    const horizontal = point => 4 + ((point.minute - (isAuction ? 555 : 0)) / (isAuction ? 10 : 240)) * 312;
    const vertical = price => (isAuction ? 92 : 65) - ((price - lower) / span) * (isAuction ? 84 : 60);
    const maximumVolume = Math.max(1, ...points.map(point => Number.isFinite(point.volume) ? point.volume : 0));
    const color = points[points.length - 1].price >= baseline ? "var(--rise)" : "var(--fall)";
    let previousMinute = null;
    const path = points.map(point => {
      const command = previousMinute === null || point.minute - previousMinute > 2 ? "M" : "L";
      previousMinute = point.minute;
      return `${command}${horizontal(point).toFixed(2)},${vertical(point.price).toFixed(2)}`;
    }).join(" ");
    const bars = isAuction ? "" : points.map((point, index) => {
      if (!Number.isFinite(point.volume) || point.volume <= 0) return "";
      const previousPrice = index > 0 ? points[index - 1].price : baseline;
      const barColor = point.price > previousPrice
        ? "var(--rise)"
        : point.price < previousPrice ? "var(--fall)" : "var(--muted)";
      const height = (point.volume / maximumVolume) * 20;
      return `<rect x="${horizontal(point).toFixed(2)}" y="${(99 - height).toFixed(2)}" width="0.9" height="${height.toFixed(2)}" fill="${barColor}"/>`;
    }).join("");
    const single = points.length === 1 ? `<circle cx="${horizontal(points[0]).toFixed(2)}" cy="${vertical(points[0].price).toFixed(2)}" r="2" fill="${color}"/>` : "";
    const timestamp = isAuction ? data.auction_source_timestamp : data.source_timestamp;
    const date = Number.isFinite(timestamp) ? marketClock(new Date(timestamp * 1000)).date : "日期未提供";
    const historical = date !== marketClock().date ? " · 非今日" : "";
    const label = isAuction ? "竞价分钟" : "普通分时";
    const description = isAuction ? "09:15至09:25竞价时段分钟价格，不含虚拟匹配量" : "真实普通分时价格及成交量，非竞价图表";
    return `<svg class="actual-chart" viewBox="0 0 320 100" preserveAspectRatio="none" role="img" aria-label="${description}">
      <line x1="0" x2="320" y1="${vertical(baseline).toFixed(2)}" y2="${vertical(baseline).toFixed(2)}" stroke="#526076" stroke-dasharray="3 4" stroke-width="0.6"/>
      <path d="${path}" fill="none" stroke="${color}" stroke-width="1.4" vector-effect="non-scaling-stroke"/>
      ${single}<g opacity="0.8">${bars}</g>
    </svg><span class="chart-source">${escapeHtml(date)} · ${label}${historical}${error ? " · 加载失败 / 旧数据" : ""}</span>${isAuction ? "" : '<span class="chart-volume-key">成交量·源单位</span>'}`;
  }

  function auctionVolumeMarkup() {
    return `<div class="auction-volume-zones" role="group" aria-label="竞价量柱分区，真实量数据未接入">
      <div class="auction-volume-zone unmatched-volume-zone" title="未匹配量及方向尚未核验；接入后买方未匹配用红色，卖方未匹配用绿色，不以买一量替代">
        <span class="volume-zone-label">未匹配量</span><span class="volume-empty">真实量数据未接入</span>
      </div>
      <div class="auction-volume-zone matched-volume-zone" title="虚拟匹配量尚未核验，不以普通成交量或分钟价格变化替代">
        <span class="volume-zone-label">虚拟匹配量</span><span class="volume-empty">真实量数据未接入</span>
      </div>
    </div>`;
  }

  function regularMetricsMarkup(quote, precision) {
    const fixedValue = (value, digits, suffix = "") =>
      Number.isFinite(value) && value >= 0
        ? `${value.toFixed(digits)}${suffix}` : "—";
    const scaledValue = (value, suffix) =>
      Number.isFinite(value) && value >= 0
        ? `${amount(value)}${suffix}` : "—";
    const priceColor = value => {
      if (!Number.isFinite(value)) return "metric-muted";
      if (!Number.isFinite(quote?.previous_close) || quote.previous_close <= 0) {
        return "metric-neutral";
      }
      return directionClass(value - quote.previous_close) || "metric-neutral";
    };
    const rows = [
      ["开盘价", fixedValue(quote?.open_price, precision), priceColor(quote?.open_price)],
      ["最高价", fixedValue(quote?.high_price, precision), priceColor(quote?.high_price)],
      ["最低价", fixedValue(quote?.low_price, precision), priceColor(quote?.low_price)],
      ["换手率", fixedValue(quote?.turnover_rate, 2, "%"), "metric-activity"],
      ["成交量", scaledValue(quote?.volume_lots, "手"), "metric-volume"],
      ["成交额", scaledValue(quote?.turnover_amount, "元"), "metric-volume"],
      ["振幅", fixedValue(quote?.amplitude_pct, 2, "%"), "metric-range"],
    ];
    return rows.map(([label, value, colorClass]) =>
      `<div title="${escapeHtml(`${label} ${value}`)}"><dt>${escapeHtml(label)}</dt><dd class="${value === "—" ? "metric-muted" : colorClass}">${escapeHtml(value)}</dd></div>`
    ).join("");
  }

  function cardView(stock) {
    const secid = identifier(stock);
    const quote = quotes.get(secid);
    const latest = watchlistView(stock);
    const data = trends.get(secid);
    const quoteError = quoteErrors.get(secid);
    const error = trendErrors.get(secid);
    const isAuction = chartMode === "auction";
    const points = selectedPoints(data);
    const lastPoint = points[points.length - 1];
    const timestamp = isAuction ? data?.auction_source_timestamp : data?.source_timestamp;
    const clock = marketClock();
    const history = Number.isFinite(timestamp) && marketClock(new Date(timestamp * 1000)).date !== clock.date;
    let status = lastPoint ? (isAuction ? "竞价分钟记录" : "普通分时记录") : "正在获取走势";
    if (!connected) status = "后端未连接";
    else if (error) status = lastPoint ? "走势失败·旧数据" : "走势获取失败";
    else if (isAuction && data && !Array.isArray(data.auction_points)) status = "竞价接口待更新";
    else if (history) status = isAuction ? "历史竞价·非今日" : "历史分时·非今日";
    else if (!lastPoint && data) status = isAuction && clock.seconds < 33300 ? "等待竞价记录" : "源无有效记录";
    else if (isAuction && lastPoint && clock.weekday && clock.seconds >= 33300 && clock.seconds < 33960) {
      status = Date.now() / 1000 - timestamp > 120 ? "竞价分钟记录延迟" : "竞价分钟·刷新中";
    }
    const precision = Number.isInteger(quote?.precision) && quote.precision >= 0 && quote.precision <= 6 ? quote.precision : 2;
    const value = isAuction ? lastPoint?.price : latest.latest_price;
    const baseline = data?.previous_close;
    const change = isAuction
      ? Number.isFinite(value) && Number.isFinite(baseline) && baseline > 0 ? (value / baseline - 1) * 100 : null
      : latest.changePct;
    const quoteText = Number.isFinite(latest.latest_price) ? latest.latest_price.toFixed(precision) : "—";
    const age = sourceAge(latest.source_timestamp);
    const quoteNote = `最新报价 ${quoteText} · 源时间 ${sourceTime(latest.source_timestamp)} · 采集 ${sourceTime(latest.fetched_at)}${age === null ? "" : ` · 距今${age}秒`}${latest.hasData && !latest.isToday && Number.isFinite(latest.source_timestamp) ? " · 历史 / 非今日" : ""}${latest.error ? " · 报价失败 / 旧数据" : ""}`;
    const ratioAvailable = Number.isFinite(quote?.volume_ratio) && quote.volume_ratio >= 0;
    const ratioHistory = Number.isFinite(quote?.source_timestamp) && marketClock(new Date(quote.source_timestamp * 1000)).date !== clock.date;
    const ratioState = quoteError ? (ratioAvailable ? "旧值" : "获取失败") : ratioHistory ? "历史" : "";
    const ratioValue = ratioAvailable ? `${quote.volume_ratio.toFixed(2)}倍` : "未提供";
    const ratioSourceTime = Number.isFinite(quote?.source_timestamp)
      ? `${marketClock(new Date(quote.source_timestamp * 1000)).date} ${sourceTime(quote.source_timestamp).split(" ").pop()}`
      : "未提供";
    let ratioTitle = `东方财富报价源量比，按源值显示；报价源时间 ${ratioSourceTime}；不是09:25历史量比，不使用走势源时间。不保证实时。`;
    if (quote && !Object.prototype.hasOwnProperty.call(quote, "volume_ratio")) ratioTitle += " 当前后端未返回量比字段，请重启 python server.py。";
    if (quoteError) ratioTitle += ` 获取失败：${quoteError}；${ratioAvailable ? "保留旧值" : "没有有效旧值"}。`;
    else if (ratioHistory) ratioTitle += " 此为历史报价量比，非今日数据。";
    const regularFields = ["open_price", "high_price", "low_price", "turnover_rate", "volume_lots", "turnover_amount", "amplitude_pct"];
    const legacyMetrics = quote && regularFields.some(field => !Object.prototype.hasOwnProperty.call(quote, field));
    const metricsFlags = [
      quoteError ? (quote ? "旧数据 / 更新失败" : "获取失败") : "",
      ratioHistory ? "历史 / 非今日" : "",
      quote && !Number.isFinite(quote.source_timestamp) ? "源时间未提供" : "",
      legacyMetrics ? "字段待更新，请重启后端" : "",
    ].filter(Boolean);
    const metricsNote = metricsFlags.join(" · ") || (quote ? "指标 · 报价快照" : "指标等待报价");
    let metricsTitle = `普通分时指标来自最新报价快照，非历史分钟选点数据；报价源时间 ${ratioSourceTime}；成交量单位为手，成交额单位为元。${metricsFlags.length ? ` ${metricsFlags.join("；")}。` : ""}不保证实时。`;
    if (legacyMetrics) metricsTitle += " 当前后端未返回完整指标字段，请重启 python server.py，再刷新页面。";
    if (quoteError) metricsTitle += ` 获取失败：${quoteError}。`;
    const resultPoints = Array.isArray(data?.preopen_result_points) ? data.preopen_result_points : [];
    const result = resultPoints.find(point => Number.isFinite(point.price) && Number.isFinite(point.timestamp));
    const resultClock = result ? sourceTime(result.timestamp).split(" ").pop().slice(0, 5) : "";
    const resultText = result ? `${resultClock}记录 ${result.price.toFixed(precision)}` : "";
    const resultTitle = result ? `${marketClock(new Date(result.timestamp * 1000)).date} ${resultText}；源09:25之后的价格记录，非09:25竞价成交确认${error ? "；获取失败，保留旧数据" : ""}` : "";
    return {
      name: quote?.name || stock.name || stock.code,
      value: Number.isFinite(value) ? value.toFixed(precision) : "—",
      change: percentage(change),
      changeClass: directionClass(change),
      caption: isAuction ? "竞价时段分钟价" : "最新报价·非竞价",
      context: `<div class="card-context"><span title="${escapeHtml(quoteNote)}">${escapeHtml(quoteNote)}</span>${isAuction && result ? `<span class="preopen-summary" title="${escapeHtml(resultTitle)}">${escapeHtml(resultText)}${history ? " · 非今日" : ""}${error ? " · 旧数据" : ""}</span>` : ""}${!isAuction ? `<span class="quote-metrics-note" title="${escapeHtml(metricsTitle)}">${escapeHtml(metricsNote)}</span>` : ""}</div>`,
      detailTitle: isAuction ? "竞价详情" : "普通分时详情",
      detailLabel: isAuction ? "分钟走势 / 匹配量未提供" : "普通分时 / 最新报价指标",
      chartLabel: isAuction ? "竞价时段分钟价格，非逐笔快照" : "普通分时，非竞价图表",
      axis: isAuction ? ["09:15", "09:20", "09:25"] : ["09:30", "11:30 / 13:00", "15:00"],
      chart: connected ? chartMarkup(secid) : `<div class="chart-placeholder"><span>请用python server.py启动后端</span><span>尚未取得行情</span></div>`,
      volumeZones: isAuction ? auctionVolumeMarkup() : "",
      regularMetrics: isAuction ? "" : regularMetricsMarkup(quote, precision),
      metricsTitle: isAuction ? "匹配量、未匹配量及方向未核实，不以普通成交量替代；报价量比单独采用东方财富源值" : metricsTitle,
      volumeRatio: `${ratioState ? `${ratioState} · ` : ""}${ratioValue}`,
      volumeRatioTitle: ratioTitle,
      volumeRatioClass: isAuction ? "" : ratioAvailable ? "metric-activity" : "metric-muted",
      status,
      sourceTime: Number.isFinite(timestamp) ? sourceTime(timestamp) : "—",
      title: `${error || "走势来源：东方财富公开网页分时"}；走势采集时间 ${sourceTime(data?.fetched_at)}；${quoteError || quoteNote}。${isAuction ? "竞价分钟价不是逐笔虚拟参考价；当前数据源未提供经核实的匹配量及未匹配量。不保证实时。" : metricsTitle}`,
    };
  }

  function currentSectorKey() {
    return state.page === "us-sectors" ? "US" : `CN:${sectorKind}:${sectorPage}`;
  }

  function updateNotice() {
    renderWatchlistFreshness();
    const badge = document.querySelector("#data-badge");
    if (!connected) {
      badge.textContent = "后端未连接";
      document.querySelector("#source-notice-text").textContent = connectionError;
      return;
    }
    badge.textContent = state.page === "auction" ? (state.view === "list" ? "公开行情 · 自选列表" : chartMode === "auction" ? "公开行情 · 竞价分钟" : "公开行情 · 普通分时") : "公开行情";
    let message;
    if (state.page === "auction") {
      const failed = visibleStocks().filter(stock => quoteErrors.has(identifier(stock)) || (state.view !== "list" && trendErrors.has(identifier(stock)))).length;
      message = state.view === "list"
        ? "列表显示最新报价及源行业分类，不是09:25竞价历史价格；每页20只，分批获取报价。点击股票名称打开当前所选竞价／普通分时详情。源时间与采集时间不同，不保证实时。"
        : chartMode === "auction"
        ? "保留竞价分钟走势，下方量柱分区的真实量数据未接入，不以普通成交量替代。报价量比取东方财富源值，非09:25历史量比；请分别核对走势与报价源时间，不保证实时。"
        : "普通分时显示开盘价、最高价、最低价、换手率、成交量、成交额、振幅和报价量比。指标采用最新报价快照，不是历史分钟选点数据；成交量以手、成交额以元计，分别核对报价与走势源时间，不保证实时。";
      if (failed) message += ` ${failed}只股票部分获取失败，旧数据会保留并标记。`;
    } else if (state.page === "us-sectors") {
      message = "Nasdaq原行业分类，按有效样本等权统计；非官方行业指数。源时间未提供，不保证实时。";
    } else {
      message = "东方财富行业 / 概念板块；涨跌幅及成交额采用源值。统计仅覆盖当前页，源时间不等于采集时间。";
    }
    const error = sectorErrors.get(currentSectorKey());
    if (state.page !== "auction" && error) message += ` 获取失败：${error}，已有数据将标为旧数据。`;
    document.querySelector("#source-notice-text").textContent = message;
  }

  function repaintCards() {
    renderGrid();
    const dialog = document.querySelector("#detail-dialog");
    if (dialog.open && detailSecid) {
      const stock = state.stocks.find(item => identifier(item) === detailSecid);
      if (stock) {
        const market = cardView(stock);
        document.querySelector("#detail-dialog-title").textContent = `${market.name} · ${market.detailTitle}`;
        document.querySelector("#detail-content").innerHTML = cardMarkup(stock, 0, true);
        renderDarkAnalysis();
      }
    }
    updateNotice();
  }

  function nextRefreshDelay(startedAt, interval, failedRounds) {
    const delay = failedRounds > 0 ? Math.min(30000, interval * (2 ** Math.min(failedRounds, 4))) : interval;
    return failedRounds > 0 ? delay : Math.max(250, delay - (performance.now() - startedAt));
  }

  function stopWatchlist() {
    watchlistGeneration += 1;
    watchlistController?.abort();
    clearTimeout(watchlistTimer);
    watchlistTimer = null;
    watchlistSubscription = "";
  }

  function syncWatchlist(force = false) {
    const stocks = state.page === "auction" ? [...state.stocks].sort((left, right) => identifier(left).localeCompare(identifier(right))) : [];
    const key = stocks.map(identifier).join(",");
    if (!key) {
      if (watchlistSubscription) stopWatchlist();
      return;
    }
    if (key === watchlistSubscription && !force) return;
    stopWatchlist();
    watchlistSubscription = key;
    const active = new Set(stocks.map(identifier));
    for (const records of [watchlistSnapshots, watchlistErrors]) {
      for (const secid of records.keys()) if (!active.has(secid)) records.delete(secid);
    }
    watchlistController = new AbortController();
    watchlistRoundFinishedAt = null;
    watchlistLoop(stocks, watchlistGeneration, watchlistController.signal);
  }

  async function watchlistLoop(stocks, currentGeneration, signal, failedRounds = 0) {
    const startedAt = performance.now();
    let failed = false;
    for (let offset = 0; offset < stocks.length; offset += 50) {
      if (watchlistGeneration !== currentGeneration || signal.aborted) return;
      const secids = stocks.slice(offset, offset + 50).map(identifier);
      try {
        const payload = await api(`/api/watchlist-snapshot?secids=${encodeURIComponent(secids.join(","))}`, signal);
        if (watchlistGeneration !== currentGeneration || signal.aborted) return;
        if (!Array.isArray(payload.data)) throw new Error("全自选快照接口结构异常，请重启后端");
        const received = new Set();
        for (const snapshot of payload.data) {
          if (!secids.includes(snapshot.secid)) continue;
          const previous = watchlistSnapshots.get(snapshot.secid);
          if (!previous || !Number.isFinite(previous.source_timestamp) ||
              (Number.isFinite(snapshot.source_timestamp) && snapshot.source_timestamp >= previous.source_timestamp)) {
            watchlistSnapshots.set(snapshot.secid, snapshot);
            watchlistErrors.delete(snapshot.secid);
          } else {
            watchlistErrors.set(snapshot.secid, "源记录时间倒退或缺失，保留已知较新快照");
            failed = true;
          }
          received.add(snapshot.secid);
        }
        for (const secid of secids) {
          if (!received.has(secid)) {
            const message = (payload.errors || []).find(error => error.secid === secid)?.message;
            watchlistErrors.set(secid, message || "本轮未返回该股票快照");
            failed = true;
          }
        }
      } catch (error) {
        if (watchlistGeneration !== currentGeneration || signal.aborted) return;
        const message = error.message.includes("接口或文件不存在") ? "后端缺少全自选快照接口，请重启 python server.py" : error.message;
        secids.forEach(secid => watchlistErrors.set(secid, message));
        failed = true;
      }
      if (watchlistGeneration !== currentGeneration || signal.aborted) return;
      repaintCards();
    }
    if (watchlistGeneration !== currentGeneration || signal.aborted) return;
    watchlistRoundFinishedAt = Date.now() / 1000;
    renderWatchlistFreshness();
    const failures = failed ? failedRounds + 1 : 0;
    watchlistTimer = setTimeout(() => watchlistLoop(stocks, currentGeneration, signal, failures), nextRefreshDelay(startedAt, 5000, failures));
  }

  async function quoteLoop(stocks, currentGeneration, signal, failedRounds = 0) {
    const startedAt = performance.now();
    let failed = false;
    for (let offset = 0; offset < stocks.length; offset += 9) {
      if (generation !== currentGeneration || signal.aborted) return;
      const secids = stocks.slice(offset, offset + 9).map(identifier);
      try {
        const payload = await api(`/api/quotes?secids=${encodeURIComponent(secids.join(","))}`, signal);
        if (generation !== currentGeneration || signal.aborted) return;
        const received = new Set();
        for (const quote of payload.data || []) {
          if (!secids.includes(quote.secid)) continue;
          const previous = quotes.get(quote.secid);
          if (!previous || !Number.isFinite(previous.source_timestamp) ||
              (Number.isFinite(quote.source_timestamp) && quote.source_timestamp >= previous.source_timestamp)) {
            quotes.set(quote.secid, quote);
            quoteErrors.delete(quote.secid);
          } else {
            quoteErrors.set(quote.secid, "源记录时间倒退或缺失，保留已知较新报价");
            failed = true;
          }
          received.add(quote.secid);
        }
        for (const error of payload.errors || []) {
          if (secids.includes(error.secid)) {
            quoteErrors.set(error.secid, error.message);
            failed = true;
          }
        }
        for (const secid of secids) {
          if (!received.has(secid) && !(payload.errors || []).some(error => error.secid === secid)) {
            quoteErrors.set(secid, "本轮未返回该股票报价");
            failed = true;
          }
        }
      } catch (error) {
        if (generation !== currentGeneration || signal.aborted) return;
        secids.forEach(secid => quoteErrors.set(secid, error.message));
        failed = true;
      }
      if (generation !== currentGeneration || signal.aborted) return;
      repaintCards();
    }
    if (generation !== currentGeneration || signal.aborted) return;
    quoteRoundFinishedAt = Date.now() / 1000;
    renderWatchlistFreshness();
    const failures = failed ? failedRounds + 1 : 0;
    schedule(() => quoteLoop(stocks, currentGeneration, signal, failures), nextRefreshDelay(startedAt, 2000, failures));
  }

  async function trendLoop(stocks, currentGeneration, signal) {
    let cursor = 0;
    async function worker() {
      while (cursor < stocks.length && generation === currentGeneration && !signal.aborted) {
        const stock = stocks[cursor++];
        const secid = identifier(stock);
        try {
          const data = await api(`/api/trends?secid=${encodeURIComponent(secid)}`, signal);
          if (generation !== currentGeneration) return;
          trends.set(secid, data);
          trendErrors.delete(secid);
        } catch (error) {
          if (generation !== currentGeneration || signal.aborted) return;
          trendErrors.set(secid, error.message);
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(3, stocks.length) }, () => worker()));
    if (generation !== currentGeneration || signal.aborted) return;
    repaintCards();
    schedule(() => trendLoop(stocks, currentGeneration, signal), trendRefreshDelay());
  }
  function amount(value) {
    if (!Number.isFinite(value)) return "—";
    if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
    if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)}万`;
    return value.toFixed(2);
  }

  function signedAmount(value) {
    return Number.isFinite(value) ? `${value > 0 ? "+" : ""}${amount(value)}` : "—";
  }

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

  function capitalEntry(secid) {
    if (!capitalCache.has(secid)) capitalCache.set(secid, { current: null, history: null, billboard: null, dark: null, darkStatus: null, errors: {} });
    return capitalCache.get(secid);
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

  function renderDarkAnalysis() {
    const section = document.querySelector("#capital-dark-section");
    section.hidden = chartMode !== "regular" || !capitalStock;
    if (section.hidden) return;
    const entry = capitalEntry(identifier(capitalStock));
    const today = marketClock().date;
    const status = entry.darkStatus?.source_date === today ? entry.darkStatus : null;
    if (entry.dark?.source_date !== today) entry.dark = null;
    const snapshot = entry.dark;
    const error = status?.error || entry.errors.dark;
    const progress = status?.updating ? `采集中 ${status.pages_loaded} / ${status.pages_total ?? "待确认"} 页` : "约5分钟更新";
    const stateLabel = error ? (snapshot ? "旧快照 / 更新失败" : "采集失败")
      : status?.stale ? "旧快照 / 等待更新"
      : status?.updating ? (snapshot ? "已取得 / 本轮更新中" : "正在采集当日榜单")
      : snapshot ? "已取得当日快照" : status?.status === "not_found" ? "本轮榜单未匹配到该股票" : "等待当日榜单";
    const coverage = status?.partial ? " · 分页覆盖不完整或排名动态变化" : "";
    document.querySelector("#capital-dark-meta").textContent = `${today} · ${stateLabel} · ${progress}${coverage}${snapshot ? ` · 源记录 ${sourceTime(snapshot.source_timestamp)} · 采集 ${sourceTime(snapshot.fetched_at)} · 金额单位：元` : ""}${error ? ` · ${error}` : ""}`;
    document.querySelector("#capital-dark").innerHTML = darkSnapshotMarkup(snapshot);
  }

  function stopDarkAnalysis() {
    darkGeneration += 1;
    darkController?.abort();
    darkController = null;
    clearTimeout(darkTimer);
    darkTimer = null;
  }

  function loadDarkAnalysis(stock) {
    stopDarkAnalysis();
    renderDarkAnalysis();
    if (chartMode !== "regular" || document.hidden || !document.querySelector("#detail-dialog").open) return;
    const secid = identifier(stock);
    const entry = capitalEntry(secid);
    if (location.protocol === "file:") {
      entry.errors.dark = "请运行python server.py并通过本地服务打开页面";
      renderDarkAnalysis();
      return;
    }
    darkController = new AbortController();
    const signal = darkController.signal;
    const currentGeneration = darkGeneration;
    const active = () => darkGeneration === currentGeneration && !signal.aborted && chartMode === "regular"
      && !document.hidden && capitalStock && identifier(capitalStock) === secid && document.querySelector("#detail-dialog").open;
    async function poll() {
      let delay = 60000;
      try {
        const payload = await api(`/api/dark-flow?secid=${encodeURIComponent(secid)}`, signal);
        if (!active()) return;
        const today = marketClock().date;
        if (payload.secid !== secid || payload.source_date !== today || (payload.snapshot && (payload.snapshot.secid !== secid || payload.snapshot.source_date !== today))) {
          throw new Error("明暗盘快照代码或日期不匹配，不展示非当日数据");
        }
        entry.darkStatus = payload;
        if (payload.snapshot) entry.dark = payload.snapshot;
        delete entry.errors.dark;
        delay = payload.updating ? 3000 : Math.min(300000, Math.max(1000, (Number(payload.poll_after_seconds) || 300) * 1000));
      } catch (error) {
        if (!active()) return;
        entry.errors.dark = error.message === "接口或文件不存在" ? "请重启python server.py，启用当日明暗盘接口" : error.message;
      }
      if (!active()) return;
      renderDarkAnalysis();
      darkTimer = setTimeout(poll, delay);
    }
    poll();
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

  function renderCapitalAnalysis() {
    if (!capitalStock) return;
    renderDarkAnalysis();
    const entry = capitalEntry(identifier(capitalStock));
    const { current, history, billboard, errors } = entry;
    const currentMeta = document.querySelector("#capital-current-meta");
    const currentBody = document.querySelector("#capital-current");
    currentMeta.textContent = current
      ? `${errors.current ? `旧数据 / 更新失败：${errors.current} · ` : ""}源行情时间 ${sourceTime(current.source_timestamp)}（非逐笔资金时间） · 采集 ${sourceTime(current.fetched_at)}${current.cached ? " · 后端缓存" : ""} · 单位：元`
      : errors.current ? `资金获取失败：${errors.current}` : "正在获取资金分类…";
    if (current) {
      const main = current.rows.find(row => row.id === "main")?.net;
      const priceLabel = Number.isFinite(current.change_pct)
        ? current.change_pct > 0 ? "价格上涨" : current.change_pct < 0 ? "价格下跌" : "价格持平" : "价格涨跌幅缺失";
      const flowLabel = Number.isFinite(main) ? main > 0 ? "主力净流入" : main < 0 ? "主力净流出" : "主力净额为零" : "主力净额缺失";
      currentBody.innerHTML = `<div class="capital-signal"><span class="capital-status">${flowLabel}</span><strong class="${directionClass(main)}">${signedAmount(main)}</strong><span class="capital-tag">${priceLabel} / ${flowLabel}</span></div>
        <div class="capital-scroll"><table class="capital-table"><caption class="capital-note">主力流入 / 流出由超大单与大单相加；主力净额及净占比保留源值。不将主力与其子项重复加总。</caption><thead><tr><th scope="col">资金分类</th><th scope="col">流入（元）</th><th scope="col">流出（元）</th><th scope="col">净额（元）</th><th scope="col">净占比</th></tr></thead><tbody>${current.rows.map(row => `<tr><td>${escapeHtml(row.label)}</td><td>${amount(row.inflow)}</td><td>${amount(row.outflow)}</td><td class="${directionClass(row.net)}">${signedAmount(row.net)}</td><td class="${directionClass(row.ratio)}">${percentage(row.ratio)}</td></tr>`).join("")}</tbody></table></div>
        <p class="capital-note">这是数据源按成交单规模统计的资金分类，不是机构、游资或散户的账户识别，也不是资金必然“出逃”或“吸筹”的判断。</p>`;
    } else {
      currentBody.innerHTML = `<p class="capital-note">${errors.current ? "未取得有效资金数据，缺失不代表零。" : "仅加载当前打开的这只股票，不为所有宫格额外请求资金。"}</p>`;
    }
    document.querySelector("#capital-history-meta").textContent = history
      ? `${errors.history ? `旧数据 / 更新失败：${errors.history} · ` : ""}最新日线日期 ${history.source_date || "未提供"} · 采集 ${sourceTime(history.fetched_at)}${history.cached ? " · 后端缓存" : ""} · 排除当日记录，样本不足不补零`
      : errors.history ? `历史资金获取失败：${errors.history}` : "正在获取历史资金…";
    const historyBody = document.querySelector("#capital-history");
    const dailyOpen = Boolean(historyBody.querySelector("details")?.open);
    historyBody.innerHTML = history ? `<div class="capital-stat-grid">${history.summaries.map(summary => `<div class="capital-stat"><span>近${summary.window}条交易日记录 · 主力净额</span><strong class="${directionClass(summary.net)}">${signedAmount(summary.net)}</strong><small>有效 ${summary.valid_count} / ${summary.window}${summary.complete ? "" : " · 样本不足或缺失"}</small><small>${escapeHtml(summary.start_date || "—")} 至 ${escapeHtml(summary.end_date || "—")}</small></div>`).join("")}</div>
      ${capitalHistoryChart(history.rows)}<p class="capital-note">红色净流入，绿色净流出；灰色表示零，×表示缺失。统计的是数据源实际返回的交易日记录，不包含当日，不作买卖建议。</p>
      ${history.rows.length ? `<details${dailyOpen ? " open" : ""}><summary class="capital-status">查看逐日净额（元）</summary><div class="capital-scroll"><table class="capital-table"><thead><tr><th scope="col">交易日</th><th scope="col">主力（汇总）</th><th scope="col">超大单</th><th scope="col">大单</th><th scope="col">中单</th><th scope="col">小单</th></tr></thead><tbody>${[...history.rows].reverse().map(row => `<tr><td>${escapeHtml(row.date)}</td>${["main", "super_large", "large", "medium", "small"].map(key => `<td class="${directionClass(row[key])}">${signedAmount(row[key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>` : `<p class="capital-note">数据源暂无已结束日期的有效资金日线。</p>`}`
      : `<p class="capital-note">${errors.history ? "历史数据尚未取得，不显示模拟累计值。" : "历史资金加载中…"}</p>`;
    const partial = billboard?.errors?.map(error => error.message).join("；");
    document.querySelector("#capital-seats-meta").textContent = billboard
      ? `${errors.billboard ? `旧数据 / 更新失败：${errors.billboard} · ` : ""}${partial ? `部分披露缺失：${partial} · ` : ""}${billboard.trade_date ? `最新上榜交易日 ${billboard.trade_date}（不是盘中数据）` : `近${billboard.lookback_days}个自然日暂无上榜记录`} · 采集 ${sourceTime(billboard.fetched_at)}${billboard.cached ? " · 后端缓存" : ""}`
      : errors.billboard ? `龙虎榜获取失败：${errors.billboard}` : "正在获取最近披露的龙虎榜…";
    const seats = document.querySelector("#capital-seats");
    if (!billboard) {
      seats.innerHTML = `<p class="capital-note">${errors.billboard ? "未取得披露，不代表机构或游资没有交易。" : "龙虎榜与盘中资金独立加载，披露较慢不会阻塞资金分类。"}</p>`;
      return;
    }
    const warning = billboard.label_warning || (billboard.association_count ? "关联标签只按已核验配置及适用日期匹配；未匹配的席位不推测身份。" : "暂无已核验的具体游资关联名单；仅显示原始席位及披露类别。未识别不等于没有游资参与。");
    seats.innerHTML = `<p class="capital-note">${escapeHtml(warning)}</p>` + (billboard.trade_date ? billboard.groups.map(group => `<section class="capital-disclosure"><p class="capital-note">上榜原因：${escapeHtml(group.reason)}</p>${billboardTotalsMarkup(group, Boolean(billboard.errors?.length))}${group.rows.length ? `<div class="capital-scroll"><table class="capital-table capital-seat-table"><thead><tr><th scope="col">席位与标签</th><th scope="col">买入（元）</th><th scope="col">卖出（元）</th><th scope="col">净额（元）</th><th scope="col">列入榜单</th></tr></thead><tbody>${group.rows.map(row => `<tr><td><div>${escapeHtml(row.department_name)}</div><span class="capital-tag">${escapeHtml(row.category)}</span>${row.associations.length ? row.associations.map(associationMarkup).join("") : row.category === "营业部席位" ? `<span class="capital-tag">游资未识别</span>` : ""}</td><td>${amount(row.buy)}</td><td>${amount(row.sell)}</td><td class="${directionClass(row.net)}">${signedAmount(row.net)}</td><td>${row.listed_sides.map(side => side === "buy" ? "买榜" : "卖榜").join(" / ")}</td></tr>`).join("")}</tbody></table></div>` : `<p class="capital-note">已取得上榜原因，但席位暂无有效记录。</p>`}</section>`).join("") : `<p class="capital-note">没有近期披露不代表没有资金活动，不填充零金额或虚构席位。</p>`);
  }

  function stopCapitalAnalysis(clearStock = false) {
    stopDarkAnalysis();
    capitalGeneration += 1;
    capitalController?.abort();
    clearTimeout(capitalTimer);
    clearTimeout(billboardTimer);
    capitalTimer = null;
    billboardTimer = null;
    if (clearStock) capitalStock = null;
  }

  function loadCapitalAnalysis(stock) {
    stopCapitalAnalysis();
    capitalStock = stock;
    const secid = identifier(stock);
    const entry = capitalEntry(secid);
    renderCapitalAnalysis();
    if (location.protocol === "file:") {
      for (const part of ["current", "history", "billboard"]) entry.errors[part] = "请运行python server.py并通过本地服务打开页面";
      if (chartMode === "regular") entry.errors.dark = "请运行python server.py并通过本地服务打开页面";
      renderCapitalAnalysis();
      return;
    }
    if (document.hidden || !document.querySelector("#detail-dialog").open) return;
    capitalController = new AbortController();
    const signal = capitalController.signal;
    const currentGeneration = capitalGeneration;
    const active = () => capitalGeneration === currentGeneration && !signal.aborted && document.querySelector("#detail-dialog").open;
    async function poll(kind) {
      try {
        const payload = await api(`/api/${kind}?secid=${encodeURIComponent(secid)}`, signal, kind === "billboard" ? 85000 : 45000);
        if (!active()) return;
        if (kind === "money-flow") {
          for (const part of ["current", "history"]) {
            if (payload[part]) { entry[part] = payload[part]; delete entry.errors[part]; }
            else entry.errors[part] = payload.errors?.find(error => error.part === part)?.message || "本轮未返回有效数据";
          }
        } else if (payload.errors?.length && entry.billboard?.trade_date === payload.trade_date && !entry.billboard.errors?.length) {
          entry.errors.billboard = "本轮披露不完整，保留上次完整数据";
        } else {
          entry.billboard = payload;
          delete entry.errors.billboard;
        }
      } catch (error) {
        if (!active()) return;
        for (const part of kind === "money-flow" ? ["current", "history"] : ["billboard"]) entry.errors[part] = error.message;
      }
      if (!active()) return;
      renderCapitalAnalysis();
      if (kind === "money-flow") capitalTimer = setTimeout(() => poll(kind), 30000);
      else billboardTimer = setTimeout(() => poll(kind), 600000);
    }
    poll("money-flow");
    poll("billboard");
    loadDarkAnalysis(stock);
  }

  function renderSectors() {
    const isUS = state.page === "us-sectors";
    const key = currentSectorKey();
    const data = sectorCache.get(key);
    const error = sectorErrors.get(key);
    document.querySelector("#sector-kind-controls").hidden = isUS;
    document.querySelectorAll("[data-sector-kind]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.sectorKind === sectorKind));
    });
    document.querySelector("#sector-title").textContent = isUS ? "美股行业样本看板 · 等权统计" : `A股${sectorKind === "industry" ? "行业" : "概念"}板块排行`;
    document.querySelector("#sector-state").textContent = error ? (data ? "获取失败 / 旧数据" : "获取失败 / 无数据") : data ? "已取得 / 不保证实时" : "正在加载";
    const headers = isUS ? ["行业原分类", "样本等权涨幅", "有效样本数", "领涨样本"] : ["板块名称", "涨跌幅", "成交额（元）", "领涨股"];
    document.querySelector("#sector-table-head").innerHTML = `<tr>${headers.map(label => `<th scope="col">${label}</th>`).join("")}</tr>`;
    document.querySelector("#sector-caption").textContent = isUS
      ? "Nasdaq筛选器样本按原sector分类取有效涨跌幅算术平均；非全市场指数，不保证实时。"
      : "数据源原板块分类，按涨幅降序；上涨 / 下跌统计仅覆盖当前页。";
    document.querySelector("#sector-up-label").textContent = isUS ? "上涨行业" : "本页上涨板块";
    document.querySelector("#sector-down-label").textContent = isUS ? "下跌行业" : "本页下跌板块";
    document.querySelector("#sector-up-count").textContent = data ? data.rows.filter(row => row.change_pct > 0).length : "—";
    document.querySelector("#sector-down-count").textContent = data ? data.rows.filter(row => Number.isFinite(row.change_pct) && row.change_pct < 0).length : "—";
    document.querySelector("#sector-source-time").textContent = data ? sourceTime(data.source_timestamp) : "—";
    document.querySelector("#sector-time-note").textContent = isUS ? "源时间未知，采集成功不代表实时" : "当前页最早有效源时间";
    const table = document.querySelector("#sector-table-body");
    if (data?.rows?.length) {
      table.innerHTML = data.rows.map(row => `<tr>
        <td><strong>${escapeHtml(row.name)}</strong>${row.code ? `<small>${escapeHtml(row.code)}</small>` : ""}</td>
        <td class="${directionClass(row.change_pct)}">${percentage(row.change_pct)}</td>
        <td>${isUS ? row.sample_count.toLocaleString("zh-CN") : amount(row.turnover)}</td>
        <td>${escapeHtml(row.leader || "—")}${isUS ? `<small>${percentage(row.leader_change_pct)}</small>` : ""}</td>
      </tr>`).join("");
    } else {
      const message = error || (data ? "数据源没有返回本页板块" : connected ? "正在获取真实板块数据…" : "请先启动本地行情后端");
      table.innerHTML = `<tr><td colspan="4"><div class="sector-empty">${icon("grid")}<h3>${escapeHtml(message)}</h3><p>不会使用模拟排行或零值填充缺失数据。</p></div></td></tr>`;
    }
    const pageCount = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
    document.querySelector("#sector-pagination").hidden = isUS;
    document.querySelector("#sector-page-number").textContent = `${sectorPage} / ${Math.max(pageCount, sectorPage)}`;
    document.querySelector("#sector-previous-page").disabled = sectorPage <= 1;
    document.querySelector("#sector-next-page").disabled = !data || sectorPage >= pageCount;
    document.querySelector("#sector-data-meta").textContent = data
      ? `${error ? "旧数据 · " : ""}采集 ${sourceTime(data.fetched_at)}${data.cached ? " · 后端缓存" : ""} · ${isUS ? `有效样本 ${data.valid_samples} / ${data.total_samples}，分类样本 ${data.classified_samples}` : `本页 ${data.rows.length} 个 / 源总数 ${data.total}`}`
      : error ? `获取失败：${error}` : "正在连接数据源";
  }

  async function sectorLoop(currentGeneration, signal) {
    const key = currentSectorKey();
    const isUS = state.page === "us-sectors";
    const parameters = new URLSearchParams({ market: isUS ? "US" : "CN", kind: sectorKind, page: String(sectorPage) });
    try {
      const data = await api(`/api/sectors?${parameters}`, signal);
      if (generation !== currentGeneration) return;
      sectorCache.set(key, data);
      sectorErrors.delete(key);
    } catch (error) {
      if (generation !== currentGeneration || signal.aborted) return;
      sectorErrors.set(key, error.message);
    }
    if (generation !== currentGeneration || signal.aborted) return;
    renderSectors();
    updateNotice();
    schedule(() => sectorLoop(currentGeneration, signal), isUS ? 600000 : 30000);
  }

  function sync(force = false) {
    if (document.hidden) return;
    if (!connected) { updateNotice(); return; }
    syncWatchlist(force);
    const visible = state.page === "auction" ? visibleStocks() : [];
    const detailStock = detailSecid && document.querySelector("#detail-dialog").open
      ? state.stocks.find(stock => identifier(stock) === detailSecid) : null;
    const stocks = detailStock && state.page === "auction" && !visible.some(stock => stock.id === detailStock.id) ? [...visible, detailStock] : visible;
    const trendStocks = state.view === "list" ? (detailStock ? [detailStock] : []) : stocks;
    const key = state.page === "auction" ? `auction:${state.view}:${stocks.map(identifier).join(",")}:trends:${trendStocks.map(identifier).join(",")}` : currentSectorKey();
    if (key === subscription && !force) return;
    subscription = key;
    quoteRoundFinishedAt = null;
    generation += 1;
    subscriptionController?.abort();
    timers.forEach(timer => clearTimeout(timer));
    timers.clear();
    subscriptionController = new AbortController();
    const signal = subscriptionController.signal;
    const currentGeneration = generation;
    updateNotice();
    if (state.page === "auction") {
      if (stocks.length) quoteLoop(stocks, currentGeneration, signal);
      if (trendStocks.length) trendLoop(trendStocks, currentGeneration, signal);
    } else {
      renderSectors();
      sectorLoop(currentGeneration, signal);
    }
  }

  async function connect() {
    if (document.hidden) return;
    if (location.protocol === "file:") {
      connectionError = "请在项目目录运行 python server.py，再打开本地服务地址。直接双击HTML文件不能连接行情。";
      updateNotice();
      return;
    }
    try {
      const health = await api("/api/health", null, 5000);
      if (health.status !== "ok") throw new Error("本地行情服务健康检查未通过");
      connected = true;
      connectionError = "";
      sync(true);
      repaintCards();
    } catch (error) {
      connected = false;
      connectionError = error.message;
      updateNotice();
      schedule(connect, 5000);
    }
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (["auction", "regular"].includes(button.dataset.chartMode)) {
      chartMode = button.dataset.chartMode;
      document.querySelectorAll("[data-chart-mode]").forEach(item => {
        item.setAttribute("aria-pressed", String(item.dataset.chartMode === chartMode));
      });
      repaintCards();
      if (capitalStock && document.querySelector("#detail-dialog").open) loadDarkAnalysis(capitalStock);
    } else if (button.id === "refresh-data-button") {
      if (connected) sync(true);
      else { timers.forEach(timer => clearTimeout(timer)); timers.clear(); connect(); }
    } else if (button.dataset.sectorKind && ["industry", "concept"].includes(button.dataset.sectorKind)) {
      sectorKind = button.dataset.sectorKind;
      sectorPage = 1;
      sync();
    } else if (button.id === "sector-previous-page" || button.id === "sector-next-page") {
      sectorPage += button.id === "sector-next-page" ? 1 : -1;
      sync();
    } else if (button.dataset.action === "detail") {
      const stock = state.stocks.find(item => item.id === button.dataset.stockId);
      detailSecid = stock ? identifier(stock) : null;
      if (stock) {
        loadCapitalAnalysis(stock);
        sync();
      }
    } else if (button.id === "capital-refresh-button" && capitalStock) {
      loadCapitalAnalysis(capitalStock);
    } else if (button.id === "capital-jump-button") {
      document.querySelector("#capital-analysis").scrollIntoView({ block: "start" });
    }
  });
  document.querySelector("#detail-dialog").addEventListener("close", () => {
    detailSecid = null;
    stopCapitalAnalysis(true);
    sync();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopWatchlist();
      generation += 1;
      subscriptionController?.abort();
      timers.forEach(timer => clearTimeout(timer));
      timers.clear();
      subscription = "";
      stopCapitalAnalysis();
    } else if (connected) sync(true);
    else connect();
    if (!document.hidden && capitalStock && document.querySelector("#detail-dialog").open) loadCapitalAnalysis(capitalStock);
  });
  window.marketData = { cardView, listView, watchlistView, inferStockMarket, resolveStock, sync };
  connect();
})();

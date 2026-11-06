import { escapeHtml, identifier } from "../utils/format.js";

export function createQuoteViews({ quotes, trends, quoteErrors, watchlistSnapshots, watchlistErrors, trendErrors, timeFormatter, calendarFormatter, getChartMode, isConnected }) {
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

  function selectedPoints(data) {
    const records = getChartMode() === "auction" ? data?.auction_points : data?.points;
    return Array.isArray(records)
      ? records.filter(point => Number.isFinite(point.price) && point.price > 0 && Number.isFinite(point.minute))
      : [];
  }

  function chartMarkup(secid) {
    const data = trends.get(secid);
    const error = trendErrors.get(secid);
    const isAuction = getChartMode() === "auction";
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
    const isAuction = getChartMode() === "auction";
    const points = selectedPoints(data);
    const lastPoint = points[points.length - 1];
    const timestamp = isAuction ? data?.auction_source_timestamp : data?.source_timestamp;
    const clock = marketClock();
    const history = Number.isFinite(timestamp) && marketClock(new Date(timestamp * 1000)).date !== clock.date;
    let status = lastPoint ? (isAuction ? "竞价分钟记录" : "普通分时记录") : "正在获取走势";
    if (!isConnected()) status = "后端未连接";
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
      chart: isConnected() ? chartMarkup(secid) : `<div class="chart-placeholder"><span>行情后端尚未连接</span><span>尚未取得行情</span></div>`,
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

  function amount(value) {
    if (!Number.isFinite(value)) return "—";
    if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
    if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)}万`;
    return value.toFixed(2);
  }

  function signedAmount(value) {
    return Number.isFinite(value) ? `${value > 0 ? "+" : ""}${amount(value)}` : "—";
  }

  return { sourceTime, percentage, directionClass, watchlistView, sourceAge, listView, marketClock, selectedPoints, chartMarkup, auctionVolumeMarkup, regularMetricsMarkup, cardView, amount, signedAmount };
}

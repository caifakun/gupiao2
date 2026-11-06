export const LEGACY_KEY = "jingguan.workspace.v1";

function validName(value) {
  return typeof value === "string" && value.trim().length > 0 && value.trim().length <= 20
    && value.trim() !== "全部自选" && !/[\x00-\x1f\x7f]/.test(value);
}

export function previewImport(raw, current, includeSettings = false) {
  if (typeof raw !== "string" || new TextEncoder().encode(raw).length > 262144) throw new Error("导入文件不得超过256KB");
  const saved = JSON.parse(raw);
  if (!saved || ![1, 2].includes(saved.version) || !Array.isArray(saved.stocks)) throw new Error("不是支持的自选备份格式");
  if (saved.stocks.length > 300 || (Array.isArray(saved.groups) && saved.groups.length > 100)) throw new Error("原始数据超过300只股票或100个分组，请先整理再导入");
  const draft = JSON.parse(JSON.stringify(current));
  const mapping = new Map();
  const warnings = [];
  const sourceGroups = Array.isArray(saved.groups) ? saved.groups : [{ id: "focus", name: "重点观察" }, { id: "watch", name: "观察名单" }];
  for (const original of sourceGroups) {
    if (!original || !/^[A-Za-z0-9_-]{1,80}$/.test(original.id) || original.id === "all" || !validName(original.name)) {
      warnings.push("跳过一个无效分组");
      continue;
    }
    if (mapping.has(original.id)) {
      warnings.push("跳过重复的原分组标识");
      continue;
    }
    const name = original.name.trim();
    const existingId = draft.groups.find(group => group.id === original.id);
    const existingName = draft.groups.find(group => group.name.toLocaleLowerCase() === name.toLocaleLowerCase());
    if (["focus", "watch"].includes(original.id)) {
      mapping.set(original.id, original.id);
      if (existingId?.name !== name) warnings.push(`默认分组保留服务端名称：${existingId?.name || original.id}`);
    } else if (existingName) mapping.set(original.id, existingName.id);
    else {
      const id = existingId ? `group-${crypto.randomUUID()}` : original.id;
      draft.groups.push({ id, name });
      mapping.set(original.id, id);
    }
  }
  const seen = new Set(draft.stocks.map(stock => stock.id));
  let duplicates = 0;
  let skipped = 0;
  let added = 0;
  for (const stock of saved.stocks) {
    if (!stock || !["SH", "SZ"].includes(stock.market) || !/^[0-9]{6}$/.test(stock.code)) { skipped += 1; continue; }
    const id = `${stock.market}.${stock.code}`;
    if (seen.has(id)) { duplicates += 1; continue; }
    const group = mapping.get(stock.group) || "focus";
    if (!mapping.has(stock.group)) warnings.push(`${id}的原分组无效，转入重点观察分组`);
    const name = typeof stock.name === "string" ? stock.name.slice(0, 40) : "";
    if (/[\x00-\x1f\x7f]/.test(name)) { skipped += 1; continue; }
    draft.stocks.push({ id, market: stock.market, code: stock.code, name, group });
    seen.add(id);
    added += 1;
  }
  if (draft.groups.length > 100 || draft.stocks.length > 300) throw new Error("合并后超过100个分组或300只股票，未导入任何数据");
  if (includeSettings) {
    const settings = saved.version === 2 ? saved.settings : saved;
    const supported = [2, 4, 6].includes(settings?.layout);
    draft.settings = { view: settings?.view === "grid" && supported ? "grid" : "list", layout: supported ? settings.layout : 6 };
  }
  return { draft, added, duplicates, skipped, warnings, newGroups: draft.groups.length - current.groups.length };
}

export function downloadWorkspace(workspace) {
  const content = JSON.stringify({ version: 2, exported_at: new Date().toISOString(), groups: workspace.groups, stocks: workspace.stocks, settings: workspace.settings }, null, 2);
  const url = URL.createObjectURL(new Blob([content], { type: "application/json;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `jingguan-watchlist-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

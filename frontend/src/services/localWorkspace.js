import { ApiError } from "./api.js";
import { LEGACY_KEY, previewImport } from "./importWorkspace.js";

const LOCAL_KEY = "jingguan.local.workspace.v2";

function emptyWorkspace() {
  return { revision: 0, groups: [{ id: "focus", name: "重点观察" }, { id: "watch", name: "观察名单" }], stocks: [], settings: { view: "list", layout: 6 } };
}

function validate(workspace) {
  const invalid = () => { throw new ApiError("本机自选数据无效，请导入有效备份后重试", 422); };
  if (!workspace || !Number.isSafeInteger(workspace.revision) || workspace.revision < 0 || !Array.isArray(workspace.groups) || workspace.groups.length < 2 || workspace.groups.length > 100 || !Array.isArray(workspace.stocks) || workspace.stocks.length > 300) invalid();
  const ids = new Set();
  const names = new Set();
  for (const group of workspace.groups) {
    if (!group || typeof group.id !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(group.id) || group.id === "all" || typeof group.name !== "string") invalid();
    const name = group.name.trim();
    if (!name || name.length > 20 || name === "全部自选" || /[\x00-\x1f\x7f]/.test(name) || ids.has(group.id) || names.has(name.toLocaleLowerCase())) invalid();
    group.name = name;
    ids.add(group.id);
    names.add(name.toLocaleLowerCase());
  }
  if (!ids.has("focus") || !ids.has("watch")) invalid();
  const stocks = new Set();
  for (const stock of workspace.stocks) {
    if (!stock || !["SH", "SZ"].includes(stock.market) || typeof stock.code !== "string" || !/^[0-9]{6}$/.test(stock.code) || stock.id !== `${stock.market}.${stock.code}` || stocks.has(stock.id) || !ids.has(stock.group) || typeof stock.name !== "string" || stock.name.length > 40 || /[\x00-\x1f\x7f]/.test(stock.name)) invalid();
    stocks.add(stock.id);
  }
  if (!["list", "grid"].includes(workspace.settings?.view) || ![2, 4, 6].includes(workspace.settings?.layout)) invalid();
  return workspace;
}

export function loadLocalWorkspace() {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    if (raw !== null) return validate(JSON.parse(raw));
    const legacy = localStorage.getItem(LEGACY_KEY);
    return legacy ? validate(previewImport(legacy, emptyWorkspace(), true).draft) : emptyWorkspace();
  } catch (failure) {
    if (failure instanceof ApiError) throw failure;
    throw new ApiError("无法读取浏览器自选，请检查浏览器存储权限或备份文件；原数据未覆盖", 422);
  }
}

export function saveLocalWorkspace(draft, expectedRevision) {
  const current = loadLocalWorkspace();
  if (current.revision !== expectedRevision) throw new ApiError("其他标签页已修改自选，请重新加载后再操作", 409);
  const saved = validate({ ...draft, revision: expectedRevision + 1 });
  try { localStorage.setItem(LOCAL_KEY, JSON.stringify(saved)); }
  catch { throw new ApiError("浏览器未能保存自选，请检查存储权限或空间；本次修改未保存", 503); }
  return saved;
}

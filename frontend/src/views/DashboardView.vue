<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useWorkspace } from "../stores/workspace.js";
import { useWatchlistFilters } from "../composables/useWatchlistFilters.js";
import { createMarketData } from "../composables/useMarketData.js";
import { downloadWorkspace } from "../services/importWorkspace.js";
import StockCard from "../components/StockCard.vue";
import WatchlistTable from "../components/WatchlistTable.vue";
import WatchlistFilters from "../components/WatchlistFilters.vue";
import GroupManager from "../components/GroupManager.vue";
import StockDialog from "../components/StockDialog.vue";
import SectorBoard from "../components/SectorBoard.vue";
import CapitalAnalysis from "../components/CapitalAnalysis.vue";
import ImportWorkspaceDialog from "../components/ImportWorkspaceDialog.vue";

const props = defineProps({ user: Object, authBusy: Boolean, authError: String });
defineEmits(["logout"]);
const store = useWorkspace();
const { workspace, loading, saving, blocked, error } = store;
const state = reactive({ page: "auction", view: "list", layout: 6, chartMode: "auction", group: "all", query: "", pageIndex: 0, stocks: [], groups: [], changeFilter: "all", changeMin: null, changeMax: null, industry: "all" });
const market = shallowRef(null);
const epoch = ref(0);
const filters = useWatchlistFilters(state, market, epoch);
const { industryTabs, filtered, visible, pageSize, pageCount } = filters;
const readOnly = computed(() => !workspace.value || saving.value || loading.value || blocked.value);
const groupsOpen = ref(false);
const stockOpen = ref(false);
const importOpen = ref(false);
const infoOpen = ref(false);
const detailOpen = ref(false);
const detailId = ref(null);
const moveOpen = ref(false);
const movingStock = ref(null);
const targetGroup = ref("focus");
const clock = ref("");
let clockTimer;
let disposed = false;

const pages = [{ id: "auction", name: "竞价监控", icon: "chart", market: "CN" }, { id: "a-sectors", name: "A股板块", icon: "grid", market: "CN" }, { id: "us-sectors", name: "美股板块", icon: "globe", market: "US" }];
const pageTitle = computed(() => pages.find(page => page.id === state.page)?.name || "行情工作台");
const detailStock = computed(() => state.stocks.find(stock => stock.id === detailId.value));
const rows = computed(() => {
  epoch.value;
  return visible.value.map(stock => ({ id: stock.id, stock, ...(market.value?.listView(stock) || { name: stock.name || stock.code, price: "—", change: "—", color: "", industry: "待分类", status: "等待行情连接", title: "尚未取得数据" }), groupName: state.groups.find(group => group.id === stock.group)?.name || "未分类" }));
});
const detailView = computed(() => { epoch.value; return detailStock.value ? market.value?.cardView(detailStock.value) : null; });

watch(workspace, value => {
  if (!value) return;
  state.stocks = value.stocks;
  state.groups = value.groups;
  state.view = value.settings.view;
  state.layout = value.settings.layout;
  if (state.group !== "all" && !state.groups.some(group => group.id === state.group)) state.group = "all";
  if (detailId.value && !state.stocks.some(stock => stock.id === detailId.value)) detailOpen.value = false;
});
watch(() => [state.page, state.view, state.pageIndex, state.group, state.query, state.changeFilter, state.changeMin, state.changeMax, state.industry, state.stocks.map(stock => stock.id).join(","), visible.value.map(stock => stock.id).join(",")].join("|"), () => market.value?.sync(), { flush: "post" });

async function reload() {
  if (await store.load() && !market.value && !disposed) {
    await nextTick();
    if (disposed) return;
    market.value = createMarketData({ state, filteredStocks: () => filtered.value, stockPageSize: () => pageSize.value, repaint: () => { epoch.value += 1; }, isDetailOpen: () => detailOpen.value });
    market.value.connect();
  }
}
function resetPage() { state.pageIndex = 0; }
function setGroup(id) { state.group = id; resetPage(); }
function applyFilters(value) { Object.assign(state, value); resetPage(); }
async function changeView(view, layout = state.layout) {
  if (await store.commit(draft => { draft.settings = { view, layout }; })) resetPage();
}
async function createGroup(name) {
  const id = `group-${crypto.randomUUID()}`;
  if (await store.commit(draft => draft.groups.push({ id, name }))) { setGroup(id); ElMessage.success(props.user.local ? "分组已保存到当前浏览器" : "分组已保存到服务器"); return id; }
  return null;
}
async function renameGroup(id, name) {
  return store.commit(draft => { const group = draft.groups.find(item => item.id === id); if (group) group.name = name; });
}
async function saveStock(verified, group) {
  if (state.stocks.some(stock => stock.id === `${verified.market}.${verified.code}`)) { ElMessage.warning("该股票已在自选中"); return false; }
  const saved = await store.commit(draft => draft.stocks.push({ id: `${verified.market}.${verified.code}`, market: verified.market, code: verified.code, name: verified.name, group }));
  if (saved) { state.query = ""; filters.clear(); setGroup(group); ElMessage.success("已保存自选；完整竞价量仍未核验"); }
  return saved;
}
async function removeStock(stock) {
  if (readOnly.value) return;
  try { await ElMessageBox.confirm(`从${props.user.local ? '当前浏览器' : '服务器'}自选中移除 ${stock.name || stock.code}？`, "移除自选", { confirmButtonText: "确认移除", cancelButtonText: "取消", type: "warning" }); }
  catch { return; }
  await store.commit(draft => { draft.stocks = draft.stocks.filter(item => item.id !== stock.id); });
}
function openMove(stock) { movingStock.value = stock; targetGroup.value = stock.group; moveOpen.value = true; }
async function saveMove() {
  if (!movingStock.value || !state.stocks.some(stock => stock.id === movingStock.value.id)) return;
  if (await store.commit(draft => { const stock = draft.stocks.find(item => item.id === movingStock.value.id); if (stock) stock.group = targetGroup.value; })) moveOpen.value = false;
}
async function reorderStock(sourceId, target) {
  if (readOnly.value) return;
  const sourceIndex = state.stocks.findIndex(stock => stock.id === sourceId);
  const targetIndex = typeof target === "number" ? sourceIndex + target : state.stocks.findIndex(stock => stock.id === target);
  if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= state.stocks.length || sourceIndex === targetIndex) return;
  await store.commit(draft => { const [stock] = draft.stocks.splice(sourceIndex, 1); draft.stocks.splice(targetIndex, 0, stock); });
}
function openDetail(stock) { detailId.value = stock.id; detailOpen.value = true; }
function startDetail() { if (detailStock.value && detailOpen.value) market.value?.openDetail(detailStock.value); }
function closeDetail() { market.value?.closeDetail(); detailId.value = null; }
async function importWorkspace(draft) {
  const saved = await store.commit(target => { target.groups = draft.groups; target.stocks = draft.stocks; target.settings = draft.settings; });
  if (saved) ElMessage.success("旧自选已合并并保存到服务器");
  return saved;
}
async function fullscreen() {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
  catch { ElMessage.warning("浏览器不允许切换全屏"); }
}
function refreshClock() { clock.value = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", dateStyle: "medium", timeStyle: "medium", hourCycle: "h23" }).format(new Date()); }
onMounted(() => { refreshClock(); clockTimer = setInterval(refreshClock, 1000); reload(); });
onBeforeUnmount(() => { disposed = true; clearInterval(clockTimer); market.value?.dispose(); });
</script>

<template>
  <div class="app">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand"><span class="brand-mark"><svg class="icon"><use href="#icon-chart"/></svg></span><div class="brand-text"><span class="brand-name">竞观</span><span class="brand-caption">MARKET WORKSPACE</span></div></div>
      <p class="nav-label">市场工作台</p>
      <nav class="nav"><button v-for="page in pages" :key="page.id" class="nav-button" type="button" :aria-current="state.page === page.id ? 'page' : undefined" :title="page.name" @click="state.page = page.id"><svg class="icon"><use :href="`#icon-${page.icon}`"/></svg><span class="nav-text">{{ page.name }}</span><span class="nav-meta">{{ page.market }}</span></button></nav>
      <div class="sidebar-bottom"><p class="field-help">只读行情 · 不提供交易下单</p><div class="user-controls"><small>{{ props.user.username }}</small><el-button v-if="!props.user.local" text :loading="authBusy" :disabled="saving" @click="$emit('logout')">退出登录</el-button></div></div>
    </aside>
    <main class="main">
      <header class="topbar"><div><span class="eyebrow">PRIVATE MARKET WORKSPACE</span><h1>{{ pageTitle }}</h1></div><div class="topbar-actions"><span class="clock">{{ clock }}</span><button class="icon-button" type="button" aria-label="全屏" @click="fullscreen"><svg class="icon"><use href="#icon-expand"/></svg></button><el-button @click="infoOpen = true">数据说明</el-button><el-button @click="market?.refresh()">刷新行情</el-button></div></header>
      <div class="source-notice"><svg class="icon"><use href="#icon-info"/></svg><span id="source-notice-text">正在连接真实行情，不保证源更新频率。</span><span id="data-badge" class="state-badge">等待连接</span></div>
      <el-alert v-if="props.user.local" title="本机免登录模式：不连接数据库，自选仅保存在当前浏览器。更换地址或浏览器前请导出备份；行情仍从真实接口获取，不使用模拟数据。" type="info" :closable="false" show-icon/>
      <el-alert v-if="error || authError" :title="error || authError" type="error" :closable="false" show-icon/>
      <div class="workspace-actions"><el-button :loading="loading" :disabled="saving" @click="reload">重新加载自选</el-button><el-button :disabled="readOnly" @click="importOpen = true">导入旧自选</el-button><el-button :disabled="!workspace || saving" @click="downloadWorkspace(workspace)">导出自选备份</el-button><span class="workspace-status">{{ saving ? '正在保存，尚未确认成功…' : blocked ? '配置未同步，重新加载成功前暂停修改' : workspace ? `${props.user.local ? '浏览器本机存储' : '服务端存储'} · 版本 ${workspace.revision}` : '等待加载工作台' }}</span></div>
      <section v-show="state.page === 'auction'" id="auction-page">
        <div class="monitor-toolbar"><div class="watchlist-group-toolbar"><div class="groups" role="group" aria-label="自选分组"><button class="group-button" type="button" :aria-pressed="state.group === 'all'" @click="setGroup('all')">全部自选 <span class="group-count">{{ state.stocks.length }}</span></button><button v-for="group in state.groups" :key="group.id" class="group-button" type="button" :aria-pressed="state.group === group.id" @click="setGroup(group.id)">{{ group.name }} <span class="group-count">{{ state.stocks.filter(stock => stock.group === group.id).length }}</span></button></div><el-button text :disabled="readOnly" @click="groupsOpen = true">＋新建／管理分组</el-button></div><el-input v-model="state.query" class="stock-search-input" placeholder="搜索名称或代码" clearable aria-label="搜索自选" @input="resetPage"/></div>
        <div class="workspace-actions"><div class="layout-switch" role="group" aria-label="展示样式"><button type="button" :disabled="readOnly" :aria-pressed="state.view === 'list'" @click="changeView('list')">列表</button><button v-for="layout in [2, 4, 6]" :key="layout" type="button" :disabled="readOnly" :aria-pressed="state.view === 'grid' && state.layout === layout" @click="changeView('grid', layout)">{{ layout }}宫格</button></div><div class="layout-switch" role="group" aria-label="走势类型"><button type="button" :aria-pressed="!market || epoch >= 0 && state.chartMode !== 'regular'" @click="state.chartMode = 'auction'; market?.setChartMode('auction')">竞价走势</button><button type="button" :aria-pressed="state.chartMode === 'regular'" @click="state.chartMode = 'regular'; market?.setChartMode('regular')">普通分时</button></div><el-button type="primary" :disabled="readOnly || !market" @click="stockOpen = true">＋添加自选股票</el-button></div>
        <WatchlistFilters :mode="state.changeFilter" :minimum="state.changeMin" :maximum="state.changeMax" @apply="applyFilters" @clear="filters.clear"/>
        <div class="industry-tabs" role="group" aria-label="按行业筛选"><button v-for="tab in industryTabs" :key="tab.id" class="group-button" type="button" :aria-pressed="state.industry === tab.id" @click="state.industry = tab.id; resetPage()">{{ tab.name }} <span class="group-count">{{ tab.count }}</span></button></div>
        <p id="watchlist-freshness" class="watchlist-freshness" role="status">等待全自选行情；缺失数据不作为平盘。</p>
        <WatchlistTable v-if="state.view === 'list'" :rows="rows" :disabled="readOnly" @detail="openDetail" @move="openMove" @remove="removeStock" @reorder="reorderStock"/>
        <div v-else id="auction-grid" class="auction-grid" :style="{ '--columns': state.layout <= 4 ? 2 : 3, '--rows': state.layout === 2 ? 1 : 2 }"><div v-if="state.stocks.length && !filtered.length" class="empty-search"><strong>当前条件下没有匹配股票</strong><el-button @click="filters.clear(); state.query = ''">清除筛选和搜索</el-button></div><StockCard v-for="slot in state.stocks.length && !filtered.length ? 0 : state.layout" :key="visible[slot - 1]?.id || `empty-${slot}`" :slot-index="slot - 1" :stock="visible[slot - 1]" :view="visible[slot - 1] && market ? (epoch >= 0 && market.cardView(visible[slot - 1])) : null" :disabled="readOnly" @add="stockOpen = true" @detail="openDetail" @remove="removeStock" @reorder="reorderStock"/></div>
        <footer class="grid-footer"><span>自选 {{ state.stocks.length }} 只 · 匹配 {{ filtered.length }} 只 · {{ state.view === 'list' ? '每页20只／最新报价' : '匹配量未提供' }}</span><div class="pagination"><button class="icon-button" type="button" :disabled="state.pageIndex === 0" aria-label="上一页" @click="state.pageIndex -= 1">‹</button><span>{{ state.pageIndex + 1 }} / {{ pageCount }}</span><button class="icon-button" type="button" :disabled="state.pageIndex >= pageCount - 1" aria-label="下一页" @click="state.pageIndex += 1">›</button></div></footer>
      </section>
      <SectorBoard v-show="state.page !== 'auction'" @kind="kind => market?.changeSector(kind)" @step="step => market?.changeSector(null, step)"/>
    </main>
    <StockDialog v-model="stockOpen" :groups="state.groups" :stocks="state.stocks" :selected-group="state.group" :busy="saving || loading || blocked" :error="error" :lookup="(code, signal) => market.resolveStock(code, signal)" :save-stock="saveStock"/>
    <GroupManager v-model="groupsOpen" :groups="state.groups" :busy="saving || loading || blocked" :error="error" :create-group="createGroup" :rename-group="renameGroup"/>
    <ImportWorkspaceDialog v-if="workspace" v-model="importOpen" :workspace="workspace" :busy="saving || loading || blocked" :error="error" :save-import="importWorkspace"/>
    <el-dialog v-model="moveOpen" title="调整股票分组" width="min(480px, 94vw)" :close-on-click-modal="!saving"><p class="dialog-description">{{ movingStock?.name || movingStock?.code }}，排序位置保持不变。</p><el-select v-model="targetGroup" :disabled="readOnly"><el-option v-for="group in state.groups" :key="group.id" :value="group.id" :label="group.name"/></el-select><p v-if="error" class="form-error">{{ error }}</p><template #footer><el-button :disabled="saving" @click="moveOpen = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="readOnly" @click="saveMove">保存分组</el-button></template></el-dialog>
    <el-dialog v-model="detailOpen" :title="`${detailView?.name || detailStock?.code || '个股'} · ${detailView?.detailTitle || '行情详情'}`" width="min(1100px, 96vw)" class="detail-dialog" @opened="startDetail" @close="closeDetail"><StockCard v-if="detailStock" :stock="detailStock" :view="detailView" detail/><CapitalAnalysis @refresh="market?.refreshCapital()"/></el-dialog>
    <el-dialog v-model="infoOpen" title="数据来源与使用边界" width="min(700px, 94vw)"><ul class="info-list"><li>只读行情，不提供买卖下单。</li><li>A股来自东方财富公开网页接口，美股为Nasdaq行业样本统计；不是交易所直连或授权实时行情。</li><li>竞价图仅使用源竞价时段分钟价格；完整虚拟匹配量、未匹配量及方向尚未核验，不画示意量柱。</li><li>普通分时显示最新报价指标、红绿量柱和源量比；不是历史分钟选点指标。</li><li>源时间、采集时间、本机时间分开；失败保留旧值并标记，不把缺失值当零。</li><li>资金分类、明暗盘及席位标签沿用原口径，不代表已确认的实际交易者身份。</li><li>{{ props.user.local ? '自选与分组仅保存在当前地址的浏览器中，不连接数据库，请定期导出备份。' : '自选与分组保存在服务端；导入需明确确认，旧浏览器配置不会自动清除。' }}</li></ul></el-dialog>
  </div>
</template>

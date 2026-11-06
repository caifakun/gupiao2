<script setup>
const props = defineProps({ stock: Object, view: Object, slotIndex: { type: Number, default: 0 }, detail: Boolean, disabled: Boolean });
const emit = defineEmits(["add", "detail", "remove", "reorder"]);
function drag(event) {
  if (props.disabled || !props.stock) { event.preventDefault(); return; }
  event.dataTransfer.setData("text/plain", props.stock.id);
  event.dataTransfer.effectAllowed = "move";
}
function drop(event) {
  if (!props.disabled && props.stock) emit("reorder", event.dataTransfer.getData("text/plain"), props.stock.id);
}
</script>

<template>
  <article class="stock-card" :data-stock-id="stock?.id" :aria-label="`${view?.name || stock?.code || '空自选位置'}行情卡片`" @dragover.prevent @drop.prevent="drop">
    <header class="card-heading">
      <div class="stock-identity"><span class="stock-name">{{ view?.name || stock?.name || stock?.code || `自选位置 ${slotIndex + 1}` }}</span><span v-if="stock" class="stock-code">{{ stock.market }} {{ stock.code }}</span></div>
      <div v-if="stock && !detail" class="card-actions">
        <button class="icon-button" type="button" draggable="true" :disabled="disabled" aria-label="拖动排序，或按Alt加左右方向键" @dragstart="drag" @keydown.alt.left.prevent="$emit('reorder', stock.id, -1)" @keydown.alt.right.prevent="$emit('reorder', stock.id, 1)"><svg class="icon"><use href="#icon-grip"/></svg></button>
        <button class="icon-button" type="button" aria-label="打开详情" @click="$emit('detail', stock)"><svg class="icon"><use href="#icon-expand"/></svg></button>
        <button class="icon-button" type="button" :disabled="disabled" aria-label="移除股票" @click="$emit('remove', stock)"><svg class="icon"><use href="#icon-close"/></svg></button>
      </div>
      <span v-else class="slot-label">{{ detail ? view?.detailLabel : `SLOT ${slotIndex + 1}` }}</span>
    </header>
    <div class="price-row"><div class="price" :class="view?.changeClass">{{ view?.value || '—' }}<span class="price-caption">{{ view?.caption || '行情待配置' }}</span></div><span class="change" :class="view?.changeClass">{{ view?.change || '—' }} <span class="price-caption">涨跌幅</span></span></div>
    <div v-if="view" v-html="view.context"></div>
    <div class="card-chart-stack">
      <div class="chart" :aria-label="view?.chartLabel || '尚未配置股票'">
        <div v-if="view" v-html="view.chart"></div>
        <div v-else class="chart-placeholder"><button type="button" @click="$emit('add')">＋ 添加自选股票</button><span>不展示模拟行情</span></div>
      </div>
      <div v-if="view?.volumeZones" v-html="view.volumeZones"></div>
      <div class="chart-axis" aria-hidden="true"><span v-for="label in view?.axis || ['—', '待接入行情', '—']" :key="label">{{ label }}</span></div>
    </div>
    <dl class="card-metrics" :title="view?.metricsTitle">
      <template v-if="view?.regularMetrics"><div class="regular-metrics-host" v-html="view.regularMetrics"></div></template>
      <template v-else><div><dt>虚拟匹配量</dt><dd>{{ stock ? '未提供' : '—' }}</dd></div><div><dt>未匹配量</dt><dd>{{ stock ? '未提供' : '—' }}</dd></div></template>
      <div class="volume-ratio-metric" :title="view?.volumeRatioTitle"><dt>报价量比</dt><dd :class="view?.volumeRatioClass">{{ view?.volumeRatio || (stock ? '未提供' : '—') }}</dd></div>
    </dl>
    <footer class="card-footer" :title="view?.title"><span>走势源时间 {{ view?.sourceTime || '—' }}</span><span class="state-badge">{{ view?.status || '未配置' }}</span></footer>
  </article>
</template>

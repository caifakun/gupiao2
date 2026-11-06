<script setup>
defineEmits(["refresh"]);
</script>
<template>
<section id="capital-analysis" class="capital-analysis" aria-labelledby="capital-title"><div class="capital-heading"><h3 id="capital-title">资金分析</h3><button id="capital-refresh-button" @click="$emit('refresh')" class="button" type="button">刷新资金</button></div><p class="capital-note">按成交单规模统计，不代表真实交易者身份；主力是超大单与大单的汇总。龙虎榜只展示已披露席位，不能代表全市场资金或全部机构交易。</p>
    <section id="capital-dark-section" class="capital-section" aria-labelledby="capital-dark-title" hidden>
      <h4 id="capital-dark-title">当日明盘／暗盘资金</h4>
      <div id="capital-dark-meta" class="capital-status" aria-live="polite">打开普通分时详情后加载</div>
      <div id="capital-dark"></div>
      <p class="capital-note">东方财富模型测算指标，非逐笔实时；不是交易所暗盘成交记录，不代表流入、流出总额，不作交易者身份判断。主力净流入（含暗盘）保留榜单源值，不与明盘、暗盘或下方其他口径再次相加。源时间为榜单记录时间；分页不是同一时刻快照，未匹配、失败或覆盖不完整均不代表零。</p>
    </section>
    <section class="capital-section" aria-labelledby="capital-current-title"><h4 id="capital-current-title">最近交易资金流向</h4><div id="capital-current-meta" class="capital-status" aria-live="polite">打开详情后加载</div><div id="capital-current"></div></section><section class="capital-section" aria-labelledby="capital-history-title"><h4 id="capital-history-title">历史主力资金 · 不含当日</h4><div id="capital-history-meta" class="capital-status" aria-live="polite">打开详情后加载</div><div id="capital-history"></div></section><section class="capital-section" aria-labelledby="capital-seats-title"><h4 id="capital-seats-title">龙虎榜与席位标签</h4><div id="capital-seats-meta" class="capital-status" aria-live="polite">打开详情后加载</div><p class="capital-note">仅查看近90个自然日内最新上榜交易日；同一披露的重复席位合并买卖榜标记，不跨上榜原因累计。游资关联标签仅作公开资料参考，不确认本次实际交易人。</p><div id="capital-seats"></div></section></section>
</template>

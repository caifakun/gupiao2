<script setup>
defineProps({ rows: { type: Array, default: () => [] }, disabled: Boolean });
defineEmits(["detail", "move", "remove", "reorder"]);
</script>

<template>
  <div id="stock-list-panel" class="stock-list-panel">
    <el-table :data="rows" row-key="id" class="watchlist-table" aria-label="自选股票最新报价，点击股票名称查看详情" :empty-text="'暂无匹配股票，可添加自选或调整筛选'">
      <el-table-column label="股票名称／代码" min-width="180" fixed="left"><template #default="{ row }"><button class="stock-list-name" type="button" @click="$emit('detail', row.stock)">{{ row.name }}</button><small class="table-code">{{ row.stock.market }} {{ row.stock.code }}</small></template></el-table-column>
      <el-table-column label="最新价" min-width="105"><template #default="{ row }"><strong :class="row.color">{{ row.price }}</strong></template></el-table-column>
      <el-table-column label="涨跌幅" min-width="105"><template #default="{ row }"><span :class="row.color">{{ row.change }}</span></template></el-table-column>
      <el-table-column prop="industry" label="所属行业" min-width="130"/>
      <el-table-column label="自选分组" min-width="140"><template #default="{ row }"><button class="text-button stock-list-group" type="button" :disabled="disabled" @click="$emit('move', row.stock)">{{ row.groupName }}</button></template></el-table-column>
      <el-table-column label="行情状态" min-width="275"><template #default="{ row }"><span class="stock-list-status" :title="row.title">{{ row.status }}</span></template></el-table-column>
      <el-table-column label="操作" min-width="120"><template #default="{ row }"><button class="icon-button" type="button" :disabled="disabled" aria-label="上移" @click="$emit('reorder', row.id, -1)">↑</button><button class="icon-button" type="button" :disabled="disabled" aria-label="下移" @click="$emit('reorder', row.id, 1)">↓</button><button class="icon-button" type="button" :disabled="disabled" aria-label="移除自选" @click="$emit('remove', row.stock)">×</button></template></el-table-column>
    </el-table>
  </div>
</template>

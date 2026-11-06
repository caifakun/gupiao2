<script setup>
import { ref, watch } from "vue";
const props = defineProps({ mode: String, minimum: Number, maximum: Number });
const emit = defineEmits(["apply", "clear"]);
const draftMode = ref(props.mode || "all");
const minimumText = ref(props.minimum === null ? "" : String(props.minimum));
const maximumText = ref(props.maximum === null ? "" : String(props.maximum));
const error = ref("");
watch(() => [props.mode, props.minimum, props.maximum], () => {
  draftMode.value = props.mode;
  minimumText.value = props.minimum === null ? "" : String(props.minimum);
  maximumText.value = props.maximum === null ? "" : String(props.maximum);
  error.value = "";
});
function apply() {
  const parse = text => text.trim() === "" ? null : /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text.trim()) ? Number(text.trim()) : NaN;
  const minimum = draftMode.value === "range" ? parse(minimumText.value) : null;
  const maximum = draftMode.value === "range" ? parse(maximumText.value) : null;
  if ((minimum !== null && !Number.isFinite(minimum)) || (maximum !== null && !Number.isFinite(maximum)) || (minimum !== null && maximum !== null && minimum > maximum)) {
    error.value = "请输入有效数字，最低涨跌幅不能高于最高涨跌幅；原筛选保持不变。";
    return;
  }
  error.value = "";
  emit("apply", { changeFilter: draftMode.value, changeMin: minimum, changeMax: maximum });
}
</script>
<template>
  <form class="watchlist-filters" @submit.prevent="apply">
    <label for="change-filter">涨跌幅</label>
    <el-select id="change-filter" v-model="draftMode" class="change-select" aria-label="涨跌幅筛选" @change="draftMode !== 'range' && apply()"><el-option label="全部" value="all"/><el-option label="上涨" value="up"/><el-option label="下跌" value="down"/><el-option label="平盘" value="flat"/><el-option label="自定义区间" value="range"/></el-select>
    <span v-if="draftMode === 'range'" class="change-range"><label for="change-min">最低</label><el-input id="change-min" v-model="minimumText" placeholder="不限" inputmode="decimal"/><span>%</span><label for="change-max">最高</label><el-input id="change-max" v-model="maximumText" placeholder="不限" inputmode="decimal"/><span>%</span></span>
    <el-button native-type="submit">应用</el-button><el-button text @click="$emit('clear')">清除筛选</el-button>
    <p v-if="error" class="watchlist-filter-error" role="alert">{{ error }}</p>
  </form>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { inferStockMarket } from "../utils/format.js";
const props = defineProps({ modelValue: Boolean, groups: Array, stocks: Array, selectedGroup: String, busy: Boolean, error: String, lookup: Function, saveStock: Function });
const emit = defineEmits(["update:modelValue"]);
const code = ref("");
const group = ref("focus");
const verified = ref(null);
const status = ref("输入6位沪深A股代码后向接口核验证券名称。");
const lookupError = ref(false);
const localError = ref("");
let timer;
let controller;
let generation = 0;
const market = computed(() => inferStockMarket(code.value.trim()));
function stop() {
  clearTimeout(timer);
  controller?.abort();
  generation += 1;
  verified.value = null;
}
function queue(immediate = false) {
  stop();
  lookupError.value = false;
  localError.value = "";
  const current = code.value.trim();
  if (!props.modelValue || !/^[0-9]{6}$/.test(current)) { status.value = "请输入完整的6位代码，保留前导零。"; return; }
  if (!market.value) { status.value = "目前仅支持60／68开头沪市A股及00／30开头深市A股，不推测其他市场。"; return; }
  status.value = "正在向行情接口核验名称…";
  const requestGeneration = generation;
  controller = new AbortController();
  const signal = controller.signal;
  timer = setTimeout(async () => {
    try {
      const result = await props.lookup(current, signal);
      if (signal.aborted || requestGeneration !== generation || !props.modelValue || code.value.trim() !== current) return;
      verified.value = result;
      status.value = "证券名称已通过接口核验，可以保存；不表示行情保证实时。";
    } catch (failure) {
      if (signal.aborted || requestGeneration !== generation || !props.modelValue) return;
      status.value = failure.message;
      lookupError.value = true;
    }
  }, immediate ? 0 : 250);
}
watch(code, () => queue());
watch(() => props.modelValue, open => {
  stop();
  if (open) {
    code.value = "";
    group.value = props.groups.some(item => item.id === props.selectedGroup) ? props.selectedGroup : "focus";
    localError.value = "";
    lookupError.value = false;
    status.value = "输入6位沪深A股代码后向接口核验证券名称。";
  }
});
onBeforeUnmount(stop);
async function save() {
  localError.value = "";
  if (!verified.value || verified.value.code !== code.value.trim() || verified.value.market !== market.value) return;
  if (props.stocks.some(stock => stock.id === `${verified.value.market}.${verified.value.code}`)) { localError.value = "该股票已在自选中。"; return; }
  if (props.stocks.length >= 300) { localError.value = "最多支持300只自选。"; return; }
  if (!props.groups.some(item => item.id === group.value)) { localError.value = "请选择有效分组。"; return; }
  if (await props.saveStock({ ...verified.value }, group.value)) emit("update:modelValue", false);
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="添加自选股票" width="min(560px, 94vw)" class="stock-dialog-large" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @update:model-value="$emit('update:modelValue', $event)">
    <p class="dialog-description">自动识别交易所并核验证券名称；只查看行情，不发起交易。</p>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="股票代码"><el-input id="stock-code" v-model="code" maxlength="6" inputmode="numeric" placeholder="例如：600519、300750" autocomplete="off" :disabled="busy"/></el-form-item>
      <el-form-item label="交易所（自动识别）"><el-input :model-value="market === 'SH' ? '上海证券交易所' : market === 'SZ' ? '深圳证券交易所' : '等待输入支持的完整代码'" readonly/></el-form-item>
      <el-form-item label="证券名称（接口核验）"><el-input :model-value="verified?.name || ''" readonly placeholder="核验成功后自动填入"/></el-form-item>
      <p class="field-help" role="status" aria-live="polite">{{ status }} <el-button v-if="lookupError" text :disabled="busy" @click="queue(true)">重新核验</el-button></p>
      <el-form-item label="自选分组"><el-select v-model="group" :disabled="busy"><el-option v-for="item in groups" :key="item.id" :value="item.id" :label="item.name"/></el-select></el-form-item>
      <p v-if="localError || error" class="form-error" role="alert">{{ localError || error }}</p>
      <div class="form-actions"><el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button><el-button id="save-stock-button" type="primary" native-type="submit" :loading="busy" :disabled="!verified || busy">保存到自选</el-button></div>
    </el-form>
  </el-dialog>
</template>

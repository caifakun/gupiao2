<script setup>
import { computed, ref, watch } from "vue";
import { LEGACY_KEY, previewImport } from "../services/importWorkspace.js";
const props = defineProps({ modelValue: Boolean, workspace: Object, busy: Boolean, error: String, saveImport: Function });
const emit = defineEmits(["update:modelValue"]);
const raw = ref("");
const includeSettings = ref(false);
const preview = ref(null);
const localError = ref("");
const sourceLabel = ref("");
const hasLocal = computed(() => { try { return Boolean(localStorage.getItem(LEGACY_KEY)); } catch { return false; } });
function prepare() {
  preview.value = null;
  localError.value = "";
  if (!raw.value) return;
  try { preview.value = previewImport(raw.value, props.workspace, includeSettings.value); }
  catch (failure) { localError.value = failure.message; }
}
watch([raw, includeSettings], prepare);
watch(() => props.workspace, prepare);
watch(() => props.modelValue, open => { if (open) { raw.value = ""; preview.value = null; localError.value = ""; sourceLabel.value = ""; includeSettings.value = false; } });
function useLocal() {
  try { raw.value = localStorage.getItem(LEGACY_KEY) || ""; sourceLabel.value = "当前浏览器旧版配置"; }
  catch { localError.value = "浏览器不允许读取旧配置，请使用导出文件。"; }
}
async function chooseFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  if (file.size > 262144) { raw.value = ""; localError.value = "文件超过256KB，未导入。"; return; }
  try { raw.value = await file.text(); sourceLabel.value = file.name; }
  catch { localError.value = "无法读取文件。"; }
}
async function save() {
  if (!preview.value || props.busy) return;
  if (await props.saveImport(preview.value.draft)) emit("update:modelValue", false);
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="导入旧自选／备份" width="min(660px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @update:model-value="$emit('update:modelValue', $event)">
    <p class="dialog-description">仅合并新增股票，重复证券保留服务端记录；默认分组保留服务端名称。确认前不会写入数据库，也不会清除原浏览器配置。</p>
    <div class="import-actions"><el-button :disabled="busy || !hasLocal" @click="useLocal">读取此浏览器旧配置</el-button><label class="import-file-label">选择JSON备份<input type="file" accept="application/json,.json" :disabled="busy" @change="chooseFile"/></label></div>
    <p class="field-help">不同访问域名或端口无法直接读取旧配置，请先在旧地址导出JSON文件。</p>
    <el-checkbox v-model="includeSettings" :disabled="busy">同时导入原来的列表／宫格设置</el-checkbox>
    <div v-if="preview" class="import-preview"><h3>{{ sourceLabel }}</h3><p>新增 {{ preview.added }} 只股票、{{ preview.newGroups }} 个分组；重复 {{ preview.duplicates }} 只；无效跳过 {{ preview.skipped }} 只。</p><p>合并后：{{ preview.draft.stocks.length }} 只股票、{{ preview.draft.groups.length }} 个分组。</p><ul v-if="preview.warnings.length"><li v-for="(warning, index) in preview.warnings.slice(0, 20)" :key="index">{{ warning }}</li></ul></div>
    <p v-if="localError || error" class="form-error" role="alert">{{ localError || error }}</p>
    <template #footer><el-button :disabled="busy" @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :disabled="!preview || busy" :loading="busy" @click="save">确认合并并保存</el-button></template>
  </el-dialog>
</template>

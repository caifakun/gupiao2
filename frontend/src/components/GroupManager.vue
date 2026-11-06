<script setup>
import { ref, watch } from "vue";
const props = defineProps({ modelValue: Boolean, groups: Array, busy: Boolean, error: String, createGroup: Function, renameGroup: Function });
const emit = defineEmits(["update:modelValue"]);
const newName = ref("");
const rows = ref([]);
const localError = ref("");
watch(() => [props.modelValue, props.groups], () => {
  rows.value = (props.groups || []).map(group => ({ ...group }));
  localError.value = "";
  newName.value = "";
}, { immediate: true });
function nameError(name, exceptId) {
  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 20 || /[\x00-\x1f\x7f]/.test(trimmed)) return "分组名称须为1至20个字符，不能包含控制字符。";
  if (trimmed === "全部自选" || props.groups.some(group => group.id !== exceptId && group.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase())) return "分组名称重复或属于保留名称。";
  return "";
}
async function create() {
  localError.value = nameError(newName.value) || (props.groups.length >= 100 ? "最多100个分组" : "");
  if (!localError.value && await props.createGroup(newName.value.trim())) newName.value = "";
}
async function rename(row) {
  localError.value = nameError(row.name, row.id);
  if (!localError.value) await props.renameGroup(row.id, row.name.trim());
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="自选分组管理" width="min(600px, 94vw)" :close-on-click-modal="!busy" :close-on-press-escape="!busy" @update:model-value="$emit('update:modelValue', $event)">
    <p class="dialog-description">可新增和重命名；股票归属按分组ID保留。“全部自选”为汇总入口。</p>
    <form class="group-create-form" @submit.prevent="create"><el-input v-model="newName" maxlength="20" placeholder="新分组名称" :disabled="busy" aria-label="新分组名称"/><el-button type="primary" native-type="submit" :loading="busy">新建分组</el-button></form>
    <p v-if="localError || error" class="form-error" role="alert">{{ localError || error }}</p>
    <div class="group-management-list"><form v-for="row in rows" :key="row.id" class="group-edit-form" @submit.prevent="rename(row)"><el-input v-model="row.name" maxlength="20" :aria-label="`重命名${row.name}`" :disabled="busy"/><el-button native-type="submit" :disabled="busy">保存名称</el-button></form></div>
    <template #footer><el-button :disabled="busy" @click="emit('update:modelValue', false)">完成</el-button></template>
  </el-dialog>
</template>

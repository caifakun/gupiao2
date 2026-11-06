<script setup>
import { ref } from "vue";
defineProps({ busy: Boolean, error: String });
const emit = defineEmits(["login"]);
const username = ref("");
const password = ref("");
function submit() { emit("login", username.value.trim(), password.value); }
</script>
<template>
  <main class="login-page"><section class="login-panel"><span class="eyebrow">JINGGUAN / PRIVATE WORKSPACE</span><h1>竞观行情工作台</h1><p class="dialog-description">登录后同步你的自选、分组与布局。只读行情，不提供买卖下单。</p>
    <el-form label-position="top" @submit.prevent="submit"><el-form-item label="用户名"><el-input v-model="username" autocomplete="username" maxlength="64" :disabled="busy"/></el-form-item><el-form-item label="密码"><el-input v-model="password" type="password" autocomplete="current-password" maxlength="128" show-password :disabled="busy"/></el-form-item><el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/><el-button type="primary" native-type="submit" :loading="busy" :disabled="!username.trim() || !password" class="login-submit">登录</el-button></el-form>
    <p class="field-help">不开放公共注册。首次部署需由管理员配置数据库、执行迁移并创建账号。</p><p class="field-help">公开数据源不保证实时，完整集合竞价量仍待核验。</p>
  </section></main>
</template>

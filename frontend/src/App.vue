<script setup>
import { defineAsyncComponent, onBeforeUnmount, onMounted } from "vue";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import IconLibrary from "./components/IconLibrary.vue";
import LoginView from "./views/LoginView.vue";
import { useAuth } from "./stores/auth.js";
const DashboardView = defineAsyncComponent(() => import("./views/DashboardView.vue"));
const auth = useAuth();
const { user, checking, busy, error, runtimeReady } = auth;
const expired = () => auth.expire();
onMounted(() => { window.addEventListener("gupiao:session-expired", expired); auth.restore(); });
onBeforeUnmount(() => window.removeEventListener("gupiao:session-expired", expired));
</script>
<template>
  <el-config-provider :locale="zhCn"><IconLibrary/><main v-if="checking" class="login-page"><p>正在连接行情工作台…</p></main><main v-else-if="!runtimeReady" class="login-page"><section class="login-panel"><h1>后端尚未连接</h1><p>{{ error }}</p><p>请先运行 start-local.ps1，使用终端显示的本机地址打开。</p><el-button type="primary" @click="auth.restore">重新连接</el-button></section></main><DashboardView v-else-if="user" :user="user" :auth-busy="busy" :auth-error="error" @logout="auth.logout"/><LoginView v-else :busy="busy" :error="error" @login="auth.login"/></el-config-provider>
</template>

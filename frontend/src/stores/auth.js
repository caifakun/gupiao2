import { ref } from "vue";
import { apiRequest, setCsrfToken } from "../services/api.js";
import { localMode } from "../services/runtime.js";

export function useAuth() {
  const user = ref(null);
  const checking = ref(true);
  const busy = ref(false);
  const error = ref("");
  const runtimeReady = ref(false);

  function acceptSession(session) {
    user.value = session.user;
    setCsrfToken(session.csrf_token);
    error.value = "";
  }

  function expire() {
    user.value = null;
    setCsrfToken("");
  }

  async function restore() {
    checking.value = true;
    error.value = "";
    try {
      const runtime = await apiRequest("/api/runtime", { timeout: 12000 });
      if (!["local", "database"].includes(runtime.mode)) throw new Error("后端运行模式无效，请确认已启动新版服务");
      localMode.value = runtime.mode === "local";
      runtimeReady.value = true;
      if (localMode.value) {
        user.value = { username: "本机工作台", local: true };
        setCsrfToken("");
      } else acceptSession(await apiRequest("/api/auth/me", { timeout: 12000 }));
    }
    catch (failure) {
      expire();
      if (failure.status !== 401) error.value = failure.message;
    } finally { checking.value = false; }
  }

  async function login(username, password) {
    busy.value = true;
    error.value = "";
    try {
      acceptSession(await apiRequest("/api/auth/login", { method: "POST", body: { username, password }, timeout: 20000 }));
      return true;
    } catch (failure) {
      error.value = failure.message;
      return false;
    } finally { busy.value = false; }
  }

  async function logout() {
    busy.value = true;
    try {
      await apiRequest("/api/auth/logout", { method: "POST", body: {} });
      expire();
    } catch (failure) {
      error.value = `未确认退出：${failure.message}`;
    } finally { busy.value = false; }
  }

  return { user, checking, busy, error, runtimeReady, restore, login, logout, expire };
}

let csrfToken = "";

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function setCsrfToken(value) {
  csrfToken = value || "";
}

export async function apiRequest(path, { method = "GET", body, signal, timeout = 35000 } = {}) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, timeout);
  try {
    const headers = { Accept: "application/json" };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrfToken;
    }
    const response = await fetch(path, {
      method, body: body === undefined ? undefined : JSON.stringify(body),
      headers, credentials: "same-origin", cache: "no-store", signal: controller.signal,
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw new ApiError("服务未返回JSON，请检查API反向代理配置", response.status); }
    if (!response.ok) {
      if (response.status === 401 && !["/api/auth/login", "/api/auth/me"].includes(path)) {
        window.dispatchEvent(new Event("gupiao:session-expired"));
      }
      throw new ApiError(payload.error || payload.errors?.[0]?.message || `请求失败 HTTP ${response.status}`, response.status);
    }
    return payload;
  } catch (error) {
    if (signal?.aborted) throw error;
    if (error.name === "AbortError") throw new ApiError("请求超时，未确认服务器结果；请重新加载后核对");
    if (error instanceof TypeError) throw new ApiError("无法连接服务，未确认保存结果；请恢复连接后重新加载");
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

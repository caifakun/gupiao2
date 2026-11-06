import { ref } from "vue";
import { apiRequest } from "../services/api.js";
import { localMode } from "../services/runtime.js";
import { loadLocalWorkspace, saveLocalWorkspace } from "../services/localWorkspace.js";

export function useWorkspace() {
  const workspace = ref(null);
  const loading = ref(false);
  const saving = ref(false);
  const blocked = ref(false);
  const error = ref("");

  async function load() {
    if (saving.value || loading.value) return false;
    loading.value = true;
    error.value = "";
    try {
      workspace.value = localMode.value ? loadLocalWorkspace() : await apiRequest("/api/workspace", { timeout: 20000 });
      blocked.value = false;
      return true;
    } catch (failure) {
      error.value = failure.message;
      blocked.value = true;
      return false;
    } finally { loading.value = false; }
  }

  async function commit(change) {
    if (!workspace.value || loading.value || saving.value || blocked.value) return false;
    const original = workspace.value;
    const draft = JSON.parse(JSON.stringify(original));
    saving.value = true;
    error.value = "";
    try {
      change(draft);
      workspace.value = localMode.value ? saveLocalWorkspace(draft, original.revision) : await apiRequest("/api/workspace", {
        method: "PUT", timeout: 25000,
        body: { expected_revision: original.revision, groups: draft.groups, stocks: draft.stocks, settings: draft.settings },
      });
      return true;
    } catch (failure) {
      error.value = failure.message;
      if (!failure.status || failure.status === 409 || failure.status >= 500) blocked.value = true;
      return false;
    } finally { saving.value = false; }
  }

  return { workspace, loading, saving, blocked, error, load, commit };
}

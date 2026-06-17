import { ref } from "vue";

/** Whether a new service worker is waiting to activate. */
const needRefresh = ref(false);

/** Function to trigger skipWaiting + reload. Stored when the SW update is detected. */
let updateFn: (() => Promise<void>) | null = null;

/**
 * Called from main.ts when the SW detects a new version.
 * Stores the update callback and sets needRefresh so the UpdatePrompt dialog appears.
 */
export function initPwaUpdate(updateServiceWorker: () => Promise<void>) {
  needRefresh.value = true;
  updateFn = updateServiceWorker;
}

export function usePwaUpdate() {
  async function applyUpdate() {
    if (updateFn) {
      await updateFn();
      needRefresh.value = false;
    }
  }

  function dismissUpdate() {
    needRefresh.value = false;
  }

  return { needRefresh, applyUpdate, dismissUpdate };
}

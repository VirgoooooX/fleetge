<template>
  <Transition name="install-banner-fade">
    <div v-if="showPrompt" class="install-prompt-banner">
      <el-icon class="install-prompt-icon"><Download /></el-icon>
      <span class="install-prompt-text">{{ t('mobile.installPrompt') }}</span>
      <el-button size="small" type="primary" @click="install">
        {{ t('mobile.install') }}
      </el-button>
      <el-button size="small" text class="install-prompt-dismiss" @click="dismiss">
        {{ t('mobile.dismiss') }}
      </el-button>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useI18n } from "vue-i18n";
import { Download } from "@element-plus/icons-vue";

const { t } = useI18n();

/** Chrome-specific BeforeInstallPromptEvent (not in standard TS libs). */
interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

const DISMISS_KEY = "fleetge_install_dismissed";

const showPrompt = ref(false);
let deferredPrompt: BeforeInstallPromptEvent | null = null;

function onBeforeInstallPrompt(e: Event) {
  e.preventDefault();
  if (localStorage.getItem(DISMISS_KEY)) return;
  deferredPrompt = e as BeforeInstallPromptEvent;
  showPrompt.value = true;
}

async function install() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  deferredPrompt = null;
  showPrompt.value = false;
  if (outcome === "accepted") {
    localStorage.setItem(DISMISS_KEY, "1");
  }
}

function dismiss() {
  showPrompt.value = false;
  deferredPrompt = null;
  localStorage.setItem(DISMISS_KEY, "1");
}

onMounted(() => {
  window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
});

onUnmounted(() => {
  window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
});
</script>

<style scoped>
.install-prompt-banner {
  position: fixed;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9980;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  border-radius: 12px;
  background: var(--surface-elevated);
  border: 1px solid var(--border-strong);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  max-width: 520px;
  width: calc(100vw - 32px);
}

.install-prompt-icon {
  font-size: 22px;
  color: var(--accent-blue);
  flex-shrink: 0;
}

.install-prompt-text {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  min-width: 0;
}

.install-prompt-dismiss {
  color: var(--text-muted) !important;
}

.install-banner-fade-enter-active,
.install-banner-fade-leave-active {
  transition: opacity 0.3s ease, transform 0.3s ease;
}

.install-banner-fade-enter-from,
.install-banner-fade-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(20px);
}
</style>

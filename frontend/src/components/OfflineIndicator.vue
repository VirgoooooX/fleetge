<template>
  <Transition name="offline-fade">
    <div v-if="isOffline" class="offline-indicator" role="alert">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ t('mobile.offline') }}</span>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue";
import { useI18n } from "vue-i18n";
import { WarningFilled } from "@element-plus/icons-vue";

const { t } = useI18n();
const isOffline = ref(!navigator.onLine);

function onOnline() { isOffline.value = false; }
function onOffline() { isOffline.value = true; }

onMounted(() => {
  window.addEventListener("online", onOnline);
  window.addEventListener("offline", onOffline);
});

onUnmounted(() => {
  window.removeEventListener("online", onOnline);
  window.removeEventListener("offline", onOffline);
});
</script>

<style scoped>
.offline-indicator {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 32px;
  background: var(--warning);
  color: #1e293b;
  font-size: 13px;
  font-weight: 700;
}

.offline-fade-enter-active,
.offline-fade-leave-active {
  transition: transform 0.3s ease;
}

.offline-fade-enter-from,
.offline-fade-leave-to {
  transform: translateY(-100%);
}
</style>

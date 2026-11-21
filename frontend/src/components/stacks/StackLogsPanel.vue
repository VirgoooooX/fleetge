<template>
  <section class="terminal-section">
    <div class="section-heading">
      <h3>{{ t('workspace.terminal') }}</h3>
      <div class="terminal-tools">
        <el-button class="ui-button ui-button--compact" size="small" text :loading="logsLoading" @click="emit('refresh')">
          <el-icon><RefreshCw /></el-icon>
          {{ t('workspace.refresh') }}
        </el-button>
      </div>
    </div>
    <div class="embedded-terminal" ref="logViewportRef">
      <div v-if="logsLoading && logLines.length === 0" class="terminal-muted">
        {{ t('workspace.loadingLogs') }}
      </div>
      <div v-else-if="logLines.length === 0" class="terminal-muted">
        {{ t('workspace.noLogs') }}
      </div>
      <div
        v-for="line in logLines"
        :key="line.id"
        class="terminal-log-line"
        :class="`level-${line.level}`"
      >
        <span v-if="line.service" class="terminal-service">{{ line.service }}</span>
        <span class="terminal-message">{{ line.text }}</span>
      </div>
      <div v-if="logsActive" class="terminal-cursor">▊</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { RefreshCw } from "@lucide/vue";
import { useI18n } from "vue-i18n";

export interface StackLogLine {
  id: number;
  service: string;
  text: string;
  level: "info" | "warn" | "error";
}

const props = defineProps<{
  logLines: StackLogLine[];
  logsLoading: boolean;
  logsActive: boolean;
}>();
const emit = defineEmits<{ refresh: [] }>();
const { t } = useI18n();
const logViewportRef = ref<HTMLElement | null>(null);

watch(() => props.logLines[props.logLines.length - 1]?.id, () => {
  const viewport = logViewportRef.value;
  if (viewport) viewport.scrollTop = viewport.scrollHeight;
}, { flush: "post" });
</script>

<style scoped>
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-heading h3 {
  margin: 3px 0 0;
  color: var(--text-primary);
}

.terminal-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.terminal-section {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  border: 0;
  background: transparent;
  padding: 0;
}

.embedded-terminal {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
  overflow: auto;
  border: 1px solid var(--terminal-border);
  border-radius: var(--radius-lg, 8px);
  background: var(--terminal-bg);
  color: var(--terminal-text);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  line-height: 1.45;
  padding: 10px;
}

.terminal-log-line {
  display: grid;
  grid-template-columns: minmax(76px, max-content) minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  padding: 2px 4px;
  border-radius: 5px;
  white-space: pre-wrap;
}

.terminal-log-line + .terminal-log-line {
  margin-top: 1px;
}

.terminal-log-line.level-error {
  background: var(--terminal-error-bg);
  color: var(--terminal-error-text);
}

.terminal-log-line.level-warn {
  background: var(--terminal-warn-bg);
  color: var(--terminal-warn-text);
}

.terminal-service {
  overflow: hidden;
  max-width: 15ch;
  border-right: 1px solid var(--terminal-border);
  color: var(--terminal-service);
  font-weight: 700;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-message {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.terminal-muted {
  color: var(--terminal-muted);
}

.terminal-cursor {
  display: inline-block;
  color: var(--terminal-cursor);
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}
</style>

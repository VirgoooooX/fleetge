<template>
  <div class="compose-preview">
    <div v-if="composeLoading" class="panel-muted">{{ t('workspace.loadingCompose') }}</div>
    <el-alert
      v-else-if="composeError"
      :title="composeError"
      type="warning"
      show-icon
      :closable="false"
    />
    <div v-else-if="!composeYaml" class="panel-muted">{{ t('workspace.noComposeFromAgent') }}</div>
    <MonacoEditor
      v-else
      :model-value="composeYaml"
      language="yaml"
      readonly
      line-numbers="off"
      word-wrap="on"
      height="100%"
    />
  </div>
</template>

<script setup lang="ts">
import { defineAsyncComponent } from "vue";
import { useI18n } from "vue-i18n";

const MonacoEditor = defineAsyncComponent(() => import("@/components/MonacoEditor.vue"));
defineProps<{ composeLoading: boolean; composeError: string; composeYaml: string }>();
const { t } = useI18n();
</script>

<style scoped>
.compose-preview {
  display: flex;
  flex: 1;
  min-height: 0;
  margin-left: -16px;
  margin-right: -16px;
  margin-bottom: -16px;
  padding-left: 8px;
  padding-right: 8px;
}

.compose-preview :deep(.monaco-editor-container) {
  border: none;
  border-radius: 0;
  height: 100%;
  width: 100%;
  background-color: transparent !important;
}

.compose-preview :deep(.monaco-editor),
.compose-preview :deep(.monaco-editor-background),
.compose-preview :deep(.monaco-editor .margin) {
  background-color: transparent !important;
}

.panel-muted {
  color: var(--text-secondary);
  font-size: 13px;
}
</style>

<template>
  <el-dialog
    :model-value="needRefresh"
    :title="t('pwa.updateTitle')"
    width="min(400px, calc(100vw - 24px))"
    class="ui-dialog"
    :close-on-click-modal="false"
    :show-close="false"
    append-to-body
    @update:model-value="(val: boolean) => { if (!val) dismiss(); }"
  >
    <p>{{ t('pwa.updateMessage') }}</p>
    <template #footer>
      <el-button class="ui-button" @click="dismiss">{{ t('pwa.updateDismiss') }}</el-button>
      <el-button class="ui-button ui-button--primary" type="primary" @click="apply">{{ t('pwa.updateApply') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { usePwaUpdate } from "@/composables/usePwaUpdate";

const { t } = useI18n();
const { needRefresh, applyUpdate, dismissUpdate } = usePwaUpdate();

function apply() { applyUpdate(); }
function dismiss() { dismissUpdate(); }
</script>

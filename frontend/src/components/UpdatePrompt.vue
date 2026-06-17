<template>
  <el-dialog
    v-model="visible"
    :title="t('pwa.updateTitle')"
    width="400px"
    :close-on-click-modal="false"
    :show-close="false"
    append-to-body
  >
    <p>{{ t('pwa.updateMessage') }}</p>
    <template #footer>
      <el-button @click="dismiss">{{ t('pwa.updateDismiss') }}</el-button>
      <el-button type="primary" @click="apply">{{ t('pwa.updateApply') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { usePwaUpdate } from "@/composables/usePwaUpdate";

const { t } = useI18n();
const { needRefresh, applyUpdate, dismissUpdate } = usePwaUpdate();

const visible = computed(() => needRefresh.value);

function apply() { applyUpdate(); }
function dismiss() { dismissUpdate(); }
</script>

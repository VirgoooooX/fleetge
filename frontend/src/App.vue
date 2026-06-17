<template>
  <el-config-provider :locale="currentElLocale">
    <OfflineIndicator />
    <UpdatePrompt />
    <router-view v-if="isAuthPage" />
    <template v-else>
      <AppShell>
        <router-view />
      </AppShell>
      <MobileInstallPrompt />
    </template>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import en from "element-plus/es/locale/lang/en";
import AppShell from "@/components/AppShell.vue";
import OfflineIndicator from "@/components/OfflineIndicator.vue";
import UpdatePrompt from "@/components/UpdatePrompt.vue";
import MobileInstallPrompt from "@/components/MobileInstallPrompt.vue";

const route = useRoute();
const { locale } = useI18n();

const isAuthPage = computed(() => route.name === "login");

const currentElLocale = computed(() => {
  return locale.value === "zh-CN" ? zhCn : en;
});
</script>

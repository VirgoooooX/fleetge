<template>
  <el-config-provider :locale="currentElLocale">
    <router-view v-if="isAuthPage" />
    <AppShell v-else>
      <router-view />
    </AppShell>
  </el-config-provider>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import en from "element-plus/es/locale/lang/en";
import AppShell from "@/components/AppShell.vue";

const route = useRoute();
const { locale } = useI18n();

const isAuthPage = computed(() => route.name === "login");

const currentElLocale = computed(() => {
  return locale.value === "zh-CN" ? zhCn : en;
});
</script>

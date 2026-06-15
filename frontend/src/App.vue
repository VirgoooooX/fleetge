<template>
  <router-view v-if="isAuthPage" />
  <AppShell v-else>
    <router-view />
  </AppShell>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import AppShell from "@/components/AppShell.vue";

const route = useRoute();
const isAuthPage = computed(() => route.name === "login");
</script>

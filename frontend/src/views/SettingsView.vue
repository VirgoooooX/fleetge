<template>
  <div class="settings-layout">
    <nav class="settings-tabs" :aria-label="t('settings.sections.navigation')" role="tablist">
      <button
        v-for="section in settingSections"
        :key="section.id"
        type="button"
        class="settings-tab"
        :class="{ active: activeSection === section.id }"
        :aria-selected="activeSection === section.id"
        role="tab"
        @click="setSection(section.id)"
      >
        <el-icon><component :is="section.icon" /></el-icon>
        <span>{{ section.label }}</span>
      </button>
    </nav>

    <div class="settings-workspace">
      <main class="settings-main">
        <ParamsSettingsSection :active="activeSection === 'params'" />
        <HostsSettingsSection :active="activeSection === 'hosts'" />
        <MaintenanceSettingsSection :active="activeSection === 'maintenance'" @edit-interval="setSection('params')" />
        <AuditSettingsSection :active="activeSection === 'audit'" />
        <AboutSettingsSection :active="activeSection === 'about'" />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { History, Server, SlidersHorizontal, Wrench, GitBranch } from "@lucide/vue";
import ParamsSettingsSection from "@/components/settings/ParamsSettingsSection.vue";
import HostsSettingsSection from "@/components/settings/HostsSettingsSection.vue";
import MaintenanceSettingsSection from "@/components/settings/MaintenanceSettingsSection.vue";
import AuditSettingsSection from "@/components/settings/AuditSettingsSection.vue";
import AboutSettingsSection from "@/components/settings/AboutSettingsSection.vue";

type SettingsSectionId = "params" | "hosts" | "maintenance" | "audit" | "about";
const { t } = useI18n();
const route = useRoute();
const router = useRouter();

const activeSection = ref<SettingsSectionId>("params");
const validSections: SettingsSectionId[] = ["params", "hosts", "maintenance", "audit", "about"];

const settingSections = computed(() => [
  {
    id: "params" as const,
    label: t("settings.sections.params"),
    icon: SlidersHorizontal,
  },
  {
    id: "hosts" as const,
    label: t("settings.sections.hosts"),
    icon: Server,
  },
  {
    id: "maintenance" as const,
    label: t("settings.sections.maintenance"),
    icon: Wrench,
  },
  {
    id: "audit" as const,
    label: t("settings.sections.audit"),
    icon: History,
  },
  {
    id: "about" as const,
    label: t("settings.sections.about"),
    icon: GitBranch,
  },
]);

function setSection(section: SettingsSectionId) {
  activeSection.value = section;
  void router.replace({ name: "settings", query: { section } });
}

watch(() => route.query.section, (value) => {
  const section = Array.isArray(value) ? value[0] : value;
  if (section && validSections.includes(section as SettingsSectionId)) {
    activeSection.value = section as SettingsSectionId;
  }
}, { immediate: true });
</script>

<style scoped>
.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.settings-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  padding: 6px;
}

.settings-tab {
  min-width: max-content;
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  text-decoration: none;
  cursor: pointer;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.settings-tab:hover,
.settings-tab.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--text-primary);
}

.settings-tab .el-icon {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-blue);
  flex: 0 0 auto;
}

.settings-workspace {
  min-width: 0;
}

.settings-main {
  min-width: 0;
}

@media (max-width: 1100px) {
  .settings-tabs {
    scrollbar-width: thin;
  }
}

@media (max-width: 768px) {
  .settings-tabs {
    padding: 5px;
  }

  .settings-tab {
    min-height: 34px;
    padding: 0 10px;
  }
}
</style>

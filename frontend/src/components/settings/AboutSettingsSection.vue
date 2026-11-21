<template>
  <section v-if="active" class="settings-section">
    <div class="section-heading">
      <div>
        <h3>{{ t("settings.sections.about") }}</h3>
        <p>{{ t("settings.about.description") }}</p>
      </div>
    </div>

    <div class="about-panel">
      <div class="about-version-row">
        <span>{{ t("settings.about.version") }}</span>
        <strong>v{{ appVersion }}</strong>
      </div>
      <div class="about-link-list">
        <a
          v-for="link in resourceLinks"
          :key="link.href"
          class="about-link-row"
          :href="link.href"
          target="_blank"
          rel="noreferrer noopener"
        >
          <el-icon><component :is="link.icon" /></el-icon>
          <span>
            <strong>{{ link.label }}</strong>
            <small>{{ link.description }}</small>
          </span>
        </a>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { BookOpen, GitBranch, History, MessageCircleQuestionMark } from "@lucide/vue";

defineProps<{ active: boolean }>();
const { t } = useI18n();
const appVersion = __APP_VERSION__;

const resourceLinks = computed(() => [
  {
    label: t("settings.about.github"),
    description: t("settings.about.githubDesc"),
    href: "https://github.com/virgooooox/fleetge",
    icon: GitBranch,
  },
  {
    label: t("settings.about.docs"),
    description: t("settings.about.docsDesc"),
    href: "https://github.com/virgooooox/fleetge#readme",
    icon: BookOpen,
  },
  {
    label: t("settings.about.releases"),
    description: t("settings.about.releasesDesc"),
    href: "https://github.com/virgooooox/fleetge/releases",
    icon: History,
  },
  {
    label: t("settings.about.issues"),
    description: t("settings.about.issuesDesc"),
    href: "https://github.com/virgooooox/fleetge/issues",
    icon: MessageCircleQuestionMark,
  },
]);
</script>

<style scoped src="./settings-section.css"></style>

<style scoped>
.about-panel {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
  overflow: hidden;
}

.about-version-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 13px;
}

.about-version-row strong {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 13px;
}

.about-link-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.about-link-row {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-top: 1px solid transparent;
  color: var(--text-secondary);
  text-decoration: none;
  transition: background 160ms ease, color 160ms ease;
}

.about-link-row:hover {
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

.about-link-row .el-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 7px;
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue);
}

.about-link-row span {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.about-link-row strong {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.2;
}

.about-link-row small {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
}
</style>

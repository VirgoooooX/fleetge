<template>
  <div class="dashboard-layout">
    <section class="overview-dashboard ui-dashboard-surface" :aria-label="t('dashboard.title')">
      <div class="overview-copy ui-dashboard-copy">
        <h2 class="ui-dashboard-title">{{ t('dashboard.title') }}</h2>
        <p class="ui-dashboard-description">{{ t('dashboard.description') }}</p>
      </div>

      <div class="fleet-health-readout">
        <div class="health-readout-heading">
          <span class="health-readout-icon"><Monitor :size="17" /></span>
          <span>{{ t('dashboard.onlineHosts') }}</span>
        </div>
        <div class="health-readout-value">
          <strong>{{ store.onlineCount }}</strong>
          <span>/ {{ store.hosts.length }}</span>
        </div>
        <div class="health-track" aria-hidden="true">
          <span :style="{ width: `${onlinePercentage}%` }" />
        </div>
      </div>

      <div class="runtime-readouts">
        <div class="runtime-readout">
          <span class="runtime-icon"><CheckCircle :size="18" /></span>
          <span class="runtime-label">{{ t('dashboard.runningContainers') }}</span>
          <strong>{{ store.runningContainers }}</strong>
          <small>{{ t('dashboard.running') }}</small>
        </div>
        <div class="runtime-readout">
          <span class="runtime-icon"><XCircle :size="18" /></span>
          <span class="runtime-label">{{ t('dashboard.stoppedContainers') }}</span>
          <strong>{{ stoppedContainers }}</strong>
          <small>{{ t('dashboard.stopped') }}</small>
        </div>
        <button
          class="runtime-readout runtime-readout--updates"
          type="button"
          @click="router.push({ name: 'apps', query: { status: 'updatable' } })"
        >
          <span class="runtime-icon"><Download :size="18" /></span>
          <span class="runtime-label">{{ t('dashboard.updatableImages') }}</span>
          <strong>{{ store.updateCount }}</strong>
          <small>{{ t('dashboard.updates') }}</small>
        </button>
      </div>
    </section>

    <el-alert
      v-if="store.error"
      :title="store.error"
      type="error"
      show-icon
      closable
      class="error-alert"
    />

    <main class="host-grid" :aria-label="t('dashboard.title')">
      <HostCard
        v-for="host in sortedHosts"
        :key="host.host_id"
        :host="host"
        :traffic="store.getHostTrafficState(host.host_id)"
        :update-count="store.getHostUpdateCount(host.host_id)"
        @click="goToHost(host.host_id)"
        @updates="goToHost(host.host_id)"
      />
    </main>

    <el-empty
      v-if="!store.loading && store.hosts.length === 0"
      :description="t('dashboard.noHosts')"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useDashboardStore } from "@/stores/dashboard";
import HostCard from "@/components/HostCard.vue";
import { Monitor, CheckCircle, XCircle, Download } from "@lucide/vue";

const router = useRouter();
const store = useDashboardStore();
const { t } = useI18n();

const stoppedContainers = computed(() =>
  store.hosts.reduce((sum, host) => sum + host.container_stopped, 0)
);
const onlinePercentage = computed(() =>
  store.hosts.length ? Math.round((store.onlineCount / store.hosts.length) * 100) : 0
);

const sortedHosts = computed(() => store.hosts);
const hostIds = computed(() => sortedHosts.value.map((host) => host.host_id));

let trafficTimer: ReturnType<typeof setInterval> | null = null;

async function refreshTrafficSummaries() {
  if (document.hidden) return;
  await Promise.allSettled(
    hostIds.value.map((hostId) => store.fetchHostTrafficSummary(hostId, true)),
  );
}

function handleVisibilityChange() {
  if (!document.hidden) void refreshTrafficSummaries();
}

onMounted(() => {
  void refreshTrafficSummaries();
  trafficTimer = setInterval(() => void refreshTrafficSummaries(), 60000);
  document.addEventListener("visibilitychange", handleVisibilityChange);
});

watch(hostIds, (next, previous) => {
  if (next.join("|") !== previous.join("|")) void refreshTrafficSummaries();
});

onUnmounted(() => {
  if (trafficTimer) clearInterval(trafficTimer);
  document.removeEventListener("visibilitychange", handleVisibilityChange);
});

function goToHost(hostId: string) {
  router.push(`/hosts/${hostId}`);
}
</script>

<style scoped>
.dashboard-layout {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.overview-dashboard {
  display: grid;
  grid-template-columns: minmax(300px, 1.05fr) minmax(170px, 0.55fr) minmax(430px, 1.45fr);
  align-items: center;
  gap: 20px;
  height: var(--ui-dashboard-header-height);
  min-height: var(--ui-dashboard-header-height);
  padding: var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline);
  background:
    radial-gradient(circle at 0 0, color-mix(in srgb, var(--accent-blue) 10%, transparent), transparent 35%),
    var(--ui-dashboard-bg);
}

.overview-copy {
  min-width: 0;
}

.overview-copy .ui-dashboard-description {
  max-width: 390px;
}

.fleet-health-readout {
  min-width: 0;
  padding-left: 20px;
  border-left: 1px solid var(--ui-dashboard-line);
}

.health-readout-heading {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 700;
}

.health-readout-icon {
  display: inline-flex;
  color: var(--accent-blue);
}

.health-readout-value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  margin-top: 7px;
  font-family: var(--font-mono);
}

.health-readout-value strong {
  color: var(--text-primary);
  font-size: 36px;
  font-weight: 700;
  letter-spacing: -0.06em;
  line-height: 1;
}

.health-readout-value span {
  color: var(--text-muted);
  font-size: var(--text-md);
}

.health-track {
  width: 100%;
  height: 3px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--ui-dashboard-inset-bg);
}

.health-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--accent-blue), var(--success));
  transition: width 240ms ease;
}

.runtime-readouts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--ui-dashboard-line);
  border-radius: var(--ui-radius-md);
  background: var(--ui-dashboard-inset-bg);
}

.runtime-readout {
  display: grid;
  min-width: 0;
  min-height: 78px;
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-rows: auto auto;
  align-items: center;
  gap: 3px 9px;
  padding: 13px 14px;
  border: 0;
  border-left: 1px solid var(--ui-dashboard-line);
  border-radius: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  text-align: left;
}

.runtime-readout:first-child {
  border-left: 0;
}

.runtime-readout--updates {
  cursor: pointer;
  transition: background 160ms ease;
}

.runtime-readout--updates:hover {
  background: color-mix(in srgb, var(--danger) 7%, transparent);
}

.runtime-icon {
  display: inline-flex;
  grid-row: 1 / 3;
  color: var(--text-muted);
}

.runtime-label {
  grid-column: 2;
  overflow: hidden;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-readout strong {
  grid-column: 3;
  grid-row: 1 / 3;
  font-family: var(--font-mono);
  font-size: 25px;
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1;
}

.runtime-readout small {
  grid-column: 2;
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.runtime-readout--updates strong,
.runtime-readout--updates small {
  color: var(--danger);
}

.error-alert {
  margin: 0;
}

.host-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
  gap: 16px;
}

@media (max-width: 1180px) {
  .overview-dashboard {
    height: auto;
    grid-template-columns: minmax(280px, 1fr) minmax(170px, 0.55fr);
  }

  .runtime-readouts {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .overview-dashboard {
    grid-template-columns: 1fr;
    gap: 16px;
    padding: var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline);
  }

  .fleet-health-readout {
    padding: 14px 0 0;
    border-top: 1px solid var(--ui-dashboard-line);
    border-left: 0;
  }

  .runtime-readouts {
    grid-column: auto;
  }

  .host-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 460px) {
  .runtime-readouts {
    grid-template-columns: 1fr;
  }

  .runtime-readout,
  .runtime-readout:first-child {
    border-top: 1px solid var(--ui-dashboard-line);
    border-left: 0;
  }

  .runtime-readout:first-child {
    border-top: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .health-track span {
    transition: none;
  }
}
</style>

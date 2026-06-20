<template>
  <div class="dashboard-layout">
    <section class="command-strip">
      <div class="command-copy">
        <ClusterHealthBg />
        <div class="command-copy-content">
          <div class="ui-section-kicker">{{ t('dashboard.kicker') }}</div>
          <h2>{{ t('dashboard.title') }}</h2>
          <p>{{ t('dashboard.description') }}</p>
        </div>
        <img src="/cloud_banner.png" alt="Cloud Banner" class="command-banner" />
      </div>
      <div class="summary-grid">
        <div class="summary-tile" @mouseenter="setTileAnim(0)">
          <span class="summary-label">{{ t('dashboard.onlineHosts') }}</span>
          <strong>{{ store.onlineCount }}</strong>
          <small>/ {{ store.hosts.length }}</small>
          <div class="tile-icon" :class="tileAnims[0] ? `anim-${tileAnims[0]}` : ''">
            <el-icon :size="60"><Monitor /></el-icon>
          </div>
        </div>
        <div class="summary-tile" @mouseenter="setTileAnim(1)">
          <span class="summary-label">{{ t('dashboard.runningContainers') }}</span>
          <strong>{{ store.runningContainers }}</strong>
          <small>{{ t('dashboard.running') }}</small>
          <div class="tile-icon" :class="tileAnims[1] ? `anim-${tileAnims[1]}` : ''">
            <el-icon :size="60"><CheckCircle /></el-icon>
          </div>
        </div>
        <div class="summary-tile" @mouseenter="setTileAnim(2)">
          <span class="summary-label">{{ t('dashboard.stoppedContainers') }}</span>
          <strong>{{ stoppedContainers }}</strong>
          <small>{{ t('dashboard.stopped') }}</small>
          <div class="tile-icon" :class="tileAnims[2] ? `anim-${tileAnims[2]}` : ''">
            <el-icon :size="60"><XCircle /></el-icon>
          </div>
        </div>
        <button class="summary-tile critical" type="button" @click="router.push('/updates')" @mouseenter="setTileAnim(3)">
          <span class="summary-label">{{ t('dashboard.updatableImages') }}</span>
          <strong>{{ store.updateCount }}</strong>
          <small>{{ t('dashboard.updates') }}</small>
          <div class="tile-icon" :class="tileAnims[3] ? `anim-${tileAnims[3]}` : ''">
            <el-icon :size="60"><Download /></el-icon>
          </div>
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
import { computed, reactive } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { useDashboardStore } from "@/stores/dashboard";
import HostCard from "@/components/HostCard.vue";
import ClusterHealthBg from "@/components/ClusterHealthBg.vue";
import { Monitor, CheckCircle, XCircle, Download } from "@lucide/vue";

const router = useRouter();
const store = useDashboardStore();
const { t } = useI18n();

const ANIM_LIST = ['slide-up', 'slide-down', 'slide-right', 'rotate-cw', 'rotate-ccw', 'tilt'] as const;
const tileAnims = reactive<string[]>(['', '', '', '']);

function setTileAnim(idx: number) {
  const prev = tileAnims[idx];
  const pool = ANIM_LIST.filter(a => a !== prev);
  tileAnims[idx] = pool[Math.floor(Math.random() * pool.length)];
}

const stoppedContainers = computed(() =>
  store.hosts.reduce((sum, host) => sum + host.container_stopped, 0)
);

const sortedHosts = computed(() => store.hosts);

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

.command-strip {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(520px, 1.4fr);
  align-items: stretch;
  gap: 16px;
}

.command-copy {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--dash-command-bg);
  padding: 18px;
}

.command-copy {
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  position: relative;
  overflow: hidden;
  isolation: isolate;
  transform: translateZ(0);
  background: var(--dash-command-bg);
}

.command-copy-content {
  position: relative;
  z-index: 1;
}

.command-banner {
  position: absolute;
  right: -10px;
  bottom: -15px;
  height: 100%;
  width: auto;
  pointer-events: none;
  opacity: 0.95;
  z-index: 0;
  transition: transform 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

.command-copy:hover .command-banner {
  transform: scale(1.06) translate(-4px, -4px) rotate(-1deg);
}


.command-copy h2 {
  margin: 0;
  margin-top: 8px;
  font-size: 24px;
  line-height: 1.15;
  color: var(--text-primary);
}

.command-copy p {
  max-width: 420px;
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 500px) {
  .command-banner {
    opacity: 0.5;
    height: 100%;
    right: -10px;
    bottom: -15px;
  }
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.summary-tile {
  min-height: 150px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--dash-tile-bg);
  color: var(--text-primary);
  padding: 16px 14px;
  text-align: left;
  position: relative;
}

button.summary-tile {
  cursor: pointer;
}

.summary-tile:hover {
  border-color: var(--border-strong);
  background: var(--dash-tile-hover-bg);
}

.summary-tile.critical {
  border-color: var(--border-subtle);
  background: var(--dash-tile-bg);
}

.summary-tile strong {
  font-size: 37px;
  line-height: 1;
  font-weight: 700;
  color: var(--text-primary);
}

.summary-label {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
}

/* ── Tile icon — large background element at center-right ──── */
.tile-icon {
  position: absolute;
  right: 4px;
  top: 44%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  opacity: 1;
  pointer-events: none;
  transition:
    transform 0.45s cubic-bezier(0.16, 1, 0.3, 1),
    opacity 0.3s ease;
}

/* Default hover — no random class yet */
.summary-tile:hover .tile-icon:not([class*="anim-"]) {
  opacity: 1;
}

/* ── Random animation variants ────────────────────────────── */

.summary-tile:hover .anim-slide-up {
  transform: translateY(-8px);
  opacity: 1;
}
.summary-tile:hover .anim-slide-down {
  transform: translateY(8px);
  opacity: 1;
}
.summary-tile:hover .anim-slide-right {
  transform: translateX(10px);
  opacity: 1;
}
.summary-tile:hover .anim-rotate-cw {
  transform: rotate(12deg) scale(1.06);
  opacity: 1;
}
.summary-tile:hover .anim-rotate-ccw {
  transform: rotate(-14deg) scale(1.06);
  opacity: 1;
}
.summary-tile:hover .anim-tilt {
  transform: rotate(3deg);
  opacity: 1;
}

.summary-tile small {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
}

.summary-tile.critical strong,
.summary-tile.critical small {
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

@media (max-width: 1100px) {
  .command-strip {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .host-grid {
    grid-template-columns: 1fr;
  }
}
</style>

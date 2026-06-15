<template>
  <div class="dashboard-layout">
    <section class="command-strip">
      <div class="command-copy">
        <div class="section-kicker">Fleet Health</div>
        <h2>多主机运行态</h2>
        <p>按在线状态、容器运行数和镜像更新优先排序，异常项保持在首屏可见。</p>
      </div>
      <div class="summary-grid">
        <div class="summary-tile">
          <span class="summary-label">在线主机</span>
          <strong>{{ store.onlineCount }}</strong>
          <small>/ {{ store.hosts.length }}</small>
        </div>
        <div class="summary-tile">
          <span class="summary-label">运行容器</span>
          <strong>{{ store.runningContainers }}</strong>
          <small>running</small>
        </div>
        <div class="summary-tile">
          <span class="summary-label">停止容器</span>
          <strong>{{ stoppedContainers }}</strong>
          <small>stopped</small>
        </div>
        <button class="summary-tile critical" type="button" @click="router.push('/updates')">
          <span class="summary-label">可更新镜像</span>
          <strong>{{ store.updateCount }}</strong>
          <small>updates</small>
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

    <main class="host-grid" aria-label="主机状态矩阵">
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
      description="暂无主机配置"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { useDashboardStore } from "@/stores/dashboard";
import HostCard from "@/components/HostCard.vue";

const router = useRouter();
const store = useDashboardStore();

const stoppedContainers = computed(() =>
  store.hosts.reduce((sum, host) => sum + host.container_stopped, 0)
);

const sortedHosts = computed(() =>
  [...store.hosts].sort((a, b) => {
    const riskA =
      (a.status === "online" ? 0 : 100) +
      store.getHostUpdateCount(a.host_id) * 10 +
      a.container_stopped;
    const riskB =
      (b.status === "online" ? 0 : 100) +
      store.getHostUpdateCount(b.host_id) * 10 +
      b.container_stopped;
    return riskB - riskA;
  })
);

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

.command-copy,
.summary-grid {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--dash-command-bg);
  padding: 18px;
}

.section-kicker {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.command-copy h2 {
  margin: 0;
  margin-top: 8px;
  font-size: 24px;
  line-height: 1.15;
  color: var(--text-primary);
}

.command-copy p {
  max-width: 560px;
  margin: 10px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  padding: 12px;
}

.summary-tile {
  min-height: 92px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: space-between;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--dash-tile-bg);
  color: var(--text-primary);
  padding: 12px;
  text-align: left;
}

button.summary-tile {
  cursor: pointer;
}

.summary-tile:hover {
  border-color: var(--border-strong);
  background: var(--dash-tile-hover-bg);
}

.summary-tile.critical {
  border-color: rgba(248, 113, 113, 0.28);
  background: var(--dash-tile-critical-bg);
}

.summary-tile strong {
  font-size: 31px;
  line-height: 1;
  font-weight: 700;
  color: var(--text-primary);
}

.summary-label {
  color: var(--text-secondary);
  font-size: 12px;
}

.summary-tile small {
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: 11px;
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
  grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px;
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

<template>
  <el-card class="host-card" shadow="never" @click="$emit('click')">
    <!-- Header: hostname / OS / update badge -->
    <div class="card-header-row">
      <div class="card-header-left">
        <StatusIcon :status="host.status" />
        <div class="card-header-text">
          <span class="host-name font-bold">{{ host.display_name }}</span>
          <span v-if="displayUpdateCount > 0" class="m-badge-danger" @click.stop="$emit('updates')">
            {{ t('hostCard.updates', { count: displayUpdateCount }) }}
          </span>
        </div>
      </div>
      <div class="card-header-right">
        <!-- Error Tooltip -->
        <el-tooltip
          v-if="hasError"
          :content="refreshIssueText"
          placement="top"
          effect="dark"
        >
          <span class="error-badge" :class="`is-${statusTone}`">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="12" y1="8" x2="12" y2="12"/>
              <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
          </span>
        </el-tooltip>

        <!-- Status Tag -->
        <span class="m-status-pill" :class="`is-${statusTone}`">
          {{ statusLabel }}
        </span>
      </div>
    </div>
    <div class="host-subtitle">{{ host.os_info || host.metrics?.hostname || host.host_id }}</div>

    <!-- Capacity: CPU / memory / disk with progress bars and Sparkline -->
    <div v-if="host.metrics" class="m-capacity-grid">
      <!-- CPU Sub-card -->
      <div class="m-sub-card">
        <div class="m-sub-card-header">
          <div class="icon-wrapper cpu-color" v-html="vibrantIcons.cpu"></div>
          <span class="sub-label">{{ t('hostCard.cpu') }}</span>
        </div>
        <div class="sub-value font-bold">
          <span class="val-amount">{{ host.metrics.cpuPercent.toFixed(1) }}</span>
          <span class="val-unit">%</span>
        </div>
        
        <!-- SVG Sparkline for CPU -->
        <div class="sub-chart">
          <svg width="100%" height="24" viewBox="0 0 100 24" preserveAspectRatio="none">
            <defs>
              <linearGradient :id="`cpuGrad-${host.host_id}`" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--accent-blue)" stop-opacity="0.45"/>
                <stop offset="100%" stop-color="var(--accent-blue)" stop-opacity="0.04"/>
              </linearGradient>
            </defs>
            <path v-if="cpuPaths.fill" :d="cpuPaths.fill" :fill="`url(#cpuGrad-${host.host_id})`"/>
            <path v-if="cpuPaths.stroke" :d="cpuPaths.stroke" fill="none" stroke="var(--accent-blue)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>

      <!-- Memory Sub-card -->
      <div class="m-sub-card">
        <div class="m-sub-card-header">
          <div class="icon-wrapper mem-color" v-html="vibrantIcons.mem"></div>
          <span class="sub-label">{{ t('hostCard.memory') }}</span>
        </div>
        <div class="sub-value font-bold">
          {{ formatBytes(host.metrics.memoryUsed) }}
          <small>/ {{ formatBytes(host.metrics.memoryTotal) }}</small>
        </div>
        
        <!-- Progress Row -->
        <div class="m-progress-row">
          <div class="m-progress-track">
            <div class="m-progress-fill" :style="{ width: `${memPercent}%`, background: metricColor(memPercent) }"></div>
          </div>
          <span class="m-percent-label">{{ memPercent }}%</span>
        </div>
      </div>

      <!-- Disk Sub-card -->
      <div class="m-sub-card">
        <div class="m-sub-card-header">
          <div class="icon-wrapper disk-color" v-html="vibrantIcons.disk"></div>
          <span class="sub-label">{{ t('hostCard.disk') }}</span>
        </div>
        <div class="sub-value font-bold">
          {{ formatBytes(host.metrics.diskUsed) }}
          <small>/ {{ formatBytes(host.metrics.diskTotal) }}</small>
        </div>
        
        <!-- Progress Row -->
        <div class="m-progress-row">
          <div class="m-progress-track">
            <div class="m-progress-fill" :style="{ width: `${diskPercent}%`, background: metricColor(diskPercent) }"></div>
          </div>
          <span class="m-percent-label">{{ diskPercent }}%</span>
        </div>
      </div>
    </div>

    <!-- Telemetry: NET / I/O as split row -->
    <div v-if="host.metrics" class="m-telemetry-box">
      <!-- Left: Network -->
      <div class="m-tel-col net-part">
        <div class="m-tel-header">
          <div class="icon-wrapper-inline net-color" v-html="vibrantIcons.net"></div>
          <span>{{ t('hostCard.net') }}</span>
        </div>

        <!-- Middle: values — fixed arrows & units, only the number changes -->
        <div class="m-net-values">
          <div class="m-net-rate-item">
            <span class="net-arrow up">↑</span>
            <strong class="net-amount">{{ formatRateParts(host.metrics.networkTxRate).amount }}</strong>
            <small class="net-unit">{{ formatRateParts(host.metrics.networkTxRate).unit }}</small>
          </div>
          <div class="m-net-rate-item">
            <span class="net-arrow down">↓</span>
            <strong class="net-amount">{{ formatRateParts(host.metrics.networkRxRate).amount }}</strong>
            <small class="net-unit">{{ formatRateParts(host.metrics.networkRxRate).unit }}</small>
          </div>
        </div>

        <!-- Bottom: mini sparkline -->
        <div class="m-net-chart">
          <svg width="100%" height="20" viewBox="0 0 100 20" preserveAspectRatio="none">
            <defs>
              <linearGradient :id="`netGrad-${host.host_id}`" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#06b6d4" stop-opacity="0.42"/>
                <stop offset="100%" stop-color="#06b6d4" stop-opacity="0.04"/>
              </linearGradient>
            </defs>
            <path v-if="netPaths.fill" :d="netPaths.fill" :fill="`url(#netGrad-${host.host_id})`"/>
            <path v-if="netPaths.stroke" :d="netPaths.stroke" fill="none" stroke="#06b6d4" stroke-width="1.05" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>

      <!-- Middle: I/O Read -->
      <div class="m-tel-col border-lr io-part">
        <div class="m-tel-header">
          <div class="icon-wrapper-inline io-color" v-html="vibrantIcons.io"></div>
          <span>{{ t('hostCard.io') }} {{ t('hostCard.read', '读取') }}</span>
        </div>
        <div class="m-io-value">
          <strong class="io-amount">{{ formatRateParts(host.metrics.diskReadRate).amount }}</strong>
          <small class="io-unit">{{ formatRateParts(host.metrics.diskReadRate).unit }}</small>
        </div>
      </div>

      <!-- Right: I/O Write -->
      <div class="m-tel-col io-part">
        <div class="m-tel-header">
          <div class="icon-wrapper-inline io-color" v-html="vibrantIcons.io"></div>
          <span>{{ t('hostCard.io') }} {{ t('hostCard.write', '写入') }}</span>
        </div>
        <div class="m-io-value">
          <strong class="io-amount">{{ formatRateParts(host.metrics.diskWriteRate).amount }}</strong>
          <small class="io-unit">{{ formatRateParts(host.metrics.diskWriteRate).unit }}</small>
        </div>
      </div>
    </div>

    <div v-else class="metrics-missing">{{ t('hostCard.metricsUnavailable') }}</div>

    <!-- Footer: container counts / images / version -->
    <div class="m-footer">
      <div class="m-foot-item flex-center" :title="t('hostCard.runningContainers')">
        <span class="foot-dot green"></span>
        <strong>{{ host.container_running }}</strong>
      </div>
      <div class="m-foot-item flex-center" :title="t('hostCard.stoppedContainers')">
        <span class="foot-dot red"></span>
        <strong>{{ host.container_stopped }}</strong>
      </div>
      <div class="m-foot-item flex-center m-foot-item--images" :title="t('hostCard.imageCount')">
        <span class="footer-icon-wrap" v-html="vibrantIcons.images"></span>
        <strong>{{ host.image_count }}</strong>
      </div>
      <div class="m-foot-item flex-center m-foot-item--version" :title="`Docker ${host.docker_version || '-'}`">
        <span class="footer-icon-wrap docker-icon" v-html="vibrantIcons.docker"></span>
        <span class="m-version-text">
          {{ host.docker_version ? `v${host.docker_version}` : '-' }}
        </span>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import StatusIcon from "./StatusIcon.vue";
import type { HostSummary } from "@/stores/dashboard";

const props = defineProps<{ host: HostSummary; updateCount?: number }>();
defineEmits<{ click: []; updates: [] }>();

const { t } = useI18n();

const displayUpdateCount = computed(() => props.updateCount ?? props.host.update_count);
const hasError = computed(() => !!props.host.error_message);
const statusTone = computed(() => {
  if (props.host.status === "online") return "online";
  if (props.host.status === "degraded") return "degraded";
  if (props.host.status === "offline") return "offline";
  return "unknown";
});
const statusLabel = computed(() => {
  const keys: Record<string, string> = {
    online: "status.online",
    degraded: "status.degraded",
    offline: "status.offline",
    unknown: "status.unknown",
  };
  return t(keys[statusTone.value] as any);
});
const refreshIssueText = computed(() => (
  `${t("hostCard.refreshIssue" as any)}${props.host.error_message || ""}`
));

// Sparkline History Queues
const cpuHistory = ref<number[]>([]);
const netHistory = ref<number[]>([]);

watch(
  () => props.host.metrics,
  (m) => {
    if (m) {
      // Push CPU
      cpuHistory.value.push(m.cpuPercent);
      if (cpuHistory.value.length > 50) cpuHistory.value.shift();

      // Push Network total rate
      const netRate = (m.networkRxRate || 0) + (m.networkTxRate || 0);
      netHistory.value.push(netRate);
      if (netHistory.value.length > 50) netHistory.value.shift();
    }
  },
  { immediate: true, deep: true }
);

// Cardinal spline smoothing — produces flowing, natural curves
// (similar to D3's curveCardinal) instead of the stiff stepped bezier look
function generateSparkline(data: number[], width = 100, height = 24) {
  if (data.length < 2) return { stroke: "", fill: "" };
  const max = Math.max(...data, 10);
  const min = 0;
  const padX = 2; // horizontal padding so the curve doesn't hit the edge
  const padY = 3; // vertical breathing room

  const points = data.map((val, idx) => {
    const x = padX + (idx / (data.length - 1)) * (width - padX * 2);
    const y = padY + (height - padY * 2) * (1 - (val - min) / (max - min || 1));
    return { x, y };
  });

  // Cardinal spline tension — 0.5 gives a nice balance of smoothness without overshoot
  const tension = 0.5;
  let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;

  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];

    const cp1x = p1.x + (p2.x - p0.x) * tension / 3;
    const cp1y = p1.y + (p2.y - p0.y) * tension / 3;
    const cp2x = p2.x - (p3.x - p1.x) * tension / 3;
    const cp2y = p2.y - (p3.y - p1.y) * tension / 3;

    d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }

  const stroke = d;
  const fill = `${d} L ${width} ${height} L 0 ${height} Z`;
  return { stroke, fill };
}

const cpuPaths = computed(() => generateSparkline(cpuHistory.value, 100, 24));
const netPaths = computed(() => generateSparkline(netHistory.value, 100, 20));

const memPercent = computed(() => {
  const m = props.host.metrics;
  if (!m) return 0;
  return m.memoryTotal > 0 ? Math.round((m.memoryUsed / m.memoryTotal) * 100) : 0;
});

const diskPercent = computed(() => {
  const m = props.host.metrics;
  if (!m) return 0;
  return m.diskTotal > 0 ? Math.round((m.diskUsed / m.diskTotal) * 100) : 0;
});

function metricColor(pct: number): string {
  if (pct > 80) return "var(--danger)";
  if (pct > 60) return "var(--warning)";
  return "var(--success)";
}

function formatBytes(bytes: number | undefined): string {
  if (bytes == null) return "0 B";
  const value = Math.abs(bytes);
  if (value === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let size = value;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(1)} ${units[i]}`;
}

function formatRateParts(bytesPerSec: number | undefined): { amount: string; unit: string } {
  const bytes = Math.abs(bytesPerSec || 0);
  if (bytes === 0) return { amount: "0", unit: "B/s" };

  const units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return { amount: size.toFixed(1), unit: units[i] };
}

// Approved Vibrant Multi-color SVGs
const vibrantIcons = {
  cpu: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect width="16" height="16" x="4" y="4" rx="3" fill="#3b82f6" fill-opacity="0.12" stroke="#3b82f6"/>
          <rect width="8" height="8" x="8" y="8" rx="1" fill="#fbbf24" fill-opacity="0.7" stroke="#d97706"/>
          <line x1="9" y1="1" x2="9" y2="4" stroke="#3b82f6"/><line x1="15" y1="1" x2="15" y2="4" stroke="#3b82f6"/>
          <line x1="9" y1="20" x2="9" y2="23" stroke="#3b82f6"/><line x1="15" y1="20" x2="15" y2="23" stroke="#3b82f6"/>
        </svg>`,
  mem: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="6" width="18" height="12" rx="2" fill="#10b981" fill-opacity="0.12" stroke="#10b981"/>
          <rect x="6" y="9" width="3" height="6" rx="0.5" fill="#10b981" fill-opacity="0.8"/>
          <rect x="11" y="9" width="3" height="6" rx="0.5" fill="#10b981" fill-opacity="0.8"/>
          <rect x="16" y="9" width="3" height="6" rx="0.5" fill="#fbbf24" fill-opacity="0.8" stroke="#d97706" stroke-width="1"/>
        </svg>`,
  disk: `<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="4" y="4" width="16" height="16" rx="2" fill="#6366f1" fill-opacity="0.12" stroke="#6366f1"/>
          <path d="M4 10h16" stroke="#6366f1"/><path d="M4 14h16" stroke="#6366f1"/>
          <circle cx="8" cy="7" r="1.5" fill="#fbbf24"/><circle cx="16" cy="17" r="1.5" fill="#10b981"/>
        </svg>`,
  net: `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" fill="#06b6d4" fill-opacity="0.12" stroke="#06b6d4"/>
          <path d="M12 8v8M9 13l3 3 3-3" stroke="#06b6d4" stroke-width="2"/>
        </svg>`,
  io: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m21 16-4 4-4-4M17 20V4" stroke="#a855f7" stroke-width="2"/>
          <path opacity="0.4" d="M3 8l4-4 4 4M7 4v16" stroke="#a855f7"/>
        </svg>`,
  images: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="5" y="5" width="14" height="14" rx="2" fill="#6366f1" fill-opacity="0.12" stroke="#6366f1"/>
          <path d="M8 9h8M8 12h8M8 15h5" stroke="#6366f1"/>
        </svg>`,
  docker: `<svg xmlns="http://www.w3.org/2000/svg" width="15" height="12" viewBox="0 0 24 18" aria-hidden="true" focusable="false">
          <path fill="currentColor" d="M7.2 6.2h2.1V4.1H7.2v2.1Zm2.7 0H12V4.1H9.9v2.1Zm2.8 0h2.1V4.1h-2.1v2.1ZM9.9 3.5H12V1.4H9.9v2.1Zm-5.4 5h15.6c.9 0 1.7.3 2.4.9-.4 2.2-1.5 4-3.2 5.2-1.6 1.1-3.7 1.7-6.2 1.7H9.2c-3 0-5.2-1.1-6.5-3.2-.7-1.1-1-2.3-.9-3.7.8-.1 1.7-.4 2.7-.9Zm0-.6h2.1V5.8H4.5v2.1Zm2.7 0h2.1V5.8H7.2v2.1Zm2.7 0H12V5.8H9.9v2.1Zm2.8 0h2.1V5.8h-2.1v2.1Zm2.7 0h2.1V5.8h-2.1v2.1Z"/>
        </svg>`
};
</script>

<style scoped>
.host-card {
  font-family: var(--font-body) !important;

  /* Typography Variables Scoped locally to HostCard */
  --font-size-title: 19px;
  --font-size-data: 15px;
  --font-size-label: 13px;
  --font-size-micro: 11.5px;

  --weight-bold: 800;
  --weight-medium: 700;
  --weight-regular: 400;

  cursor: pointer;
  min-height: 286px;
  background: var(--host-card-bg) !important;
  border-color: var(--border-subtle) !important;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.host-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.host-card:hover {
  border-color: var(--border-strong) !important;
  transform: translateY(-2px);
  box-shadow: var(--host-card-hover-shadow) !important;
}

/* Header Row */
.card-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 26px;
}
.card-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.card-header-text {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.host-name {
  font-size: var(--font-size-title);
  font-weight: var(--weight-bold);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* Pills & Badges */
.m-badge-danger {
  font-size: var(--font-size-micro);
  color: var(--danger);
  background: rgba(248, 113, 113, 0.10);
  border: 1px solid rgba(248, 113, 113, 0.18);
  padding: 1px 8px;
  border-radius: 999px;
  font-weight: var(--weight-bold);
  white-space: nowrap;
}
.m-status-pill {
  font-size: var(--font-size-micro);
  padding: 1px 9px;
  border-radius: 999px;
  font-weight: var(--weight-bold);
  white-space: nowrap;
}

.m-status-pill.is-online {
  color: var(--success);
  border: 1px solid rgba(52, 211, 153, 0.24);
  background: rgba(52, 211, 153, 0.06);
}

.m-status-pill.is-degraded {
  color: var(--warning);
  border: 1px solid rgba(245, 158, 11, 0.26);
  background: rgba(245, 158, 11, 0.08);
}

.m-status-pill.is-offline {
  color: var(--danger);
  border: 1px solid rgba(248, 113, 113, 0.28);
  background: rgba(248, 113, 113, 0.08);
}

.m-status-pill.is-unknown {
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  background: var(--surface-muted);
}

.error-badge {
  display: inline-flex;
  align-items: center;
  cursor: help;
}

.error-badge.is-online,
.error-badge.is-degraded {
  color: var(--warning);
}

.error-badge.is-offline {
  color: var(--danger);
}

.error-badge.is-unknown {
  color: var(--text-muted);
}

.host-subtitle {
  font-size: var(--font-size-label);
  font-weight: var(--weight-regular);
  color: var(--text-muted);
  margin-top: 3px;
  margin-left: 18px;
  margin-bottom: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Capacity sub-cards */
.m-capacity-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 10px;
}
.m-sub-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
  min-height: 110px;
}
.m-sub-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.icon-wrapper {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.icon-wrapper :deep(svg) {
  width: 14px;
  height: 14px;
  display: block;
}
.icon-wrapper.cpu-color { background: rgba(59, 130, 246, 0.08); color: #3b82f6; }
.icon-wrapper.mem-color { background: rgba(16, 185, 129, 0.08); color: #10b981; }
.icon-wrapper.disk-color { background: rgba(99, 102, 241, 0.08); color: #6366f1; }

.sub-label {
  font-size: var(--font-size-label);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
}
.sub-value {
  font-size: var(--font-size-data);
  font-weight: var(--weight-bold);
  color: var(--text-primary);
  line-height: 1.25;
  display: flex;
  align-items: baseline;
  gap: 2px;
  margin-top: 3px;
}
.val-amount {
  width: 2.6em;
  display: inline-block;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: var(--weight-bold);
  color: var(--text-primary);
}
.val-unit {
  width: 1.5em;
  display: inline-block;
  text-align: right;
  font-weight: var(--weight-bold);
  color: var(--text-muted);
  font-size: var(--font-size-micro);
}
.sub-value small {
  font-size: var(--font-size-micro);
  font-weight: var(--weight-regular);
  color: var(--text-muted);
}

.m-progress-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: auto;
  margin-bottom: 2px;
}
.m-progress-track {
  flex: 1;
  height: 6px;
  background: rgba(148, 163, 184, 0.12);
  border-radius: 99px;
  overflow: hidden;
}
.m-progress-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}
.m-percent-label {
  font-size: var(--font-size-micro);
  font-weight: var(--weight-regular);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}

.sub-chart {
  position: absolute;
  bottom: 6px;
  left: 0;
  width: 100%;
  height: 32px;
}

/* Telemetry split panel */
.m-telemetry-box {
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  display: grid;
  grid-template-columns: minmax(0, 2.2fr) minmax(88px, 0.9fr) minmax(88px, 0.9fr);
  padding: 12px;
  margin-bottom: 12px;
  min-height: 110px;
}
.m-tel-col {
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
  min-width: 0;
  min-height: 86px;
}
.net-part {
  padding-right: 10px;
}
.io-part .m-tel-header {
  justify-content: center;
  padding-left: 0;
}
.io-part {
  justify-content: flex-start;
}
.m-tel-header {
  font-size: var(--font-size-label);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
}
.icon-wrapper-inline {
  width: 22px;
  height: 22px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.icon-wrapper-inline.net-color { background: rgba(6, 182, 212, 0.08); color: #06b6d4; }
.icon-wrapper-inline.io-color { background: rgba(168, 85, 247, 0.08); color: #a855f7; }
.icon-wrapper-inline :deep(svg) {
  width: 14px;
  height: 14px;
  display: block;
}
/* Network middle value row — fills space between header & bottom, vertically centered */
.m-net-values {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 0;
  padding-bottom: 22px;
  line-height: 1;
  position: relative;
  z-index: 1;
}
.m-net-rate-item {
  display: flex;
  align-items: baseline;
  gap: 2px;
  line-height: 1;
  white-space: nowrap;
}
.net-arrow {
  width: 14px;
  text-align: center;
  font-size: var(--font-size-data);
  font-weight: 900;
  flex-shrink: 0;
  line-height: 1;
}
.net-arrow.up   { color: #10b981; }
.net-arrow.down { color: #f59e0b; }
.net-amount {
  font-size: var(--font-size-data);
  line-height: 1;
  font-weight: var(--weight-bold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  display: inline-block;
}
.net-unit {
  font-size: var(--font-size-micro);
  line-height: 1;
  font-weight: var(--weight-regular);
  color: var(--text-muted);
  flex-shrink: 0;
  display: inline-block;
  margin-left: 2px;
}
.m-net-chart {
  position: absolute;
  bottom: 4px;
  left: 0;
  width: 100%;
  height: 24px;
}
.border-lr {
  border-left: 1px solid var(--border-subtle);
  border-right: 1px solid var(--border-subtle);
}
.text-center {
  text-align: center;
}
.flex-center {
  display: flex;
  align-items: center;
  justify-content: center;
}
/* I/O middle value row — fills space between header & bottom, vertically centered */
.m-io-value {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  margin-top: 0;
  padding-bottom: 0;
  line-height: 1;
  position: relative;
  z-index: 1;
}
.io-amount {
  font-size: var(--font-size-data);
  line-height: 1;
  font-weight: var(--weight-bold);
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  display: inline-block;
}
.io-unit {
  font-size: var(--font-size-micro);
  line-height: 1;
  font-weight: var(--weight-regular);
  color: var(--text-muted);
  flex-shrink: 0;
  display: inline-block;
  margin-left: 2px;
}

.metrics-missing {
  min-height: 96px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--border-subtle);
  border-radius: 8px;
  color: var(--text-muted);
  font-size: var(--font-size-label);
  font-weight: var(--weight-regular);
  margin-bottom: 16px;
}

/* Footer splits */
.m-footer {
  display: flex;
  border-top: 1px solid var(--border-subtle);
  padding-top: 9px;
  margin-top: auto;
  align-items: center;
}
.m-foot-item {
  flex: 1;
  font-size: var(--font-size-label);
  color: var(--text-primary);
  border-right: 1px solid var(--border-subtle);
  height: 18px;
  gap: 4px;
  min-width: 0;
}
.m-foot-item strong {
  font-size: var(--font-size-data);
  font-weight: var(--weight-bold);
  font-variant-numeric: tabular-nums;
}
.foot-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.foot-dot.green { background: var(--success); }
.foot-dot.red { background: var(--danger); }

.footer-icon-wrap :deep(svg) {
  width: 13px;
  height: 13px;
  display: block;
}
.docker-icon {
  color: #1d9bf0;
}
.docker-icon :deep(svg) {
  width: 15px;
  height: 12px;
}
.m-foot-item--version {
  flex: 1.5;
  border-right: none;
}
.m-version-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--font-size-micro);
  font-weight: var(--weight-bold);
  font-variant-numeric: tabular-nums;
  opacity: 0.82;
}

.font-bold { font-weight: var(--weight-bold); }
.text-right { text-align: right; }

@media (max-width: 420px) {
  .m-capacity-grid {
    grid-template-columns: 1fr;
  }
  .m-telemetry-box {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .border-lr {
    border-left: none;
    border-right: none;
    border-top: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
    padding: 8px 0;
  }
}
</style>

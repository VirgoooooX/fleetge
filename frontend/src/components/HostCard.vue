<template>
  <el-card class="host-card" shadow="never" @click="$emit('click')">
    <!-- Header: hostname / OS / update badge -->
    <div class="card-header">
      <div class="card-header-left">
        <StatusIcon :status="host.status" />
        <div class="card-header-text">
          <span class="host-name">{{ host.display_name }}</span>
          <span class="host-meta">{{ host.os_info || host.metrics?.hostname || host.host_id }}</span>
        </div>
      </div>
      <div class="card-header-right">
        <el-tooltip
          v-if="hasError"
          :content="host.error_message"
          placement="top"
          effect="dark"
        >
          <span class="error-badge">
            <el-icon :size="14"><Warning /></el-icon>
          </span>
        </el-tooltip>
        <button
          v-if="displayUpdateCount > 0"
          class="update-action"
          type="button"
          @click.stop="$emit('updates')"
        >
          {{ displayUpdateCount }} 更新
        </button>
      </div>
    </div>

    <!-- Capacity: CPU / memory / disk with progress bars -->
    <div v-if="host.metrics" class="capacity-grid">
      <div
        v-for="metric in capacityMetrics"
        :key="metric.label"
        class="capacity-metric"
        :style="{ '--metric-color': metric.color }"
      >
        <div class="metric-topline">
          <span class="metric-label">{{ metric.label }}</span>
          <span class="metric-value">{{ metric.value }}</span>
        </div>
        <div class="metric-track">
          <span class="metric-fill" :style="{ width: `${metric.percent}%` }" />
        </div>
      </div>
    </div>

    <!-- Telemetry: NET / I/O as text rates -->
    <div v-if="host.metrics" class="telemetry-grid">
      <div v-for="item in telemetry" :key="item.label" class="telemetry-item">
        <div class="telemetry-label-row">
          <span class="activity-dot" :class="item.level" />
          <span class="telemetry-label">{{ item.label }}</span>
        </div>
        <div class="telemetry-lines">
          <div v-for="line in item.lines" :key="line.label" class="telemetry-line">
            <span class="tl-label">{{ line.label }}</span>
            <span class="tl-value">
              <span class="tl-amount">{{ line.amount }}</span>
              <span class="tl-unit">{{ line.unit }}</span>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="metrics-missing">指标不可用</div>

    <!-- Footer: container counts / images / version -->
    <div class="card-footer">
      <div class="docker-stat strong" title="运行容器">
        <span class="stat-label" aria-label="运行容器">
          <span class="stat-icon running-dot" />
        </span>
        <strong class="stat-value">{{ host.container_running }}</strong>
      </div>
      <div class="docker-stat stopped" title="停止容器">
        <span class="stat-label" aria-label="停止容器">
          <span class="stat-icon stopped-dot" />
        </span>
        <strong class="stat-value">{{ host.container_stopped }}</strong>
      </div>
      <div class="docker-stat images" title="镜像数量">
        <span class="stat-label" aria-label="镜像数量">
          <el-icon :size="13"><Monitor /></el-icon>
        </span>
        <strong class="stat-value">{{ host.image_count }}</strong>
      </div>
      <div class="docker-stat version" :title="`Docker ${host.docker_version || '-'}`">
        <span class="stat-label docker-mark" aria-label="Docker 版本">
          <svg viewBox="0 0 24 18" aria-hidden="true" focusable="false">
            <path
              d="M7.2 6.2h2.1V4.1H7.2v2.1Zm2.7 0H12V4.1H9.9v2.1Zm2.8 0h2.1V4.1h-2.1v2.1ZM9.9 3.5H12V1.4H9.9v2.1Zm-5.5 5h15.7c.9 0 1.7.3 2.4.9-.4 2.2-1.5 4-3.2 5.2-1.6 1.1-3.7 1.7-6.2 1.7H9.2c-3 0-5.2-1.1-6.5-3.2-.7-1.1-1-2.3-.9-3.7.8-.1 1.6-.4 2.6-.9Zm.1-.6h2.1V5.8H4.5v2.1Zm2.7 0h2.1V5.8H7.2v2.1Zm2.7 0H12V5.8H9.9v2.1Zm2.8 0h2.1V5.8h-2.1v2.1Zm2.7 0h2.1V5.8h-2.1v2.1Z"
            />
          </svg>
        </span>
        <strong class="stat-value">{{ host.docker_version ? `v${host.docker_version}` : "-" }}</strong>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { Monitor, Warning } from "@element-plus/icons-vue";
import StatusIcon from "./StatusIcon.vue";
import type { HostSummary } from "@/stores/dashboard";

const props = defineProps<{ host: HostSummary; updateCount?: number }>();
defineEmits<{ click: []; updates: [] }>();

const displayUpdateCount = computed(() => props.updateCount ?? props.host.update_count);

const hasError = computed(() => !!props.host.error_message);
const isTimeout = computed(() => {
  const msg = props.host.error_message;
  return msg ? /(timeout|network|econnaborted)/i.test(msg) : false;
});

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

// ── Capacity: CPU / memory / disk with progress bars ───────────────────

const capacityMetrics = computed(() => {
  const m = props.host.metrics;
  if (!m) return [];

  const cpu = Math.round(m.cpuPercent);
  return [
    {
      label: "CPU",
      percent: cpu,
      value: `${m.cpuPercent.toFixed(1)}%`,
      color: metricColor(cpu),
    },
    {
      label: "内存",
      percent: memPercent.value,
      value: `${formatBytes(m.memoryUsed)} / ${formatBytes(m.memoryTotal)}`,
      color: metricColor(memPercent.value),
    },
    {
      label: "磁盘",
      percent: diskPercent.value,
      value: `${formatBytes(m.diskUsed)} / ${formatBytes(m.diskTotal)}`,
      color: metricColor(diskPercent.value),
    },
  ];
});

// ── Telemetry: NET / I/O rates without progress bars ───────────────────

function activityLevel(totalRate: number): string {
  if (totalRate >= 10 * 1024 * 1024) return "busy";
  if (totalRate >= 512 * 1024) return "active";
  if (totalRate > 0) return "low";
  return "idle";
}

const telemetry = computed(() => {
  const m = props.host.metrics;
  if (!m) return [];

  const netTotal = (m.networkRxRate || 0) + (m.networkTxRate || 0);
  const ioTotal = (m.diskReadRate || 0) + (m.diskWriteRate || 0);

  return [
    {
      label: "NET",
      level: activityLevel(netTotal),
      lines: [
        { label: "↓", ...formatRateParts(m.networkRxRate) },
        { label: "↑", ...formatRateParts(m.networkTxRate) },
      ],
    },
    {
      label: "I/O",
      level: activityLevel(ioTotal),
      lines: [
        { label: "R", ...formatRateParts(m.diskReadRate) },
        { label: "W", ...formatRateParts(m.diskWriteRate) },
      ],
    },
  ];
});

// ── Helpers ────────────────────────────────────────────────────────────

function metricColor(pct: number): string {
  if (pct > 80) return "#f56c6c";
  if (pct > 60) return "#e6a23c";
  return "#67c23a";
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
  return `${size.toFixed(1)}${units[i]}`;
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
</script>

<style scoped>
/* ── Card shell ──────────────────────────────────────────── */
.host-card {
  cursor: pointer;
  min-height: 238px;
  border-color: var(--border-subtle) !important;
  background: var(--host-card-bg) !important;
}
.host-card:hover {
  border-color: var(--border-strong) !important;
  transform: translateY(-1px);
  box-shadow: var(--host-card-hover-shadow);
}

/* ── Header ──────────────────────────────────────────────── */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 42px;
  margin-bottom: 14px;
}
.card-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.card-header-text {
  min-width: 0;
  flex: 1;
}
.host-name {
  display: block;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.host-meta {
  display: block;
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 12px;
  max-width: 250px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.update-action {
  flex: 0 0 auto;
  height: 26px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  border-radius: 6px;
  background: rgba(127, 29, 29, 0.24);
  color: var(--danger);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  padding: 0 9px;
}
.update-action:hover {
  background: rgba(248, 113, 113, 0.16);
  border-color: rgba(248, 113, 113, 0.58);
}

.card-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
}

.error-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: 1px solid rgba(248, 113, 113, 0.34);
  background: rgba(127, 29, 29, 0.24);
  color: var(--danger);
  cursor: help;
}

/* ── Capacity grid (CPU / 内存 / 磁盘) ──────────────────── */
.capacity-grid {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 102px;
  margin-bottom: 12px;
}
.capacity-metric {
  min-height: 26px;
}
.metric-topline {
  display: grid;
  grid-template-columns: auto 14ch;
  align-items: center;
  gap: 12px;
  margin-bottom: 5px;
}
.metric-label {
  font-size: 13px;
  color: var(--text-secondary);
}
.metric-value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--text-secondary);
  min-width: 14ch;
  text-align: right;
  white-space: nowrap;
}
.metric-track {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.14);
}
.metric-fill {
  display: block;
  height: 100%;
  min-width: 2px;
  border-radius: inherit;
  background: var(--metric-color);
  box-shadow: 0 0 16px color-mix(in srgb, var(--metric-color), transparent 45%);
}

/* ── Telemetry grid (NET / I/O, text rates only) ────────── */
.telemetry-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  min-height: 48px;
  margin-bottom: 12px;
}
.telemetry-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 44px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--surface-muted);
}
.telemetry-label-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.telemetry-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.activity-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.activity-dot.idle { background: var(--text-muted); }
.activity-dot.low { background: var(--accent-cyan); }
.activity-dot.active { background: var(--warning); }
.activity-dot.busy { background: var(--danger); }
.telemetry-lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.telemetry-line {
  display: grid;
  grid-template-columns: 14px max-content;
  justify-content: end;
  align-items: center;
  gap: 3px;
}
.tl-label {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  text-align: center;
  user-select: none;
}
.tl-value {
  display: grid;
  grid-template-columns: 6.5ch 4.4ch;
  justify-content: end;
  align-items: baseline;
  gap: 2px;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--text-primary);
  white-space: nowrap;
}
.tl-amount {
  min-width: 6.5ch;
  text-align: right;
}
.tl-unit {
  min-width: 4.4ch;
  color: var(--text-secondary);
  text-align: left;
}

/* ── Missing metrics placeholder ─────────────────────────── */
.metrics-missing {
  min-height: 102px;
  display: grid;
  place-items: center;
  border: 1px dashed var(--border-subtle);
  border-radius: 7px;
  color: var(--text-muted);
  font-size: 12px;
  margin-bottom: 14px;
}

/* ── Footer ──────────────────────────────────────────────── */
.card-footer {
  display: grid;
  grid-template-columns: 0.8fr 0.8fr 0.8fr 1.6fr;
  min-height: 30px;
  padding-top: 9px;
  border-top: 1px solid var(--border-subtle);
}
.docker-stat {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  min-height: 22px;
  padding: 0 6px;
  color: var(--text-secondary);
}
.docker-stat:not(:last-child) {
  border-right: 1px solid var(--border-subtle);
}
.stat-label {
  width: 14px;
  min-width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  color: var(--text-secondary);
  font-size: 10.5px;
  font-weight: 500;
  white-space: nowrap;
}
.stat-value {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  line-height: 1;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.docker-stat.strong .stat-value {
  color: var(--success);
}
.docker-stat.stopped .stat-value {
  color: var(--danger);
}
.docker-stat.version .stat-value {
  font-size: 11px;
}
.docker-mark svg {
  width: 15px;
  height: 12px;
  display: block;
  fill: currentColor;
}
.docker-stat.version .stat-label {
  color: #1d9bf0;
}
.running-dot, .stopped-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.running-dot { background: var(--el-color-success); }
.stopped-dot { background: var(--el-color-danger); }

/* ── Responsive ──────────────────────────────────────────── */
@media (max-width: 420px) {
  .telemetry-grid {
    grid-template-columns: 1fr;
  }
}
</style>

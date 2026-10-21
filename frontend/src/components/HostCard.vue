<template>
  <article
    class="host-card host-card-v1"
    :class="[`is-${host.status}`, { 'has-error': !!host.error_message }]"
    tabindex="0"
    :aria-label="`${host.display_name}，查看主机详情`"
    @keydown.enter.self.prevent="$emit('click')"
    @keydown.space.self.prevent="$emit('click')"
    @click="$emit('click')"
  >
    <!-- Top Header: Identity & Actionable Badges -->
    <header class="card-header">
      <div class="identity-left">
        <!-- 呼吸脉冲指示灯：表达在线/离线，在线时消除右侧胶囊冗余 -->
        <span class="status-pulse" :class="`is-${host.status}`" />
        <div class="title-group">
          <div class="name-row">
            <h3 class="host-name" :title="host.display_name">{{ host.display_name }}</h3>
            <span class="host-meta-badge">{{ host.os_info || host.architecture || 'Linux' }}</span>
          </div>
        </div>
      </div>

      <div class="badges-right">
        <!-- 待更新镜像徽标：矢量描边升级圆环，无 emoji，严格居中 -->
        <button
          v-if="displayUpdateCount > 0"
          type="button"
          class="badge-chip is-update"
          :title="t('hostCard.updates', { count: displayUpdateCount })"
          @click.stop="$emit('updates')"
        >
          <svg class="chip-svg" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10"/>
            <path d="m16 12-4-4-4 4"/>
            <path d="M12 16V8"/>
          </svg>
          <span class="chip-text">{{ displayUpdateCount }} {{ t('dashboard.updates') || '更新' }}</span>
        </button>

        <!-- 到期天数：远期弱化，临近到期逐级强调 -->
        <button
          v-if="effectiveExpiryDays != null"
          type="button"
          class="badge-chip is-expiry"
          :class="`expiry-${getExpiryTier(effectiveExpiryDays)}`"
          :title="effectiveSubscription?.service_expiry_date ? `到期日期：${effectiveSubscription.service_expiry_date} · 点击查看账单与续费详情` : '点击查看账单与续费详情'"
          @click.stop="$emit('open-bill')"
        >
          <svg class="chip-svg" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
          </svg>
          <span class="chip-text">{{ formatExpiryText(effectiveExpiryDays) }}</span>
        </button>

        <!-- 异常/离线时才突出状态胶囊（管理异常原则：正常在线时不堆砌胶囊） -->
        <span v-if="host.status !== 'online'" class="badge-chip status-alert-chip" :class="`is-${host.status}`">
          <span class="chip-text">{{ getStatusLabel(host.status) }}</span>
        </span>
      </div>
    </header>

    <!-- Normal Metrics Body -->
    <div v-if="host.metrics" class="card-body">
      <!-- 1. 无界三联算力微轨 -->
      <section class="compute-rail-group">
        <!-- CPU -->
        <div class="compute-rail-item">
          <div class="rail-top">
            <span class="rail-label">{{ t('hostCard.cpu') }}</span>
            <strong class="rail-val font-mono" :style="{ color: getMetricColor(cpuPercent, 95) }">
              {{ cpuPercent.toFixed(1) }}%
            </strong>
          </div>
          <div class="rail-track">
            <div
              class="rail-fill"
              :style="{ width: `${cpuPercent}%`, background: getMetricColor(cpuPercent, 95) }"
            />
          </div>
          <div class="rail-sub font-mono">
            <span>{{ host.metrics.loadavg?.[0] != null ? `Load ${host.metrics.loadavg[0].toFixed(2)}` : '标准算力' }}</span>
          </div>
        </div>

        <!-- 内存 -->
        <div class="compute-rail-item">
          <div class="rail-top">
            <span class="rail-label">{{ t('hostCard.memory') }}</span>
            <strong class="rail-val font-mono" :style="{ color: getMetricColor(memPercent) }">
              {{ memPercent }}%
            </strong>
          </div>
          <div class="rail-track">
            <div
              class="rail-fill"
              :style="{ width: `${memPercent}%`, background: getMetricColor(memPercent) }"
            />
          </div>
          <div class="rail-sub font-mono" :title="`${formatBytes(host.metrics.memoryUsed)} / ${formatBytes(host.metrics.memoryTotal)}`">
            {{ formatBytes(host.metrics.memoryUsed) }} / {{ formatBytes(host.metrics.memoryTotal) }}
          </div>
        </div>

        <!-- 磁盘 -->
        <div class="compute-rail-item">
          <div class="rail-top">
            <span class="rail-label">{{ t('hostCard.disk') }}</span>
            <strong class="rail-val font-mono" :style="{ color: getMetricColor(diskPercent) }">
              {{ diskPercent }}%
            </strong>
          </div>
          <div class="rail-track">
            <div
              class="rail-fill"
              :style="{ width: `${diskPercent}%`, background: getMetricColor(diskPercent) }"
            />
          </div>
          <div class="rail-sub font-mono" :title="`${formatBytes(host.metrics.diskUsed)} / ${formatBytes(host.metrics.diskTotal)}`">
            {{ formatBytes(host.metrics.diskUsed) }} / {{ formatBytes(host.metrics.diskTotal) }}
          </div>
        </div>
      </section>

      <!-- 2. 一体化 WAN 态势舱（两种模式：配额型 VPS vs 自由流量/本地设备） -->
      <section class="wan-capsule" :class="{ 'is-quota': hasQuota, 'is-unmetered': !hasQuota }">
        <!-- 顶栏：左侧标题，右侧实时网速仪表槽（以 /s 为右贴齐锚点，零像素抖动） -->
        <div class="capsule-header">
          <div class="capsule-title">
            <svg class="capsule-globe-icon" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <span>{{ hasQuota ? 'WAN 流量与配额' : '网络流量' }}</span>
          </div>

          <!-- 右侧实时网速：位置绝对锚定 + 微定向指示灯（8槽固定列宽，零像素水平抖动） -->
          <div
            class="stream-anchored font-mono"
            :title="`实时下行: ${formatRate(host.metrics?.networkRxRate)} | 实时上行: ${formatRate(host.metrics?.networkTxRate)}`"
          >
            <!-- 锚定槽 1: 实时标签（绝不漂移） -->
            <span class="anchored-label">
              <span class="label-text">实时</span>
            </span>

            <!-- 锚定槽 2: 下行箭头指示 -->
            <span class="col-indicator rx">
              <span class="indicator-glyph">↓</span>
            </span>

            <!-- 锚定槽 3: 下行数值（固定右对齐） -->
            <span class="col-num rx">{{ splitRate(host.metrics?.networkRxRate).val }}</span>

            <!-- 锚定槽 4: 下行单位（固定左对齐） -->
            <span class="col-unit rx">{{ splitRate(host.metrics?.networkRxRate).unit }}</span>

            <!-- 锚定槽 5: 中缝分隔符（居中锚定） -->
            <span class="speed-sep">·</span>

            <!-- 锚定槽 6: 上行箭头指示 -->
            <span class="col-indicator tx">
              <span class="indicator-glyph">↑</span>
            </span>

            <!-- 锚定槽 7: 上行数值（固定右对齐） -->
            <span class="col-num tx">{{ splitRate(host.metrics?.networkTxRate).val }}</span>

            <!-- 锚定槽 8: 上行单位（固定左对齐） -->
            <span class="col-unit tx">{{ splitRate(host.metrics?.networkTxRate).unit }}</span>
          </div>
        </div>

        <!-- 配额型 VPS 水位轨 (仅在有配额时展示) -->
        <div v-if="hasQuota" class="capsule-quota-rail">
          <div class="quota-rail-info font-mono">
            <span class="quota-ratio">已用 {{ formatBytes(quotaUsedBytes) }} / {{ formatBytes(quotaTotalBytes) }} · {{ quotaUsagePercent }}%</span>
            <span
              class="quota-remain"
              :class="{
                'is-warn': quotaUsagePercent >= 70 && quotaUsagePercent < 85,
                'is-danger': quotaUsagePercent >= 85
              }"
            >
              剩余 {{ formatBytes(quotaRemainingBytes) }}
            </span>
          </div>
          <div class="capsule-progress-track">
            <div
              class="capsule-progress-fill"
              :style="{
                width: `${Math.min(100, quotaUsagePercent)}%`,
                minWidth: quotaUsedBytes > 0 ? '4.5px' : '0',
                background: getQuotaColor(quotaUsagePercent)
              }"
            />
          </div>
        </div>

        <!-- 流量矩阵：本期/本月 与 今日 (下方总流量 100% 保持原有鲜明色彩) -->
        <div class="capsule-traffic-matrix">
          <!-- 行 1: 本期 / 本月流量 -->
          <div class="traffic-row">
            <div class="traffic-row-left">
              <span class="scope-label">{{ hasQuota ? '本期：' : '本月：' }}</span>
              <span class="total-vol-slot font-mono">
                <strong class="total-num">{{ splitBytes(hasQuota ? quotaUsedBytes : effectiveTrafficMonthTotal).val }}</strong>
                <span class="total-unit">{{ splitBytes(hasQuota ? quotaUsedBytes : effectiveTrafficMonthTotal).unit }}</span>
              </span>
              <template v-if="hasQuota">
                <span class="meta-dot">·</span>
                <span class="reset-tag">{{ effectiveNextResetText }}</span>
              </template>
            </div>

            <!-- 本期/本月双通道：去掉重复箭头，槽位完全继承顶栏，单位以中缝为基准右对齐 -->
            <div class="traffic-row-right stream-columns font-mono">
              <span class="col-indicator rx" />
              <span class="col-num rx">{{ splitBytes(effectiveTrafficMonthRx).val }}</span>
              <span class="col-unit rx">{{ splitBytes(effectiveTrafficMonthRx).unit }}</span>
              <span class="col-sep">│</span>
              <span class="col-indicator tx" />
              <span class="col-num tx">{{ splitBytes(effectiveTrafficMonthTx).val }}</span>
              <span class="col-unit tx">{{ splitBytes(effectiveTrafficMonthTx).unit }}</span>
            </div>
          </div>

          <!-- 行 2: 今日流量 -->
          <div class="traffic-row">
            <div class="traffic-row-left">
              <span class="scope-label">今日：</span>
              <span class="total-vol-slot font-mono">
                <strong class="total-num">{{ splitBytes(effectiveTrafficTodayTotal).val }}</strong>
                <span class="total-unit">{{ splitBytes(effectiveTrafficTodayTotal).unit }}</span>
              </span>
            </div>

            <!-- 今日双通道：与上面完全相同的槽位定义，去箭头，中缝线绝对对齐 -->
            <div class="traffic-row-right stream-columns font-mono">
              <span class="col-indicator rx" />
              <span class="col-num rx">{{ splitBytes(effectiveTrafficTodayRx).val }}</span>
              <span class="col-unit rx">{{ splitBytes(effectiveTrafficTodayRx).unit }}</span>
              <span class="col-sep">│</span>
              <span class="col-indicator tx" />
              <span class="col-num tx">{{ splitBytes(effectiveTrafficTodayTx).val }}</span>
              <span class="col-unit tx">{{ splitBytes(effectiveTrafficTodayTx).unit }}</span>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 离线/异常退化兜底 -->
    <div v-else class="card-fallback">
      <div class="fallback-icon-wrap">
        <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
      </div>
      <div class="fallback-info">
        <p class="fallback-title">{{ host.error_message || t('hostCard.metricsUnavailable') }}</p>
        <span class="fallback-desc">Agent 正在重连或网络策略未放行端口</span>
      </div>
    </div>

    <!-- Bottom Footer: Workload Capsule & Subscription Price Trigger -->
    <footer class="card-footer">
      <div class="footer-left">
        <!-- 容器状态胶囊 -->
        <div class="workload-capsule" :class="{ 'has-stopped': host.container_stopped > 0 }">
          <span class="dot-indicator" :class="host.container_stopped > 0 ? 'is-warn' : 'is-good'" />
          <span class="workload-text">
            <strong>{{ host.container_running }}</strong> {{ t('dashboard.running') || '运行' }}
            <template v-if="host.container_stopped > 0">
              · <strong class="text-warn">{{ host.container_stopped }}</strong> {{ t('dashboard.stopped') || '停止' }}
            </template>
          </span>
        </div>

        <!-- 引擎标识 -->
        <span class="docker-tag" :title="`Docker Engine ${host.docker_version || '-'}`">
          <svg class="docker-whale-svg" viewBox="0 0 24 18" aria-hidden="true" focusable="false">
            <path fill="currentColor" d="M7.2 6.2h2.1V4.1H7.2v2.1Zm2.7 0H12V4.1H9.9v2.1Zm2.8 0h2.1V4.1h-2.1v2.1ZM9.9 3.5H12V1.4H9.9v2.1Zm-5.4 5h15.6c.9 0 1.7.3 2.4.9-.4 2.2-1.5 4-3.2 5.2-1.6 1.1-3.7 1.7-6.2 1.7H9.2c-3 0-5.2-1.1-6.5-3.2-.7-1.1-1-2.3-.9-3.7.8-.1 1.7-.4 2.7-.9Zm0-.6h2.1V5.8H4.5v2.1Zm2.7 0h2.1V5.8H7.2v2.1Zm2.7 0H12V5.8H9.9v2.1Zm2.8 0h2.1V5.8h-2.1v2.1Zm2.7 0h2.1V5.8h-2.1v2.1Z"/>
          </svg>
          <span>v{{ host.docker_version || '28.0' }}</span>
        </span>
      </div>

      <!-- 资费触发按钮（点击打开套餐弹窗） -->
      <button
        v-if="effectivePriceText"
        type="button"
        class="price-trigger-btn font-mono"
        title="点击查看资费与账单明细"
        @click.stop="$emit('open-bill')"
      >
        <span>{{ effectivePriceText }}</span>
        <svg class="trigger-arrow" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"/>
        </svg>
      </button>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { HostSummary, HostTrafficState, HostSubscriptionSummary } from "@/stores/dashboard";

import { formatBytes } from "@/utils/formatBytes";

const props = defineProps<{
  host: HostSummary;
  updateCount?: number;
  traffic?: HostTrafficState;
  subscription?: HostSubscriptionSummary | null;
  quota?: {
    usedBytes?: number;
    quotaBytes?: number;
    remainingBytes?: number;
    usagePercent?: number;
    nextResetText?: string;
    rxBytes?: number;
    txBytes?: number;
  };
}>();

const emit = defineEmits<{
  (e: "click"): void;
  (e: "updates"): void;
  (e: "open-bill"): void;
}>();

const { t } = useI18n();

const displayUpdateCount = computed(() => {
  return props.updateCount ?? props.host.update_count ?? 0;
});

const effectiveSubscription = computed(() => {
  return props.subscription ?? props.host.subscription;
});

const effectiveExpiryDays = computed(() => {
  return effectiveSubscription.value?.service_days_remaining;
});

const effectiveTrafficMonthTotal = computed(() => {
  if (hasQuota.value && (props.quota?.usedBytes != null || props.traffic?.summary?.quota?.usedBytes != null)) {
    return props.quota?.usedBytes ?? props.traffic?.summary?.quota?.usedBytes ?? 0;
  }
  return props.traffic?.summary?.month?.totalBytes ?? 0;
});

const effectiveTrafficMonthRx = computed(() => {
  if (hasQuota.value && (props.quota?.rxBytes != null || props.traffic?.summary?.quota?.rxBytes != null)) {
    return props.quota?.rxBytes ?? props.traffic?.summary?.quota?.rxBytes ?? 0;
  }
  return props.traffic?.summary?.month?.rxBytes ?? 0;
});

const effectiveTrafficMonthTx = computed(() => {
  if (hasQuota.value && (props.quota?.txBytes != null || props.traffic?.summary?.quota?.txBytes != null)) {
    return props.quota?.txBytes ?? props.traffic?.summary?.quota?.txBytes ?? 0;
  }
  return props.traffic?.summary?.month?.txBytes ?? 0;
});

const effectiveTrafficTodayTotal = computed(() => {
  return props.traffic?.summary?.today?.totalBytes ?? 0;
});

const effectiveTrafficTodayRx = computed(() => {
  return props.traffic?.summary?.today?.rxBytes ?? 0;
});

const effectiveTrafficTodayTx = computed(() => {
  return props.traffic?.summary?.today?.txBytes ?? 0;
});

const hasQuota = computed(() => {
  if (props.quota?.quotaBytes) return true;
  if (props.traffic?.summary?.quota?.quotaBytes) return true;
  const sub = effectiveSubscription.value;
  if (sub?.quota_enabled && (sub.traffic_quota_bytes || sub.traffic_quota_value)) return true;
  return false;
});

const quotaTotalBytes = computed(() => {
  if (props.quota?.quotaBytes) return props.quota.quotaBytes;
  if (props.traffic?.summary?.quota?.quotaBytes) return props.traffic.summary.quota.quotaBytes;
  return effectiveSubscription.value?.traffic_quota_bytes ?? 0;
});

const quotaUsedBytes = computed(() => {
  if (props.quota?.usedBytes != null) return props.quota.usedBytes;
  if (props.traffic?.summary?.quota?.usedBytes != null) return props.traffic.summary.quota.usedBytes;
  return effectiveTrafficMonthTotal.value;
});

const quotaRemainingBytes = computed(() => {
  if (props.quota?.remainingBytes != null) return props.quota.remainingBytes;
  if (props.traffic?.summary?.quota?.remainingBytes != null) return props.traffic.summary.quota.remainingBytes;
  return Math.max(0, quotaTotalBytes.value - quotaUsedBytes.value);
});

const quotaUsagePercent = computed(() => {
  if (props.quota?.usagePercent != null) return props.quota.usagePercent;
  if (props.traffic?.summary?.quota?.usagePercent != null) return props.traffic.summary.quota.usagePercent;
  if (!quotaTotalBytes.value) return 0;
  return Math.round((quotaUsedBytes.value / quotaTotalBytes.value) * 1000) / 10;
});

const effectivePriceText = computed(() => {
  const sub = effectiveSubscription.value;
  if (!sub || sub.payment_amount == null) return "";
  return formatPrice(sub.payment_amount, sub.currency || "CNY", sub.payment_cycle || "annual");
});

const cpuPercent = computed(() => {
  return props.host.metrics ? Math.min(100, Math.max(0, props.host.metrics.cpuPercent)) : 0;
});

const memPercent = computed(() => {
  const m = props.host.metrics;
  if (!m || !m.memoryTotal) return 0;
  return Math.min(100, Math.round((m.memoryUsed / m.memoryTotal) * 100));
});

const diskPercent = computed(() => {
  const m = props.host.metrics;
  if (!m || !m.diskTotal) return 0;
  return Math.min(100, Math.round((m.diskUsed / m.diskTotal) * 100));
});

function getMetricColor(pct: number, dangerThreshold = 90): string {
  if (pct >= dangerThreshold) return "var(--danger, #f87171)";
  if (pct >= 80) return "#f59e0b";
  return "var(--accent-blue, #60a5fa)";
}

function getQuotaColor(pct: number): string {
  if (pct >= 85) return "var(--quota-danger-grad)";
  if (pct >= 70) return "var(--quota-warn-grad)";
  return "var(--quota-healthy-grad)";
}

function getExpiryTier(days?: number): "safe" | "notice" | "warn" | "urgent" | "critical" {
  if (days == null) return "safe";
  if (days <= 0) return "critical";
  if (days <= 7) return "urgent";
  if (days <= 14) return "warn";
  if (days <= 30) return "notice";
  return "safe";
}

function formatExpiryText(days?: number): string {
  if (days == null) return "";
  if (days < 0) return `已逾期 ${Math.abs(days)} 天`;
  if (days === 0) return "今日到期";
  return `${days} 天到期`;
}

function getStatusLabel(status: string): string {
  const map: Record<string, string> = {
    online: t("status.online") || "在线",
    degraded: t("status.degraded") || "异常",
    offline: t("status.offline") || "离线",
    unknown: t("status.unknown") || "未知",
  };
  return map[status] || status;
}

const effectiveNextResetText = computed(() => {
  const q: any = props.quota || props.traffic?.summary?.quota;
  if (q?.nextResetText) return q.nextResetText;
  if (q?.nextResetAt) {
    try {
      const d = new Date(q.nextResetAt);
      if (!isNaN(d.getTime())) {
        return `${d.getMonth() + 1}月${d.getDate()}日重置`;
      }
    } catch {}
  }
  return `每月 ${props.host.traffic_billing_day || 1} 日重置`;
});

function formatRate(bytesPerSec?: number | null): string {
  const b = Math.abs(bytesPerSec || 0);
  if (b === 0) return "0 B/s";
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let i = 0;
  let val = b;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

function splitBytes(bytes?: number | null): { val: string; unit: string } {
  if (bytes == null || isNaN(bytes) || bytes === 0) return { val: "0", unit: "B" };
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return {
    val: val < 10 ? val.toFixed(1) : Math.round(val).toString(),
    unit: units[i]
  };
}

function splitRate(bytesPerSec?: number | null): { val: string; unit: string } {
  const b = Math.abs(bytesPerSec || 0);
  if (b === 0) return { val: "0", unit: "B/s" };
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let i = 0;
  let val = b;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return {
    val: val < 10 ? val.toFixed(1) : Math.round(val).toString(),
    unit: units[i]
  };
}

function formatPrice(amount?: number, currency = "CNY", cycle = "annual"): string {
  if (amount == null) return "";
  const sym = currency === "USD" ? "$" : currency === "EUR" ? "€" : "¥";
  const cycleMap: Record<string, string> = {
    monthly: "月",
    quarterly: "季",
    semiannual: "半年",
    annual: "年",
    once: "次",
  };
  // 保留小数显示（如 49.9、49.99），整数则展示整数（如 52），绝不截断进位
  const formattedAmount = Number.isInteger(amount)
    ? amount.toString()
    : parseFloat(amount.toFixed(2)).toString();
  return `${sym}${formattedAmount} / ${cycleMap[cycle] || "年"}`;
}
</script>

<style scoped>
.host-card-v1 {
  display: flex;
  flex-direction: column;
  min-height: 220px;
  padding: 15px 16px;
  box-sizing: border-box;
  background: var(--surface-panel, #0b1220);
  border: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.16));
  border-radius: 12px;
  cursor: pointer;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.host-card-v1:hover {
  transform: translateY(-2px);
  border-color: rgba(96, 165, 250, 0.35);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.3);
}

.host-card-v1:focus-visible,
.badge-chip:focus-visible,
.price-trigger-btn:focus-visible {
  outline: 2px solid var(--accent-blue, #60a5fa);
  outline-offset: 2px;
}

/* 顶部身份栏 */
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.identity-left {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.status-pulse {
  width: 8.5px;
  height: 8.5px;
  border-radius: 50%;
  flex-shrink: 0;
  position: relative;
}
.status-pulse.is-online {
  background: var(--success, #34d399);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2);
}
.status-pulse.is-degraded {
  background: var(--warning, #fbbf24);
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.2);
}
.status-pulse.is-offline {
  background: var(--danger, #f87171);
}
.status-pulse.is-unknown {
  background: var(--text-muted, #64748b);
}

.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.host-name {
  margin: 0;
  font-size: 17.5px;
  font-weight: 700;
  color: var(--text-primary, #f1f5f9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.host-meta-badge {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.badges-right {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
}

/* 徽标胶囊基准：严格重设，无内外边距偏移，保证在所有浏览器下像素级居中 */
.badge-chip {
  appearance: none;
  -webkit-appearance: none;
  margin: 0;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  font-family: inherit;
  font-size: 12px;
  height: 24px;
  padding: 0 9px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  cursor: pointer;
  font-weight: 600;
  line-height: 1;
  transition: all 0.15s ease;
  white-space: nowrap;
  vertical-align: middle;
}

.chip-svg {
  display: block;
  width: 13px;
  height: 13px;
  flex-shrink: 0;
}

/* 图标与文字行框沿同一中心线对齐。 */
.chip-text {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  letter-spacing: 0.01em;
}

/* 待更新镜像徽标 (Update Chip) */
.badge-chip.is-update {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.32);
  color: var(--warning, #fbbf24);
}
.badge-chip.is-update:hover {
  background: rgba(245, 158, 11, 0.18);
  border-color: rgba(245, 158, 11, 0.45);
}
[data-theme="light"] .badge-chip.is-update {
  background: rgba(245, 158, 11, 0.1);
  border-color: rgba(245, 158, 11, 0.38);
  color: #d97706;
}

/* 到期五级色彩梯次 (Expiry 5-tier Gradation) */
/* Tier 1: 充裕安全 (> 30 天) - 中性弱标签 */
.badge-chip.is-expiry.expiry-safe {
  background: rgba(148, 163, 184, 0.06);
  border-color: var(--border-subtle, rgba(148, 163, 184, 0.16));
  color: var(--text-secondary, #94a3b8);
}

/* Tier 2: 月度例行 (15 ~ 30 天) - 典雅微紫靛蓝 */
.badge-chip.is-expiry.expiry-notice {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.25);
  color: #818cf8;
}
[data-theme="light"] .badge-chip.is-expiry.expiry-notice {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.28);
  color: #4f46e5;
}

/* Tier 3: 关注提醒 (8 ~ 14 天) - 温暖琥珀黄 */
.badge-chip.is-expiry.expiry-warn {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.32);
  color: #fbbf24;
}
[data-theme="light"] .badge-chip.is-expiry.expiry-warn {
  background: rgba(245, 158, 11, 0.12);
  border-color: rgba(245, 158, 11, 0.4);
  color: #b45309;
}

/* Tier 4: 临近紧迫 (1 ~ 7 天) - 警示急迫橙红 */
.badge-chip.is-expiry.expiry-urgent {
  background: rgba(249, 115, 22, 0.15);
  border-color: rgba(249, 115, 22, 0.4);
  color: #fb923c;
  font-weight: 700;
}
[data-theme="light"] .badge-chip.is-expiry.expiry-urgent {
  background: rgba(249, 115, 22, 0.12);
  border-color: rgba(249, 115, 22, 0.45);
  color: #c2410c;
}

/* Tier 5: 临界/已逾期 (<= 0 天) - 珊瑚红高亮脉冲 */
.badge-chip.is-expiry.expiry-critical {
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.5);
  color: #f87171;
  font-weight: 750;
  animation: expiry-pulse 2s infinite ease-in-out;
}
[data-theme="light"] .badge-chip.is-expiry.expiry-critical {
  background: rgba(220, 38, 38, 0.12);
  border-color: rgba(220, 38, 38, 0.5);
  color: #b91c1c;
}

@keyframes expiry-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.85; transform: scale(1.02); }
}

/* 异常状态芯片 (Status Alert Chip) */
.status-alert-chip.is-degraded {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.32);
  color: var(--warning, #fbbf24);
}
.status-alert-chip.is-offline {
  background: rgba(248, 113, 113, 0.12);
  border-color: rgba(248, 113, 113, 0.35);
  color: var(--danger, #f87171);
}

/* 算力三联微轨 */
.compute-rail-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.compute-rail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.rail-label {
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}

.rail-val {
  font-size: 14.5px;
  font-weight: 700;
}

.rail-track {
  width: 100%;
  height: 4px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
}

.rail-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}

.rail-sub {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 一体化 WAN 态势舱 */
.wan-capsule {
  --quota-healthy-grad: linear-gradient(90deg, #10b981, #22d3ee);
  --quota-warn-grad: linear-gradient(90deg, #f59e0b, #fbbf24);
  --quota-danger-grad: linear-gradient(90deg, #f87171, #ef4444);
  background: rgba(148, 163, 184, 0.04);
  border: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.12));
  border-radius: 8px;
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.capsule-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.capsule-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}
.capsule-globe-icon {
  display: block;
  flex-shrink: 0;
  color: var(--accent-cyan, #22d3ee);
  width: 14px;
  height: 14px;
}

/* 统一双通道流矩阵（顶栏独占箭头，下方两行去箭头，中缝线绝对贯通） */
.stream-columns {
  display: inline-grid;
  grid-template-columns: 11px 36px 30px 14px 11px 36px 30px;
  align-items: center;
  font-size: 12px;
}

/* ── 核心：绝对位置锚定流矩阵 (Strictly Anchored Stream Grid) ── */
/* 8 槽固定列宽：
   col 1: 实时标签 (38px, 左对齐，严丝合缝)
   col 2: 下行箭头 (12px, 居中)
   col 3: 下行数值 (38px, 右对齐 tabular-nums)
   col 4: 下行单位 (30px, 左对齐)
   col 5: 隔离中点 (10px, 居中)
   col 6: 上行箭头 (12px, 居中)
   col 7: 上行数值 (38px, 右对齐 tabular-nums)
   col 8: 上行单位 (30px, 左对齐)
   总宽度固定 208px，右侧贴齐，左侧坐标绝对锁死，0 像素水平抖动！
*/
.stream-anchored {
  display: inline-grid;
  grid-template-columns: 38px 12px 38px 30px 10px 12px 38px 30px;
  align-items: center;
  justify-items: stretch;
  width: 208px;
  user-select: none;
}

.stream-anchored .anchored-label {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted, #94a3b8);
  white-space: nowrap;
}

.stream-anchored .col-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.stream-anchored .indicator-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  font-size: 10px;
  line-height: 1;
}

.stream-anchored .col-indicator.rx .indicator-glyph {
  background: rgba(34, 211, 238, 0.12);
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-indicator.tx .indicator-glyph {
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  font-size: 12.5px;
}
.stream-anchored .col-num.rx {
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-num.tx {
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .col-unit {
  text-align: left;
  padding-left: 2px;
  font-size: 11px;
  opacity: 0.85;
}
.stream-anchored .col-unit.rx {
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-unit.tx {
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .speed-sep {
  text-align: center;
  opacity: 0.35;
  color: var(--text-muted, #94a3b8);
  font-size: 11px;
}

/* 浅色模式适配 */
[data-theme="light"] .stream-anchored .col-num.rx,
[data-theme="light"] .stream-anchored .col-unit.rx {
  color: #0a6c82;
}
[data-theme="light"] .stream-anchored .col-num.tx,
[data-theme="light"] .stream-anchored .col-unit.tx {
  color: #2563eb;
}
[data-theme="light"] .stream-anchored .col-indicator.rx .indicator-glyph {
  background: rgba(10, 108, 130, 0.1);
  color: #0a6c82;
}
[data-theme="light"] .stream-anchored .col-indicator.tx .indicator-glyph {
  background: rgba(37, 99, 235, 0.1);
  color: #2563eb;
}

.col-indicator {
  text-align: center;
  font-weight: 700;
  line-height: 1;
}
.col-indicator.rx { color: var(--accent-cyan, #22d3ee); }
.col-indicator.tx { color: var(--accent-blue, #60a5fa); }

.col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.capsule-header .col-num.rx { color: var(--accent-cyan, #22d3ee); }
.capsule-header .col-num.tx { color: var(--accent-blue, #60a5fa); }

/* 下方行如果染色：采用微柔和或全染测试 */
.traffic-row-right .col-num.rx { color: var(--accent-cyan, #22d3ee); }
.traffic-row-right .col-num.tx { color: var(--accent-blue, #60a5fa); }

.col-unit {
  text-align: right; /* 统一右对齐：顶栏 /s 贴右，下方 B 贴右 */
  font-size: 11.5px;
  color: var(--text-muted, #94a3b8);
}
.capsule-header .col-unit.rx { color: var(--accent-cyan, #22d3ee); opacity: 0.85; }
.capsule-header .col-unit.tx { color: var(--accent-blue, #60a5fa); opacity: 0.85; }
.traffic-row-right .col-unit.rx { color: var(--accent-cyan, #22d3ee); opacity: 0.75; }
.traffic-row-right .col-unit.tx { color: var(--accent-blue, #60a5fa); opacity: 0.75; }

.col-sep {
  text-align: center;
  color: var(--border-subtle, rgba(148, 163, 184, 0.35));
  font-size: 11px;
  line-height: 1;
}

/* 配额水位轨 */
.capsule-quota-rail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quota-rail-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.quota-remain.is-warn {
  color: var(--warning, #fbbf24);
  font-weight: 600;
}

.quota-remain.is-danger {
  color: var(--danger, #f87171);
  font-weight: 700;
}

.capsule-progress-track {
  width: 100%;
  height: 4.5px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
}

.capsule-progress-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), background 0.4s ease;
}

/* 流量矩阵 */
.capsule-traffic-matrix {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.traffic-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 18px;
  font-size: 12px;
}

/* 按字形的大写高度裁去上下留白，再对齐中英文的可见中心。 */
.traffic-row :is(.scope-label, .total-num, .total-unit, .reset-tag, .col-num, .col-unit) {
  text-box: trim-both cap alphabetic;
}

.traffic-row .scope-label {
  transform: translateY(0.75px);
}

.traffic-row :is(.total-num, .reset-tag, .col-num) {
  transform: translateY(0.5px);
}

.traffic-row-left {
  display: inline-flex;
  align-items: center;
  color: var(--text-muted, #64748b);
}

.scope-label {
  display: inline-block;
  width: 42px;
  color: var(--text-secondary, #94a3b8);
  font-weight: 500;
}

.total-vol-slot {
  display: inline-flex;
  align-items: center;
}

.total-num {
  min-width: 30px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.total-unit {
  width: 24px;
  text-align: right; /* "B" 严格右对齐锚定 */
  font-size: 11.5px;
  color: var(--text-muted, #94a3b8);
  margin-left: 2px;
}

.meta-dot {
  margin: 0 4px;
  opacity: 0.45;
}

.reset-tag {
  color: var(--text-muted, #64748b);
  font-size: 11.5px;
}

[data-theme="light"] .wan-capsule {
  --quota-healthy-grad: linear-gradient(90deg, #059669, #0891b2);
  --quota-warn-grad: linear-gradient(90deg, #d97706, #f59e0b);
  --quota-danger-grad: linear-gradient(90deg, #dc2626, #ef4444);
}

[data-theme="light"] .capsule-globe-icon {
  color: #0a6c82;
}
[data-theme="light"] .total-num,
[data-theme="light"] .col-num {
  color: #0f172a;
}
[data-theme="light"] .col-indicator.rx,
[data-theme="light"] .capsule-header .col-num.rx,
[data-theme="light"] .traffic-row-right .col-num.rx {
  color: #0a6c82;
  font-weight: 700;
}
[data-theme="light"] .capsule-header .col-unit.rx,
[data-theme="light"] .traffic-row-right .col-unit.rx {
  color: #0a6c82;
  opacity: 1;
  font-weight: 600;
}
[data-theme="light"] .col-indicator.tx,
[data-theme="light"] .capsule-header .col-num.tx,
[data-theme="light"] .traffic-row-right .col-num.tx {
  color: #1d4ed8;
  font-weight: 700;
}
[data-theme="light"] .capsule-header .col-unit.tx,
[data-theme="light"] .traffic-row-right .col-unit.tx {
  color: #1d4ed8;
  opacity: 1;
  font-weight: 600;
}

/* 兜底状态 */
.card-fallback {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px 14px;
  background: rgba(248, 113, 113, 0.04);
  border: 1px dashed rgba(248, 113, 113, 0.2);
  border-radius: 8px;
  margin-bottom: 12px;
}
.fallback-icon-wrap {
  color: var(--danger, #f87171);
}
.fallback-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}
.fallback-desc {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

/* 底部栏 */
.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.1));
  padding-top: 8px;
  margin-top: auto;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.workload-capsule {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
  padding: 2.5px 8px;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.06);
}
.workload-capsule.has-stopped {
  background: rgba(251, 191, 36, 0.1);
  color: var(--warning, #fbbf24);
}

.dot-indicator {
  width: 6.5px;
  height: 6.5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.dot-indicator.is-good {
  background: var(--success, #34d399);
}
.dot-indicator.is-warn {
  background: var(--warning, #fbbf24);
}

.text-warn {
  color: var(--warning, #fbbf24);
}

.docker-tag {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}
.docker-whale-svg {
  width: 15px;
  height: 12px;
  color: var(--accent-cyan, #22d3ee);
}

.price-trigger-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary, #94a3b8);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2.5px 7px;
  border-radius: 4px;
  transition: all 0.15s ease;
}
.price-trigger-btn:hover {
  color: var(--accent-blue, #60a5fa);
  background: rgba(96, 165, 250, 0.1);
}

.trigger-arrow {
  width: 13px;
  height: 13px;
  opacity: 0.6;
  transition: transform 0.15s;
}
.price-trigger-btn:hover .trigger-arrow {
  transform: translateX(2px);
  opacity: 1;
}

/* Light Mode Overrides */
[data-theme="light"] .host-card-v1 {
  background: #ffffff;
  border-color: rgba(203, 213, 225, 0.8);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
[data-theme="light"] .host-card-v1:hover {
  border-color: rgba(59, 130, 246, 0.4);
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.08);
}
[data-theme="light"] .wan-capsule {
  background: rgba(241, 245, 249, 0.7);
  border-color: rgba(226, 232, 240, 0.9);
}
[data-theme="light"] .workload-capsule {
  background: rgba(241, 245, 249, 0.9);
}
</style>

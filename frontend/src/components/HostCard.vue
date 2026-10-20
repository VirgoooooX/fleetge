<template>
  <article
    class="host-card host-card-v1"
    :class="[`is-${host.status}`, { 'has-error': !!host.error_message }]"
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

        <!-- 到期天数：五级状态阶梯渐变色（>30天青蓝, 15-30天靛蓝, 8-14天琥珀, 1-7天橙红, <=0天红警报） -->
        <button
          v-if="effectiveExpiryDays != null"
          type="button"
          class="badge-chip is-expiry"
          :class="`expiry-${getExpiryTier(effectiveExpiryDays)}`"
          title="点击查看账单与续费详情"
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
            <strong class="rail-val font-mono" :style="{ color: getMetricColor(cpuPercent) }">
              {{ cpuPercent.toFixed(1) }}%
            </strong>
          </div>
          <div class="rail-track">
            <div
              class="rail-fill"
              :style="{ width: `${cpuPercent}%`, background: getMetricColor(cpuPercent) }"
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

      <!-- 2. 一体化 WAN 态势舱（网络吞吐与配额） -->
      <section class="wan-capsule">
        <div class="capsule-top">
          <div class="capsule-title">
            <svg class="capsule-globe-icon" xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            <span>WAN 流量与配额</span>
          </div>

          <div class="capsule-quota-stat font-mono">
            <template v-if="effectiveQuota?.quotaBytes">
              <span>本期</span>
              <strong>{{ formatBytes(effectiveQuota.usedBytes) }}</strong>
              <small>/ {{ formatBytes(effectiveQuota.quotaBytes) }}</small>
            </template>
            <template v-else>
              <span>本月总计</span>
              <strong>{{ formatBytes(effectiveTrafficMonthTotal) }}</strong>
            </template>
          </div>
        </div>

        <!-- 配额进度条（若未配置配额则平滑收拢） -->
        <div v-if="effectiveQuota?.quotaBytes" class="capsule-progress-track">
          <div
            class="capsule-progress-fill"
            :style="{
              width: `${Math.min(100, effectiveQuota.usagePercent || 0)}%`,
              background: getQuotaColor(effectiveQuota.usagePercent || 0)
            }"
          />
        </div>

        <div class="capsule-bottom">
          <!-- 静态配额/重置日 -->
          <div class="quota-meta-left">
            <template v-if="effectiveQuota?.quotaBytes">
              <span>剩余 {{ formatBytes(effectiveQuota.remainingBytes) }}</span>
              <span class="meta-dot">·</span>
              <span>{{ effectiveNextResetText }}</span>
            </template>
            <template v-else>
              <span>今日 {{ formatBytes(effectiveTrafficTodayTotal) }}</span>
              <span class="meta-dot">·</span>
              <span>每月 {{ host.traffic_billing_day || 1 }} 日结算</span>
            </template>
          </div>

          <!-- 实时动态吞吐 -->
          <div class="live-rates-right font-mono">
            <span class="rate-tag rx" title="当前实时下载吞吐">
              <span class="arrow">↓</span> {{ formatRate(host.metrics.networkRxRate) }}
            </span>
            <span class="rate-sep">/</span>
            <span class="rate-tag tx" title="当前实时上传吞吐">
              <span class="arrow">↑</span> {{ formatRate(host.metrics.networkTxRate) }}
            </span>
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
import type { HostSummary, HostTrafficState } from "@/stores/dashboard";

const props = defineProps<{
  host: HostSummary;
  updateCount?: number;
  traffic?: HostTrafficState;
  subscription?: {
    provider?: string;
    plan_name?: string;
    payment_amount?: number;
    currency?: string;
    payment_cycle?: string;
    service_expiry_date?: string;
    service_days_remaining?: number;
    auto_renew?: boolean;
    quota_enabled?: boolean;
    traffic_direction?: string;
  };
  quota?: {
    usedBytes?: number;
    quotaBytes?: number;
    remainingBytes?: number;
    usagePercent?: number;
    nextResetText?: string;
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

const effectiveQuota = computed(() => {
  if (props.quota) return props.quota;
  return props.traffic?.summary?.quota;
});

const effectiveTrafficMonthTotal = computed(() => {
  return props.traffic?.summary?.month?.totalBytes ?? 0;
});

const effectiveTrafficTodayTotal = computed(() => {
  return props.traffic?.summary?.today?.totalBytes ?? 0;
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

function getMetricColor(pct: number): string {
  if (pct >= 85) return "var(--danger, #f87171)";
  if (pct >= 65) return "var(--warning, #fbbf24)";
  return "var(--accent-blue, #60a5fa)";
}

function getQuotaColor(pct: number): string {
  if (pct >= 90) return "var(--danger, #f87171)";
  if (pct >= 75) return "var(--warning, #fbbf24)";
  return "var(--accent-cyan, #22d3ee)";
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
  const q: any = effectiveQuota.value;
  if (!q) return "";
  if (q.nextResetText) return q.nextResetText;
  if (q.nextResetAt) {
    try {
      const d = new Date(q.nextResetAt);
      if (!isNaN(d.getTime())) {
        return `${d.getMonth() + 1}月${d.getDate()}日重置`;
      }
    } catch {}
  }
  return `每月 ${props.host.traffic_billing_day || 1} 日重置`;
});

function formatBytes(bytes?: number | null): string {
  if (bytes == null || isNaN(bytes)) return "0 B";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

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
  return `${sym}${amount.toFixed(0)} / ${cycleMap[cycle] || "年"}`;
}
</script>

<style scoped>
.host-card-v1 {
  display: flex;
  flex-direction: column;
  min-height: 215px;
  padding: 14px 16px;
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
  width: 8px;
  height: 8px;
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
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.host-name {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary, #f1f5f9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.host-meta-badge {
  font-size: 11px;
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
  font-size: 11px;
  height: 22px;
  padding: 0 8px;
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
.badge-chip:hover {
  transform: translateY(-1px);
}

.chip-svg {
  display: block;
  width: 12px;
  height: 12px;
  flex-shrink: 0;
}

/* 文字垂直对齐微调：抵消中文字形底部分离空间，实现与矢量图标视觉轴心精准对齐 */
.chip-text {
  display: inline-flex;
  align-items: center;
  line-height: 1;
  transform: translateY(-1px);
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
/* Tier 1: 充裕安全 (> 30 天) - 淡雅天青 */
.badge-chip.is-expiry.expiry-safe {
  background: rgba(56, 189, 248, 0.08);
  border-color: rgba(56, 189, 248, 0.22);
  color: #38bdf8;
}
[data-theme="light"] .badge-chip.is-expiry.expiry-safe {
  background: rgba(14, 165, 233, 0.08);
  border-color: rgba(14, 165, 233, 0.25);
  color: #0284c7;
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
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
}

.rail-label {
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}

.rail-val {
  font-size: 13px;
  font-weight: 700;
}

.rail-track {
  width: 100%;
  height: 3.5px;
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
  font-size: 11px;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 一体化 WAN 态势舱 */
.wan-capsule {
  background: rgba(148, 163, 184, 0.04);
  border: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.12));
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.capsule-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.capsule-title {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}
.capsule-globe-icon {
  color: var(--accent-cyan, #22d3ee);
}

.capsule-quota-stat {
  font-size: 12px;
  color: var(--text-muted, #64748b);
}
.capsule-quota-stat strong {
  font-size: 13px;
  color: var(--text-primary, #f1f5f9);
  margin-left: 4px;
}

.capsule-progress-track {
  width: 100%;
  height: 4px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
}

.capsule-progress-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}

.capsule-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}

.quota-meta-left {
  color: var(--text-muted, #64748b);
}
.meta-dot {
  margin: 0 3px;
  opacity: 0.5;
}

.live-rates-right {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 11px;
}

.rate-tag.rx {
  color: var(--accent-cyan, #22d3ee);
}
.rate-tag.tx {
  color: var(--accent-blue, #60a5fa);
}
.rate-sep {
  color: var(--text-muted, #64748b);
  opacity: 0.4;
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
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}
.fallback-desc {
  font-size: 11px;
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
  font-size: 12px;
  color: var(--text-secondary, #94a3b8);
  padding: 2px 7px;
  border-radius: 6px;
  background: rgba(148, 163, 184, 0.06);
}
.workload-capsule.has-stopped {
  background: rgba(251, 191, 36, 0.1);
  color: var(--warning, #fbbf24);
}

.dot-indicator {
  width: 6px;
  height: 6px;
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
  font-size: 11px;
  color: var(--text-muted, #64748b);
}
.docker-whale-svg {
  width: 14px;
  height: 11px;
  color: var(--accent-cyan, #22d3ee);
}

.price-trigger-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary, #94a3b8);
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.15s ease;
}
.price-trigger-btn:hover {
  color: var(--accent-blue, #60a5fa);
  background: rgba(96, 165, 250, 0.1);
}

.trigger-arrow {
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

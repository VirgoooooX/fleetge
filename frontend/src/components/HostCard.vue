<template>
  <article
    class="host-card host-card-v1"
    :class="[`is-${host.status}`, { 'has-error': !!host.error_message }]"
    tabindex="0"
    :aria-label="t('hostCard.openHost', { name: host.display_name })"
    @keydown.enter.self.prevent="$emit('click')"
    @keydown.space.self.prevent="$emit('click')"
    @click="$emit('click')"
  >
    <!-- Center Brand Watermark (between card background and foreground content) -->
    <div
      v-if="resolvedLogo"
      class="card-brand-watermark"
      :class="{ 'is-wide': resolvedLogo.isWide }"
      aria-hidden="true"
    >
      <img
        :src="watermarkSrc"
        alt=""
        class="watermark-img"
        draggable="false"
      />
    </div>

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
          <ArrowUpCircle :size="12" class="chip-svg" aria-hidden="true" />
          <span class="chip-text">{{ displayUpdateCount }} {{ t('dashboard.updates') }}</span>
        </button>

        <!-- 到期天数：远期弱化，临近到期逐级强调 -->
        <button
          v-if="effectiveExpiryDays != null"
          type="button"
          class="badge-chip is-expiry"
          :class="`expiry-${getExpiryTier(effectiveExpiryDays)}`"
          :title="effectiveSubscription?.service_expiry_date ? t('hostCard.openBillWithDate', { date: effectiveSubscription.service_expiry_date }) : t('hostCard.openBill')"
          @click.stop="$emit('open-bill')"
        >
          <Calendar :size="12" class="chip-svg" aria-hidden="true" />
          <span class="chip-text">{{ formatExpiry(effectiveExpiryDays) }}</span>
        </button>

        <!-- 异常/离线时才突出状态胶囊（管理异常原则：正常在线时不堆砌胶囊） -->
        <span v-if="host.status !== 'online'" class="badge-chip status-alert-chip" :class="`is-${host.status}`">
          <span class="chip-text">{{ getStatusLabel(host.status) }}</span>
        </span>
      </div>
    </header>

    <!-- Normal Metrics Body -->
    <div v-if="host.metrics" class="card-body">
      <HostComputeRails :metrics="host.metrics" />
      <HostWanCapsule
        :host="host"
        :traffic="traffic"
        :quota="quota"
        :subscription="effectiveSubscription"
      />
    </div>

    <!-- 离线/异常退化兜底 -->
    <div v-else class="card-fallback">
      <div class="fallback-icon-wrap">
        <AlertCircle :size="22" aria-hidden="true" />
      </div>
      <div class="fallback-info">
        <p class="fallback-title">{{ host.error_message || t('hostCard.metricsUnavailable') }}</p>
        <span class="fallback-desc">{{ t('hostCard.metricsHelp') }}</span>
      </div>
    </div>

    <!-- Bottom Footer: Workload Capsule & Subscription Price Trigger -->
    <footer class="card-footer">
      <div class="footer-left">
        <!-- 容器状态胶囊 -->
        <div class="workload-capsule" :class="{ 'has-stopped': host.container_stopped > 0 }">
          <span class="dot-indicator" :class="host.container_stopped > 0 ? 'is-warn' : 'is-good'" />
          <span class="workload-text">
            <strong>{{ host.container_running }}</strong> {{ t('dashboard.running') }}
            <template v-if="host.container_stopped > 0">
              · <strong class="text-warn">{{ host.container_stopped }}</strong> {{ t('dashboard.stopped') }}
            </template>
          </span>
        </div>

        <!-- 引擎标识 -->
        <span v-if="host.docker_version" class="docker-tag" :title="`Docker Engine ${host.docker_version}`">
          <svg class="docker-whale-svg" viewBox="0 0 24 18" aria-hidden="true" focusable="false">
            <path fill="currentColor" d="M7.2 6.2h2.1V4.1H7.2v2.1Zm2.7 0H12V4.1H9.9v2.1Zm2.8 0h2.1V4.1h-2.1v2.1ZM9.9 3.5H12V1.4H9.9v2.1Zm-5.4 5h15.6c.9 0 1.7.3 2.4.9-.4 2.2-1.5 4-3.2 5.2-1.6 1.1-3.7 1.7-6.2 1.7H9.2c-3 0-5.2-1.1-6.5-3.2-.7-1.1-1-2.3-.9-3.7.8-.1 1.7-.4 2.7-.9Zm0-.6h2.1V5.8H4.5v2.1Zm2.7 0h2.1V5.8H7.2v2.1Zm2.7 0H12V5.8H9.9v2.1Zm2.8 0h2.1V5.8h-2.1v2.1Zm2.7 0h2.1V5.8h-2.1v2.1Z"/>
          </svg>
          <span>v{{ host.docker_version }}</span>
        </span>
      </div>

      <!-- 资费触发按钮（点击打开套餐弹窗） -->
      <button
        v-if="effectivePriceText"
        type="button"
        class="price-trigger-btn u-mono u-tabular"
        :title="t('hostCard.openBill')"
        @click.stop="$emit('open-bill')"
      >
        <span>{{ effectivePriceText }}</span>
        <ChevronRight :size="13" class="trigger-arrow" aria-hidden="true" />
      </button>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { AlertCircle, ArrowUpCircle, Calendar, ChevronRight } from "@lucide/vue";
import type { HostSummary, HostTrafficState, HostSubscriptionSummary } from "@/stores/dashboard";
import { useTheme } from "@/composables/useTheme";
import { resolveHostLogo } from "@/utils/hostLogo";
import { formatExpiry, formatSubscriptionPrice } from "@/utils/format";
import HostComputeRails from "./hosts/HostComputeRails.vue";
import HostWanCapsule, { type HostQuotaOverride } from "./hosts/HostWanCapsule.vue";

const props = defineProps<{
  host: HostSummary;
  updateCount?: number;
  traffic?: HostTrafficState;
  subscription?: HostSubscriptionSummary | null;
  quota?: HostQuotaOverride;
}>();

defineEmits<{
  (e: "click"): void;
  (e: "updates"): void;
  (e: "open-bill"): void;
}>();

const { t } = useI18n();
const theme = useTheme();

const resolvedLogo = computed(() => resolveHostLogo(props.host.logo));
const watermarkSrc = computed(() => {
  if (!resolvedLogo.value) return "";
  return theme.current.value === "dark"
    ? resolvedLogo.value.darkSrc
    : resolvedLogo.value.src;
});

const displayUpdateCount = computed(() => {
  return props.updateCount ?? props.host.update_count ?? 0;
});

const effectiveSubscription = computed(() => {
  return props.subscription ?? props.host.subscription;
});

const effectiveExpiryDays = computed(() => {
  return effectiveSubscription.value?.service_days_remaining;
});

const effectivePriceText = computed(() => {
  const sub = effectiveSubscription.value;
  if (!sub || sub.payment_amount == null) return "";
  return formatSubscriptionPrice(sub.payment_amount, sub.currency, sub.payment_cycle);
});

function getExpiryTier(days?: number): "safe" | "notice" | "warn" | "urgent" | "critical" {
  if (days == null) return "safe";
  if (days <= 0) return "critical";
  if (days <= 7) return "urgent";
  if (days <= 14) return "warn";
  if (days <= 30) return "notice";
  return "safe";
}

function getStatusLabel(status: string): string {
  const map: Record<string, string> = {
    online: t("status.online"),
    degraded: t("status.degraded"),
    offline: t("status.offline"),
    unknown: t("status.unknown"),
  };
  return map[status] || status;
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

/* 居中品牌底纹水印：置于卡片背景之上、前景文字之下 */
.card-brand-watermark {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  height: 60%;
  width: 60%;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  user-select: none;
  z-index: 0;
  opacity: 0.12;
  transition: opacity 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.card-brand-watermark.is-wide {
  width: 52%;
  height: 44%;
}

.watermark-img {
  max-width: 100%;
  max-height: 100%;
  width: auto;
  height: 100%;
  object-fit: contain;
  display: block;
}

.card-brand-watermark.is-wide .watermark-img {
  width: 100%;
  height: auto;
}

.host-card-v1:hover .card-brand-watermark {
  opacity: 0.2;
  transform: translate(-50%, -50%) scale(1.03);
}

[data-theme="light"] .card-brand-watermark {
  opacity: 0.09;
}

[data-theme="light"] .host-card-v1:hover .card-brand-watermark {
  opacity: 0.16;
}

.card-header,
.card-body,
.card-fallback,
.card-footer {
  position: relative;
  z-index: 1;
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
  font-size: 17px;
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
  transition:
    background-color var(--duration-fast, 120ms) ease,
    border-color var(--duration-fast, 120ms) ease,
    color var(--duration-fast, 120ms) ease;
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
  font-weight: 700;
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
  padding: 3px 7px;
  border-radius: 4px;
  transition: color var(--duration-fast, 120ms) ease, background-color var(--duration-fast, 120ms) ease;
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
[data-theme="light"] .workload-capsule {
  background: rgba(241, 245, 249, 0.9);
}
</style>

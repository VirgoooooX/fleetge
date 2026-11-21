<template>
  <div
    ref="themeToggleWrapRef"
    class="ops-theme-toggle-wrap" :class="{ mobile }"
    @contextmenu.prevent="toggleTuner"
    @keydown.shift.f10.prevent="toggleTuner"
    @keydown.context-menu.prevent="toggleTuner"
  >
    <button
      v-if="mobile"
      type="button"
      class="ops-sidebar-footer-btn ops-sidebar-mobile-action"
      data-theme-toggle
      :title="t('shell.themeTunerHint')"
      :aria-expanded="tunerOpen"
      aria-haspopup="dialog"
      @click="handleThemeBtnClick"
    >
      <el-icon><component :is="themeIcon" /></el-icon>
      <span>{{ themeLabel }}</span>
    </button>
    <el-button
      v-else
      class="ops-control ui-icon-button ops-desktop-tool"
      size="small"
      data-theme-toggle
      :icon="themeIcon"
      :title="t('shell.themeTunerHint')"
      :aria-label="themeLabel"
      :aria-expanded="tunerOpen"
      aria-haspopup="dialog"
      @click="handleThemeBtnClick($event)"
    />
    <div v-if="tunerOpen" class="ops-pour-tuner" role="dialog" @keydown.esc.stop.prevent="closeTuner(true)" :aria-label="t('themePour.title')" @click.stop>
      <div class="ops-pour-tuner-head">
        <strong>{{ t("themePour.title") }}</strong>
        <span class="ops-pour-tuner-badge">{{ t(`themePour.preset.${theme.activePreset.value}`) }}</span>
      </div>
      <div class="ops-pour-presets" role="group">
        <button
          v-for="p in pourPresetOptions"
          :key="p"
          type="button"
          class="ops-pour-chip"
          :class="{ active: theme.activePreset.value === p }"
          :aria-pressed="theme.activePreset.value === p"
          @click="theme.applyPreset(p)"
        >
          {{ t(`themePour.preset.${p}`) }}
        </button>
      </div>
      <div class="ops-pour-sliders" :class="{ 'is-disabled': !theme.pourConfig.enabled }">
        <label v-for="slider in sliders" :key="slider.key" class="ops-pour-row">
          <span>{{ t(`themePour.${slider.key}`) }}</span>
          <input
            type="range"
            :min="slider.min"
            :max="slider.max"
            :step="slider.step"
            :value="theme.pourConfig[slider.key]"
            @input="updatePourNumber(slider.key, $event)"
          />
          <output>{{ theme.pourConfig[slider.key].toFixed(slider.precision) }}{{ slider.unit }}</output>
        </label>
      </div>
      <div class="ops-pour-actions">
        <button type="button" class="ops-pour-btn" @click="theme.resetPourConfig()">
          {{ t("themePour.reset") }}
        </button>
        <button type="button" class="ops-pour-btn primary" @click="previewPourFromTuner">
          {{ t("themePour.preview") }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Moon, Sun } from "@lucide/vue";
import { useTheme } from "@/composables/useTheme";

const props = defineProps<{ mobile?: boolean; disabled?: boolean }>();
const theme = useTheme();
const { t } = useI18n();
const themeIcon = computed(() => theme.current.value === "dark" ? Sun : Moon);
const themeLabel = computed(() => t(theme.current.value === "dark" ? "shell.switchLight" : "shell.switchDark"));
const tunerOpen = ref(false);
const themeToggleWrapRef = ref<HTMLElement | null>(null);
const pourPresetOptions = ["off", "crisp", "standard", "lush"] as const;
const sliders = [
  { key: "duration", min: 400, max: 2400, step: 50, precision: 0, unit: "ms" },
  { key: "waveAmp", min: 0, max: 36, step: 1, precision: 0, unit: "px" },
  { key: "splash", min: 0, max: 2, step: 0.1, precision: 1, unit: "×" },
  { key: "streamWidth", min: 2, max: 12, step: 0.5, precision: 1, unit: "px" },
] as const;

function anchor() {
  return themeToggleWrapRef.value?.querySelector<HTMLElement>("[data-theme-toggle]") ?? null;
}

function closeTuner(restoreFocus = false) {
  tunerOpen.value = false;
  if (restoreFocus) anchor()?.focus();
}

function toggleTuner() {
  if (props.disabled) return;
  if (tunerOpen.value) closeTuner(true);
  else tunerOpen.value = true;
}

function handleThemeBtnClick(event: MouseEvent) {
  if (event.altKey) {
    toggleTuner();
    return;
  }
  closeTuner();
  theme.toggle(event);
}

function updatePourNumber(key: (typeof sliders)[number]["key"], event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber;
  if (!Number.isFinite(value)) return;
  theme.pourConfig.enabled = true;
  theme.pourConfig[key] = value;
}

function previewPourFromTuner() {
  theme.pourConfig.enabled = true;
  theme.toggle(anchor());
}

watch(() => props.disabled, disabled => { if (disabled) closeTuner(); });
watch(tunerOpen, async (open, _, onCleanup) => {
  if (!open) return;
  function handleOutside(event: PointerEvent) {
    if (event.target instanceof Node && !themeToggleWrapRef.value?.contains(event.target)) closeTuner();
  }
  document.addEventListener("pointerdown", handleOutside);
  onCleanup(() => document.removeEventListener("pointerdown", handleOutside));
  await nextTick();
  if (tunerOpen.value) themeToggleWrapRef.value?.querySelector<HTMLElement>(".ops-pour-chip")?.focus();
});
</script>

<style scoped>
.ops-control {
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--pill-bg);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.ops-theme-toggle-wrap {
  position: relative;
  display: inline-flex;
}

.ops-pour-tuner {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 40;
  width: 248px;
  padding: 11px 12px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-panel) 96%, transparent);
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  box-shadow: 0 18px 40px -16px rgba(0, 0, 0, 0.55);
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 12px;
}

.ops-pour-tuner-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.ops-pour-tuner-head strong {
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 700;
}

.ops-pour-tuner-badge {
  padding: 1px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 600;
}

.ops-pour-presets {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.ops-pour-chip {
  height: 26px;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  background: var(--surface-panel-raised);
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.ops-pour-chip:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.ops-pour-chip.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--accent-blue);
}

.ops-pour-sliders {
  display: grid;
  gap: 7px;
}

.ops-pour-sliders.is-disabled {
  opacity: 0.48;
}

.ops-pour-row {
  display: grid;
  grid-template-columns: 58px 1fr 44px;
  align-items: center;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 12px;
}

.ops-pour-row output {
  text-align: right;
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  font-size: 11px;
}

.ops-pour-row input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 3px;
  border-radius: 2px;
  background: var(--surface-elevated);
  margin: 0;
}

.ops-pour-row input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--accent-blue);
  border: 2px solid var(--surface-panel);
  box-shadow: 0 0 0 1px var(--border-strong);
  cursor: pointer;
}

.ops-pour-actions {
  display: flex;
  gap: 6px;
  padding-top: 2px;
}

.ops-pour-btn {
  flex: 1;
  height: 27px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--surface-panel-raised);
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.ops-pour-btn:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.ops-pour-btn.primary {
  border-color: transparent;
  background: var(--accent-blue);
  color: #fff;
}
@media (max-width: 900px) {
  .ops-theme-toggle-wrap:not(.mobile) {
    display: none;
  }

  .ops-theme-toggle-wrap.mobile {
    display: flex;
  }

  .ops-theme-toggle-wrap.mobile .ops-pour-tuner {
    top: auto;
    bottom: calc(100% + 6px);
    right: 0;
    width: 100%;
    box-sizing: border-box;
  }

  .ops-theme-toggle-wrap.mobile .ops-pour-row {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ops-pour-chip,
  .ops-pour-btn {
    transition: none;
  }
}
</style>

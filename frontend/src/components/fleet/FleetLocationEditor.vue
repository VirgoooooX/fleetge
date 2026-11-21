<template>
  <section class="inspector-panel location-editor-panel">
    <div class="inspector-section-heading">
      <div>
        <span>{{ t("map.locationKicker") }}</span>
        <h3>{{ locationTarget === "center" ? t("map.centerLocation") : hostCount > 1 ? t("map.setSharedLocation") : t("map.editHostLocation") }}</h3>
      </div>
      <MapPinned :size="18" />
    </div>
    <form class="location-form" @submit.prevent="emit('save')">
      <label v-if="locationTarget === 'center'">
        <span>{{ t("map.centerName") }}</span>
        <el-input v-model="locationForm.name" :aria-label="t('map.centerName')" />
      </label>
      <div>
        <label :for="cityInputId">{{ t("map.city") }}</label>
        <div class="city-search">
          <el-input :id="cityInputId" v-model="locationForm.city" :placeholder="t('map.cityPlaceholder')" @input="handleCityInput" @keydown.esc.stop="clearCitySearch" />
          <div v-if="citySearching || cityResults.length" class="city-results">
            <div v-if="citySearching" class="city-searching" role="status"><LoaderCircle class="spin" :size="14" />{{ t("map.searchingCity") }}</div>
            <button v-for="result in cityResults" :key="`${result.latitude}-${result.longitude}-${result.name}`" type="button" @click="selectCityResult(result)">
              <strong>{{ result.name }}</strong>
              <small>{{ [result.region, result.country].filter(Boolean).join(" · ") }} · {{ result.latitude.toFixed(4) }}, {{ result.longitude.toFixed(4) }}</small>
            </button>
          </div>
        </div>
      </div>
      <div class="coordinate-row">
        <label><span>{{ t("map.latitude") }}</span><el-input-number v-model="locationForm.latitude" :aria-label="t('map.latitude')" :min="-90" :max="90" :precision="6" controls-position="right" /></label>
        <label><span>{{ t("map.longitude") }}</span><el-input-number v-model="locationForm.longitude" :aria-label="t('map.longitude')" :min="-180" :max="180" :precision="6" controls-position="right" /></label>
      </div>
      <div class="location-hint"><ShieldCheck :size="17" />{{ t("map.ipLocationHint") }}</div>
      <div class="location-editor-actions">
        <button v-if="locationTarget === 'center' || hostCount === 1" class="ui-button" type="button" :disabled="suggesting || savingLocation" @click="suggestLocation">
          <LoaderCircle v-if="suggesting" class="spin" :size="15" /><LocateFixed v-else :size="15" />{{ t("map.autoSuggest") }}
        </button>
        <span class="action-spacer"></span>
        <button class="ui-button" type="button" @click="emit('cancel')">{{ t("map.cancel") }}</button>
        <button class="ui-button ui-button--primary" type="submit" :disabled="savingLocation || suggesting">
          <LoaderCircle v-if="savingLocation" class="spin" :size="15" />{{ t("map.saveLocation") }}
        </button>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, useId } from "vue";
import { useI18n } from "vue-i18n";
import { LoaderCircle, LocateFixed, MapPinned, ShieldCheck } from "@lucide/vue";
import { ElMessage } from "element-plus";
import { searchFleetLocations, type FleetLocationSearchResult } from "@/api/fleetMap";
import type { FleetLocationDraft } from "@/utils/fleetMap";

const locationForm = defineModel<FleetLocationDraft>({ required: true });
defineProps<{
  locationTarget: "center" | "hosts";
  hostCount: number;
  suggesting: boolean;
  savingLocation: boolean;
}>();
const emit = defineEmits<{ suggest: []; cancel: []; save: [] }>();
const { t, locale } = useI18n();
const cityInputId = useId();
const cityResults = ref<FleetLocationSearchResult[]>([]);
const citySearching = ref(false);
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let activeSearch: AbortController | undefined;

function clearCitySearch() {
  clearTimeout(searchTimer);
  activeSearch?.abort();
  activeSearch = undefined;
  cityResults.value = [];
  citySearching.value = false;
}

function suggestLocation() {
  clearCitySearch();
  emit("suggest");
}

function handleCityInput(value: string) {
  clearCitySearch();
  const query = value.trim();
  if (query.length < 2) return;
  const request = new AbortController();
  activeSearch = request;
  searchTimer = setTimeout(async () => {
    citySearching.value = true;
    try {
      const results = await searchFleetLocations(query, locale.value === "zh-CN" ? "zh" : "en", request.signal);
      if (activeSearch === request) cityResults.value = results;
    } catch {
      // Manual coordinate entry remains available if city lookup fails.
    } finally {
      if (activeSearch === request) {
        activeSearch = undefined;
        citySearching.value = false;
      }
    }
  }, 280);
}

function selectCityResult(result: FleetLocationSearchResult) {
  clearCitySearch();
  Object.assign(locationForm.value, {
    city: result.city || result.name,
    region: result.region || "",
    country: result.country || "",
    country_code: result.country_code || "",
    latitude: result.latitude,
    longitude: result.longitude,
  });
  ElMessage.success(t("map.cityMatched"));
}

onBeforeUnmount(clearCitySearch);
</script>

<style scoped>
.inspector-section-heading span { color: var(--accent-blue); font: 700 var(--text-2xs)/1.2 var(--font-mono); letter-spacing: .13em; }
.inspector-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.inspector-section-heading h3 { margin: 4px 0 0; color: var(--text-primary); font-size: var(--text-base); }
.location-form { display: grid; gap: 14px; }.location-form label>span{display:block;margin-bottom:6px;color:var(--text-secondary);font-size:var(--text-sm)}.coordinate-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.coordinate-row .el-input-number{width:100%}.location-hint{display:flex;align-items:flex-start;gap:8px;padding:10px;border:1px solid color-mix(in srgb,var(--accent-blue) 22%,var(--border-subtle));border-radius:var(--ui-radius-md);color:var(--text-secondary);background:color-mix(in srgb,var(--accent-blue) 6%,var(--surface-panel-raised));font-size:var(--text-xs);line-height:1.5}.location-editor-actions{display:flex;align-items:center;gap:8px;padding-top:2px}.action-spacer{flex:1}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none!important}}
.city-search { position: relative; }
.city-results { position: absolute; z-index: 20; top: calc(100% + 5px); right: 0; left: 0; display: grid; gap: 2px; max-height: 238px; overflow: auto; padding: 5px; border: 1px solid var(--fleet-map-border); border-radius: 9px; background: var(--fleet-map-panel); box-shadow: var(--fleet-map-shadow); }
.city-results button { display: grid; gap: 3px; padding: 9px 10px; border: 0; border-radius: 6px; color: var(--fleet-map-ink); background: transparent; text-align: left; cursor: pointer; }
.city-results button:hover { background: color-mix(in srgb, var(--accent-blue, #2563eb) 10%, transparent); }
.city-results strong { font-size: 12px; }
.city-results small,.city-searching { color: var(--fleet-map-muted); font-size: 11px; }
.city-searching { display: flex; align-items: center; gap: 6px; padding: 10px; }
.location-form label[for] { display:block; margin-bottom:6px; color:var(--text-secondary); font-size:var(--text-sm); }
@media (max-width:640px) {
  .coordinate-row { grid-template-columns:1fr; }
  .location-editor-actions { flex-wrap:wrap; }
  .action-spacer { display:none; }
  .location-editor-actions .ui-button--primary { flex:1; }
}
</style>

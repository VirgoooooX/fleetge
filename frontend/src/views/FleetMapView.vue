<template>
  <div class="fleet-map-view" :class="{ 'is-theme-dark': isDarkTheme }">
    <section class="map-dashboard ui-dashboard-surface">
      <div class="map-dashboard-copy ui-dashboard-copy">
        <h2 class="ui-dashboard-title">{{ t("map.eyebrow") }}</h2>
        <p class="ui-dashboard-description">{{ t("map.description") }}</p>
      </div>

      <div class="map-command-deck" role="group" :aria-label="t('map.summaryAria')">
        <div class="map-status-strip">
          <button
            v-for="item in summaryItems"
            :key="item.key"
            class="summary-card"
            :class="['tone-' + item.tone, { active: store.filter === item.key }]"
            type="button"
            :aria-pressed="store.filter === item.key"
            @click="store.filter = item.key"
          >
            <span class="summary-dot" :class="item.tone"></span>
            <span class="summary-label">{{ item.label }}</span>
            <strong class="summary-value">{{ item.value }}</strong>
          </button>
        </div>

        <div class="map-command-actions">
          <label class="issue-toggle">
            <input v-model="store.onlyIssues" class="issue-toggle-input" type="checkbox" />
            <span class="issue-switch" aria-hidden="true"><i /></span>
            <span>{{ t("map.onlyIssues") }}</span>
          </label>

          <button class="ui-button center-config-button" type="button" @click="openCenterEditor">
            <Crosshair :size="15" />
            {{ store.snapshot?.center.confirmed ? t("map.centerLocation") : t("map.configureCenter") }}
          </button>
        </div>
      </div>
    </section>

    <section ref="mapWorkspace" class="map-workspace ui-panel" :class="{ 'has-unlocated': store.unlocatedHosts.length > 0 }">
      <div class="map-stage">
        <FleetGeoMap
          ref="geoMapRef"
          :center="store.snapshot?.center || null"
          :hosts="store.hosts"
          @select="openMapSelection"
        />
        <div class="map-legend" role="group" :aria-label="t('map.legendAria')">
          <span><i class="legend-dot online"></i>{{ t("map.online") }}</span>
          <span><i class="legend-dot degraded"></i>{{ t("map.issues") }}</span>
          <span><i class="legend-dot offline"></i>{{ t("map.offline") }}</span>
          <span><i class="legend-ring"></i>{{ t("map.pending") }}</span>
        </div>
        <div v-if="store.loading && !store.snapshot" class="map-empty" role="status">
          <LoaderCircle class="spin" :size="26" />
          <span>{{ t("map.buildingTopology") }}</span>
        </div>
        <div v-else-if="store.error" class="map-empty error">
          <TriangleAlert :size="24" />
          <span role="alert">{{ store.error }}</span>
          <button type="button" @click="store.fetchSnapshot">{{ t("map.retry") }}</button>
        </div>
      </div>

      <aside v-if="store.unlocatedHosts.length" class="unlocated-panel">
        <div class="panel-heading">
          <div>
            <span class="panel-kicker">{{ t("map.unlocatedKicker") }}</span>
            <h3>{{ t("map.unlocatedNodes") }}</h3>
          </div>
          <div class="panel-heading-actions">
            <button v-if="store.unlocatedHosts.length" class="auto-locate-button" type="button" :disabled="autoLocating" @click="autoLocateUnlocatedHosts">
              <LoaderCircle v-if="autoLocating" class="spin" :size="13" />
              <LocateFixed v-else :size="13" />
              {{ t("map.autoLocate") }}
            </button>
            <span class="panel-count">{{ store.unlocatedHosts.length }}</span>
          </div>
        </div>
        <button
          v-for="host in store.unlocatedHosts"
          :key="host.host_id"
          class="unlocated-host"
          type="button"
          @click="openUnlocatedHost(host)"
        >
          <span class="host-state" :class="host.status"></span>
          <span>
            <strong>{{ host.display_name }}</strong>
            <small>{{ host.error_message || t("map.awaitingCoordinates") }}</small>
          </span>
          <ChevronRight :size="16" />
        </button>
      </aside>
    </section>

    <FleetTopologyMatrix
      :snapshot="store.snapshot"
      :selected-host-id="selectedHostId"
      @inspect="openNodeDrawer"
      @focus="focusNodeOnMap"
    />
    <FleetMapInspector ref="inspector" v-model:selected-host-id="selectedHostId" />
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useTemplateRef, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ChevronRight, Crosshair, LoaderCircle, LocateFixed, TriangleAlert } from "@lucide/vue";
import FleetGeoMap from "@/components/FleetGeoMap.vue";
import FleetMapInspector from "@/components/fleet/FleetMapInspector.vue";
import FleetTopologyMatrix from "@/components/fleet/FleetTopologyMatrix.vue";
import { useTheme } from "@/composables/useTheme";
import { useFleetMapStore } from "@/stores/fleetMap";
import type { FleetMapHost } from "@/api/fleetMap";

const store = useFleetMapStore();
const { t } = useI18n();
const theme = useTheme();
const isDarkTheme = computed(() => theme.current.value === "dark");
const geoMapRef = useTemplateRef<InstanceType<typeof FleetGeoMap>>("geoMapRef");
const inspector = useTemplateRef<InstanceType<typeof FleetMapInspector>>("inspector");
const mapWorkspace = useTemplateRef<HTMLElement>("mapWorkspace");
const selectedHostId = ref("");
const autoLocating = ref(false);
let active = true;

const summaryItems = computed(() => {
  const counts = store.snapshot?.counts || { total: 0, online: 0, degraded: 0, offline: 0, unlocated: 0 };
  return [
    { key: "all" as const, label: t("map.totalHosts"), value: counts.total, tone: "neutral" },
    { key: "online" as const, label: t("map.online"), value: counts.online, tone: "online" },
    { key: "degraded" as const, label: t("map.issues"), value: counts.degraded, tone: "degraded" },
    { key: "offline" as const, label: t("map.offline"), value: counts.offline, tone: "offline" },
    { key: "unlocated" as const, label: t("map.unlocated"), value: counts.unlocated, tone: "unlocated" },
  ];
});

function openCenterEditor() {
  inspector.value?.openCenterEditor();
}

function openMapSelection(hosts: FleetMapHost[]) {
  inspector.value?.openMapSelection(hosts);
}

function openNodeDrawer(host: FleetMapHost) {
  openMapSelection([host]);
}

function openUnlocatedHost(host: FleetMapHost) {
  openNodeDrawer(host);
  inspector.value?.beginLocationEdit([host]);
}

function focusNodeOnMap(host: FleetMapHost) {
  selectedHostId.value = host.host_id;
  if (host.location) {
    geoMapRef.value?.focusLocations([[host.location.latitude, host.location.longitude]]);
  }
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  mapWorkspace.value?.scrollIntoView({ behavior: reduceMotion ? "instant" : "smooth", block: "nearest" });
}

async function autoLocateUnlocatedHosts() {
  if (autoLocating.value) return;
  autoLocating.value = true;
  try {
    for (const host of store.unlocatedHosts) {
      if (!active) break;
      try {
        await store.suggestLocation(host.host_id);
      } catch {
        // Leave the host available for manual placement if lookup fails.
      }
    }
  } finally {
    autoLocating.value = false;
  }
}

const stopInitialSnapshot = watch(() => store.snapshot, (snapshot) => {
  if (!snapshot) return;
  stopInitialSnapshot();
  if (!snapshot.center.confirmed) {
    inspector.value?.openCenterEditor(true);
  }
  void autoLocateUnlocatedHosts();
});

onMounted(store.startPolling);
onBeforeUnmount(() => {
  active = false;
  store.stopPolling();
});
</script>

<style scoped>
.fleet-map-view { display: grid; gap: 16px; min-width: 0; }
.map-dashboard { display:grid;grid-template-columns:minmax(320px,1fr) auto;align-items:center;gap:24px;height:var(--ui-dashboard-header-height);min-height:var(--ui-dashboard-header-height);padding:var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline);background:var(--fleet-hero-bg);border-color:var(--fleet-map-border);box-shadow:var(--fleet-map-shadow); }
.map-dashboard-copy { position:relative;z-index:1;min-width:0;max-width:500px; }
.map-command-deck { position:relative;z-index:1;display:flex;min-width:0;align-items:center;justify-content:flex-end;gap:12px; }
.map-status-strip { display:flex;min-width:0;overflow:hidden;border:1px solid var(--fleet-map-border);border-radius:var(--ui-radius-md);background:color-mix(in srgb,var(--fleet-map-panel-raised) 78%,transparent); }
.summary-card { position:relative;display:inline-flex;flex:0 0 auto;align-items:center;gap:7px;height:38px;padding:0 12px;border:0;border-left:1px solid var(--fleet-map-border);border-radius:0;color:var(--text-secondary);background:transparent;cursor:pointer;transition:color .15s ease,background .15s ease;font:700 12px/1 var(--font-body);white-space:nowrap; }
.summary-card:first-child { border-left:0; }
.summary-card:hover { color:var(--accent-blue);background:color-mix(in srgb,var(--accent-blue) 7%,transparent); }
.summary-card.active { color:var(--accent-blue);background:color-mix(in srgb,var(--accent-blue) 12%,transparent);box-shadow:inset 0 -2px 0 var(--accent-blue); }
.summary-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); flex-shrink: 0; }
.summary-dot.online { background: var(--accent-cyan); box-shadow: 0 0 6px color-mix(in srgb, var(--accent-cyan) 45%, transparent); }
.summary-dot.degraded { background: var(--warning); box-shadow: 0 0 6px color-mix(in srgb, var(--warning) 45%, transparent); }
.summary-dot.offline { background: var(--danger); box-shadow: 0 0 6px color-mix(in srgb, var(--danger) 45%, transparent); }
.summary-dot.unlocated { background: #a78bfa; box-shadow: 0 0 6px rgba(167,139,250,.4); }
.summary-label { color: var(--text-secondary); }
.summary-card.active .summary-label { color:currentColor; }
.summary-value { color: var(--text-primary); font: 700 13px/1 var(--font-mono); }

.map-command-actions { display:flex;align-items:center;gap:10px;padding-left:12px;border-left:1px solid var(--fleet-map-border); }
.issue-toggle { position:relative;display:inline-flex;align-items:center;gap:7px;height:38px;color:var(--text-secondary);cursor:pointer;white-space:nowrap;font-size:12px; }
.issue-toggle-input { position:absolute;width:1px;height:1px;overflow:hidden;opacity:0; }
.issue-switch { position:relative;width:28px;height:16px;flex:0 0 auto;border:1px solid var(--fleet-map-border);border-radius:999px;background:var(--fleet-map-panel-raised);transition:background 160ms ease,border-color 160ms ease; }
.issue-switch i { position:absolute;top:2px;left:2px;width:10px;height:10px;border-radius:50%;background:var(--text-muted);transition:transform 160ms ease,background 160ms ease; }
.issue-toggle-input:checked + .issue-switch { border-color:color-mix(in srgb,var(--warning) 55%,var(--fleet-map-border));background:color-mix(in srgb,var(--warning) 13%,var(--fleet-map-panel-raised)); }
.issue-toggle-input:checked + .issue-switch i { background:var(--warning);transform:translateX(12px); }
.issue-toggle-input:focus-visible + .issue-switch { outline:2px solid var(--focus-ring);outline-offset:2px; }
.center-config-button { height:38px;padding:0 13px !important;border-color:color-mix(in srgb,var(--accent-blue) 38%,var(--fleet-map-border)) !important;color:var(--accent-blue) !important;background:color-mix(in srgb,var(--accent-blue) 8%,var(--fleet-map-panel)) !important;font-size:12px;border-radius:var(--ui-radius-md); }
.map-workspace { display:grid; grid-template-columns:minmax(0,1fr); min-height:620px; padding:0; overflow:hidden; isolation: isolate; background:var(--fleet-map-panel); border:1px solid var(--fleet-map-border); box-shadow:var(--fleet-map-shadow); }
.map-workspace.has-unlocated { grid-template-columns:minmax(0,1fr) 260px; }
.map-stage { position:relative; min-height:620px; overflow:hidden; }
.map-legend { position:absolute; z-index:5; left:18px; bottom:16px; display:flex; gap:13px; flex-wrap:wrap; padding:9px 11px; border:1px solid var(--fleet-map-border); border-radius:8px; color:var(--fleet-map-muted); background:var(--fleet-map-overlay); box-shadow:0 8px 22px rgba(53,91,126,.12); -webkit-backdrop-filter:blur(12px); backdrop-filter:blur(12px); font-size:11px; }
.map-legend span { display:flex; align-items:center; gap:6px; }.legend-dot,.legend-ring{width:8px;height:8px;border-radius:50%;display:inline-block}.legend-dot.online{background:#22d3ee;box-shadow:0 0 9px #22d3ee}.legend-dot.degraded{background:#fbbf24}.legend-dot.offline{background:#f87171}.legend-ring{border:1px dashed #93c5fd}
.map-empty { position:absolute; z-index:6; inset:0; display:grid; place-content:center; gap:10px; text-align:center; color:var(--fleet-map-muted); background:color-mix(in srgb,var(--fleet-map-panel) 70%,transparent); }.map-empty.error{color:var(--danger)}.map-empty button{color:var(--accent-blue);background:none;border:0;cursor:pointer}
.unlocated-panel { border-left:1px solid var(--fleet-map-border); padding:17px 13px; background:linear-gradient(180deg,var(--fleet-map-panel),var(--fleet-map-panel-raised)); overflow:auto; }
.panel-heading { display:flex; align-items:center; justify-content:space-between; padding:4px 5px 14px; }.panel-heading h3{margin:4px 0 0;color:var(--fleet-map-ink);font-size:15px}.panel-count{display:grid;place-items:center;min-width:28px;height:28px;border-radius:8px;color:var(--accent-blue);background:color-mix(in srgb,var(--accent-blue) 12%,transparent);font:700 12px var(--font-mono)}
.unlocated-host { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:10px; width:100%; padding:11px 8px; border:0; border-top:1px solid color-mix(in srgb,var(--fleet-map-border) 70%,transparent); color:var(--fleet-map-ink); background:transparent; text-align:left; cursor:pointer; }.unlocated-host:hover{background:color-mix(in srgb,var(--accent-blue) 8%,transparent)}.unlocated-host strong,.unlocated-host small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.unlocated-host strong{font-size:12px}.unlocated-host small{margin-top:3px;color:var(--fleet-map-muted);font-size:11px}.host-state{width:7px;height:7px;border-radius:50%;background:var(--text-muted)}.host-state.online{background:var(--accent-cyan)}.host-state.degraded{background:var(--warning)}.host-state.offline{background:var(--danger)}
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce){.spin{animation:none!important}}
@media (max-width:1200px){.map-dashboard{height:auto;grid-template-columns:1fr}.map-command-deck{justify-content:flex-start}}
@media (max-width:900px){
  .map-workspace,
  .map-workspace.has-unlocated{grid-template-columns:1fr}
  .map-stage{min-height:58vh}
  .unlocated-panel{max-height:260px;border-top:1px solid var(--fleet-map-border);border-left:0}
}
@media (max-width:640px){.map-dashboard{gap:16px;padding:var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline)}.map-command-deck{align-items:stretch;flex-direction:column}.map-status-strip{width:100%;overflow-x:auto}.summary-card{flex:1 0 auto;justify-content:center;padding:0 10px}.map-command-actions{justify-content:space-between;padding:10px 0 0;border-top:1px solid var(--fleet-map-border);border-left:0}.map-legend{right:12px;left:12px}}
/* Theme tokens keep the map a part of the application, not a dark island. */
.fleet-map-view {
  --fleet-map-bg: radial-gradient(circle at 48% 45%, #f8fbff 0, #eaf2fa 52%, #dce8f4 100%);
  --fleet-hero-bg: linear-gradient(115deg, #f7fbff, #e7f0f9);
  --fleet-map-panel: rgba(248, 251, 255, .94);
  --fleet-map-panel-raised: rgba(238, 245, 252, .92);
  --fleet-map-border: rgba(107, 139, 171, .28);
  --fleet-map-ink: #27415d;
  --fleet-map-muted: #607991;
  --fleet-map-overlay: rgba(255, 255, 255, .84);
  --fleet-map-shadow: 0 14px 32px rgba(53, 91, 126, .12);
}
.fleet-map-view.is-theme-dark {
  --fleet-map-bg: radial-gradient(circle at 48% 45%, #10233b 0, #07111e 48%, #040912 100%);
  --fleet-hero-bg: linear-gradient(115deg, rgba(15,32,53,.92), rgba(5,11,23,.9));
  --fleet-map-panel: rgba(10, 20, 34, .96);
  --fleet-map-panel-raised: rgba(17, 29, 46, .94);
  --fleet-map-border: rgba(148, 163, 184, .16);
  --fleet-map-ink: #dbeafe;
  --fleet-map-muted: #94a3b8;
  --fleet-map-overlay: rgba(4, 9, 18, .82);
  --fleet-map-shadow: 0 14px 32px rgba(0, 0, 0, .28);
}
.panel-heading-actions { display: flex; align-items: center; gap: 8px; }
.auto-locate-button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 7px; border: 1px solid var(--fleet-map-border); border-radius: 7px; color: var(--accent-blue, #2563eb); background: transparent; font-size: 11px; cursor: pointer; }
.auto-locate-button:disabled { opacity: .6; cursor: wait; }
.summary-card:focus-visible, .unlocated-host:focus-visible { outline: 2px solid var(--accent-blue); outline-offset: -2px; }
</style>

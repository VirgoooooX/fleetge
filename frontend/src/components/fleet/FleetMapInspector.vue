<template>
  <el-drawer
    v-model="drawerVisible"
    class="fleet-inspector"
    :direction="isMobile ? 'btt' : 'rtl'"
    :size="isMobile ? '86vh' : 'min(520px, 100vw)'"
    :with-header="false"
    :title="inspectorTitle"
    @closed="resetInspector"
  >
    <div class="inspector-shell">
      <header class="inspector-header">
        <button v-if="canBackToCluster" class="ui-icon-button inspector-back" type="button" :aria-label="t('map.backToCluster')" @click="selectedHostId = ''">
          <ArrowLeft :size="17" />
        </button>
        <div class="inspector-mark" :class="inspectorStatus">
          <Crosshair v-if="drawerMode === 'center'" :size="19" />
          <Users v-else-if="isClusterView" :size="19" />
          <Server v-else :size="19" />
        </div>
        <div class="inspector-heading">
          <span class="inspector-kicker">{{ inspectorKicker }}</span>
          <h2>{{ inspectorTitle }}</h2>
          <p>{{ inspectorSubtitle }}</p>
        </div>
        <button class="ui-icon-button inspector-close" type="button" :aria-label="t('map.close')" @click="drawerVisible = false">
          <X :size="18" />
        </button>
      </header>

      <div class="inspector-scroll">
        <FleetLocationEditor
          v-if="drawerVisible && locationEditing"
          :key="editorKey"
          v-model="locationForm"
          :location-target="locationTarget"
          :host-count="locationHostIds.length"
          :suggesting="suggesting"
          :saving-location="savingLocation"
          @suggest="suggestCurrentLocation"
          @cancel="cancelLocationEdit"
          @save="saveLocation"
        />
        <template v-else-if="isClusterView">
          <section class="inspector-panel location-overview">
            <div class="cluster-status-summary">
              <span><i class="status-dot online"></i><strong>{{ clusterCounts.online }}</strong> {{ t("map.online") }}</span>
              <span><i class="status-dot degraded"></i><strong>{{ clusterCounts.degraded }}</strong> {{ t("map.issues") }}</span>
              <span><i class="status-dot offline"></i><strong>{{ clusterCounts.offline }}</strong> {{ t("map.offline") }}</span>
            </div>
            <button class="ui-button" type="button" @click="beginLocationEdit(drawerHosts)"><MapPinned :size="15" />{{ t("map.editSharedLocation") }}</button>
          </section>
          <section class="inspector-panel">
            <div class="inspector-section-heading"><div><span>{{ t("map.hostsKicker") }}</span><h3>{{ t("map.hostsAtLocation") }}</h3></div><b>{{ drawerHosts.length }}</b></div>
            <div class="cluster-host-list">
              <button v-for="host in drawerHosts" :key="host.host_id" class="cluster-host-row" type="button" @click="selectedHostId = host.host_id">
                <span class="host-state" :class="host.status"></span>
                <span class="cluster-host-copy"><strong>{{ host.display_name }}</strong><small>{{ statusLabel(host.status) }} · {{ t("map.containerCount", { count: host.container_count }) }}</small></span>
                <span class="cluster-host-metric"><small>CPU</small><strong>{{ metricPercent(host.metrics, 'cpuPercent', 'cpu_percent') }}</strong></span>
                <ChevronRight :size="16" />
              </button>
            </div>
          </section>
        </template>

        <template v-else-if="selectedHost">
          <div class="inspector-actions">
            <button class="ui-button" type="button" @click="beginLocationEdit([selectedHost])"><MapPinned :size="15" />{{ t("map.editLocation") }}</button>
            <button class="ui-button ui-button--primary" type="button" @click="router.push('/hosts/' + encodeURIComponent(selectedHost.host_id))"><ExternalLink :size="15" />{{ t("map.openHostDetail") }}</button>
          </div>
          <section class="inspector-panel">
            <div class="inspector-section-heading"><div><span>{{ t("map.runtimeKicker") }}</span><h3>{{ t("map.runtimeMetrics") }}</h3></div><span class="status-pill" :class="selectedHost.status">{{ statusLabel(selectedHost.status) }}</span></div>
            <div class="metric-grid">
              <article><span>CPU</span><strong>{{ metricPercent(selectedHost.metrics, "cpuPercent", "cpu_percent") }}</strong></article>
              <article><span>{{ t("map.memory") }}</span><strong>{{ memoryPercent(selectedHost.metrics) }}</strong></article>
              <article><span>{{ t("map.disk") }}</span><strong>{{ diskPercent(selectedHost.metrics) }}</strong></article>
              <article><span>{{ t("map.containers") }}</span><strong>{{ selectedHost.container_count }}</strong></article>
            </div>
            <div class="drawer-meta"><span><Activity :size="14" />{{ statusLabel(selectedHost.status) }}</span><span><Clock3 :size="14" />{{ selectedHost.last_seen ? formatTime(selectedHost.last_seen) : t("map.noRefreshRecord") }}</span></div>
          </section>
          <section class="inspector-panel identity-panel">
            <div class="inspector-section-heading">
              <div><span>{{ t("map.identityKicker") }}</span><h3>{{ t("map.networkIdentity") }}</h3></div>
              <span class="identity-confidence" :class="{ conflict: networkIdentity?.conflict }">
                {{ networkIdentity?.conflict ? t("map.identityConflict") : (networkIdentity?.confidence || t("map.identityUnknown")) }}
              </span>
            </div>
            <div class="identity-effective">
              <span>{{ t("map.effectivePublicIp") }}</span>
              <strong>{{ networkIdentity?.effectiveIp || t("map.identityUnresolved") }}</strong>
              <small>{{ networkIdentity?.effectiveSource || "—" }}</small>
            </div>
            <div v-if="networkIdentity?.locationDrift" class="identity-drift">
              <TriangleAlert :size="14" />{{ t("map.identityDrift") }}
            </div>
            <div class="identity-evidence-list">
              <div v-for="row in identityCategoryRows" :key="row.key" class="identity-evidence-row">
                <div><strong>{{ row.label }}</strong><small>{{ row.status }}</small></div>
                <code>{{ row.addresses || "—" }}</code>
                <small v-if="row.reason" class="identity-reason">{{ row.reason }}</small>
              </div>
            </div>
            <div class="identity-override-row">
              <el-input v-model="ipOverride" :placeholder="t('map.fixedIpPlaceholder')" :aria-label="t('map.fixedIpPlaceholder')" clearable />
              <button class="ui-button" type="button" :disabled="overrideSaving || identityRefreshing" @click="saveIpOverride()">{{ t("map.applyFixedIp") }}</button>
            </div>
            <div class="identity-actions">
              <button class="ui-button" type="button" :disabled="identityRefreshing || overrideSaving" @click="refreshIdentity(true)">
                <LoaderCircle v-if="identityRefreshing" class="spin" :size="14" />
                <LocateFixed v-else :size="14" />{{ t("map.refreshIdentity") }}
              </button>
              <button v-if="networkIdentity?.fixedOverride" class="ui-button" type="button" :disabled="overrideSaving || identityRefreshing" @click="saveIpOverride(null)">{{ t("map.clearFixedIp") }}</button>
              <span v-if="networkIdentity?.observedAt" class="identity-checked"><Clock3 :size="13" />{{ formatTime(networkIdentity.observedAt) }}</span>
            </div>
          </section>
          <section class="inspector-panel">
            <div class="inspector-section-heading"><div><span>{{ t("map.stacksKicker") }}</span><h3>{{ t("map.appStacks") }}</h3></div><b>{{ selectedHost.stacks.length }}</b></div>
            <div v-if="selectedHost.stacks.length" class="stack-list">
              <details v-for="stack in selectedHost.stacks" :key="stack.name" class="stack-item">
                <summary><span class="stack-indicator" :class="stack.status"></span><strong>{{ stack.name }}</strong><small>{{ stack.running_count }} / {{ stack.service_count }}</small><ChevronRight :size="15" /></summary>
                <div class="service-list"><div v-for="service in stack.services" :key="service.container_id || service.name" class="fleet-service-row"><span class="service-state" :class="service.state"></span><span><strong>{{ service.name }}</strong><small>{{ service.status || service.state }}</small></span></div></div>
              </details>
            </div>
            <div v-else class="drawer-empty">{{ t("map.noStackSnapshot") }}</div>
          </section>
          <section class="inspector-panel location-overview">
            <div><span class="inspector-kicker">{{ t("map.locationKicker") }}</span><h3>{{ locationLabel(selectedHost) }}</h3></div>
            <button class="ui-button" type="button" @click="beginLocationEdit([selectedHost])"><MapPinned :size="15" />{{ t("map.editLocation") }}</button>
          </section>
        </template>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { Activity, ArrowLeft, ChevronRight, Clock3, Crosshair, ExternalLink, LoaderCircle,
  LocateFixed, MapPinned, Server, TriangleAlert, Users, X } from "@lucide/vue";
import { ElMessage } from "element-plus";
import FleetLocationEditor from "./FleetLocationEditor.vue";
import { useMobile } from "@/composables/useMobile";
import { useFleetMapStore } from "@/stores/fleetMap";
import { fleetRequestError, type FleetLocation, type FleetMapHost } from "@/api/fleetMap";
import { fleetStatusKey, type FleetLocationDraft } from "@/utils/fleetMap";

const router = useRouter();
const store = useFleetMapStore();
const { isMobile } = useMobile();
const { t, locale } = useI18n();
const selectedHostId = defineModel<string>("selectedHostId", { required: true });
const drawerVisible = ref(false);
const drawerMode = ref<"selection" | "center">("selection");
const drawerHostIds = ref<string[]>([]);
const locationEditing = ref(false);
const editorKey = ref(0);
const locationTarget = ref<"center" | "hosts">("hosts");
const locationHostIds = ref<string[]>([]);
const suggesting = ref(false);
const savingLocation = ref(false);
const identityRefreshing = ref(false);
let identityRequest: AbortController | undefined;
let disposed = false;
const overrideSaving = ref(false);
const ipOverride = ref("");
const locationForm = ref<FleetLocationDraft>({
  name: "Fleetge Control Center",
  city: "",
  region: "",
  country: "",
  country_code: "",
  latitude: 0,
  longitude: 0,
});

const selectedHost = computed(() =>
  drawerHosts.value.find((host) => host.host_id === selectedHostId.value) || null
);
const networkIdentity = computed(() => selectedHost.value?.network_identity || null);
const identityCategoryRows = computed(() => {
  const categories = networkIdentity.value?.categories || {};
  return [
    { key: "agent", label: t("map.identityAgent") },
    { key: "callback", label: t("map.identityCallback") },
    { key: "dns", label: t("map.identityDns") },
  ].map(({ key, label }) => {
    const item = categories[key] || {};
    const addresses = item.eligibleAddresses?.length ? item.eligibleAddresses : item.addresses;
    return {
      key,
      label,
      status: item.status || t("map.identityUnknown"),
      addresses: addresses?.join(", ") || "",
      reason: [...(item.excludedReasons || []), item.excludedReason || ""].filter(Boolean).join(", "),
    };
  });
});
const drawerHosts = computed(() => {
  const ids = new Set(drawerHostIds.value);
  return (store.snapshot?.hosts || []).filter((host) => ids.has(host.host_id));
});
const isClusterView = computed(() => drawerMode.value === "selection" && drawerHosts.value.length > 1 && !selectedHost.value);
const canBackToCluster = computed(() => drawerMode.value === "selection" && drawerHosts.value.length > 1 && !!selectedHost.value && !locationEditing.value);
const clusterCounts = computed(() => ({
  online: drawerHosts.value.filter((host) => host.status === "online").length,
  degraded: drawerHosts.value.filter((host) => host.status === "degraded").length,
  offline: drawerHosts.value.filter((host) => ["offline", "unknown"].includes(host.status)).length,
}));
const inspectorStatus = computed(() => {
  if (drawerMode.value === "center") return "center";
  if (selectedHost.value) return selectedHost.value.status;
  if (clusterCounts.value.offline) return "offline";
  if (clusterCounts.value.degraded) return "degraded";
  return "online";
});
const inspectorKicker = computed(() => {
  if (locationEditing.value) return t("map.locationEditorKicker");
  if (drawerMode.value === "center") return t("map.controlCenterKicker");
  return isClusterView.value ? t("map.locationClusterKicker") : t("map.hostNodeKicker");
});
const inspectorTitle = computed(() => {
  if (drawerMode.value === "center") return locationForm.value.name || "Fleetge Control Center";
  if (selectedHost.value) return selectedHost.value.display_name;
  if (drawerHosts.value.length) return clusterLocationLabel(drawerHosts.value);
  return t("map.inspectorTitle");
});
const inspectorSubtitle = computed(() => {
  if (drawerMode.value === "center") return [locationForm.value.city, locationForm.value.region, locationForm.value.country].filter(Boolean).join(" · ") || t("map.configureCenterLocation");
  if (selectedHost.value) return locationLabel(selectedHost.value);
  return `${t("map.hostCount", { count: drawerHosts.value.length })} · ${t("map.onlineCount", { count: clusterCounts.value.online })} · ${t("map.issueCount", { count: clusterCounts.value.degraded + clusterCounts.value.offline })}`;
});

function locationLabel(host: FleetMapHost) {
  const location = host.location;
  if (!location) return t("map.unlocated");
  const text = [location.city, location.region, location.country].filter(Boolean).join(" · ");
  return (text || (location.latitude.toFixed(2) + ", " + location.longitude.toFixed(2)))
    + (location.confirmed ? "" : ` · ${t("map.pending")}`);
}

function clusterLocationLabel(hosts: FleetMapHost[]) {
  const first = hosts.find((host) => host.location)?.location;
  if (!first) return t("map.unlocatedPosition");
  return [first.city, first.region, first.country].filter(Boolean).join(" · ")
    || `${first.latitude.toFixed(2)}, ${first.longitude.toFixed(2)}`;
}

const statusLabel = (status: FleetMapHost["status"]) => t(fleetStatusKey[status]);

function openMapSelection(hosts: FleetMapHost[]) {
  drawerMode.value = "selection";
  drawerHostIds.value = hosts.map((host) => host.host_id);
  selectedHostId.value = hosts.length === 1 ? hosts[0].host_id : "";
  locationEditing.value = false;
  drawerVisible.value = true;
}

function resetInspector() {
  if (drawerVisible.value) return;
  drawerHostIds.value = [];
  selectedHostId.value = "";
  locationHostIds.value = [];
  locationEditing.value = false;
}

function metricValue(metrics: Record<string, unknown> | null | undefined, camel: string, snake: string) {
  return Number(metrics?.[camel] ?? metrics?.[snake] ?? 0);
}

function metricPercent(metrics: Record<string, unknown> | null | undefined, camel: string, snake: string) {
  return metricValue(metrics, camel, snake).toFixed(1) + "%";
}

function memoryPercent(metrics: Record<string, unknown> | null | undefined) {
  const used = metricValue(metrics, "memoryUsed", "memory_used");
  const total = metricValue(metrics, "memoryTotal", "memory_total");
  return total ? ((used / total) * 100).toFixed(1) + "%" : "—";
}

function diskPercent(metrics: Record<string, unknown> | null | undefined) {
  const used = metricValue(metrics, "diskUsed", "disk_used");
  const total = metricValue(metrics, "diskTotal", "disk_total");
  return total ? ((used / total) * 100).toFixed(1) + "%" : "—";
}

function formatTime(value: string) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "short", timeStyle: "medium" }).format(date);
}

function stopIdentityRefresh() {
  identityRequest?.abort();
  identityRequest = undefined;
  identityRefreshing.value = false;
}

async function refreshIdentity(force = true) {
  const hostId = selectedHost.value?.host_id;
  if (!hostId || identityRequest || overrideSaving.value) return;
  const request = new AbortController();
  identityRequest = request;
  identityRefreshing.value = true;
  try {
    const evidence = await store.refreshNetworkIdentity(hostId, force, request.signal);
    if (identityRequest !== request || !drawerVisible.value || selectedHost.value?.host_id !== hostId) return;
    ipOverride.value = evidence.fixedOverride || "";
    if (force) ElMessage.success(t("map.identityRefreshed"));
  } catch (error) {
    if (identityRequest === request) ElMessage.error(fleetRequestError(error) || t("map.identityRefreshFailed"));
  } finally {
    if (identityRequest === request) stopIdentityRefresh();
  }
}

async function saveIpOverride(ip = ipOverride.value.trim() || null) {
  const hostId = selectedHost.value?.host_id;
  if (!hostId || overrideSaving.value || identityRefreshing.value) return;
  overrideSaving.value = true;
  try {
    await store.setNetworkIdentityOverride(hostId, ip);
    if (disposed || !drawerVisible.value || selectedHost.value?.host_id !== hostId) return;
    ipOverride.value = ip ?? "";
    ElMessage.success(t("map.fixedIpSaved"));
  } catch (error) {
    if (!disposed && drawerVisible.value && selectedHost.value?.host_id === hostId) {
      ElMessage.error(fleetRequestError(error) || t("map.fixedIpInvalid"));
    }
  } finally {
    overrideSaving.value = false;
  }
}

function startLocationEdit(name: string, location?: FleetLocation | null) {
  editorKey.value++;
  locationForm.value = {
    name,
    city: location?.city ?? "",
    region: location?.region ?? "",
    country: location?.country ?? "",
    country_code: location?.country_code ?? "",
    latitude: location?.latitude ?? 0,
    longitude: location?.longitude ?? 0,
  };
  suggesting.value = false;
  savingLocation.value = false;
  locationEditing.value = true;
}

function openCenterEditor(suggest = false) {
  const center = store.snapshot?.center;
  drawerMode.value = "center";
  drawerHostIds.value = [];
  selectedHostId.value = "";
  locationTarget.value = "center";
  locationHostIds.value = [];
  startLocationEdit(center?.name || "Fleetge Control Center", center);
  drawerVisible.value = true;
  if (suggest) void suggestCurrentLocation();
}

function beginLocationEdit(hosts: FleetMapHost[]) {
  const source = hosts.find((host) => host.location) || hosts[0];
  if (!source) return;
  locationTarget.value = "hosts";
  locationHostIds.value = hosts.map((host) => host.host_id);
  startLocationEdit(hosts.length > 1 ? clusterLocationLabel(hosts) : source.display_name, source.location);
}

function cancelLocationEdit() {
  if (drawerMode.value === "center") drawerVisible.value = false;
  locationEditing.value = false;
}

function isCurrentEdit(draft: FleetLocationDraft) {
  return !disposed && drawerVisible.value && locationEditing.value && locationForm.value === draft;
}

async function suggestCurrentLocation() {
  if (suggesting.value || savingLocation.value) return;
  const draft = locationForm.value;
  const { city, latitude, longitude } = draft;
  const hostId = locationHostIds.value[0];
  const isCenter = locationTarget.value === "center";
  if (!isCenter && !hostId) return;
  suggesting.value = true;
  try {
    const suggestion = isCenter ? await store.suggestCenterLocation() : await store.suggestLocation(hostId);
    if (!isCurrentEdit(draft) || draft.city !== city || draft.latitude !== latitude || draft.longitude !== longitude) return;
    Object.assign(draft, {
      city: suggestion.city ?? "",
      region: suggestion.region ?? "",
      country: suggestion.country ?? "",
      country_code: suggestion.country_code ?? "",
      latitude: suggestion.latitude,
      longitude: suggestion.longitude,
    });
  } catch {
    // The editor retains its manual coordinates when no location can be suggested.
  } finally {
    if (locationForm.value === draft) suggesting.value = false;
  }
}

async function saveLocation() {
  if (savingLocation.value || suggesting.value) return;
  const draft = locationForm.value;
  const { name, city, region, country, country_code, latitude, longitude } = draft;
  if (latitude === undefined || longitude === undefined || !Number.isFinite(latitude) || !Number.isFinite(longitude)
    || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
    ElMessage.error(t("map.invalidCoordinates"));
    return;
  }
  const isCenter = locationTarget.value === "center";
  const hostIds = locationHostIds.value;
  const data = { city, region, country, country_code, latitude, longitude, confirmed: true };
  savingLocation.value = true;
  try {
    if (isCenter) {
      await store.saveCenterSettings({ ...data, name });
    } else {
      const results = await Promise.allSettled(hostIds.map((hostId) =>
        store.updateLocation(hostId, { ...data, source: "manual" }),
      ));
      const failure = results.find((result) => result.status === "rejected");
      if (failure) throw failure.reason;
    }
    if (!isCurrentEdit(draft)) return;
    cancelLocationEdit();
    ElMessage.success(hostIds.length > 1 ? t("map.multiLocationSaved", { count: hostIds.length }) : t("map.locationSaved"));
  } catch (error) {
    if (isCurrentEdit(draft)) ElMessage.error(fleetRequestError(error, true) || t("map.locationSaveFailed"));
  } finally {
    if (locationForm.value === draft) savingLocation.value = false;
  }
}

watch(
  () => drawerVisible.value ? selectedHost.value?.host_id : undefined,
  (hostId) => {
    stopIdentityRefresh();
    if (!hostId) return;
    ipOverride.value = networkIdentity.value?.fixedOverride || "";
    if (!networkIdentity.value) void refreshIdentity(false);
  },
);

onBeforeUnmount(() => {
  disposed = true;
  stopIdentityRefresh();
});

defineExpose({ openMapSelection, beginLocationEdit, openCenterEditor });
</script>

<style scoped>
:global(.fleet-inspector.el-drawer) { border-left: 1px solid var(--border-subtle); background: var(--surface-base) !important; box-shadow: -18px 0 48px rgba(2,6,23,.24); }
:global(.fleet-inspector .el-drawer__body) { padding: 0; overflow: hidden; }
.inspector-shell { display: grid; grid-template-rows: auto minmax(0,1fr); height: 100%; color: var(--text-primary); background: var(--surface-base); }
.inspector-header { display: grid; grid-template-columns: auto auto minmax(0,1fr) auto; align-items: center; gap: 11px; padding: 15px 16px; border-bottom: 1px solid var(--border-subtle); background: color-mix(in srgb, var(--surface-panel) 92%, transparent); -webkit-backdrop-filter: blur(18px); backdrop-filter: blur(18px); }
.inspector-header:not(:has(.inspector-back)) { grid-template-columns: auto minmax(0,1fr) auto; }
.inspector-mark { display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid color-mix(in srgb, var(--accent-cyan) 35%, var(--border-subtle)); border-radius: var(--ui-radius-lg); color: var(--accent-cyan); background: color-mix(in srgb, var(--accent-cyan) 10%, var(--surface-panel-raised)); }
.inspector-mark.degraded { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 35%, var(--border-subtle)); background: color-mix(in srgb, var(--warning) 9%, var(--surface-panel-raised)); }
.inspector-mark.offline,.inspector-mark.unknown { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 35%, var(--border-subtle)); background: color-mix(in srgb, var(--danger) 9%, var(--surface-panel-raised)); }
.inspector-mark.center { color: var(--accent-blue); border-color: color-mix(in srgb, var(--accent-blue) 35%, var(--border-subtle)); background: color-mix(in srgb, var(--accent-blue) 10%, var(--surface-panel-raised)); }
.inspector-heading { min-width: 0; }
.inspector-kicker,.inspector-section-heading span { color: var(--accent-blue); font: 700 var(--text-2xs)/1.2 var(--font-mono); letter-spacing: .13em; }
.inspector-heading h2 { overflow: hidden; margin: 4px 0 2px; color: var(--text-primary); font-size: var(--title-sm); text-overflow: ellipsis; white-space: nowrap; }
.inspector-heading p { overflow: hidden; margin: 0; color: var(--text-muted); font-size: var(--text-xs); text-overflow: ellipsis; white-space: nowrap; }
.inspector-scroll { display: grid; align-content: start; gap: 12px; min-height: 0; overflow: auto; padding: 14px; }
.inspector-actions { display: grid; grid-template-columns: 1fr 1.35fr; gap: 8px; }
.inspector-panel { overflow: visible; padding: 14px; border: 1px solid var(--border-subtle); border-radius: var(--ui-radius-lg); background: var(--surface-panel); }
.inspector-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.inspector-section-heading h3,.location-overview h3 { margin: 4px 0 0; color: var(--text-primary); font-size: var(--text-base); }
.inspector-section-heading b { display: grid; place-items: center; min-width: 26px; height: 26px; padding: 0 7px; border: 1px solid var(--border-subtle); border-radius: var(--ui-radius-md); color: var(--accent-blue); background: var(--surface-panel-raised); font: 700 var(--text-xs) var(--font-mono); }
.metric-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 7px; }
.metric-grid article { padding: 11px 9px; border: 1px solid var(--border-subtle); border-radius: var(--ui-radius-md); background: var(--surface-panel-raised); }
.metric-grid span { display: block; color: var(--text-muted); font-size: var(--text-2xs); }
.metric-grid strong { display: block; margin-top: 6px; color: var(--text-primary); font: 700 16px var(--font-mono); }
.drawer-meta { display: flex; gap: 15px; margin-top: 11px; padding-top: 11px; border-top: 1px solid var(--border-subtle); color: var(--text-muted); font-size: var(--text-xs); }
.drawer-meta span { display: flex; align-items: center; gap: 5px; }
.identity-panel { display:grid; gap:11px; }
.identity-confidence { padding:4px 7px; border-radius:999px; color:var(--accent-cyan); background:color-mix(in srgb,var(--accent-cyan) 10%,transparent); font:700 var(--text-2xs) var(--font-mono); }
.identity-confidence.conflict { color:var(--warning); background:color-mix(in srgb,var(--warning) 10%,transparent); }
.identity-effective { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:4px 10px; padding:11px; border:1px solid var(--border-subtle); border-radius:var(--ui-radius-md); background:var(--surface-panel-raised); }
.identity-effective span,.identity-effective small { color:var(--text-muted); font-size:var(--text-2xs); }.identity-effective strong{font:700 var(--text-sm) var(--font-mono)}.identity-effective small{grid-column:1/-1}
.identity-evidence-list{display:grid;gap:6px}.identity-evidence-row{display:grid;grid-template-columns:90px minmax(0,1fr);gap:5px 9px;padding:8px;border-bottom:1px solid var(--border-subtle)}.identity-evidence-row div{display:grid}.identity-evidence-row small{color:var(--text-muted);font-size:var(--text-2xs)}.identity-evidence-row code{overflow:hidden;color:var(--text-secondary);font-size:var(--text-2xs);text-overflow:ellipsis}.identity-reason{grid-column:2}
.identity-override-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.identity-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.identity-checked{display:flex;align-items:center;gap:4px;margin-left:auto;color:var(--text-muted);font-size:var(--text-2xs)}
.identity-drift{display:flex;align-items:center;gap:7px;padding:8px;border-radius:var(--ui-radius-md);color:var(--warning);background:color-mix(in srgb,var(--warning) 8%,transparent);font-size:var(--text-xs)}
.status-pill { padding: 5px 8px; border-radius: 999px; color: var(--accent-cyan) !important; background: color-mix(in srgb, var(--accent-cyan) 10%, transparent); letter-spacing: 0 !important; }
.status-pill.degraded { color: var(--warning) !important; background: color-mix(in srgb, var(--warning) 10%, transparent); }
.status-pill.offline,.status-pill.unknown { color: var(--danger) !important; background: color-mix(in srgb, var(--danger) 10%, transparent); }
.cluster-status-summary { display: flex; flex-wrap: wrap; gap: 12px; color: var(--text-secondary); font-size: var(--text-xs); }
.cluster-status-summary span { display: flex; align-items: center; gap: 5px; }
.cluster-status-summary strong { color: var(--text-primary); font-family: var(--font-mono); }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); }.status-dot.online{background:var(--accent-cyan)}.status-dot.degraded{background:var(--warning)}.status-dot.offline{background:var(--danger)}
.location-overview { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.cluster-host-list { display: grid; margin: 0 -6px -6px; }
.cluster-host-row { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto; align-items: center; gap: 10px; width: 100%; padding: 11px 7px; border: 0; border-top: 1px solid var(--border-subtle); color: var(--text-primary); background: transparent; text-align: left; cursor: pointer; }
.cluster-host-row:hover { background: var(--ui-control-hover-bg); }
.cluster-host-copy,.cluster-host-metric { display: grid; min-width: 0; }
.cluster-host-copy strong { overflow: hidden; font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.cluster-host-copy small,.cluster-host-metric small { margin-top: 3px; color: var(--text-muted); font-size: var(--text-2xs); }
.cluster-host-metric { justify-items: end; }.cluster-host-metric strong { margin-top: 2px; font: 700 var(--text-sm) var(--font-mono); }
.stack-list { display: grid; gap: 7px; }
.stack-item { overflow: hidden; border: 1px solid var(--border-subtle); border-radius: var(--ui-radius-md); background: var(--surface-panel-raised); }
.stack-item summary { display: grid; grid-template-columns: auto minmax(0,1fr) auto auto; align-items: center; gap: 9px; padding: 10px; cursor: pointer; list-style: none; }
.stack-item summary::-webkit-details-marker { display: none; }.stack-item summary strong{overflow:hidden;font-size:var(--text-sm);text-overflow:ellipsis}.stack-item summary small{color:var(--text-muted);font:var(--text-2xs) var(--font-mono)}.stack-item[open] summary svg{transform:rotate(90deg)}
.stack-indicator,.service-state,.host-state { width: 7px; height: 7px; border-radius: 50%; background: var(--text-muted); }.stack-indicator.running,.service-state.running,.host-state.online{background:var(--accent-cyan)}.host-state.degraded{background:var(--warning)}.stack-indicator.stopped,.service-state.exited,.host-state.offline{background:var(--danger)}
.service-list { display: grid; gap: 5px; padding: 0 8px 8px; }.fleet-service-row{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;padding:8px;border-radius:var(--ui-radius-sm);background:var(--surface-muted)}.fleet-service-row strong,.fleet-service-row small{display:block}.fleet-service-row strong{font-size:var(--text-xs)}.fleet-service-row small{margin-top:2px;color:var(--text-muted);font-size:var(--text-2xs)}
.drawer-empty { padding: 28px; color: var(--text-muted); text-align: center; font-size: var(--text-sm); }
.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none!important}}
@media (max-width:900px) {
  .metric-grid { grid-template-columns:repeat(2,1fr); }
  :global(.fleet-inspector.el-drawer) { border-top:1px solid var(--border-subtle); border-left:0; border-radius:var(--ui-radius-lg) var(--ui-radius-lg) 0 0; }
  .inspector-scroll { padding-bottom:calc(14px + var(--safe-area-bottom)); }
}
@media (max-width:640px) {
  .inspector-actions { grid-template-columns:1fr; }
  .cluster-host-row { grid-template-columns:auto minmax(0,1fr) auto; }
  .cluster-host-metric { display:none; }
}
</style>

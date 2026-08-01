<template>
  <div class="fleet-map-view" :class="{ 'is-theme-dark': isDarkTheme }">
    <section class="fleet-map-hero ui-panel">
      <div>
        <div class="fleet-map-eyebrow">{{ t("map.eyebrow") }}</div>
        <h2>{{ t("map.title") }}</h2>
        <p>{{ t("map.description") }}</p>
      </div>
      <button class="ui-button ui-button--large center-config-button" type="button" @click="openCenterEditor">
        <Crosshair :size="17" />
        {{ store.snapshot?.center.confirmed ? t("map.centerLocation") : t("map.configureCenter") }}
      </button>
    </section>

    <section class="fleet-summary" :aria-label="t('map.summaryAria')">
      <button
        v-for="item in summaryItems"
        :key="item.key"
        class="summary-card"
        :class="['tone-' + item.tone, { active: store.filter === item.key }]"
        type="button"
        @click="store.filter = item.key"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
      </button>
      <label class="issue-toggle">
        <input v-model="store.onlyIssues" type="checkbox" />
        <span>{{ t("map.onlyIssues") }}</span>
      </label>
    </section>

    <section class="map-workspace ui-panel" :class="{ 'has-unlocated': store.unlocatedHosts.length > 0 }">
      <div class="map-stage">
        <FleetGeoMap
          :center="store.snapshot?.center || null"
          :hosts="store.hosts"
          @select="openMapSelection"
        />
        <div class="map-legend" :aria-label="t('map.legendAria')">
          <span><i class="legend-dot online"></i>{{ t("map.online") }}</span>
          <span><i class="legend-dot degraded"></i>{{ t("map.issues") }}</span>
          <span><i class="legend-dot offline"></i>{{ t("map.offline") }}</span>
          <span><i class="legend-ring"></i>{{ t("map.pending") }}</span>
        </div>
        <div v-if="store.loading && !store.snapshot" class="map-empty">
          <LoaderCircle class="spin" :size="26" />
          <span>{{ t("map.buildingTopology") }}</span>
        </div>
        <div v-else-if="store.error" class="map-empty error">
          <TriangleAlert :size="24" />
          <span>{{ store.error }}</span>
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

    <el-drawer
      v-model="drawerVisible"
      class="fleet-inspector"
      :direction="isMobile ? 'btt' : 'rtl'"
      :size="isMobile ? '86vh' : 'min(520px, 100vw)'"
      :with-header="false"
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
          <section v-if="locationEditing" class="inspector-panel location-editor-panel">
            <div class="inspector-section-heading">
              <div>
                <span>{{ t("map.locationKicker") }}</span>
                <h3>{{ locationTarget === "center" ? t("map.centerLocation") : locationHostIds.length > 1 ? t("map.setSharedLocation") : t("map.editHostLocation") }}</h3>
              </div>
              <MapPinned :size="18" />
            </div>
            <div class="location-form">
              <label v-if="locationTarget === 'center'">
                <span>{{ t("map.centerName") }}</span>
                <el-input v-model="locationForm.name" />
              </label>
              <label>
                <span>{{ t("map.city") }}</span>
                <div class="city-search">
                  <el-input v-model="locationForm.city" :placeholder="t('map.cityPlaceholder')" @input="handleCityInput" />
                  <div v-if="citySearching || cityResults.length" class="city-results">
                    <div v-if="citySearching" class="city-searching"><LoaderCircle class="spin" :size="14" />{{ t("map.searchingCity") }}</div>
                    <button v-for="result in cityResults" :key="`${result.latitude}-${result.longitude}-${result.name}`" type="button" @click="selectCityResult(result)">
                      <strong>{{ result.name }}</strong>
                      <small>{{ [result.region, result.country].filter(Boolean).join(" · ") }} · {{ result.latitude.toFixed(4) }}, {{ result.longitude.toFixed(4) }}</small>
                    </button>
                  </div>
                </div>
              </label>
              <div class="coordinate-row">
                <label><span>{{ t("map.latitude") }}</span><el-input-number v-model="locationForm.latitude" :min="-90" :max="90" :precision="6" controls-position="right" /></label>
                <label><span>{{ t("map.longitude") }}</span><el-input-number v-model="locationForm.longitude" :min="-180" :max="180" :precision="6" controls-position="right" /></label>
              </div>
              <div class="location-hint"><ShieldCheck :size="17" />{{ t("map.ipLocationHint") }}</div>
              <div class="location-editor-actions">
                <button v-if="locationTarget === 'center' || locationHostIds.length === 1" class="ui-button" type="button" :disabled="suggesting" @click="suggestCurrentLocation">
                  <LoaderCircle v-if="suggesting" class="spin" :size="15" /><LocateFixed v-else :size="15" />{{ t("map.autoSuggest") }}
                </button>
                <span class="action-spacer"></span>
                <button class="ui-button" type="button" @click="cancelLocationEdit">{{ t("map.cancel") }}</button>
                <button class="ui-button ui-button--primary" type="button" :disabled="savingLocation" @click="saveLocation">
                  <LoaderCircle v-if="savingLocation" class="spin" :size="15" />{{ t("map.saveLocation") }}
                </button>
              </div>
            </div>
          </section>

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
              <button class="ui-button ui-button--primary" type="button" @click="router.push('/hosts/' + selectedHost.host_id)"><ExternalLink :size="15" />{{ t("map.openHostDetail") }}</button>
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
                <el-input v-model="ipOverride" :placeholder="t('map.fixedIpPlaceholder')" clearable />
                <button class="ui-button" type="button" :disabled="overrideSaving" @click="saveIpOverride">{{ t("map.applyFixedIp") }}</button>
              </div>
              <div class="identity-actions">
                <button class="ui-button" type="button" :disabled="identityRefreshing" @click="refreshIdentity(true)">
                  <LoaderCircle v-if="identityRefreshing" class="spin" :size="14" />
                  <LocateFixed v-else :size="14" />{{ t("map.refreshIdentity") }}
                </button>
                <button v-if="networkIdentity?.fixedOverride" class="ui-button" type="button" :disabled="overrideSaving" @click="clearIpOverride">{{ t("map.clearFixedIp") }}</button>
                <span v-if="networkIdentity?.observedAt" class="identity-checked"><Clock3 :size="13" />{{ formatTime(networkIdentity.observedAt) }}</span>
              </div>
            </section>
            <section class="inspector-panel">
              <div class="inspector-section-heading"><div><span>{{ t("map.stacksKicker") }}</span><h3>{{ t("map.appStacks") }}</h3></div><b>{{ selectedHost.stacks.length }}</b></div>
              <div v-if="selectedHost.stacks.length" class="stack-list">
                <details v-for="stack in selectedHost.stacks" :key="stack.name" class="stack-item">
                  <summary><span class="stack-indicator" :class="stack.status"></span><strong>{{ stack.name }}</strong><small>{{ stack.running_count }} / {{ stack.service_count }}</small><ChevronRight :size="15" /></summary>
                  <div class="service-list"><div v-for="service in stack.services" :key="service.container_id || service.name" class="service-row"><span class="service-state" :class="service.state"></span><span><strong>{{ service.name }}</strong><small>{{ service.status || service.state }}</small></span></div></div>
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
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  Activity, ArrowLeft, ChevronRight, Clock3, Crosshair, ExternalLink, LoaderCircle,
  LocateFixed, MapPinned, Server, ShieldCheck, TriangleAlert, Users, X,
} from "lucide-vue-next";
import { ElMessage } from "element-plus";
import FleetGeoMap from "@/components/FleetGeoMap.vue";
import { useMobile } from "@/composables/useMobile";
import { useTheme } from "@/composables/useTheme";
import { useFleetMapStore, type FleetLocationSearchResult, type FleetMapHost } from "@/stores/fleetMap";

const router = useRouter();
const store = useFleetMapStore();
const { isMobile } = useMobile(899);
const { t, locale } = useI18n();
const theme = useTheme();
const isDarkTheme = computed(() => theme.current.value === "dark");
const drawerVisible = ref(false);
const drawerMode = ref<"selection" | "center">("selection");
const drawerHostIds = ref<string[]>([]);
const selectedHostId = ref("");
const locationEditing = ref(false);
const locationTarget = ref<"center" | "hosts">("hosts");
const locationHostIds = ref<string[]>([]);
const suggesting = ref(false);
const savingLocation = ref(false);
const autoLocating = ref(false);
const citySearching = ref(false);
const identityRefreshing = ref(false);
const overrideSaving = ref(false);
const ipOverride = ref("");
const cityResults = ref<FleetLocationSearchResult[]>([]);
let citySearchTimer: ReturnType<typeof setTimeout> | null = null;
const locationForm = reactive({
  name: "Fleetge Control Center",
  city: "",
  region: "",
  country: "",
  country_code: "",
  latitude: 0,
  longitude: 0,
});

const selectedHost = computed(() =>
  store.snapshot?.hosts.find((host) => host.host_id === selectedHostId.value) || null
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
  if (drawerMode.value === "center") return locationForm.name || "Fleetge Control Center";
  if (selectedHost.value) return selectedHost.value.display_name;
  if (drawerHosts.value.length) return clusterLocationLabel(drawerHosts.value);
  return t("map.inspectorTitle");
});
const inspectorSubtitle = computed(() => {
  if (drawerMode.value === "center") return [locationForm.city, locationForm.region, locationForm.country].filter(Boolean).join(" · ") || t("map.configureCenterLocation");
  if (selectedHost.value) return locationLabel(selectedHost.value);
  return `${t("map.hostCount", { count: drawerHosts.value.length })} · ${t("map.onlineCount", { count: clusterCounts.value.online })} · ${t("map.issueCount", { count: clusterCounts.value.degraded + clusterCounts.value.offline })}`;
});

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

function statusLabel(status: FleetMapHost["status"]) {
  if (status === "online") return t("map.online");
  if (status === "degraded") return t("map.issues");
  if (status === "offline") return t("map.offline");
  return t("map.unknown");
}

function openMapSelection(hosts: FleetMapHost[]) {
  drawerMode.value = "selection";
  drawerHostIds.value = hosts.map((host) => host.host_id);
  selectedHostId.value = hosts.length === 1 ? hosts[0].host_id : "";
  locationEditing.value = false;
  drawerVisible.value = true;
}

function openUnlocatedHost(host: FleetMapHost) {
  openMapSelection([host]);
  beginLocationEdit([host]);
}

function resetInspector() {
  drawerHostIds.value = [];
  selectedHostId.value = "";
  locationHostIds.value = [];
  locationEditing.value = false;
  cityResults.value = [];
}

function metricValue(metrics: Record<string, any> | null | undefined, camel: string, snake: string) {
  return Number(metrics?.[camel] ?? metrics?.[snake] ?? 0);
}

function metricPercent(metrics: Record<string, any> | null | undefined, camel: string, snake: string) {
  return metricValue(metrics, camel, snake).toFixed(1) + "%";
}

function memoryPercent(metrics: Record<string, any> | null | undefined) {
  const used = metricValue(metrics, "memoryUsed", "memory_used");
  const total = metricValue(metrics, "memoryTotal", "memory_total");
  return total ? ((used / total) * 100).toFixed(1) + "%" : "—";
}

function diskPercent(metrics: Record<string, any> | null | undefined) {
  const used = metricValue(metrics, "diskUsed", "disk_used");
  const total = metricValue(metrics, "diskTotal", "disk_total");
  return total ? ((used / total) * 100).toFixed(1) + "%" : "—";
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: "short", timeStyle: "medium" }).format(new Date(value));
}

async function refreshIdentity(force = true) {
  if (!selectedHost.value || identityRefreshing.value) return;
  identityRefreshing.value = true;
  try {
    const evidence = await store.refreshNetworkIdentity(selectedHost.value.host_id, force);
    ipOverride.value = evidence.fixedOverride || "";
    if (force) ElMessage.success(t("map.identityRefreshed"));
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t("map.identityRefreshFailed"));
  } finally {
    identityRefreshing.value = false;
  }
}

async function saveIpOverride() {
  if (!selectedHost.value) return;
  overrideSaving.value = true;
  try {
    await store.setNetworkIdentityOverride(selectedHost.value.host_id, ipOverride.value.trim() || null);
    ElMessage.success(t("map.fixedIpSaved"));
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || t("map.fixedIpInvalid"));
  } finally {
    overrideSaving.value = false;
  }
}

async function clearIpOverride() {
  ipOverride.value = "";
  await saveIpOverride();
}

function openCenterEditor() {
  const center = store.snapshot?.center;
  drawerMode.value = "center";
  drawerHostIds.value = [];
  selectedHostId.value = "";
  locationTarget.value = "center";
  locationHostIds.value = [];
  locationForm.name = center?.name || "Fleetge Control Center";
  locationForm.city = center?.city || "";
  locationForm.region = center?.region || "";
  locationForm.country = center?.country || "";
  locationForm.country_code = center?.country_code || "";
  locationForm.latitude = center?.latitude || 0;
  locationForm.longitude = center?.longitude || 0;
  cityResults.value = [];
  locationEditing.value = true;
  drawerVisible.value = true;
}

function beginLocationEdit(hosts: FleetMapHost[]) {
  const source = hosts.find((host) => host.location) || hosts[0];
  if (!source) return;
  locationTarget.value = "hosts";
  locationHostIds.value = hosts.map((host) => host.host_id);
  locationForm.name = hosts.length > 1 ? clusterLocationLabel(hosts) : source.display_name;
  locationForm.city = source.location?.city || "";
  locationForm.region = source.location?.region || "";
  locationForm.country = source.location?.country || "";
  locationForm.country_code = source.location?.country_code || "";
  locationForm.latitude = source.location?.latitude || 0;
  locationForm.longitude = source.location?.longitude || 0;
  cityResults.value = [];
  locationEditing.value = true;
}

function cancelLocationEdit() {
  cityResults.value = [];
  if (drawerMode.value === "center") {
    drawerVisible.value = false;
  } else {
    locationEditing.value = false;
  }
}

function handleCityInput(value: string) {
  cityResults.value = [];
  if (citySearchTimer) clearTimeout(citySearchTimer);
  if (value.trim().length < 2) return;
  citySearchTimer = setTimeout(async () => {
    citySearching.value = true;
    try {
      cityResults.value = await store.searchLocations(value.trim(), locale.value === "zh-CN" ? "zh" : "en");
    } catch {
      cityResults.value = [];
    } finally {
      citySearching.value = false;
    }
  }, 280);
}

function selectCityResult(result: FleetLocationSearchResult) {
  locationForm.city = result.city || result.name;
  locationForm.region = result.region || "";
  locationForm.country = result.country || "";
  locationForm.country_code = result.country_code || "";
  locationForm.latitude = result.latitude;
  locationForm.longitude = result.longitude;
  cityResults.value = [];
  ElMessage.success(t("map.cityMatched"));
}

async function autoLocateUnlocatedHosts() {
  if (autoLocating.value) return;
  autoLocating.value = true;
  const pending = [...store.unlocatedHosts];
  let located = 0;
  for (const host of pending) {
    try {
      await store.suggestLocation(host.host_id);
      located += 1;
    } catch {
      // Private IPs and failed DNS lookups stay in the manual list.
    }
  }
  autoLocating.value = false;
  if (located) ElMessage.success(t("map.autoLocatedSuccess", { count: located }));
  else ElMessage.info(t("map.autoLocatedEmpty"));
}

async function suggestCurrentLocation() {
  suggesting.value = true;
  try {
    let suggestion: any;
    if (locationTarget.value === "hosts") {
      const hostId = locationHostIds.value[0];
      if (!hostId) throw new Error(t("map.noLocatableHost"));
      suggestion = await store.suggestLocation(hostId);
    } else {
      suggestion = await store.suggestCenterLocation();
    }
    locationForm.city = suggestion.city || "";
    locationForm.region = suggestion.region || "";
    locationForm.country = suggestion.country || "";
    locationForm.country_code = suggestion.country_code || "";
    locationForm.latitude = Number(suggestion.latitude);
    locationForm.longitude = Number(suggestion.longitude);
    ElMessage.success(t("map.suggestionReady"));
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || t("map.suggestionUnavailable"));
  } finally {
    suggesting.value = false;
  }
}

async function saveLocation() {
  if (!Number.isFinite(locationForm.latitude) || !Number.isFinite(locationForm.longitude)) {
    ElMessage.error(t("map.invalidCoordinates"));
    return;
  }
  savingLocation.value = true;
  try {
    if (locationTarget.value === "center") {
      await store.saveCenterSettings({
        name: locationForm.name,
        city: locationForm.city,
        region: locationForm.region,
        country: locationForm.country,
        country_code: locationForm.country_code,
        latitude: locationForm.latitude,
        longitude: locationForm.longitude,
        confirmed: true,
      });
    } else {
      await Promise.all(locationHostIds.value.map((hostId) => store.updateLocation(hostId, {
          city: locationForm.city,
          region: locationForm.region,
          country: locationForm.country,
          country_code: locationForm.country_code,
          latitude: locationForm.latitude,
          longitude: locationForm.longitude,
          source: "manual",
          confirmed: true,
        })));
    }
    if (locationTarget.value === "center") drawerVisible.value = false;
    else locationEditing.value = false;
    ElMessage.success(locationHostIds.value.length > 1 ? t("map.multiLocationSaved", { count: locationHostIds.value.length }) : t("map.locationSaved"));
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || t("map.locationSaveFailed"));
  } finally {
    savingLocation.value = false;
  }
}

onMounted(() => {
  store.startPolling();
  const stop = watch(
    () => store.snapshot,
    (snapshot) => {
      if (!snapshot) return;
      if (!snapshot.center.confirmed) {
        openCenterEditor();
        void suggestCurrentLocation();
      }
      void autoLocateUnlocatedHosts();
      stop();
    },
  );
});

watch(
  () => selectedHost.value?.host_id,
  (hostId) => {
    if (!hostId) return;
    ipOverride.value = networkIdentity.value?.fixedOverride || "";
    if (!networkIdentity.value) void refreshIdentity(false);
  },
);

onBeforeUnmount(() => {
  store.stopPolling();
  if (citySearchTimer) clearTimeout(citySearchTimer);
});
</script>

<style scoped>
.fleet-map-view { display: grid; gap: 16px; min-width: 0; }
.fleet-map-hero { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 22px 24px; border: 1px solid rgba(96,165,250,.14); background: linear-gradient(115deg, rgba(15,32,53,.92), rgba(5,11,23,.9)); }
.fleet-map-eyebrow,.panel-kicker,.drawer-kicker { color: #60a5fa; font: 700 10px/1.2 "JetBrains Mono",monospace; letter-spacing: .16em; }
.fleet-map-hero h2 { margin: 5px 0 5px; font-size: clamp(24px,3vw,34px); color: var(--text-primary); }
.fleet-map-hero p { margin: 0; color: var(--text-secondary); font-size: 13px; }
.fleet-summary { display: grid; grid-template-columns: repeat(5,minmax(95px,1fr)) auto; gap: 10px; }
.summary-card { position: relative; display: flex; align-items: center; justify-content: space-between; min-height: 62px; padding: 11px 15px; border: 1px solid var(--border-subtle); border-radius: var(--ui-radius-lg); color: var(--text-secondary); background: var(--surface-panel); cursor: pointer; overflow: hidden; }
.summary-card::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:#64748b; opacity:.6; }
.summary-card strong { color: var(--text-primary); font: 700 24px/1 "JetBrains Mono",monospace; }
.summary-card.active { border-color: rgba(96,165,250,.45); box-shadow: 0 0 0 1px rgba(96,165,250,.12) inset; }
.summary-card.tone-online::before { background:#22d3ee; }.summary-card.tone-degraded::before{background:#fbbf24}.summary-card.tone-unlocated::before{background:#a78bfa}
.summary-card.tone-offline::before{background:#f87171}
.issue-toggle { display:flex; align-items:center; gap:9px; padding:0 14px; border:1px solid var(--border-subtle); border-radius:var(--ui-radius-lg); color:var(--text-secondary); background:var(--surface-panel); cursor:pointer; white-space:nowrap; }
.issue-toggle input { accent-color:#fbbf24; }
.map-workspace { display:grid; grid-template-columns:minmax(0,1fr); min-height:620px; padding:0; overflow:hidden; background:#050b16; border:1px solid rgba(96,165,250,.13); }
.map-workspace.has-unlocated { grid-template-columns:minmax(0,1fr) 260px; }
.map-stage { position:relative; min-height:620px; overflow:hidden; }
.map-legend { position:absolute; z-index:500; left:18px; bottom:16px; display:flex; gap:13px; flex-wrap:wrap; padding:9px 11px; border:1px solid rgba(148,163,184,.15); border-radius:8px; color:#94a3b8; background:rgba(4,9,18,.82); backdrop-filter:blur(12px); font-size:11px; }
.map-legend span { display:flex; align-items:center; gap:6px; }.legend-dot,.legend-ring{width:8px;height:8px;border-radius:50%;display:inline-block}.legend-dot.online{background:#22d3ee;box-shadow:0 0 9px #22d3ee}.legend-dot.degraded{background:#fbbf24}.legend-dot.offline{background:#f87171}.legend-ring{border:1px dashed #93c5fd}
.map-empty { position:absolute; z-index:600; inset:0; display:grid; place-content:center; gap:10px; text-align:center; color:#94a3b8; background:rgba(4,9,18,.5); }.map-empty.error{color:#fca5a5}.map-empty button{color:#bfdbfe;background:none;border:0;cursor:pointer}
.unlocated-panel { border-left:1px solid rgba(148,163,184,.12); padding:17px 13px; background:linear-gradient(180deg,rgba(10,20,34,.96),rgba(5,11,21,.98)); overflow:auto; }
.panel-heading { display:flex; align-items:center; justify-content:space-between; padding:4px 5px 14px; }.panel-heading h3{margin:4px 0 0;color:#e2e8f0;font-size:15px}.panel-count{display:grid;place-items:center;min-width:28px;height:28px;border-radius:8px;color:#c4b5fd;background:rgba(139,92,246,.12);font:700 12px "JetBrains Mono",monospace}
.panel-empty{display:grid;place-items:center;gap:9px;padding:42px 10px;color:#64748b;font-size:12px;text-align:center}
.unlocated-host { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:10px; width:100%; padding:11px 8px; border:0; border-top:1px solid rgba(148,163,184,.08); color:#cbd5e1; background:transparent; text-align:left; cursor:pointer; }.unlocated-host:hover{background:rgba(96,165,250,.06)}.unlocated-host strong,.unlocated-host small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.unlocated-host strong{font-size:12px}.unlocated-host small{margin-top:3px;color:#64748b;font-size:10px}.host-state,.service-state,.stack-indicator{width:7px;height:7px;border-radius:50%;background:#64748b}.host-state.online,.service-state.running{background:#22d3ee}.host-state.degraded{background:#fbbf24}.host-state.offline,.service-state.exited{background:#f87171}
:global(.fleet-inspector.el-drawer) { border-left: 1px solid var(--border-subtle); background: var(--surface-base) !important; box-shadow: -18px 0 48px rgba(2,6,23,.24); }
:global(.fleet-inspector .el-drawer__body) { padding: 0; overflow: hidden; }
.inspector-shell { display: grid; grid-template-rows: auto minmax(0,1fr); height: 100%; color: var(--text-primary); background: var(--surface-base); }
.inspector-header { display: grid; grid-template-columns: auto auto minmax(0,1fr) auto; align-items: center; gap: 11px; padding: 15px 16px; border-bottom: 1px solid var(--border-subtle); background: color-mix(in srgb, var(--surface-panel) 92%, transparent); backdrop-filter: blur(18px); }
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
.service-list { display: grid; gap: 5px; padding: 0 8px 8px; }.service-row{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:9px;padding:8px;border-radius:var(--ui-radius-sm);background:var(--surface-muted)}.service-row strong,.service-row small{display:block}.service-row strong{font-size:var(--text-xs)}.service-row small{margin-top:2px;color:var(--text-muted);font-size:var(--text-2xs)}
.drawer-empty { padding: 28px; color: var(--text-muted); text-align: center; font-size: var(--text-sm); }
.location-form { display: grid; gap: 14px; }.location-form label>span{display:block;margin-bottom:6px;color:var(--text-secondary);font-size:var(--text-sm)}.coordinate-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.coordinate-row .el-input-number{width:100%}.location-hint{display:flex;align-items:flex-start;gap:8px;padding:10px;border:1px solid color-mix(in srgb,var(--accent-blue) 22%,var(--border-subtle));border-radius:var(--ui-radius-md);color:var(--text-secondary);background:color-mix(in srgb,var(--accent-blue) 6%,var(--surface-panel-raised));font-size:var(--text-xs);line-height:1.5}.location-editor-actions{display:flex;align-items:center;gap:8px;padding-top:2px}.action-spacer{flex:1}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none!important}}
@media (max-width:899px){.fleet-map-hero{align-items:flex-start;flex-direction:column}.fleet-summary{grid-template-columns:repeat(2,1fr)}.issue-toggle{min-height:48px}.map-workspace{grid-template-columns:1fr}.map-stage{min-height:58vh}.unlocated-panel{max-height:260px;border-top:1px solid rgba(148,163,184,.12);border-left:0}.metric-grid{grid-template-columns:repeat(2,1fr)}}
@media (max-width:899px){:global(.fleet-inspector.el-drawer){border-top:1px solid var(--border-subtle);border-left:0;border-radius:var(--ui-radius-lg) var(--ui-radius-lg) 0 0}.inspector-scroll{padding-bottom:calc(14px + var(--safe-area-bottom))}}
@media (max-width:560px){.fleet-map-hero{padding:18px}.fleet-summary{gap:7px}.summary-card{min-height:54px;padding:9px 11px}.summary-card strong{font-size:20px}.map-legend{right:12px;left:12px}.coordinate-row{grid-template-columns:1fr}.inspector-actions{grid-template-columns:1fr}.location-editor-actions{flex-wrap:wrap}.action-spacer{display:none}.location-editor-actions .ui-button--primary{flex:1}.cluster-host-row{grid-template-columns:auto minmax(0,1fr) auto}.cluster-host-metric{display:none}}
@media (max-width:899px){.map-workspace.has-unlocated{grid-template-columns:1fr}}

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
.fleet-map-hero { background: var(--fleet-hero-bg); border-color: var(--fleet-map-border); box-shadow: var(--fleet-map-shadow); }
.center-config-button { color: var(--accent-blue) !important; background: color-mix(in srgb, var(--accent-blue) 9%, var(--surface-panel)) !important; border-color: color-mix(in srgb, var(--accent-blue) 32%, var(--border-subtle)) !important; }
.map-workspace { background: var(--fleet-map-panel); border-color: var(--fleet-map-border); box-shadow: var(--fleet-map-shadow); }
.map-legend { color: var(--fleet-map-muted); background: var(--fleet-map-overlay); border-color: var(--fleet-map-border); box-shadow: 0 8px 22px rgba(53, 91, 126, .12); }
.map-empty { color: var(--fleet-map-muted); background: color-mix(in srgb, var(--fleet-map-panel) 70%, transparent); }
.map-empty button { color: var(--accent-blue, #2563eb); }
.unlocated-panel { background: linear-gradient(180deg, var(--fleet-map-panel), var(--fleet-map-panel-raised)); border-color: var(--fleet-map-border); }
.panel-heading h3,.unlocated-host { color: var(--fleet-map-ink); }
.unlocated-host { border-color: color-mix(in srgb, var(--fleet-map-border) 70%, transparent); }
.unlocated-host:hover { background: color-mix(in srgb, var(--accent-blue, #2563eb) 8%, transparent); }
.unlocated-host small { color: var(--fleet-map-muted); }
.panel-heading-actions { display: flex; align-items: center; gap: 8px; }
.auto-locate-button { display: inline-flex; align-items: center; gap: 4px; padding: 5px 7px; border: 1px solid var(--fleet-map-border); border-radius: 7px; color: var(--accent-blue, #2563eb); background: transparent; font-size: 10px; cursor: pointer; }
.auto-locate-button:disabled { opacity: .6; cursor: wait; }
.city-search { position: relative; }
.city-results { position: absolute; z-index: 20; top: calc(100% + 5px); right: 0; left: 0; display: grid; gap: 2px; max-height: 238px; overflow: auto; padding: 5px; border: 1px solid var(--fleet-map-border); border-radius: 9px; background: var(--fleet-map-panel); box-shadow: var(--fleet-map-shadow); }
.city-results button { display: grid; gap: 3px; padding: 9px 10px; border: 0; border-radius: 6px; color: var(--fleet-map-ink); background: transparent; text-align: left; cursor: pointer; }
.city-results button:hover { background: color-mix(in srgb, var(--accent-blue, #2563eb) 10%, transparent); }
.city-results strong { font-size: 12px; }
.city-results small,.city-searching { color: var(--fleet-map-muted); font-size: 10px; }
.city-searching { display: flex; align-items: center; gap: 6px; padding: 10px; }
</style>

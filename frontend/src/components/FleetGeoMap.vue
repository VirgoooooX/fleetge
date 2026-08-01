<template>
  <div
    ref="stageElement"
    class="fleet-geo-map"
    :class="[`mode-${interactionMode}`, { 'is-dragging': dragging, 'is-theme-dark': isDarkTheme }]"
  >
    <svg
      ref="svgElement"
      class="fleet-geo-map__svg"
      :viewBox="`0 0 ${size.width} ${size.height}`"
      role="img"
      :aria-label="t('map.globeAria')"
      @wheel.prevent="handleWheel"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
      @pointerleave="handlePointerLeave"
    >
      <g class="map-camera" :transform="cameraTransform">
        <path :d="geometry.sphere" class="map-sphere" />
        <path :d="geometry.graticule" class="map-graticule" />
        <path :d="geometry.land" class="map-land" />
        <path :d="geometry.borders" class="map-borders" />

        <g
          v-if="geometry.centerPoint && center?.confirmed"
          class="fleet-center-node"
          :transform="`translate(${geometry.centerPoint[0]} ${geometry.centerPoint[1]})`"
          aria-hidden="true"
        >
          <circle class="fleet-center-node__halo" :r="15 * inverseScale" />
          <circle class="fleet-center-node__ring" :r="9 * inverseScale" />
          <circle class="fleet-center-node__core" :r="4.5 * inverseScale" />
          <g class="fleet-center-label" aria-hidden="true">
            <path
              class="fleet-center-label__leader"
              :d="`M ${6 * inverseScale} ${-6 * inverseScale} L ${17 * inverseScale} ${-24 * inverseScale} L ${22 * inverseScale} ${-24 * inverseScale}`"
            />
            <rect
              class="fleet-center-label__plate"
              :x="20 * inverseScale"
              :y="-42 * inverseScale"
              :width="centerLabelWidth * inverseScale"
              :height="35 * inverseScale"
              :rx="6 * inverseScale"
            />
            <circle class="fleet-center-label__dot" :cx="31 * inverseScale" :cy="-29.5 * inverseScale" :r="2.4 * inverseScale" />
            <text
              class="fleet-center-label__name"
              :x="39 * inverseScale"
              :y="-26 * inverseScale"
              :font-size="10 * inverseScale"
            >{{ center.name }}</text>
            <text
              class="fleet-center-label__location"
              :x="29 * inverseScale"
              :y="-14 * inverseScale"
              :font-size="8.5 * inverseScale"
            >{{ centerLocationText }}</text>
          </g>
        </g>

        <g
          v-for="cluster in clusters"
          :key="cluster.id"
          :class="[
            cluster.hosts.length > 1 ? 'fleet-host-cluster' : 'fleet-host-node',
            `is-${cluster.primaryStatus}`,
            { 'is-unconfirmed': cluster.hasUnconfirmed },
          ]"
          :transform="`translate(${cluster.point[0]} ${cluster.point[1]})`"
          role="button"
          tabindex="0"
          :aria-label="clusterAriaLabel(cluster.hosts)"
          @mouseenter="showTooltip(cluster.id)"
          @mouseleave="hideTooltip"
          @focus="showTooltip(cluster.id)"
          @blur="hideTooltip"
          @pointerdown.stop
          @click.stop="selectHosts(cluster.hosts)"
          @keydown.enter.prevent="selectHosts(cluster.hosts)"
          @keydown.space.prevent="selectHosts(cluster.hosts)"
        >
          <template v-if="cluster.hosts.length === 1">
            <circle v-if="cluster.hasUnconfirmed" class="fleet-host-node__pending" :r="11.5 * inverseScale" />
            <circle class="fleet-host-node__aura" :r="13 * inverseScale" />
            <circle class="fleet-host-node__ring" :r="8.2 * inverseScale" />
            <circle class="fleet-host-node__core" :r="5 * inverseScale" />
            <circle class="fleet-host-node__highlight" :cx="-1.7 * inverseScale" :cy="-1.8 * inverseScale" :r="1.35 * inverseScale" />
            <g v-if="camera.k >= 2.2" class="fleet-node-label" aria-hidden="true">
              <path class="fleet-node-label__leader" :d="`M ${6 * inverseScale} ${5 * inverseScale} L ${15 * inverseScale} ${12 * inverseScale}`" />
              <rect class="fleet-node-label__plate" :x="14 * inverseScale" :y="6 * inverseScale" :width="cluster.labelWidth * inverseScale" :height="30 * inverseScale" :rx="5 * inverseScale" />
              <text class="fleet-node-label__title" :x="22 * inverseScale" :y="18 * inverseScale" :font-size="9 * inverseScale">{{ cluster.locationText }}</text>
              <text class="fleet-node-label__meta" :x="22 * inverseScale" :y="29 * inverseScale" :font-size="8 * inverseScale">{{ cluster.hosts[0].display_name }}</text>
            </g>
          </template>
          <template v-else>
            <circle v-if="cluster.hasUnconfirmed" class="fleet-host-cluster__pending" :r="17 * inverseScale" />
            <circle class="fleet-host-cluster__aura" :r="18 * inverseScale" />
            <circle class="fleet-host-cluster__track" :r="13 * inverseScale" />
            <circle
              v-for="segment in cluster.segments"
              :key="segment.status"
              class="fleet-host-cluster__segment"
              :class="`is-${segment.status}`"
              :r="13 * inverseScale"
              pathLength="100"
              :stroke-dasharray="`${segment.length} ${100 - segment.length}`"
              :stroke-dashoffset="-segment.offset"
              transform="rotate(-90)"
            />
            <circle class="fleet-host-cluster__core" :r="9.2 * inverseScale" />
            <text class="fleet-host-cluster__count" :font-size="9.5 * inverseScale" :y="3.2 * inverseScale">{{ cluster.hosts.length }}</text>
            <g class="fleet-node-label fleet-node-label--cluster" aria-hidden="true">
              <path class="fleet-node-label__leader" :d="`M ${8 * inverseScale} ${7 * inverseScale} L ${21 * inverseScale} ${13 * inverseScale}`" />
              <rect class="fleet-node-label__plate" :x="20 * inverseScale" :y="7 * inverseScale" :width="cluster.labelWidth * inverseScale" :height="30 * inverseScale" :rx="5 * inverseScale" />
              <text class="fleet-node-label__title" :x="28 * inverseScale" :y="19 * inverseScale" :font-size="9 * inverseScale">{{ cluster.locationText }}</text>
              <text class="fleet-node-label__meta" :x="28 * inverseScale" :y="30 * inverseScale" :font-size="8 * inverseScale">{{ t("map.hostCount", { count: cluster.hosts.length }) }}{{ cluster.hasUnconfirmed ? ` · ${t("map.pending")}` : "" }}</text>
            </g>
          </template>
        </g>
      </g>
    </svg>

    <div class="map-controls" :aria-label="t('map.controlsAria')">
      <button type="button" :aria-label="t('map.zoomIn')" :disabled="camera.k >= MAX_ZOOM" @click="zoomBy(1.35)">+</button>
      <button type="button" :aria-label="t('map.zoomOut')" :disabled="camera.k <= MIN_ZOOM" @click="zoomBy(1 / 1.35)">−</button>
      <button class="map-controls__reset" type="button" :aria-label="t('map.resetView')" @click="resetView">◎</button>
      <button type="button" :aria-label="t('map.fitHosts')" :title="t('map.fitHosts')" @click="fitHostsToView"><Maximize2 :size="15" /></button>
      <button
        class="map-controls__mode"
        type="button"
        :aria-label="interactionMode === 'rotate' ? t('map.switchToPan') : t('map.switchToRotate')"
        :title="interactionMode === 'rotate' ? t('map.currentRotate') : t('map.currentPan')"
        @click="interactionMode = interactionMode === 'rotate' ? 'pan' : 'rotate'"
      >
        <Orbit v-if="interactionMode === 'rotate'" :size="15" />
        <Move v-else :size="15" />
      </button>
    </div>

    <div class="projection-badge"><span></span>{{ projectionLabel }}</div>
    <div class="map-gesture-hint">{{ interactionMode === "rotate" ? t("map.rotateHint") : t("map.panHint") }}</div>

    <div
      v-if="hoveredCluster"
      class="fleet-map-tooltip"
      :style="tooltipStyle"
      role="tooltip"
    >
      <strong>{{ clusterTitle(hoveredCluster.hosts) }}</strong>
      <span>{{ clusterSummary(hoveredCluster.hosts) }}</span>
      <em>{{ hoveredCluster.hosts.length > 1 ? t("map.openCluster") : t("map.openHost") }}</em>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Maximize2, Move, Orbit } from "lucide-vue-next";
import { feature, mesh as topoMesh } from "topojson-client";
import { geoGraticule10, geoPath } from "d3-geo";
import worldTopology from "world-atlas/countries-110m.json";
import type { FleetMapHost, FleetMapSnapshot } from "@/stores/fleetMap";
import { useTheme } from "@/composables/useTheme";
import {
  calculateGeographicFocus,
  clusterProjectedNodes,
  createFleetProjection,
  projectFleetPoint,
} from "@/utils/fleetMap";

const props = defineProps<{
  center: FleetMapSnapshot["center"] | null;
  hosts: FleetMapHost[];
}>();

const emit = defineEmits<{ select: [hosts: FleetMapHost[]] }>();
const { t } = useI18n();
const theme = useTheme();
const isDarkTheme = computed(() => theme.current.value === "dark");

const MIN_ZOOM = 1;
const MAX_ZOOM = 5;
const stageElement = ref<HTMLElement | null>(null);
const svgElement = ref<SVGSVGElement | null>(null);
const size = reactive({ width: 960, height: 620 });
const camera = reactive({ panX: 0, panY: 0, k: 1 });
const rotation = reactive({ longitude: -105, latitude: 0 });
const interactionMode = ref<"rotate" | "pan">("rotate");
const dragging = ref(false);
const dragMoved = ref(false);
const hoveredClusterId = ref("");
let resizeObserver: ResizeObserver | null = null;
let dragPointerId: number | null = null;
let dragStart = { x: 0, y: 0 };
let rotationOrigin = { longitude: -105, latitude: 0 };
let panOrigin = { x: 0, y: 0 };
let activeDragMode: "rotate" | "pan" = "rotate";

const topology = worldTopology as any;
const countries = feature(topology, topology.objects.countries) as any;
const countryBorders = topoMesh(topology, topology.objects.countries, (a, b) => a !== b) as any;

const geometry = computed(() => {
  const projection = createFleetProjection(size.width, size.height, 24, [rotation.longitude, rotation.latitude]);
  const path = geoPath(projection);
  const centerPoint = props.center?.confirmed
    ? projectFleetPoint(projection, [props.center.latitude, props.center.longitude])
    : null;
  const nodes = props.hosts.flatMap((host) => {
    if (!host.location) return [];
    const point = projectFleetPoint(projection, [host.location.latitude, host.location.longitude]);
    return point ? [{ host, point }] : [];
  });
  return {
    sphere: path({ type: "Sphere" }) || "",
    graticule: path(geoGraticule10()) || "",
    land: path(countries) || "",
    borders: path(countryBorders) || "",
    centerPoint,
    nodes,
  };
});

const inverseScale = computed(() => 1 / camera.k);
const centerLocationText = computed(() => {
  const center = props.center;
  if (!center) return t("map.locationNotSet");
  const primary = center.city || center.region || center.country;
  const country = center.country_code || (primary !== center.country ? center.country : "");
  return [primary, country].filter(Boolean).join(" · ") || `${center.latitude.toFixed(2)}, ${center.longitude.toFixed(2)}`;
});
const centerLabelWidth = computed(() => {
  const name = props.center?.name || "Fleetge Control Center";
  const estimated = Math.max(estimateTextWidth(name, 22), estimateTextWidth(centerLocationText.value, 18));
  return Math.max(104, Math.min(210, estimated));
});
const cameraOffset = computed(() => ({
  x: (size.width * (1 - camera.k)) / 2 + camera.panX,
  y: (size.height * (1 - camera.k)) / 2 + camera.panY,
}));
const cameraTransform = computed(() => `translate(${cameraOffset.value.x} ${cameraOffset.value.y}) scale(${camera.k})`);
const projectionLabel = computed(() => {
  const longitude = ((-rotation.longitude + 540) % 360) - 180;
  const latitude = -rotation.latitude;
  const longitudeText = `${Math.abs(Math.round(longitude))}°${longitude >= 0 ? "E" : "W"}`;
  const latitudeText = Math.abs(latitude) < 1 ? t("map.equator") : `${Math.abs(Math.round(latitude))}°${latitude >= 0 ? "N" : "S"}`;
  const isChinaCenter = Math.abs(longitude - 105) < 1 && Math.abs(latitude) < 1;
  return `${isChinaCenter ? t("map.chinaCenter") : t("map.viewCenter")} · ${longitudeText} · ${latitudeText}`;
});
const clusters = computed(() => clusterProjectedNodes(
  geometry.value.nodes.map((node) => ({ item: node.host, point: node.point })),
  34 / camera.k,
).map((cluster) => {
  const hosts = cluster.items;
  const counts = {
    online: hosts.filter((host) => host.status === "online").length,
    degraded: hosts.filter((host) => host.status === "degraded").length,
    offline: hosts.filter((host) => ["offline", "unknown"].includes(host.status)).length,
  };
  let offset = 0;
  const segments = (["online", "degraded", "offline"] as const).flatMap((status) => {
    if (!counts[status]) return [];
    const share = (counts[status] / hosts.length) * 100;
    const segment = { status, offset, length: Math.max(share - 2, 1) };
    offset += share;
    return [segment];
  });
  const primaryStatus: FleetMapHost["status"] = counts.offline
    ? "offline"
    : counts.degraded
      ? "degraded"
      : "online";
  return {
    id: hosts.map((host) => host.host_id).sort().join("|"),
    hosts,
    point: cluster.point,
    segments,
    primaryStatus,
    hasUnconfirmed: hosts.some((host) => !host.location?.confirmed),
    locationText: shortLocationLabel(hosts[0], hosts.length === 1),
    labelWidth: Math.max(88, Math.min(184, Math.max(
      estimateTextWidth(hosts.length === 1 ? hosts[0].display_name : shortLocationLabel(hosts[0], false), 16),
      estimateTextWidth(hosts.length === 1 ? shortLocationLabel(hosts[0]) : t("map.hostCount", { count: hosts.length }), 16),
    ))),
  };
}));
const hoveredCluster = computed(() => clusters.value.find((cluster) => cluster.id === hoveredClusterId.value) || null);
const tooltipStyle = computed(() => {
  const cluster = hoveredCluster.value;
  if (!cluster) return {};
  const rawX = cameraOffset.value.x + cluster.point[0] * camera.k;
  const rawY = cameraOffset.value.y + cluster.point[1] * camera.k;
  const x = Math.min(Math.max(rawX, 126), size.width - 126);
  const y = Math.max(rawY - 15, 72);
  return { left: `${x}px`, top: `${y}px` };
});

function statusLabel(status: FleetMapHost["status"]) {
  if (status === "online") return t("map.online");
  if (status === "degraded") return t("map.issues");
  if (status === "offline") return t("map.offline");
  return t("map.unknown");
}

function locationLabel(host: FleetMapHost) {
  const location = host.location;
  if (!location) return t("map.unlocated");
  const label = [location.city, location.region, location.country].filter(Boolean).join(" · ");
  const fallback = `${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`;
  return `${label || fallback}${location.confirmed ? "" : ` · ${t("map.pending")}`}`;
}

function estimateTextWidth(text: string, padding: number) {
  return Array.from(text).reduce((width, character) => width + (character.charCodeAt(0) > 255 ? 10.5 : 5.8), padding);
}

function shortLocationLabel(host: FleetMapHost, includePending = true) {
  const location = host.location;
  if (!location) return t("map.locationNotSet");
  const primary = location.city || location.region || location.country;
  const country = location.country_code || (primary !== location.country ? location.country : "");
  const text = [primary, country].filter(Boolean).join(" · ")
    || `${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`;
  return `${text}${includePending && !location.confirmed ? ` · ${t("map.pending")}` : ""}`;
}

function clusterTitle(hosts: FleetMapHost[]) {
  if (hosts.length === 1) return hosts[0].display_name;
  const location = locationLabel(hosts[0]).replace(` · ${t("map.pending")}`, "");
  return `${location} · ${t("map.hostCount", { count: hosts.length })}`;
}

function clusterSummary(hosts: FleetMapHost[]) {
  if (hosts.length === 1) return `${statusLabel(hosts[0].status)} · ${locationLabel(hosts[0])}`;
  const online = hosts.filter((host) => host.status === "online").length;
  const degraded = hosts.filter((host) => host.status === "degraded").length;
  const offline = hosts.length - online - degraded;
  return [t("map.onlineCount", { count: online }), degraded ? t("map.issueCount", { count: degraded }) : "", offline ? t("map.offlineCount", { count: offline }) : ""].filter(Boolean).join(" · ");
}

function clusterAriaLabel(hosts: FleetMapHost[]) {
  return `${clusterTitle(hosts)}，${clusterSummary(hosts)}`;
}

function showTooltip(clusterId: string) {
  hoveredClusterId.value = clusterId;
}

function hideTooltip() {
  hoveredClusterId.value = "";
}

function selectHosts(hosts: FleetMapHost[]) {
  if (dragMoved.value) return;
  emit("select", hosts);
}

function localPoint(event: WheelEvent | PointerEvent) {
  const rect = svgElement.value?.getBoundingClientRect();
  if (!rect) return { x: size.width / 2, y: size.height / 2 };
  return {
    x: ((event.clientX - rect.left) / rect.width) * size.width,
    y: ((event.clientY - rect.top) / rect.height) * size.height,
  };
}

function constrainPan() {
  const maxX = size.width * (0.36 + Math.max(0, camera.k - 1) / 2);
  const maxY = size.height * (0.36 + Math.max(0, camera.k - 1) / 2);
  camera.panX = Math.max(-maxX, Math.min(maxX, camera.panX));
  camera.panY = Math.max(-maxY, Math.min(maxY, camera.panY));
}

function setZoom(nextZoom: number) {
  camera.k = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextZoom));
  constrainPan();
}

function zoomBy(factor: number) {
  setZoom(camera.k * factor);
}

function resetView() {
  camera.k = 1;
  camera.panX = 0;
  camera.panY = 0;
  rotation.longitude = -105;
  rotation.latitude = 0;
}

function fitHostsToView() {
  const locations = props.hosts.flatMap((host) => host.location
    ? [[host.location.latitude, host.location.longitude] as [number, number]]
    : []);
  if (!locations.length) {
    resetView();
    return;
  }

  const focus = calculateGeographicFocus(locations);
  rotation.longitude = -focus[1];
  rotation.latitude = -focus[0];
  const projection = createFleetProjection(size.width, size.height, 34, [rotation.longitude, rotation.latitude]);
  const points = locations.flatMap((location) => {
    const point = projectFleetPoint(projection, location);
    return point ? [point] : [];
  });
  if (!points.length) return;

  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = maxX - minX;
  const spanY = maxY - minY;
  const compact = spanX < size.width * .04 && spanY < size.height * .04;
  const scaleX = (size.width * .72) / Math.max(spanX, 1);
  const scaleY = (size.height * .68) / Math.max(spanY, 1);
  camera.k = compact ? 2.55 : Math.max(1, Math.min(3.2, scaleX, scaleY));
  camera.panX = camera.k * (size.width / 2 - (minX + maxX) / 2);
  camera.panY = camera.k * (size.height / 2 - (minY + maxY) / 2);
  constrainPan();
}

function handleWheel(event: WheelEvent) {
  const factor = Math.exp(-event.deltaY * 0.0012);
  setZoom(camera.k * factor);
}

function handlePointerDown(event: PointerEvent) {
  if (event.button !== 0) return;
  dragPointerId = event.pointerId;
  dragging.value = true;
  dragMoved.value = false;
  dragStart = localPoint(event);
  rotationOrigin = { longitude: rotation.longitude, latitude: rotation.latitude };
  panOrigin = { x: camera.panX, y: camera.panY };
  activeDragMode = event.shiftKey ? "pan" : interactionMode.value;
  svgElement.value?.setPointerCapture(event.pointerId);
}

function handlePointerMove(event: PointerEvent) {
  if (!dragging.value || dragPointerId !== event.pointerId) return;
  const point = localPoint(event);
  const dx = point.x - dragStart.x;
  const dy = point.y - dragStart.y;
  if (Math.hypot(dx, dy) > 4) dragMoved.value = true;
  if (activeDragMode === "pan") {
    camera.panX = panOrigin.x + dx;
    camera.panY = panOrigin.y + dy;
    constrainPan();
  } else {
    rotation.longitude = ((rotationOrigin.longitude + dx * 0.24 / camera.k + 540) % 360) - 180;
    rotation.latitude = Math.max(-60, Math.min(60, rotationOrigin.latitude - dy * 0.18 / camera.k));
  }
}

function handlePointerUp(event: PointerEvent) {
  if (dragPointerId !== event.pointerId) return;
  if (svgElement.value?.hasPointerCapture(event.pointerId)) {
    svgElement.value.releasePointerCapture(event.pointerId);
  }
  dragging.value = false;
  dragPointerId = null;
  window.setTimeout(() => { dragMoved.value = false; }, 0);
}

function handlePointerLeave() {
  if (!dragging.value) hideTooltip();
}

onMounted(() => {
  if (!stageElement.value) return;
  resizeObserver = new ResizeObserver(([entry]) => {
    const width = Math.max(320, Math.round(entry.contentRect.width));
    const height = Math.max(360, Math.round(entry.contentRect.height));
    if (width === size.width && height === size.height) return;
    size.width = width;
    size.height = height;
    fitHostsToView();
  });
  resizeObserver.observe(stageElement.value);
});

watch(
  () => props.hosts
    .flatMap((host) => host.location ? [`${host.host_id}:${host.location.latitude.toFixed(5)}:${host.location.longitude.toFixed(5)}`] : [])
    .sort()
    .join("|"),
  () => fitHostsToView(),
  { immediate: true, flush: "post" },
);

onBeforeUnmount(() => resizeObserver?.disconnect());
</script>

<style scoped>
.fleet-geo-map {
  --geo-ocean: #edf5fc;
  --geo-land: #d8e7f4;
  --geo-border: #9db8d2;
  --geo-graticule: rgba(88, 126, 161, .12);
  position: absolute;
  inset: 0;
  overflow: hidden;
  color: var(--fleet-map-ink, #27415d);
  background: var(--fleet-map-bg, radial-gradient(circle at 48% 45%, #f8fbff 0, #eaf2fa 52%, #dce8f4 100%));
  user-select: none;
}
.fleet-geo-map.is-theme-dark {
  --geo-ocean: #071221;
  --geo-land: #0d1e33;
  --geo-border: #29425e;
  --geo-graticule: rgba(116, 157, 198, .09);
}
.fleet-geo-map__svg { width: 100%; height: 100%; display: block; cursor: grab; touch-action: none; }
.fleet-geo-map.mode-pan:not(.is-dragging) .fleet-geo-map__svg { cursor: move; }
.fleet-geo-map.is-dragging .fleet-geo-map__svg { cursor: grabbing; }
.map-sphere { fill: var(--geo-ocean); stroke: var(--geo-border); stroke-width: .8; vector-effect: non-scaling-stroke; }
.map-graticule { fill: none; stroke: var(--geo-graticule); stroke-width: .65; vector-effect: non-scaling-stroke; }
.map-land { fill: var(--geo-land); stroke: none; }
.map-borders { fill: none; stroke: var(--geo-border); stroke-width: .72; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.fleet-center-node { color: #3b82f6; }
.fleet-center-node__halo { fill: currentColor; opacity: .12; animation: center-breathe 2.8s ease-out infinite; transform-box: fill-box; transform-origin: center; }
.fleet-center-node__ring { fill: color-mix(in srgb, currentColor 16%, transparent); stroke: currentColor; stroke-width: 1.4; vector-effect: non-scaling-stroke; }
.fleet-center-node__core { fill: #60a5fa; filter: drop-shadow(0 0 5px #3b82f6); }
.fleet-center-label { pointer-events: none; filter: drop-shadow(0 5px 10px rgba(15,23,42,.14)); }
.fleet-center-label__leader { fill: none; stroke: color-mix(in srgb, var(--accent-blue, #60a5fa) 68%, var(--geo-border)); stroke-width: 1; stroke-linecap: round; stroke-linejoin: round; vector-effect: non-scaling-stroke; }
.fleet-center-label__plate { fill: var(--fleet-map-overlay, var(--surface-panel)); stroke: color-mix(in srgb, var(--accent-blue, #60a5fa) 34%, var(--fleet-map-border)); stroke-width: 1; vector-effect: non-scaling-stroke; }
.fleet-center-label__dot { fill: var(--accent-blue, #60a5fa); filter: drop-shadow(0 0 3px var(--accent-blue, #60a5fa)); }
.fleet-center-label__name { fill: var(--fleet-map-ink, var(--text-primary)); font-family: var(--font-body, sans-serif); font-weight: 700; letter-spacing: 0; }
.fleet-center-label__location { fill: var(--fleet-map-muted, var(--text-muted)); font-family: var(--font-body, sans-serif); font-weight: 500; letter-spacing: .01em; }
.fleet-host-node { cursor: pointer; outline: none; color: #ef4444; }
.fleet-host-node.is-online { color: #06b6d4; }
.fleet-host-node.is-degraded { color: #f59e0b; }
.fleet-host-node__aura { fill: currentColor; opacity: .1; transform-box: fill-box; transform-origin: center; }
.fleet-host-node.is-online .fleet-host-node__aura { animation: host-beacon 3.2s ease-out infinite; }
.fleet-host-node__ring { fill: color-mix(in srgb, currentColor 13%, transparent); stroke: currentColor; stroke-width: 1.15; opacity: .78; vector-effect: non-scaling-stroke; }
.fleet-host-node__core { fill: currentColor; stroke: color-mix(in srgb, currentColor 25%, white); stroke-width: 1.35; filter: drop-shadow(0 0 4px currentColor); vector-effect: non-scaling-stroke; }
.fleet-host-node__highlight { fill: rgba(255,255,255,.78); pointer-events: none; }
.fleet-host-node__pending { fill: none; stroke: currentColor; stroke-width: 1.2; stroke-dasharray: 2 4; vector-effect: non-scaling-stroke; animation: pending-orbit 5s linear infinite; transform-box: fill-box; transform-origin: center; }
.fleet-host-node:hover .fleet-host-node__aura,.fleet-host-node:focus-visible .fleet-host-node__aura { opacity: .24; }
.fleet-host-node:hover .fleet-host-node__ring,.fleet-host-node:focus-visible .fleet-host-node__ring { stroke-width: 2; opacity: 1; }
.fleet-host-node:focus-visible .fleet-host-node__core { stroke: #fff; stroke-width: 2.5; }
.fleet-host-cluster { cursor: pointer; outline: none; color: var(--accent-cyan, #22d3ee); }
.fleet-host-cluster.is-degraded { color: var(--warning, #fbbf24); }
.fleet-host-cluster.is-offline,.fleet-host-cluster.is-unknown { color: var(--danger, #f87171); }
.fleet-host-cluster__aura { fill: currentColor; opacity: .1; transform-box: fill-box; transform-origin: center; }
.fleet-host-cluster__track { fill: none; stroke: color-mix(in srgb, var(--geo-border) 68%, transparent); stroke-width: 4.2; vector-effect: non-scaling-stroke; }
.fleet-host-cluster__segment { fill: none; stroke-width: 4.2; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.fleet-host-cluster__segment.is-online { stroke: var(--accent-cyan, #22d3ee); }
.fleet-host-cluster__segment.is-degraded { stroke: var(--warning, #fbbf24); }
.fleet-host-cluster__segment.is-offline { stroke: var(--danger, #f87171); }
.fleet-host-cluster__core { fill: var(--fleet-map-overlay, var(--surface-panel)); stroke: color-mix(in srgb, currentColor 46%, var(--geo-border)); stroke-width: 1; vector-effect: non-scaling-stroke; }
.fleet-host-cluster__count { fill: var(--fleet-map-ink, var(--text-primary)); text-anchor: middle; font-family: var(--font-mono, monospace); font-weight: 800; pointer-events: none; }
.fleet-host-cluster__pending { fill: none; stroke: var(--accent-blue, #60a5fa); stroke-width: 1.1; stroke-dasharray: 2 4; vector-effect: non-scaling-stroke; animation: pending-orbit 5s linear infinite; transform-box: fill-box; transform-origin: center; }
.fleet-host-cluster:hover .fleet-host-cluster__aura,.fleet-host-cluster:focus-visible .fleet-host-cluster__aura { opacity: .24; }
.fleet-host-cluster:focus-visible .fleet-host-cluster__core { stroke: var(--accent-blue); stroke-width: 2.5; }
.fleet-node-label { pointer-events: none; filter: drop-shadow(0 4px 9px rgba(15,23,42,.12)); }
.fleet-node-label__leader { fill: none; stroke: color-mix(in srgb, currentColor 52%, var(--geo-border)); stroke-width: 1; stroke-linecap: round; vector-effect: non-scaling-stroke; }
.fleet-node-label__plate { fill: var(--fleet-map-overlay, var(--surface-panel)); stroke: color-mix(in srgb, currentColor 24%, var(--fleet-map-border)); stroke-width: 1; vector-effect: non-scaling-stroke; }
.fleet-node-label__title { fill: var(--fleet-map-ink, var(--text-primary)); font-family: var(--font-body, sans-serif); font-weight: 700; }
.fleet-node-label__meta { fill: var(--fleet-map-muted, var(--text-muted)); font-family: var(--font-body, sans-serif); font-weight: 500; }
.fleet-node-label--cluster .fleet-node-label__plate { stroke: color-mix(in srgb, currentColor 38%, var(--fleet-map-border)); }
.map-controls { position: absolute; z-index: 4; top: 12px; left: 12px; display: grid; overflow: hidden; border: 1px solid var(--fleet-map-border, rgba(107,139,171,.28)); border-radius: 8px; background: var(--fleet-map-overlay, rgba(255,255,255,.84)); box-shadow: var(--fleet-map-shadow, 0 8px 22px rgba(53,91,126,.12)); backdrop-filter: blur(12px); }
.map-controls button { display: grid; place-items: center; width: 34px; height: 34px; border: 0; border-bottom: 1px solid var(--fleet-map-border, rgba(107,139,171,.28)); color: var(--fleet-map-ink, #27415d); background: transparent; font: 500 21px/1 system-ui; cursor: pointer; }
.map-controls button:last-child { border-bottom: 0; }
.map-controls button:hover:not(:disabled),.map-controls button:focus-visible { color: #2563eb; background: color-mix(in srgb, #3b82f6 10%, transparent); outline: none; }
.map-controls button:disabled { opacity: .35; cursor: default; }
.map-controls__reset { font-size: 17px !important; }
.map-controls__mode { color: var(--accent-blue, #3b82f6) !important; }
.projection-badge,.map-gesture-hint { position: absolute; z-index: 3; color: var(--fleet-map-muted, #607991); background: var(--fleet-map-overlay, rgba(255,255,255,.84)); border: 1px solid var(--fleet-map-border, rgba(107,139,171,.28)); backdrop-filter: blur(10px); font: 700 9px/1 "JetBrains Mono", monospace; letter-spacing: .1em; }
.projection-badge { top: 14px; right: 14px; display: flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: 999px; }
.projection-badge span { width: 5px; height: 5px; border-radius: 50%; background: #3b82f6; box-shadow: 0 0 8px #3b82f6; }
.map-gesture-hint { right: 14px; bottom: 14px; padding: 7px 9px; border-radius: 7px; font-weight: 500; letter-spacing: .04em; }
.fleet-map-tooltip { position: absolute; z-index: 6; display: grid; gap: 4px; min-width: 190px; max-width: 250px; padding: 9px 11px; color: var(--fleet-map-ink, #27415d); background: var(--fleet-map-overlay, rgba(255,255,255,.94)); border: 1px solid var(--fleet-map-border, rgba(107,139,171,.28)); border-radius: 8px; box-shadow: var(--fleet-map-shadow, 0 12px 30px rgba(53,91,126,.16)); pointer-events: none; transform: translate(-50%, -100%); backdrop-filter: blur(12px); }
.fleet-map-tooltip strong { font-size: 12px; }
.fleet-map-tooltip span { color: var(--fleet-map-muted, #607991); font-size: 10px; line-height: 1.4; }
.fleet-map-tooltip em { padding-top: 5px; border-top: 1px solid var(--fleet-map-border, rgba(107,139,171,.28)); color: #3b82f6; font-size: 10px; font-style: normal; }
@keyframes center-breathe { 70%,100% { opacity: 0; transform: scale(1.8); } }
@keyframes host-beacon { 70%,100% { opacity: 0; transform: scale(1.65); } }
@keyframes pending-orbit { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .fleet-center-node__halo,.fleet-host-node__aura,.fleet-host-node__pending,.fleet-host-cluster__pending { animation: none !important; }
}
@media (max-width: 560px) {
  .projection-badge { top: 11px; right: 11px; }
  .map-gesture-hint { display: none; }
}
</style>

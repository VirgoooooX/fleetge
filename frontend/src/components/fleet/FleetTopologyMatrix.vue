<template>
  <section v-if="nodes.length" class="topology-matrix-panel ui-panel">
    <header class="topology-matrix-header">
      <div class="topology-matrix-title">
        <span class="ui-section-kicker">{{ t("map.topologyKicker") }}</span>
        <h3>{{ t("map.topologyTitle") }}</h3>
      </div>
      <div class="topology-matrix-pills">
        <span class="matrix-pill">
          <Globe :size="13" />
          <span>{{ t("map.locatedNodes") }} <strong>{{ hostsWithLocationCount }} / {{ nodes.length }}</strong></span>
        </span>
        <span v-if="averageRttMs > 0" class="matrix-pill">
          <Radio :size="13" />
          <span>{{ t("map.avgLatency") }} <strong>{{ averageRttMs }} ms</strong></span>
        </span>
      </div>
    </header>

    <div class="topology-table-container">
      <table class="topology-table" :aria-label="t('map.topologyTitle')">
        <thead>
          <tr>
            <th scope="col">{{ t("map.colNode") }}</th>
            <th scope="col">{{ t("map.colStatus") }}</th>
            <th scope="col">{{ t("map.colLocation") }}</th>
            <th scope="col">{{ t("map.colPublicIp") }}</th>
            <th scope="col">{{ t("map.colDistance") }}</th>
            <th scope="col">{{ t("map.colLatency") }}</th>
            <th scope="col">{{ t("map.colContainers") }}</th>
            <th scope="col" class="u-text-right">{{ t("map.colActions") }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="node in nodes"
            :key="node.host_id"
            class="topology-row"
            :class="{ 'is-selected': selectedHostId === node.host_id }"
            @click="emit('inspect', node.host)"
          >
            <td class="cell-node">
              <button class="node-identity" type="button" @click.stop="emit('inspect', node.host)">
                <span class="node-dot" :class="node.status"></span>
                <strong>{{ node.display_name }}</strong>
              </button>
            </td>
            <td>
              <span class="m-status-pill" :class="`is-${node.status}`">
                {{ statusLabel(node.status) }}
              </span>
            </td>
            <td class="cell-location">
              <span class="location-text">{{ node.locationText }}</span>
            </td>
            <td class="cell-ip">
              <code v-if="node.effectiveIp !== '—'" class="ip-code">{{ node.effectiveIp }}</code>
              <span v-else class="u-text-muted">—</span>
            </td>
            <td class="cell-distance">
              <span v-if="node.distanceKm !== null" class="distance-text">
                {{ node.distanceKm === 0 ? t("map.distanceLocal") : `${node.distanceKm.toLocaleString(locale)} km` }}
              </span>
              <span v-else class="u-text-muted">—</span>
            </td>
            <td class="cell-latency">
              <div v-if="node.rttMs !== null" class="rtt-badge" :class="`rtt-${node.rttTone}`">
                <span class="rtt-dot"></span>
                <strong>{{ node.rttMs }}</strong>
                <small>ms</small>
              </div>
              <span v-else class="u-text-muted">—</span>
            </td>
            <td class="cell-containers">
              <strong>{{ node.container_count }}</strong>
              <small class="u-text-muted"> {{ t("map.containersCountSuffix") }}</small>
            </td>
            <td class="cell-actions u-text-right" @click.stop>
              <button
                class="ui-button ui-button--compact"
                type="button"
                @click.stop="emit('focus', node.host)"
              >
                <ExternalLink :size="13" />
                {{ t("map.inspectNode") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { ExternalLink, Globe, Radio } from "@lucide/vue";
import type { FleetMapHost, FleetMapSnapshot } from "@/api/fleetMap";
import { buildFleetTopology, fleetStatusKey } from "@/utils/fleetMap";

const props = defineProps<{ snapshot: FleetMapSnapshot | null; selectedHostId: string }>();
const emit = defineEmits<{ inspect: [host: FleetMapHost]; focus: [host: FleetMapHost] }>();
const { t, locale } = useI18n();

const topology = computed(() => buildFleetTopology(props.snapshot));
const averageRttMs = computed(() => topology.value.averageRttMs);
const hostsWithLocationCount = computed(() => topology.value.locatedCount);
const nodes = computed(() => topology.value.nodes.map((node) => ({
  ...node,
  locationText: node.locationText || t("map.unlocated"),
})));
const statusLabel = (status: FleetMapHost["status"]) => t(fleetStatusKey[status]);
</script>

<style scoped>
.topology-matrix-panel {
  margin-top: 16px;
  background: var(--fleet-map-panel);
  border-color: var(--fleet-map-border);
  box-shadow: var(--fleet-map-shadow);
  border-radius: var(--ui-radius-lg);
  overflow: hidden;
}

.topology-matrix-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--fleet-map-border);
  background: var(--fleet-map-panel);
}

.topology-matrix-title h3 {
  margin: 2px 0 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--fleet-map-ink);
}

.topology-matrix-pills {
  display: flex;
  align-items: center;
  gap: 10px;
}

.matrix-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--ui-radius-sm);
  background: var(--fleet-map-panel-raised);
  border: 1px solid var(--fleet-map-border);
  font-size: var(--text-xs);
  color: var(--fleet-map-muted);
}

.matrix-pill strong {
  color: var(--fleet-map-ink);
  font-weight: 700;
}

.topology-table-container {
  overflow-x: auto;
}

.topology-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-body);
  font-size: var(--text-xs);
}

.topology-table th {
  padding: 10px 16px;
  background: var(--fleet-map-panel-raised);
  color: var(--fleet-map-muted);
  font-size: 12px;
  font-weight: 700;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid var(--fleet-map-border);
}

.topology-row {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.topology-row:hover {
  background-color: color-mix(in srgb, var(--accent-blue) 6%, var(--fleet-map-panel));
}

.topology-row.is-selected {
  background-color: color-mix(in srgb, var(--accent-blue) 12%, var(--fleet-map-panel));
}

.topology-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--fleet-map-border);
  color: var(--fleet-map-ink);
  vertical-align: middle;
  white-space: nowrap;
}

.topology-row:last-child td {
  border-bottom: none;
}

.node-identity {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.node-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.node-dot.online { background: var(--success); }
.node-dot.degraded { background: var(--warning); }
.node-dot.offline { background: var(--danger); }
.node-dot.unknown { background: var(--fleet-map-muted); }

.m-status-pill {
  font-size: 11px;
  padding: 2px 9px;
  border-radius: 999px;
  font-weight: 700;
  white-space: nowrap;
}
.m-status-pill.is-online {
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 24%, transparent);
  background: color-mix(in srgb, var(--success) 8%, transparent);
}
.m-status-pill.is-degraded {
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 26%, transparent);
  background: color-mix(in srgb, var(--warning) 8%, transparent);
}
.m-status-pill.is-offline {
  color: var(--danger);
  border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
  background: color-mix(in srgb, var(--danger) 8%, transparent);
}
.m-status-pill.is-unknown {
  color: var(--fleet-map-muted);
  border: 1px solid var(--fleet-map-border);
  background: var(--fleet-map-panel-raised);
}

.ip-code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 2px 7px;
  border-radius: var(--ui-radius-sm);
  background: var(--fleet-map-panel-raised);
  color: var(--fleet-map-ink);
  border: 1px solid var(--fleet-map-border);
}

.rtt-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}

.rtt-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.rtt-badge.rtt-excellent {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--success) 24%, transparent);
}
.rtt-badge.rtt-excellent .rtt-dot { background: var(--success); }

.rtt-badge.rtt-good {
  color: var(--accent-cyan);
  background: color-mix(in srgb, var(--accent-cyan) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent-cyan) 24%, transparent);
}
.rtt-badge.rtt-good .rtt-dot { background: var(--accent-cyan); }

.rtt-badge.rtt-fair {
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 24%, transparent);
}
.rtt-badge.rtt-fair .rtt-dot { background: var(--warning); }

.rtt-badge.rtt-offline {
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 28%, transparent);
}
.rtt-badge.rtt-offline .rtt-dot { background: var(--danger); }

.node-identity {
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  cursor: pointer;
}
.node-identity:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: 3px;
  border-radius: var(--ui-radius-sm);
}
</style>

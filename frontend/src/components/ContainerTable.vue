<template>
  <div class="container-table-panel">
    <el-table :data="containers" stripe style="width: 100%" size="small">
      <el-table-column :label="t('containerTable.name')" prop="name" min-width="200">
        <template #default="{ row }">
          <div class="container-name">
            <StatusIcon :status="row.state === 'running' ? 'online' : 'offline'" />
            <span>{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('containerTable.image')" prop="image" min-width="260">
        <template #default="{ row }">
          <div class="image-cell">
            <code class="image-ref">{{ row.image }}</code>
            <UpdateBadge
              v-if="updateStatuses?.[row.image] && updateStatuses[row.image] !== 'up_to_date'"
              :status="updateStatuses[row.image]"
            />
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('containerTable.status')" prop="state" width="100">
        <template #default="{ row }">
          <el-tag :type="row.state === 'running' ? 'success' : 'info'" size="small">
            {{ row.state }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('containerTable.ports')" width="150">
        <template #default="{ row }">
          <span class="port-text" v-if="row.ports && row.ports.length > 0">
            {{ formatPorts(row.ports) }}
          </span>
          <span v-else class="port-none">-</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('containerTable.created')" width="140">
        <template #default="{ row }">
          {{ formatTime(row.created) }}
        </template>
      </el-table-column>
      <el-table-column :label="t('containerTable.resources')" width="210">
        <template #default="{ row }">
          <ContainerStats
            v-if="row.state === 'running' && containerStats?.[row.id]"
            :stats="containerStats[row.id]"
          />
          <span v-else class="stats-none">-</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import StatusIcon from "./StatusIcon.vue";
import ContainerStats from "./ContainerStats.vue";
import UpdateBadge from "./UpdateBadge.vue";

export interface ContainerPort {
  private_port: number;
  public_port?: number;
  ip?: string;
  type: string;
}

export interface ContainerSummary {
  id: string;
  name: string;
  image: string;
  state: string;
  status: string;
  created: number;
  ports: ContainerPort[];
  stack_name?: string;
  service_name?: string;
}

export interface ContainerStatsData {
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
  block_read_bytes: number;
  block_write_bytes: number;
}

defineProps<{
  containers: ContainerSummary[];
  containerStats?: Record<string, ContainerStatsData>;
  updateStatuses?: Record<string, string>;
}>();

const { t, locale } = useI18n();

function formatPorts(ports: ContainerPort[]): string {
  return ports
    .map((p) => (p.public_port ? `${p.public_port}:${p.private_port}` : `${p.private_port}`))
    .join(", ");
}

function formatTime(created: number): string {
  const d = new Date(created * 1000);
  const loc = locale.value;
  const months = d.toLocaleDateString(loc, { month: "2-digit", day: "2-digit" });
  const time = d.toLocaleTimeString(loc, { hour: "2-digit", minute: "2-digit" });
  return `${months} ${time}`;
}
</script>

<style scoped>
.container-table-panel {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
}
.container-name {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.container-name span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.image-ref {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: var(--code-bg, rgba(5, 9, 20, 0.78));
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text-primary);
}
.image-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.image-cell .image-ref {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.port-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.port-none, .stats-none {
  color: var(--text-secondary);
}
</style>

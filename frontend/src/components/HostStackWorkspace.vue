<template>
  <section class="host-workspace">
    <aside class="workspace-sidebar">
      <div class="sidebar-compose-row">
        <el-tooltip :content="t('workspace.newStack')" placement="top">
          <button class="ui-button ui-button--primary compose-add-button" type="button" @click="openNewCompose">
            <el-icon><Plus /></el-icon>
            Compose
          </button>
        </el-tooltip>

        <el-tooltip :content="t('workspace.pruneDocker')" placement="top">
          <el-button
            class="ui-icon-button ui-icon-button--danger sidebar-icon-button"
            size="small"
            :loading="pruneLoading"
            :aria-label="t('workspace.pruneDocker')"
            @click="confirmPrune"
          >
            <el-icon v-if="!pruneLoading"><Brush /></el-icon>
          </el-button>
        </el-tooltip>
        <el-tooltip :content="t('workspace.updateAll')" placement="top">
          <el-badge
            :value="updatableStacks.length"
            :hidden="updatableStacks.length === 0"
            class="sidebar-update-badge"
          >
            <el-button
              class="ui-icon-button ui-icon-button--warning sidebar-icon-button"
              size="small"
              :loading="bulkUpdateLoading"
              :disabled="updatableStacks.length === 0 || bulkUpdateLoading"
              :aria-label="t('workspace.updateAll')"
              @click="confirmUpdateAll"
            >
              <el-icon v-if="!bulkUpdateLoading"><Top /></el-icon>
            </el-button>
          </el-badge>
        </el-tooltip>
      </div>

      <div class="sidebar-search">
        <el-icon><Search /></el-icon>
        <input v-model="stackSearch" type="search" :placeholder="t('workspace.searchPlaceholder')" />
      </div>

      <template v-if="structureLoading">
        <div class="sidebar-loading">{{ t('workspace.loadingStructure') }}</div>
      </template>
      <template v-else>
        <button
          class="stack-nav-item all"
          :class="{ active: !selectedStackName }"
          type="button"
          @click="showAllStacks"
        >
          <span>{{ t('workspace.allStacks') }}</span>
          <span class="nav-count">{{ filteredStacks.length }}</span>
        </button>

        <div class="stack-nav-list">
          <button
            v-for="stack in filteredStacks"
            :key="stack.name"
            class="stack-nav-item"
            :class="{ active: selectedStackName === stack.name, 'is-stopped': stack.status === 'stopped' || stack.status === 'inactive' || stack.status === 'exited' }"
            type="button"
            @click="selectStack(stack.name)"
          >
            <span class="nav-stack-icon-wrap">
              <img
                v-if="stack.icon_url"
                :src="stack.icon_url"
                class="nav-stack-icon-img"
                @error="onIconError"
              />
              <el-icon v-else class="nav-stack-icon"><FolderOpened /></el-icon>
            </span>
            <span class="nav-stack-copy">
              <span class="nav-stack-name">{{ stack.name }}</span>
              <span class="nav-stack-meta">
                <span class="nav-status-pill" :class="`status-${stackStatusType(stack.status)}`">
                  {{ statusLabel(stack.status) }}
                </span>
                <span
                  v-if="stack.management_status === 'unmanaged'"
                  class="management-pill management-unmanaged"
                >
                  {{ managementStatusLabel(stack.management_status) }}
                </span>
                <UpdateBadge v-if="stackUpdateStatus(stack)" :status="stackUpdateStatus(stack)!" />
              </span>
            </span>
          </button>
        </div>
      </template>
    </aside>

    <main class="workspace-main">
      <div v-if="!selectedStack" class="all-stacks-view">
        <div class="workspace-headline">
          <div>
            <div class="workspace-kicker">{{ t('workspace.stacksKicker') }}</div>
            <h3>{{ t('workspace.allStacksTitle') }}</h3>
          </div>
          <div class="workspace-summary">
            <span>{{ t('workspace.stacksCount', { count: stacks.length }) }}</span>
            <span>{{ t('workspace.runningCount', { count: runningStackCount }) }}</span>
          </div>
        </div>

        <div v-if="structureLoading" class="structure-loading">
          <el-skeleton :rows="4" animated />
        </div>
        <div v-else-if="filteredStacks.length > 0" class="stack-card-list">
          <article
            v-for="stack in filteredStacks"
            :key="stack.name"
            class="stack-card"
            :class="{
              'is-stopped': stack.status === 'stopped' || stack.status === 'inactive' || stack.status === 'exited',
              'is-operating': runningOperations[stack.name]
            }"
            @click="selectStack(stack.name)"
            @mousemove="handleCardMouseMove"
            @mouseleave="handleCardMouseLeave"
          >
            <div class="stack-header">
              <div class="stack-title-row">
                <img v-if="stack.icon_url" :src="stack.icon_url" class="stack-icon-img" @error="onIconError" />
                <el-icon v-else class="stack-title-icon"><FolderOpened /></el-icon>
                <span class="stack-name">{{ stack.name }}</span>
                <span class="dot-state" :class="`dot-${stackStatusType(stack.status)}`" />
                <span class="stack-state-text">{{ statusLabel(stack.status) }}</span>
                <span
                  v-if="stack.management_status === 'unmanaged'"
                  class="management-pill management-unmanaged"
                >
                  {{ managementStatusLabel(stack.management_status) }}
                </span>
                <UpdateBadge v-if="stackUpdateStatus(stack)" :status="stackUpdateStatus(stack)!" />
              </div>
              <div class="stack-card-actions" @click.stop>
                <span class="stack-running-count">
                  {{ t('workspace.running', { running: stack.running_count, total: stack.service_count }) }}
                </span>
                <StackActions
                  :host-id="hostId"
                  :stack-name="stack.name"
                  :app-url="stack.app_url"
                  show-compose
                  show-detail
                  :can-edit-compose="stack.management_status !== 'unmanaged'"
                  @refresh="$emit('refresh')"
                  @operation-start="onOperationStart"
                  @terminal-chunk="onTerminalChunk"
                  @operation-complete="handleOperationComplete"
                  @compose="openCompose(stack.name)"
                  @detail="selectStack(stack.name)"
                />
              </div>
            </div>

            <StackOperationDock
              v-if="isOperationDockVisible(stack.name)"
              class="card-operation-dock"
              :stack-name="stack.name"
              :action="operationPanelAction"
              :lines="terminalOutputs[stack.name] || []"
              :status="operationPanelStatus"
              :message="operationPanelMessage"
              compact
              @close="handleDockClose(stack.name)"
              @cancel="cancelOperation(stack.name)"
              @click.stop
            />

            <div v-if="stack.services?.length" class="service-strip">
              <button
                v-for="service in stack.services"
                :key="service.name"
                class="service-strip-row"
                type="button"
                @click.stop="selectServiceContainer(stack.name, service)"
              >
                <StatusIcon :status="service.state === 'running' ? 'online' : 'offline'" />
                <span class="service-name">{{ service.name }}</span>
                <span class="service-status">{{ service.status || service.state }}</span>
                <UpdateBadge
                  v-if="serviceUpdateStatus(stack, service)"
                  :status="serviceUpdateStatus(stack, service)!"
                />
                <span class="service-actions" @click.stop>
                  <el-tooltip :content="t('workspace.serviceStart')" placement="top">
                    <el-button
                      class="ui-icon-button ui-icon-button--small"
                      size="small"
                      text
                      :icon="VideoPlay"
                      :disabled="isServiceOperationRunning(stack.name) || service.state === 'running'"
                      @click="runServiceAction(stack.name, service.name, 'start')"
                    />
                  </el-tooltip>
                  <el-tooltip :content="t('workspace.serviceStop')" placement="top">
                    <el-button
                      class="ui-icon-button ui-icon-button--small"
                      size="small"
                      text
                      :icon="VideoPause"
                      :disabled="isServiceOperationRunning(stack.name) || service.state !== 'running'"
                      @click="runServiceAction(stack.name, service.name, 'stop')"
                    />
                  </el-tooltip>
                  <el-tooltip :content="t('workspace.serviceRestart')" placement="top">
                    <el-button
                      class="ui-icon-button ui-icon-button--small"
                      size="small"
                      text
                      :icon="Refresh"
                      :disabled="isServiceOperationRunning(stack.name)"
                      @click="runServiceAction(stack.name, service.name, 'restart')"
                    />
                  </el-tooltip>
                </span>
              </button>
            </div>
          </article>
        </div>

        <el-empty v-else-if="!structureLoading" :description="t('workspace.noMatchingStack')" />
      </div>

      <div v-else class="stack-detail-view">
        <header class="detail-hero" :class="{ 'is-stopped': selectedStack.status === 'stopped' || selectedStack.status === 'inactive' || selectedStack.status === 'exited' }">
          <div class="detail-title-block">
            <div class="detail-title-row">
              <span class="dot-state detail-status-dot" :class="`dot-${stackStatusType(selectedStack.status)}`" />
              <span class="stack-state-text detail-state-text">{{ statusLabel(selectedStack.status) }}</span>
              <img
                v-if="selectedStack.icon_url"
                :src="selectedStack.icon_url"
                class="stack-icon-img detail-stack-icon"
                @error="onIconError"
              />
              <el-icon v-else class="stack-title-icon detail-stack-icon"><FolderOpened /></el-icon>
              <h2>{{ selectedStack.name }}</h2>
              <el-tooltip
                v-if="selectedStack.app_url"
                :content="isStackStopped(selectedStack.status) ? t('stackGroup.appUnavailable') : t('stackGroup.openApp')"
                placement="top"
              >
                <button
                  type="button"
                  class="detail-open-app"
                  :disabled="isStackStopped(selectedStack.status)"
                  :aria-label="`${t('stackGroup.openApp')}: ${selectedStack.name}`"
                  @click="openStackApp(selectedStack.app_url)"
                >
                  <el-icon><TopRight /></el-icon>
                  <span>{{ t('stackGroup.openApp') }}</span>
                </button>
              </el-tooltip>
              <UpdateBadge
                v-if="stackUpdateStatus(selectedStack)"
                class="detail-update-badge"
                :status="stackUpdateStatus(selectedStack)!"
              />
              <span
                v-if="selectedStack.management_status === 'unmanaged'"
                class="management-pill detail-management-pill management-unmanaged"
              >
                {{ managementStatusLabel(selectedStack.management_status) }}
              </span>
            </div>
          </div>
          <div class="detail-actions">
            <StackActions
              :host-id="hostId"
              :stack-name="selectedStack.name"
              show-compose
              management-menu
              size="large"
              :can-edit-compose="selectedStack.management_status !== 'unmanaged'"
              @refresh="$emit('refresh')"
              @operation-start="onOperationStart"
              @terminal-chunk="onTerminalChunk"
              @operation-complete="handleOperationComplete"
              @compose="openCompose(selectedStack.name)"
            />
          </div>
        </header>

        <StackOperationDock
          v-if="isOperationDockVisible(selectedStack.name)"
          class="detail-operation-dock"
          :stack-name="selectedStack.name"
          :action="operationPanelAction"
          :lines="terminalOutputs[selectedStack.name] || []"
          :status="operationPanelStatus"
          :message="operationPanelMessage"
          @close="handleDockClose(selectedStack.name)"
          @cancel="cancelOperation(selectedStack.name)"
        />

        <div class="stack-detail-grid" ref="detailGridRef">
          <div class="detail-left-column" :style="{ flex: `0 0 ${detailLeftPct}%` }">
            <section class="workspace-section">
              <div class="section-heading">
                <h3>{{ t('workspace.containerGroup') }}</h3>
                <span>{{ t('workspace.containers', { count: selectedStackContainers.length }) }}</span>
              </div>
              <div class="container-group">
                <button
                  v-for="container in selectedStackContainers"
                  :key="container.id"
                  class="container-row"
                  :class="{ active: selectedContainerId === container.id }"
                  type="button"
                  @click="selectContainer(container.id)"
                >
                  <StatusIcon :status="container.state === 'running' ? 'online' : 'offline'" />
                  <div class="container-main">
                    <span class="container-name">{{ container.service_name || container.name }}</span>
                    <span class="container-meta container-meta--mono">{{ container.image }}</span>
                  </div>
                  <span class="container-status">{{ container.status || container.state }}</span>

                  <div class="container-actions-wrap" @click.stop>
                    <UpdateBadge
                      v-if="containerUpdateStatus(container)"
                      :status="containerUpdateStatus(container)!"
                    />
                    <span class="service-actions container-service-actions">
                      <el-tooltip :content="t('workspace.serviceStart')" placement="top">
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="VideoPlay"
                          :disabled="!container.service_name || isServiceOperationRunning(selectedStack.name) || container.state === 'running'"
                          @click="container.service_name && runServiceAction(selectedStack.name, container.service_name, 'start')"
                        />
                      </el-tooltip>
                      <el-tooltip :content="t('workspace.serviceStop')" placement="top">
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="VideoPause"
                          :disabled="!container.service_name || isServiceOperationRunning(selectedStack.name) || container.state !== 'running'"
                          @click="container.service_name && runServiceAction(selectedStack.name, container.service_name, 'stop')"
                        />
                      </el-tooltip>
                      <el-tooltip :content="t('workspace.serviceRestart')" placement="top">
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="Refresh"
                          :disabled="!container.service_name || isServiceOperationRunning(selectedStack.name)"
                          @click="container.service_name && runServiceAction(selectedStack.name, container.service_name, 'restart')"
                        />
                      </el-tooltip>
                    </span>
                  </div>
                </button>
                <el-empty v-if="selectedStackContainers.length === 0" :description="t('workspace.noContainers')" />
              </div>
            </section>

            <section class="workspace-section terminal-section">
              <div class="section-heading">
                <h3>{{ t('workspace.terminal') }}</h3>
                <div class="terminal-tools">
                  <el-button class="ui-button ui-button--compact" size="small" text :loading="logsLoading" @click="loadLogs">
                    <el-icon><Refresh /></el-icon>
                    {{ t('workspace.refresh') }}
                  </el-button>
                </div>
              </div>
              <div class="embedded-terminal" ref="logViewportRef">
                <div v-if="logsLoading && logLines.length === 0" class="terminal-muted">
                  {{ t('workspace.loadingLogs') }}
                </div>
                <div v-else-if="logLines.length === 0" class="terminal-muted">
                  {{ t('workspace.noLogs') }}
                </div>
                <div
                  v-for="(line, index) in logLines"
                  :key="`${index}-${line.service}-${line.text}`"
                  class="terminal-log-line"
                  :class="`level-${line.level}`"
                >
                  <span v-if="line.service" class="terminal-service">{{ line.service }}</span>
                  <span class="terminal-message">{{ line.text }}</span>
                </div>
                <div v-if="logsActive" class="terminal-cursor">▊</div>
              </div>
            </section>
          </div>

          <div class="detail-grid-resizer" @mousedown="startDetailResize" />

          <aside class="detail-panel">
            <div class="panel-header">
              <div>
                <div class="workspace-kicker">
                  {{ selectedContainer ? t('workspace.containerDetail') : t('workspace.composePreview') }}
                </div>
                <div class="panel-header-title-row">
                  <h3>{{ selectedContainer ? (selectedContainer.service_name || selectedContainer.name) : composeFileName }}</h3>
                  <span v-if="selectedContainer" class="status-badge" :class="selectedContainer.state">
                    <span class="status-badge-dot" />
                    <span class="status-badge-text">{{ selectedContainer.status || selectedContainer.state }}</span>
                  </span>
                </div>
              </div>
              <el-button
                v-if="selectedContainer"
                class="ui-button ui-button--compact"
                size="small"
                text
                @click="selectedContainerId = ''"
              >
                {{ t('workspace.showCompose') }}
              </el-button>
            </div>

            <div v-if="selectedContainer" class="container-detail-panel">
              <!-- Stats Dashboard -->
              <div class="stats-dashboard">
                <div class="stat-card cpu" :class="cpuLevel">
                  <div class="stat-card-head">
                    <el-icon><Cpu /></el-icon>
                    <span>CPU</span>
                  </div>
                  <div class="stat-card-body">
                    <span class="stat-card-value">
                      {{ selectedContainerStats?.cpu_percent.toFixed(1) ?? '-' }}<small>%</small>
                    </span>
                  </div>
                  <el-progress
                    v-if="selectedContainerStats"
                    :percentage="Math.min(selectedContainerStats.cpu_percent, 100)"
                    :stroke-width="4"
                    :show-text="false"
                    :color="cpuColor"
                  />
                  <span v-else class="stat-na">-</span>
                </div>

                <div class="stat-card mem" :class="memLevel">
                  <div class="stat-card-head">
                    <el-icon><Monitor /></el-icon>
                    <span>MEM</span>
                  </div>
                  <div class="stat-card-body">
                    <span class="stat-card-value">
                      {{ selectedContainerStats?.memory_percent.toFixed(1) ?? '-' }}<small>%</small>
                    </span>
                    <span class="stat-card-sub" v-if="selectedContainerStats">
                      {{ formatBytes(selectedContainerStats.memory_usage) }}
                    </span>
                  </div>
                  <el-progress
                    v-if="selectedContainerStats"
                    :percentage="Math.min(selectedContainerStats.memory_percent, 100)"
                    :stroke-width="4"
                    :show-text="false"
                    :color="memColor"
                  />
                  <span v-else class="stat-na">-</span>
                </div>

                <div class="stat-card rx">
                  <div class="stat-card-head">
                    <el-icon><Download /></el-icon>
                    <span>RX</span>
                  </div>
                  <div class="stat-card-body">
                    <span class="stat-card-value net-val">
                      {{ selectedContainerStats ? formatBytes(selectedContainerStats.network_rx_bytes) : '-' }}
                    </span>
                  </div>
                  <div class="stat-card-bar-spacer" />
                </div>

                <div class="stat-card tx">
                  <div class="stat-card-head">
                    <el-icon><Top /></el-icon>
                    <span>TX</span>
                  </div>
                  <div class="stat-card-body">
                    <span class="stat-card-value net-val">
                      {{ selectedContainerStats ? formatBytes(selectedContainerStats.network_tx_bytes) : '-' }}
                    </span>
                  </div>
                  <div class="stat-card-bar-spacer" />
                </div>
              </div>

              <!-- Basic Info List Card -->
              <div class="info-card-list">
                <!-- Image Row -->
                <div class="info-row image-row">
                  <div class="info-row-left">
                    <el-icon><Collection /></el-icon>
                    <span class="info-row-label">{{ t('workspace.containerImage') }}</span>
                  </div>
                  <div class="info-row-right">
                    <el-tooltip :content="selectedContainer.image" placement="top" :show-after="500">
                      <span class="info-row-value monospace">{{ selectedContainer.image }}</span>
                    </el-tooltip>
                    <el-button 
                      class="ui-icon-button ui-icon-button--small row-copy-btn"
                      size="small" 
                      text 
                      :icon="DocumentCopy"
                      @click="copyToClipboard(selectedContainer.image, t('workspace.containerImage'))"
                      :aria-label="t('stackOp.copy')"
                    />
                  </div>
                </div>
                <!-- ID Row -->
                <div class="info-row id-row">
                  <div class="info-row-left">
                    <el-icon><Monitor /></el-icon>
                    <span class="info-row-label">{{ t('workspace.containerId') }}</span>
                  </div>
                  <div class="info-row-right">
                    <span class="info-row-value monospace">{{ selectedContainer.id }}</span>
                    <el-button 
                      class="ui-icon-button ui-icon-button--small row-copy-btn"
                      size="small" 
                      text 
                      :icon="DocumentCopy"
                      @click="copyToClipboard(selectedContainer.id, t('workspace.containerId'))"
                      :aria-label="t('stackOp.copy')"
                    />
                  </div>
                </div>
                <!-- Created Row -->
                <div class="info-row created-row">
                  <div class="info-row-left">
                    <el-icon><Calendar /></el-icon>
                    <span class="info-row-label">{{ t('containerTable.created') }}</span>
                  </div>
                  <div class="info-row-right">
                    <span class="info-row-value">{{ formatTime(selectedContainer.created) }}</span>
                  </div>
                </div>
              </div>

              <!-- Ports -->
              <div class="ports-section" v-if="deduplicatedPorts.length">
                <span class="ports-section-label">{{ t('workspace.containerPorts') }}</span>
                <div class="ports-grid">
                  <div v-for="(port, idx) in deduplicatedPorts" :key="idx" class="port-row-item">
                    <span class="port-arrow-icon">⚡</span>
                    <div class="port-mapping">
                      <span v-if="port.public_port" class="port-host-link" @click="copyToClipboard(`${port.public_port}`, 'Public Port')">
                        {{ port.public_port }}
                      </span>
                      <span v-else class="port-host-none">-</span>
                      <span class="port-arrow">➔</span>
                      <span class="port-target">{{ port.private_port }}</span>
                      <span class="port-protocol-tag">{{ port.type }}</span>
                    </div>
                    <el-button
                      v-if="port.public_port"
                      class="ui-icon-button ui-icon-button--small port-action-btn"
                      size="small"
                      text
                      :icon="DocumentCopy"
                      @click="copyToClipboard(port.public_port ? `${port.public_port}` : `${port.private_port}`, 'Port')"
                    />
                  </div>
                </div>
              </div>
              <div class="ports-section empty" v-else>
                <span class="ports-section-label">{{ t('workspace.containerPorts') }}</span>
                <span class="ports-empty-text">-</span>
              </div>

              <!-- Collapsible Details -->
              <el-collapse v-model="activeCollapseNames" class="detail-collapse">
                <el-collapse-item name="runtime">
                  <template #title>
                    <div class="collapse-title">
                      <el-icon><Setting /></el-icon>
                      <span>{{ t('workspace.runtime') }}</span>
                    </div>
                  </template>
                  <div class="collapse-grid">
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.restart') }}</span>
                      <strong class="field-value">{{ formatRestartPolicy(selectedContainer.restart_policy) }}</strong>
                    </div>
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.restarts') }}</span>
                      <strong class="field-value">{{ selectedContainer.restart_count ?? 0 }}</strong>
                    </div>
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.networkMode') }}</span>
                      <strong class="field-value monospace">{{ selectedContainer.network_mode || '-' }}</strong>
                    </div>
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.privileged') }}</span>
                      <strong class="field-value">{{ selectedContainer.privileged ? t('workspace.yes') : t('workspace.no') }}</strong>
                    </div>
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.user') }}</span>
                      <strong class="field-value">{{ selectedContainer.user || t('workspace.default') }}</strong>
                    </div>
                    <div class="collapse-field">
                      <span class="field-label">{{ t('workspace.workdir') }}</span>
                      <div class="field-value-wrapper">
                        <code class="field-value monospace" :title="selectedContainer.working_dir">{{ selectedContainer.working_dir || '-' }}</code>
                        <el-button
                          v-if="selectedContainer.working_dir"
                          class="ui-icon-button ui-icon-button--small field-copy-btn"
                          size="small"
                          text
                          :icon="DocumentCopy"
                          @click="copyToClipboard(selectedContainer.working_dir, t('workspace.workdir'))"
                        />
                      </div>
                    </div>
                  </div>
                </el-collapse-item>

                <el-collapse-item
                  v-if="formatCommand(selectedContainer.entrypoint) || formatCommand(selectedContainer.command)"
                  name="command"
                >
                  <template #title>
                    <div class="collapse-title">
                      <el-icon><Document /></el-icon>
                      <span>{{ t('workspace.command') }}</span>
                    </div>
                  </template>
                  <div class="command-block-list">
                    <div v-if="formatCommand(selectedContainer.entrypoint)" class="command-block">
                      <div class="command-block-header">
                        <span>Entrypoint</span>
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="DocumentCopy"
                          @click="copyToClipboard(formatCommand(selectedContainer.entrypoint), 'Entrypoint')"
                        />
                      </div>
                      <pre class="command-terminal-box"><code>{{ formatCommand(selectedContainer.entrypoint) }}</code></pre>
                    </div>
                    <div v-if="formatCommand(selectedContainer.command)" class="command-block">
                      <div class="command-block-header">
                        <span>Cmd</span>
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="DocumentCopy"
                          @click="copyToClipboard(formatCommand(selectedContainer.command), 'Command')"
                        />
                      </div>
                      <pre class="command-terminal-box"><code>{{ formatCommand(selectedContainer.command) }}</code></pre>
                    </div>
                  </div>
                </el-collapse-item>

                <el-collapse-item v-if="networkEntries.length" name="networks">
                  <template #title>
                    <div class="collapse-title">
                      <el-icon><Link /></el-icon>
                      <span>{{ t('workspace.networks') }}</span>
                    </div>
                  </template>
                  <div class="network-detail-list">
                    <div v-for="[name, network] in networkEntries" :key="name" class="network-row-card">
                      <div class="network-row-header">
                        <span class="network-name-badge">{{ name }}</span>
                        <el-button
                          v-if="network.IPAddress || network.GlobalIPv6Address"
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="DocumentCopy"
                          @click="copyToClipboard(network.IPAddress || network.GlobalIPv6Address || '', 'IP')"
                        />
                      </div>
                      <div class="network-row-body">
                        <div class="network-metric-item">
                          <span class="network-metric-label">IP Address</span>
                          <code class="network-metric-value monospace">{{ network.IPAddress || network.GlobalIPv6Address || '-' }}</code>
                        </div>
                        <div class="network-metric-item">
                          <span class="network-metric-label">Mac Address</span>
                          <code class="network-metric-value monospace">{{ network.MacAddress || '-' }}</code>
                        </div>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>

                <el-collapse-item v-if="visibleMounts.length" name="mounts">
                  <template #title>
                    <div class="collapse-title">
                      <el-icon><FolderOpened /></el-icon>
                      <span>{{ t('workspace.mounts') }}</span>
                    </div>
                  </template>
                  <div class="mount-detail-list">
                    <div v-for="mount in visibleMounts" :key="`${mount.Source}-${mount.Destination}`" class="mount-row-card">
                      <div class="mount-row-header">
                        <span class="mount-type-badge" :class="mount.Type || 'mount'">{{ mount.Type || 'mount' }}</span>
                        <span class="mount-rw-badge" :class="mount.RW === false ? 'ro' : 'rw'">
                          {{ mount.RW === false ? 'Read-only' : 'Read-Write' }}
                        </span>
                      </div>
                      <div class="mount-path-group">
                        <div class="mount-path-item host-path">
                          <span class="path-icon">🖥️</span>
                          <div class="path-content">
                            <span class="path-title">Host Source</span>
                            <code class="path-value monospace" :title="mount.Source || mount.Name">{{ mount.Source || mount.Name || '-' }}</code>
                          </div>
                          <el-button
                            v-if="mount.Source || mount.Name"
                            class="ui-icon-button ui-icon-button--small"
                            size="small"
                            text
                            :icon="DocumentCopy"
                            @click="copyToClipboard(mount.Source || mount.Name || '', 'Mount Source')"
                          />
                        </div>
                        <div class="mount-path-divider">
                          <el-icon><ArrowRight /></el-icon>
                        </div>
                        <div class="mount-path-item container-path">
                          <span class="path-icon">📦</span>
                          <div class="path-content">
                            <span class="path-title">Container Dest</span>
                            <code class="path-value monospace" :title="mount.Destination">{{ mount.Destination || '-' }}</code>
                          </div>
                          <el-button
                            v-if="mount.Destination"
                            class="ui-icon-button ui-icon-button--small"
                            size="small"
                            text
                            :icon="DocumentCopy"
                            @click="copyToClipboard(mount.Destination || '', 'Mount Dest')"
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>

                <el-collapse-item v-if="visibleContainerLabels.length" name="labels">
                  <template #title>
                    <div class="collapse-title">
                      <el-icon><Collection /></el-icon>
                      <span>{{ t('workspace.labels') }}</span>
                    </div>
                  </template>
                  <div class="label-list">
                    <div v-for="[key, value] in visibleContainerLabels" :key="key" class="label-row-card">
                      <div class="label-key-wrap">
                        <span class="label-key monospace">{{ key }}</span>
                        <el-button
                          class="ui-icon-button ui-icon-button--small"
                          size="small"
                          text
                          :icon="DocumentCopy"
                          @click="copyToClipboard(`${key}=${value}`, 'Label')"
                        />
                      </div>
                      <div class="label-value-wrap">
                        <code class="label-value monospace">{{ value }}</code>
                      </div>
                    </div>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>

            <div v-else class="compose-preview">
              <div v-if="composeLoading" class="panel-muted">{{ t('workspace.loadingCompose') }}</div>
              <el-alert
                v-else-if="composeError"
                :title="composeError"
                type="warning"
                show-icon
                :closable="false"
              />
              <div v-else-if="!composeYaml" class="panel-muted">{{ t('workspace.noComposeFromAgent') }}</div>
              <MonacoEditor
                v-else
                v-model="composeYaml"
                language="yaml"
                readonly
                line-numbers="off"
                word-wrap="on"
                height="100%"
              />
            </div>
          </aside>
        </div>
      </div>
    </main>

    <ComposeDrawer
      v-if="composeDrawerVisible"
      :visible="composeDrawerVisible"
      :host-id="hostId"
      :stack-name="currentComposeStack"
      :create-mode="composeDrawerMode === 'create'"
      @close="composeDrawerVisible = false"
      @saved="onComposeSaved"
      @deploy="handleComposeDeploy"
    />

    <!-- Docker Clean Dialog -->
    <el-dialog
      v-model="pruneDialogVisible"
      :title="t('workspace.pruneDocker')"
      width="700px"
      :close-on-click-modal="false"
      destroy-on-close
      append-to-body
      class="prune-dialog"
    >
      <StackOperationDock
        class="prune-terminal"
        stack-name="Docker System"
        :action="operationPanelAction"
        :lines="terminalOutputs['__prune__'] || []"
        :status="operationPanelStatus"
        :message="operationPanelMessage"
        @close="handleDockClose('__prune__')"
        @cancel="cancelOperation('__prune__')"
      />
    </el-dialog>

    <!-- Global Operation Dialog (for new stacks being deployed) -->
    <el-dialog
      v-model="showGlobalOperationDialog"
      :title="t('compose.deployOutput')"
      width="700px"
      :close-on-click-modal="false"
      destroy-on-close
      append-to-body
      class="operation-dialog"
    >
      <StackOperationDock
        class="global-terminal"
        :stack-name="operationPanelStack"
        :action="operationPanelAction"
        :lines="terminalOutputs[operationPanelStack] || []"
        :status="operationPanelStatus"
        :message="operationPanelMessage"
        @close="handleDockClose(operationPanelStack)"
        @cancel="cancelOperation(operationPanelStack)"
      />
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  Collection,
  Cpu,
  Document,
  DocumentCopy,
  Download,
  EditPen,
  FolderOpened,
  Link,
  Monitor,
  Plus,
  Refresh,
  Search,
  Setting,
  Top,
  Calendar,
  ArrowRight,
  Brush,
  VideoPause,
  VideoPlay,
  TopRight,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import { useConfirm } from "@/composables/useConfirm";
import StatusIcon from "./StatusIcon.vue";
import StackActions from "./StackActions.vue";
import type { OperationState, TerminalChunkEvent } from "./StackActions.vue";
import StackOperationDock from "./StackOperationDock.vue";
import ComposeDrawer, { type ComposeDeployPayload } from "./ComposeDrawer.vue";
import MonacoEditor from "@/components/MonacoEditor.vue";
import UpdateBadge from "./UpdateBadge.vue";
import { sortStacks } from "@/utils/stackSorting";

export interface StackService {
  name: string;
  container_id?: string;
  state: string;
  status: string;
}

export interface StackSummary {
  name: string;
  status: string;
  compose_file?: string;
  service_count: number;
  running_count: number;
  services: StackService[];
  icon_url?: string;  // 自定义图标（网络 URL 或 /api/static/icons/...）
  management_status?: string;
  app_url?: string;
}

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
  image_id?: string;
  repo_digests?: string[];
  state: string;
  status: string;
  created: number;
  ports: ContainerPort[];
  labels?: Record<string, string>;
  stack_name?: string;
  service_name?: string;
  restart_count?: number;
  driver?: string;
  platform?: string;
  hostname?: string;
  domainname?: string;
  user?: string;
  working_dir?: string;
  entrypoint?: string[] | string | null;
  command?: string[] | string | null;
  restart_policy?: Record<string, any>;
  network_mode?: string;
  privileged?: boolean;
  mounts?: ContainerMount[];
  networks?: Record<string, ContainerNetwork>;
  health?: Record<string, any> | null;
}

export interface ContainerMount {
  Type?: string;
  Name?: string;
  Source?: string;
  Destination?: string;
  Mode?: string;
  RW?: boolean;
  Propagation?: string;
}

export interface ContainerNetwork {
  IPAddress?: string;
  GlobalIPv6Address?: string;
  MacAddress?: string;
  Gateway?: string;
  NetworkID?: string;
  Aliases?: string[];
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

interface StackLogLine {
  service: string;
  text: string;
  level: "info" | "warn" | "error";
}

const props = defineProps<{
  hostId: string;
  stacks: StackSummary[];
  containers: ContainerSummary[];
  containerStats: Record<string, ContainerStatsData>;
  updateStatuses: Record<string, string>;
  updateLoading?: boolean;
  structureLoading?: boolean;
}>();

const emit = defineEmits<{
  refresh: [];
  "check-updates": [];
}>();

const { t, locale } = useI18n();
const route = useRoute();
const { confirm } = useConfirm();

const stackSearch = ref("");
const selectedStackName = ref("");
const selectedContainerId = ref("");

const composeYaml = ref("");
const composeFileName = ref("compose.yaml");
const composeLoading = ref(false);
const composeError = ref("");

// ── Draggable detail‑grid split ─────────────────────────────────────────────
const DETAIL_SPLIT_KEY = "detail-grid-split-pct";
const DETAIL_MIN_LEFT_PCT = 25;
const DETAIL_MAX_LEFT_PCT = 80;
const DETAIL_DEFAULT_PCT = 65;

const detailGridRef = ref<HTMLElement | null>(null);
const detailLeftPct = ref<number>(
  (() => {
    try {
      const v = parseFloat(localStorage.getItem(DETAIL_SPLIT_KEY) || "");
      return isNaN(v) ? DETAIL_DEFAULT_PCT : Math.min(DETAIL_MAX_LEFT_PCT, Math.max(DETAIL_MIN_LEFT_PCT, v));
    } catch {
      return DETAIL_DEFAULT_PCT;
    }
  })()
);

function startDetailResize(e: MouseEvent) {
  e.preventDefault();
  const grid = detailGridRef.value;
  if (!grid) return;
  const gridRect = grid.getBoundingClientRect();
  const startX = e.clientX;
  const startPct = detailLeftPct.value;
  let nextPct = startPct;
  let rafId: number | null = null;

  function flush() {
    rafId = null;
    detailLeftPct.value = nextPct;
  }

  function onMove(ev: MouseEvent) {
    const deltaPx = ev.clientX - startX;
    const deltaPct = (deltaPx / gridRect.width) * 100;
    nextPct = Math.min(
      DETAIL_MAX_LEFT_PCT,
      Math.max(DETAIL_MIN_LEFT_PCT, startPct + deltaPct)
    );
    // Coalesce mousemove bursts into a single reactive update per animation frame
    if (rafId === null) {
      rafId = requestAnimationFrame(flush);
    }
  }

  function onUp() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    detailLeftPct.value = nextPct;
    document.body.style.removeProperty("cursor");
    document.body.style.removeProperty("user-select");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    try {
      localStorage.setItem(DETAIL_SPLIT_KEY, String(detailLeftPct.value));
    } catch {}
  }

  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}
// ────────────────────────────────────────────────────────────────────────────

const logLines = ref<StackLogLine[]>([]);
const logsLoading = ref(false);
const logsActive = ref(false);
const logViewportRef = ref<HTMLElement | null>(null);
let logStreamController: AbortController | null = null;
let logReconnectTimer: ReturnType<typeof setTimeout> | null = null;
const LOG_RECONNECT_ACTIONS = new Set(["start", "restart", "update", "up", "service-start", "service-restart"]);
const LOG_STOP_ACTIONS = new Set(["stop", "down", "delete", "service-stop"]);
const MAX_LOG_RECONNECT_ATTEMPTS = 6;

const terminalOutputs = reactive<Record<string, string[]>>({});
const runningOperations = reactive<Record<string, { abort: () => void; action: string }>>({});
const operationPanelVisible = ref(false);
const operationPanelStack = ref("");
const operationPanelStatus = ref<"running" | "success" | "error" | "idle">("idle");
const operationPanelMessage = ref("");
const operationPanelAction = ref("");
let operationAutoCloseTimer: ReturnType<typeof setTimeout> | null = null;

const pruneDialogVisible = computed({
  get() {
    return operationPanelVisible.value && operationPanelStack.value === "__prune__";
  },
  set(val) {
    if (!val) {
      closeOperationDock();
    }
  }
});

const showGlobalOperationDialog = computed({
  get() {
    if (!operationPanelVisible.value) return false;
    const name = operationPanelStack.value;
    if (!name || name === "__prune__") return false;
    if (selectedStackName.value === name) return false;
    const exists = props.stacks.some((s) => s.name === name);
    return !exists;
  },
  set(val) {
    if (!val) {
      closeOperationDock();
    }
  }
});

const composeDrawerVisible = ref(false);
const currentComposeStack = ref("");
const composeDrawerMode = ref<"edit" | "create">("edit");
const pruneLoading = ref(false);
const bulkUpdateLoading = ref(false);
let bulkUpdateAbortController: AbortController | null = null;

const filteredStacks = computed(() => {
  const query = stackSearch.value.trim().toLowerCase();
  const filtered = query
    ? props.stacks.filter((stack) => stack.name.toLowerCase().includes(query))
    : [...props.stacks];
  return sortStacks(filtered);
});

const updatableStacks = computed(() =>
  sortStacks(props.stacks.filter((stack) => stackUpdateStatus(stack) === "updatable"))
);

const selectedStack = computed(() =>
  props.stacks.find((stack) => stack.name === selectedStackName.value) || null
);

const selectedStackContainers = computed(() => {
  if (!selectedStack.value) return [];
  return props.containers
    .filter((container) => container.stack_name === selectedStack.value?.name)
    .sort((a, b) => (a.service_name || a.name).localeCompare(b.service_name || b.name));
});

const selectedContainer = computed(() =>
  selectedStackContainers.value.find((container) => container.id === selectedContainerId.value) || null
);

const selectedContainerStats = computed(() =>
  selectedContainer.value ? props.containerStats[selectedContainer.value.id] : null
);

const deduplicatedPorts = computed(() => {
  if (!selectedContainer.value || !selectedContainer.value.ports) return [];
  const seen = new Set<string>();
  return selectedContainer.value.ports.filter((port) => {
    const key = `${port.public_port || ''}:${port.private_port}/${port.type}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
});

async function copyToClipboard(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success(`${label}: ${t("stackOp.copied")}`);
  } catch (err) {
    ElMessage.error(t("stackOp.copyFailed") || "Copy failed");
  }
}

const activeCollapseNames = ref<string[]>(["runtime"]);

const cpuColor = computed(() => {
  const pct = selectedContainerStats.value?.cpu_percent ?? 0;
  if (pct > 80) return "#f87171";
  if (pct > 50) return "#fbbf24";
  return "#34d399";
});

const cpuLevel = computed(() => {
  const pct = selectedContainerStats.value?.cpu_percent ?? 0;
  if (pct > 80) return "critical";
  if (pct > 50) return "warn";
  return "ok";
});

const memColor = computed(() => {
  const pct = selectedContainerStats.value?.memory_percent ?? 0;
  if (pct > 80) return "#f87171";
  if (pct > 50) return "#fbbf24";
  return "#34d399";
});

const memLevel = computed(() => {
  const pct = selectedContainerStats.value?.memory_percent ?? 0;
  if (pct > 80) return "critical";
  if (pct > 50) return "warn";
  return "ok";
});

function formatTime(created: number): string {
  const d = new Date(created * 1000);
  const months = d.toLocaleDateString(locale.value, { month: "2-digit", day: "2-digit" });
  const time = d.toLocaleTimeString(locale.value, { hour: "2-digit", minute: "2-digit" });
  return `${months} ${time}`;
}

const visibleContainerLabels = computed(() => {
  const labels = selectedContainer.value?.labels || {};
  return Object.entries(labels)
    .filter(([key]) => !isInternalDockerLabel(key))
    .sort(([a], [b]) => a.localeCompare(b));
});

const networkEntries = computed(() =>
  Object.entries(selectedContainer.value?.networks || {})
    .sort(([a], [b]) => a.localeCompare(b))
);

const visibleMounts = computed(() =>
  (selectedContainer.value?.mounts || [])
    .filter((mount) => mount.Destination || mount.Source || mount.Name)
    .sort((a, b) => String(a.Destination || "").localeCompare(String(b.Destination || "")))
);

const runningStackCount = computed(() =>
  props.stacks.filter((stack) => stack.status === "running" || stack.status === "active").length
);

function statusLabel(status: string): string {
  if (status === "running" || status === "active") return t("stackStatus.running");
  if (status === "exited") return t("stackStatus.exited");
  if (status === "stopped" || status === "inactive") return t("stackStatus.stopped");
  if (status === "partially running" || status === "partial") return t("stackStatus.partial");
  return status || t("stackStatus.unknown");
}

function managementStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    managed: t("workspace.stackManaged"),
    deployed: t("workspace.stackDeployed"),
    "file-only": t("workspace.stackFileOnly"),
    unmanaged: t("workspace.stackUnmanaged"),
  };
  return labels[status] || status;
}

function stackStatusType(status: string): string {
  if (status === "running" || status === "active") return "running";
  if (status === "exited") return "exited";
  if (status === "stopped" || status === "inactive") return "stopped";
  return "partial";
}

function isStackStopped(status: string): boolean {
  return status === "stopped" || status === "inactive" || status === "exited";
}

function openStackApp(url?: string) {
  if (!url || !selectedStack.value || isStackStopped(selectedStack.value.status)) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function onIconError(event: Event) {
  // Hide broken <img> so the fallback <el-icon> shows through
  const img = event.target as HTMLImageElement;
  if (img) {
    img.style.display = "none";
  }
}

function containerUpdateStatus(container: ContainerSummary): string | null {
  const status = props.updateStatuses[container.image];
  return status && status !== "up_to_date" && status !== "needs_auth" ? status : null;
}

function isInternalDockerLabel(key: string): boolean {
  return key.startsWith("com.docker.compose.") ||
    key.startsWith("org.opencontainers.image.") ||
    key === "desktop.docker.io/wsl-distro";
}

function stackUpdateStatus(stack: StackSummary): string | null {
  const statuses = props.containers
    .filter((container) => container.stack_name === stack.name)
    .map((container) => containerUpdateStatus(container))
    .filter((status): status is string => Boolean(status));

  if (statuses.includes("updatable")) return "updatable";
  return null;
}

function containerForService(stack: StackSummary, service: StackService): ContainerSummary | null {
  return props.containers.find((container) => {
    if (service.container_id && container.id.startsWith(service.container_id)) return true;
    return container.stack_name === stack.name &&
      (container.service_name === service.name || container.name === service.name);
  }) || null;
}

function serviceUpdateStatus(stack: StackSummary, service: StackService): string | null {
  const container = containerForService(stack, service);
  return container ? containerUpdateStatus(container) : null;
}

function isServiceOperationRunning(stackName: string): boolean {
  return Boolean(runningOperations[stackName]?.action?.startsWith("service-"));
}

async function runServiceAction(stackName: string, serviceName: string, action: "start" | "stop" | "restart") {
  if (!serviceName || isServiceOperationRunning(stackName)) return;

  const actionKey = `service-${action}`;
  const labelMap: Record<"start" | "stop" | "restart", string> = {
    start: t("workspace.serviceStart"),
    stop: t("workspace.serviceStop"),
    restart: t("workspace.serviceRestart"),
  };
  const label = `${labelMap[action]} ${serviceName}`;
  const controller = new AbortController();
  const startedAt = Date.now();

  onOperationStart(stackName, {
    action: actionKey,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
    abort: () => controller.abort(),
  });

  let completed = false;

  try {
    const url =
      `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackName)}` +
      `/services/${encodeURIComponent(serviceName)}/${action}?cols=110&rows=24`;

    await streamSse({
      url,
      method: "POST",
      timeoutMs: 120000,
      signal: controller.signal,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        onOperationComplete(stackName, {
          action: actionKey,
          status: "timeout",
          message: t("stack.confirm.timeout"),
          updatedAt: Date.now(),
        });
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          onTerminalChunk(stackName, { action: actionKey, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          onTerminalChunk(stackName, { action: actionKey, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          const succeeded = data.status === "success";
          onOperationComplete(stackName, {
            action: actionKey,
            status: succeeded ? "success" : "error",
            message: data.message || t(succeeded ? "stack.confirm.success" : "stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          });
          if (succeeded) {
            emit("refresh");
          }
        } else if (ev.event === "error") {
          completed = true;
          onOperationComplete(stackName, {
            action: actionKey,
            status: "error",
            message: ev.data?.message || t("stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          });
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        onOperationComplete(stackName, {
          action: actionKey,
          status: "error",
          message: t("stack.confirm.cancelled"),
          updatedAt: Date.now(),
        });
        return;
      }
      onOperationComplete(stackName, {
        action: actionKey,
        status: "success",
        message: t("stack.confirm.success", { action: label }),
        updatedAt: Date.now(),
      });
      emit("refresh");
    }
  } catch (e: any) {
    if (!completed) {
      onOperationComplete(stackName, {
        action: actionKey,
        status: "error",
        message: t("stack.confirm.failure", { action: label }) + ": " + (e.message || t("stack.confirm.unknownError")),
        updatedAt: Date.now(),
      });
    }
  }
}

function formatPorts(ports: ContainerPort[] = []): string {
  return ports
    .map((port) => port.public_port
      ? `${port.public_port}:${port.private_port}/${port.type}`
      : `${port.private_port}/${port.type}`)
    .join(", ");
}

function formatPortsPreview(ports: ContainerPort[] = []): string {
  const visiblePorts = ports.slice(0, 3);
  const summary = formatPorts(visiblePorts);
  const hiddenCount = ports.length - visiblePorts.length;
  return hiddenCount > 0 ? `${summary} +${hiddenCount}` : summary;
}

function formatCommand(value: string[] | string | null | undefined): string {
  if (!value) return "";
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" ");
  }
  return value;
}

function formatRestartPolicy(policy?: Record<string, any>): string {
  if (!policy) return "-";
  const name = policy.Name || policy.name || "";
  const retryCount = policy.MaximumRetryCount ?? policy.maximum_retry_count;
  if (!name) return "-";
  return retryCount ? `${name} (${retryCount})` : name;
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`;
}

function showAllStacks() {
  selectedStackName.value = "";
  selectedContainerId.value = "";
  stopLogs();
}

function handleCardMouseMove(e: MouseEvent) {
  const card = e.currentTarget as HTMLElement;
  if (!card) return;
  const rect = card.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  
  card.style.transform = "translate3d(0, -3px, 0)";
  card.style.setProperty("--shine-x", `${x}px`);
  card.style.setProperty("--shine-y", `${y}px`);
}

function handleCardMouseLeave(e: MouseEvent) {
  const card = e.currentTarget as HTMLElement;
  if (!card) return;
  card.style.transform = "translate3d(0, 0, 0)";
  card.style.removeProperty("--shine-x");
  card.style.removeProperty("--shine-y");
}

function selectStack(stackName: string) {
  selectedStackName.value = stackName;
  selectedContainerId.value = "";
}

function selectContainer(containerId: string) {
  selectedContainerId.value = containerId;
}

function selectServiceContainer(stackName: string, service: StackService) {
  selectStack(stackName);
  const stack = props.stacks.find((item) => item.name === stackName);
  if (!stack) return;
  const container = containerForService(stack, service);
  if (container) {
    selectedContainerId.value = container.id;
  }
}

function openCompose(stackName: string) {
  composeDrawerMode.value = "edit";
  currentComposeStack.value = stackName;
  composeDrawerVisible.value = true;
}

function openNewCompose() {
  composeDrawerMode.value = "create";
  currentComposeStack.value = "";
  composeDrawerVisible.value = true;
}

async function confirmPrune() {
  try {
    await confirm(
      t("workspace.pruneMessage"),
      t("workspace.pruneConfirm"),
      {
        tone: "danger",
        confirmButtonText: t("stack.delete.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  }

  pruneLoading.value = true;
  const pruneKey = "__prune__";
  terminalOutputs[pruneKey] = [];
  operationPanelStack.value = pruneKey;
  operationPanelStatus.value = "running";
  operationPanelMessage.value = t("stack.confirm.running", { action: t("workspace.pruneDocker") });
  operationPanelAction.value = "prune";
  operationPanelVisible.value = true;

  const controller = new AbortController();
  runningOperations[pruneKey] = {
    abort: () => controller.abort(),
    action: "prune"
  };

  let completed = false;

  try {
    const url = `/api/hosts/${props.hostId}/prune`;
    await streamSse({
      url,
      method: "POST",
      signal: controller.signal,
      timeoutMs: 300000,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        operationPanelStatus.value = "error";
        operationPanelMessage.value = t("stack.confirm.timeout");
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          if (!terminalOutputs[pruneKey]) terminalOutputs[pruneKey] = [];
          terminalOutputs[pruneKey].push(ev.data?.raw ?? ev.rawData);
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          operationPanelStatus.value = data.status === "success" ? "success" : "error";
          operationPanelMessage.value = data.message || "";
          emit("refresh");
          scheduleOperationAutoClose(pruneKey, 4000);
        } else if (ev.event === "error") {
          completed = true;
          operationPanelStatus.value = "error";
          operationPanelMessage.value = ev.data?.message || t("stack.confirm.failure", { action: t("workspace.pruneDocker") });
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        operationPanelStatus.value = "error";
        operationPanelMessage.value = t("stack.confirm.cancelled");
        return;
      }
      operationPanelStatus.value = "success";
      operationPanelMessage.value = t("stack.confirm.success", { action: t("workspace.pruneDocker") });
      emit("refresh");
      scheduleOperationAutoClose(pruneKey, 3000);
    }
  } catch (e: any) {
    if (completed) return;
    completed = true;
    if (controller.signal.aborted) {
      operationPanelStatus.value = "error";
      operationPanelMessage.value = t("stack.confirm.cancelled");
      return;
    }
    operationPanelStatus.value = "error";
    operationPanelMessage.value = e.message || t("stack.confirm.failure", { action: t("workspace.pruneDocker") });
  } finally {
    delete runningOperations[pruneKey];
    pruneLoading.value = false;
  }
}

async function confirmUpdateAll() {
  const stacksToUpdate = updatableStacks.value;
  if (stacksToUpdate.length === 0 || bulkUpdateLoading.value) return;

  try {
    await confirm(
      t("workspace.updateAllMessage", { count: stacksToUpdate.length }),
      t("workspace.updateAllConfirm"),
      {
        tone: "warning",
        confirmButtonText: t("stack.confirm.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  }

  bulkUpdateLoading.value = true;
  let successCount = 0;

  try {
    for (const stack of stacksToUpdate) {
      const ok = await runStackUpdate(stack.name, { refreshOnSuccess: false });
      if (ok) successCount += 1;
    }

    if (successCount === stacksToUpdate.length) {
      ElMessage.success(t("workspace.updateAllSuccess", { count: successCount }));
    } else {
      ElMessage.warning(t("workspace.updateAllPartial", {
        success: successCount,
        total: stacksToUpdate.length,
      }));
    }
    emit("refresh");
    emit("check-updates");
  } finally {
    bulkUpdateLoading.value = false;
    bulkUpdateAbortController = null;
  }
}

async function runStackUpdate(
  stackName: string,
  options: { refreshOnSuccess?: boolean } = {},
): Promise<boolean> {
  const refreshOnSuccess = options.refreshOnSuccess !== false;
  const action = "update";
  const label = t("stack.action.update");
  const startedAt = Date.now();
  const controller = new AbortController();
  bulkUpdateAbortController = controller;

  const runningState: OperationState = {
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
    abort: () => controller.abort(),
  };
  onOperationStart(stackName, runningState);

  let completed = false;
  let succeeded = false;

  try {
    const url =
      `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackName)}` +
      `/${action}?cols=110&rows=24`;

    await streamSse({
      url,
      method: "POST",
      timeoutMs: 600000,
      signal: controller.signal,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        onOperationComplete(stackName, {
          action,
          status: "timeout",
          message: t("stack.confirm.timeout"),
          updatedAt: Date.now(),
        });
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          succeeded = data.status === "success";
          onOperationComplete(stackName, {
            action,
            status: succeeded ? "success" : "error",
            message: data.message || t(succeeded ? "stack.confirm.success" : "stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          });
          if (succeeded && refreshOnSuccess) {
            emit("refresh");
          }
        } else if (ev.event === "error") {
          completed = true;
          onOperationComplete(stackName, {
            action,
            status: "error",
            message: ev.data?.message || t("stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          });
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        onOperationComplete(stackName, {
          action,
          status: "error",
          message: t("stack.confirm.cancelled"),
          updatedAt: Date.now(),
        });
        return false;
      }
      succeeded = true;
      onOperationComplete(stackName, {
        action,
        status: "success",
        message: t("stack.confirm.success", { action: label }),
        updatedAt: Date.now(),
      });
      if (refreshOnSuccess) {
        emit("refresh");
      }
    }
  } catch (e: any) {
    if (!completed) {
      onOperationComplete(stackName, {
        action,
        status: "error",
        message: t("stack.confirm.failure", { action: label }) + ": " + (e.message || t("stack.confirm.unknownError")),
        updatedAt: Date.now(),
      });
    }
    succeeded = false;
  } finally {
    delete runningOperations[stackName];
    if (bulkUpdateAbortController === controller) {
      bulkUpdateAbortController = null;
    }
  }

  return succeeded;
}

function applyComposeToPreview(payload: ComposeDeployPayload) {
  if (selectedStackName.value !== payload.stackName) return;
  composeYaml.value = payload.composeYaml;
  composeFileName.value = payload.composeFileName || "compose.yaml";
  composeError.value = "";
  composeLoading.value = false;
}

function onComposeSaved(payload: ComposeDeployPayload) {
  applyComposeToPreview(payload);
  emit("refresh");
}

async function handleComposeDeploy(payload: ComposeDeployPayload) {
  const stackName = payload.stackName;
  const action = "deploy";
  const label = t("stackOp.deploying");
  const startedAt = Date.now();
  const controller = new AbortController();

  const runningState: OperationState = {
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
    abort: () => controller.abort(),
  };

  onOperationStart(stackName, runningState);
  runningOperations[stackName] = {
    abort: () => controller.abort(),
    action,
  };

  let completed = false;

  try {
    const cols = 110;
    const rows = 24;
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackName)}/compose/deploy?cols=${cols}&rows=${rows}`;

    await streamSse({
      url,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      timeoutMs: 300000,
      signal: controller.signal,
      body: JSON.stringify({
        compose_yaml: payload.composeYaml,
        compose_env: payload.composeEnv,
        compose_file_name: payload.composeFileName,
        is_add: payload.isAdd,
      }),
      onTimeout: () => {
        if (completed) return;
        completed = true;
        onOperationComplete(stackName, {
          action,
          status: "timeout",
          message: t("compose.deployTimeout"),
          updatedAt: Date.now(),
        });
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          const success = data.status === "success";

          onOperationComplete(stackName, {
            action,
            status: success ? "success" : "error",
            message: data.message || (success ? t("compose.deploySuccess") : t("compose.deployFailed", { detail: "" })),
            updatedAt: Date.now(),
          });

          if (success) {
            applyComposeToPreview(payload);
            ElMessage.success(payload.isAdd ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
            emit("refresh");
          } else {
            ElMessage.error(t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }));
          }
        } else if (ev.event === "error") {
          completed = true;
          const data = ev.data || {};
          onOperationComplete(stackName, {
            action,
            status: "error",
            message: t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }),
            updatedAt: Date.now(),
          });
          ElMessage.error(t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }));
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        onOperationComplete(stackName, {
          action,
          status: "error",
          message: t("stack.confirm.cancelled"),
          updatedAt: Date.now(),
        });
        return;
      }
      onOperationComplete(stackName, {
        action,
        status: "success",
        message: t("compose.deployCompleted"),
        updatedAt: Date.now(),
      });
      applyComposeToPreview(payload);
      ElMessage.success(payload.isAdd ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
      emit("refresh");
    }
  } catch (e: any) {
    if (completed) return;
    completed = true;
    const detail = e.message || t("compose.unknownError");
    onOperationComplete(stackName, {
      action,
      status: "error",
      message: t("compose.deployFailed", { detail }),
      updatedAt: Date.now(),
    });
    ElMessage.error(t("compose.deployFailed", { detail }));
  } finally {
    delete runningOperations[stackName];
  }
}

function isOperationDockVisible(stackName: string): boolean {
  return operationPanelVisible.value && operationPanelStack.value === stackName;
}

function closeOperationDock() {
  clearOperationAutoClose();
  operationPanelVisible.value = false;
}

function cancelOperation(stackName: string) {
  const op = runningOperations[stackName];
  if (op) {
    op.abort();
    delete runningOperations[stackName];
  }
  if (operationPanelStack.value === stackName) {
    operationPanelStatus.value = "error";
    operationPanelMessage.value = t("stack.confirm.cancelled");
  }
}

function handleDockClose(stackName: string) {
  if (runningOperations[stackName]) {
    cancelOperation(stackName);
  }
  closeOperationDock();
}

function clearOperationAutoClose() {
  if (operationAutoCloseTimer) {
    clearTimeout(operationAutoCloseTimer);
    operationAutoCloseTimer = null;
  }
}

function scheduleOperationAutoClose(stackName: string, delayMs: number) {
  clearOperationAutoClose();
  operationAutoCloseTimer = setTimeout(() => {
    if (operationPanelStack.value === stackName && operationPanelStatus.value !== "running") {
      operationPanelVisible.value = false;
    }
  }, delayMs);
}

async function loadCompose() {
  if (!selectedStack.value) return;
  composeLoading.value = true;
  composeError.value = "";
  composeYaml.value = "";
  composeFileName.value = "compose.yaml";
  try {
    const res = await apiClient.get(
      `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(selectedStack.value.name)}/compose`
    );
    composeYaml.value = res.data.compose_yaml || "";
    composeFileName.value = res.data.compose_file_name || "compose.yaml";
  } catch (error: any) {
    composeError.value = error.response?.data?.detail || error.message || t("workspace.composeLoadFailed");
  } finally {
    composeLoading.value = false;
  }
}

function appendLogLine(text: string, service = "", level: StackLogLine["level"] = "info") {
  const cleanText = normalizeLogText(text);
  if (!cleanText && !service) return;
  logLines.value.push({ service, text: cleanText, level });
  if (logLines.value.length > 500) {
    logLines.value = logLines.value.slice(-500);
  }
  nextTick(() => {
    if (logViewportRef.value) {
      logViewportRef.value.scrollTop = logViewportRef.value.scrollHeight;
    }
  });
}

function normalizeLogText(text: string): string {
  return text.replace(/\t/g, "  ").trimEnd();
}

function clearLogReconnectTimer() {
  if (logReconnectTimer) {
    clearTimeout(logReconnectTimer);
    logReconnectTimer = null;
  }
}

function stopLogs() {
  clearLogReconnectTimer();
  if (logStreamController) {
    logStreamController.abort();
    logStreamController = null;
  }
  logsActive.value = false;
  logsLoading.value = false;
}

function scheduleLogReconnect(stackName: string, attempt: number) {
  if (attempt >= MAX_LOG_RECONNECT_ATTEMPTS || selectedStackName.value !== stackName) return;
  clearLogReconnectTimer();
  const delay = Math.min(5000, 600 + attempt * 900);
  logReconnectTimer = setTimeout(() => {
    logReconnectTimer = null;
    if (selectedStackName.value === stackName) {
      loadLogs({ preserveLines: true, retry: true, attempt: attempt + 1, stackName });
    }
  }, delay);
}

function loadLogs(options: { preserveLines?: boolean; retry?: boolean; attempt?: number; stackName?: string } = {}) {
  const stackName = options.stackName || selectedStack.value?.name;
  if (!stackName) return;
  stopLogs();
  logsLoading.value = true;
  logsActive.value = true;
  if (!options.preserveLines) {
    logLines.value = [];
  }

  const controller = new AbortController();
  logStreamController = controller;
  const url =
    `/api/hosts/${encodeURIComponent(props.hostId)}` +
    `/stacks/${encodeURIComponent(stackName)}` +
    "/logs/stream?tail=120";

  void streamSse({
    url,
    signal: controller.signal,
    onEvent: (ev) => {
      if (ev.event === "ready") {
        logsLoading.value = false;
        return;
      }
      if (ev.event === "line") {
        logsLoading.value = false;
        const service = ev.data?.service;
        const text = ev.data?.text ?? "";
        appendLogLine(text, service || "", logLevel(text));
        return;
      }
      if (ev.event === "error") {
        logsLoading.value = false;
        appendLogLine(ev.data?.message || "log stream failed", ev.data?.service || "", "error");
        return;
      }
      if (ev.event === "complete") {
        logsLoading.value = false;
        logsActive.value = false;
        appendLogLine(ev.data?.message || "Log stream ended.", "", "warn");
        if (options.retry) {
          scheduleLogReconnect(stackName, options.attempt || 0);
        }
      }
    },
  }).catch((error: any) => {
    if (controller.signal.aborted) return;
    appendLogLine(`Failed to stream logs: ${error.message}`, "", "error");
    if (options.retry) {
      scheduleLogReconnect(stackName, options.attempt || 0);
    }
  }).finally(() => {
    if (logStreamController === controller) {
      logStreamController = null;
      logsLoading.value = false;
      logsActive.value = false;
    }
  });
}

function logLevel(text: string): StackLogLine["level"] {
  if (/\b(error|fatal|exception|traceback|failed)\b/i.test(text)) return "error";
  if (/\b(warn|warning|deprecated|retry)\b/i.test(text)) return "warn";
  return "info";
}

function onTerminalChunk(stackName: string, payload: TerminalChunkEvent) {
  if (!terminalOutputs[stackName]) {
    terminalOutputs[stackName] = [];
  }
  terminalOutputs[stackName].push(payload.chunk);

  if (!operationPanelVisible.value || operationPanelStack.value !== stackName) {
    operationPanelStack.value = stackName;
    operationPanelStatus.value = "running";
    operationPanelAction.value = payload.action;
    operationPanelVisible.value = true;
  }
}

function onOperationStart(stackName: string, state: OperationState) {
  clearOperationAutoClose();
  terminalOutputs[stackName] = [];
  operationPanelStack.value = stackName;
  operationPanelStatus.value = "running";
  operationPanelMessage.value = state.message;
  operationPanelAction.value = state.action;
  operationPanelVisible.value = true;
  if (state.abort) {
    runningOperations[stackName] = {
      abort: state.abort,
      action: state.action
    };
  }

  if (
    selectedStackName.value === stackName &&
    LOG_RECONNECT_ACTIONS.has(state.action)
  ) {
    stopLogs();
    if (state.action === "start" || state.action === "service-start" || logLines.value.length === 0) {
      logLines.value = [];
    }
    logsLoading.value = true;
  }
}

function onOperationComplete(stackName: string, state: OperationState) {
  operationPanelStatus.value = state.status === "success"
    ? "success"
    : state.status === "error"
      ? "error"
      : "idle";
  operationPanelMessage.value = state.message;
  operationPanelAction.value = state.action;
  scheduleOperationAutoClose(stackName, state.status === "success" ? 2400 : 6500);
  delete runningOperations[stackName];

  if (selectedStackName.value !== stackName) return;

  if (state.status === "success" && LOG_RECONNECT_ACTIONS.has(state.action)) {
    loadLogs({
      preserveLines: state.action !== "start" && state.action !== "service-start",
      retry: true,
      stackName,
    });
  } else if (
    state.status === "success" &&
    LOG_STOP_ACTIONS.has(state.action)
  ) {
    stopLogs();
  } else if (logsLoading.value) {
    logsLoading.value = false;
  }
}

function handleOperationComplete(stackName: string, state: OperationState) {
  onOperationComplete(stackName, state);
  if (state.status === "success" && state.action === "update") {
    emit("check-updates");
  }
}

watch(selectedStackName, () => {
  if (!selectedStack.value) {
    composeYaml.value = "";
    selectedContainerId.value = "";
    stopLogs();
    return;
  }
  selectedContainerId.value = "";
  void loadCompose();
  loadLogs();
});

watch(
  () => props.hostId,
  () => {
    showAllStacks();
    composeDrawerVisible.value = false;
    composeYaml.value = "";
    composeError.value = "";
    logLines.value = [];
    Object.keys(runningOperations).forEach((stackName) => {
      cancelOperation(stackName);
    });
    if (bulkUpdateAbortController) {
      bulkUpdateAbortController.abort();
      bulkUpdateAbortController = null;
    }
    closeOperationDock();
    Object.keys(terminalOutputs).forEach((stackName) => {
      delete terminalOutputs[stackName];
    });
  }
);

watch(
  () => props.stacks,
  () => {
    if (selectedStackName.value && !selectedStack.value) {
      showAllStacks();
    }
  }
);

function applyQueryStack() {
  const qStack = route.query.stack;
  if (typeof qStack === "string" && qStack) {
    if (props.stacks.some((s) => s.name === qStack)) {
      selectStack(qStack);
    }
  }
}

watch(
  [() => route.query.stack, () => props.stacks],
  () => {
    applyQueryStack();
  },
  { immediate: true }
);

onUnmounted(() => {
  if (bulkUpdateAbortController) {
    bulkUpdateAbortController.abort();
    bulkUpdateAbortController = null;
  }
  clearOperationAutoClose();
  stopLogs();
});
</script>

<style scoped>
.host-workspace {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 10px;
  height: 100%;
  min-height: 0;
  flex: 1;
}

.workspace-sidebar,
.workspace-main {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  min-height: 0;
}

.workspace-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  min-width: 0;
}

.sidebar-compose-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.compose-add-button {
  height: 34px;
  border-radius: 999px !important;
  padding: 0 14px !important;
  font-size: 13px;
}

.sidebar-icon-button {
  height: 34px;
  min-height: 34px;
  width: 34px;
}

.sidebar-update-badge {
  line-height: 1;
}

.prune-dialog :deep(.el-dialog__header) {
  display: none;
}

.prune-dialog :deep(.el-dialog__body) {
  padding: 0;
  border-radius: 7px;
  overflow: hidden;
}

.prune-terminal :deep(.terminal-surface) {
  height: 380px;
}

.sidebar-search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-base);
  color: var(--text-secondary);
}

.workspace-summary,
.section-heading span {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 12px;
}

.stack-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.sidebar-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.sidebar-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1;
  padding: 24px 8px;
  color: var(--text-secondary);
  font-size: 13px;
  user-select: none;
}

.structure-loading {
  padding: 24px 0;
}

.stack-nav-list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  overflow: auto;
}

.stack-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 60px;
  padding: 7px 9px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.stack-nav-item:hover,
.stack-nav-item.active {
  border-color: var(--border-subtle);
  background: var(--surface-muted);
}

.stack-nav-item.is-stopped {
  opacity: 0.75;
}

.stack-nav-item.is-stopped:hover {
  opacity: 0.95;
}

.stack-nav-item.is-stopped .nav-stack-icon {
  color: var(--text-muted) !important;
}

.stack-nav-item.is-stopped .nav-stack-icon-img {
  filter: grayscale(100%);
  opacity: 0.55;
}

.stack-nav-item.is-stopped .nav-stack-name {
  color: var(--text-secondary);
}

.stack-nav-item.all {
  min-height: 50px;
  padding-block: 5px;
  justify-content: space-between;
  color: var(--text-secondary);
}

.nav-stack-icon-wrap {
  position: relative;
  flex: 0 0 40px;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background:
    linear-gradient(145deg, rgba(255, 255, 255, 0.42), rgba(203, 213, 225, 0.36)),
    rgba(148, 163, 184, 0.24);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.58),
    0 1px 2px rgba(15, 23, 42, 0.06);
}

.nav-stack-icon-img {
  width: 40px;
  height: 40px;
  display: block;
  border-radius: 8px;
  object-fit: contain;
}

.nav-stack-icon {
  color: var(--text-secondary);
  font-size: 32px;
}

.nav-stack-copy {
  min-width: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-stack-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 650;
  line-height: 1.05;
}

.nav-stack-meta {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  line-height: 1;
  white-space: nowrap;
}

.nav-status-pill {
  min-height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 750;
  line-height: 18px;
  white-space: nowrap;
}

.nav-status-pill.status-running {
  border-color: rgba(34, 197, 94, 0.22);
  background: rgba(34, 197, 94, 0.08);
  color: var(--success);
}

.nav-status-pill.status-stopped,
.nav-status-pill.status-exited {
  border-color: rgba(148, 163, 184, 0.22);
  background: rgba(148, 163, 184, 0.10);
  color: var(--text-secondary);
}

.nav-status-pill.status-partial {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.10);
  color: var(--warning);
}

.management-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 18px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 750;
  line-height: 18px;
  white-space: nowrap;
}

.management-unmanaged {
  border-color: rgba(168, 85, 247, 0.28);
  background: rgba(168, 85, 247, 0.10);
  color: #c084fc;
}

[data-theme="light"] .management-unmanaged {
  border-color: rgba(124, 58, 237, 0.22);
  background: rgba(124, 58, 237, 0.06);
  color: #7c3aed;
}

.detail-management-pill {
  margin-left: 2px;
}

.nav-count {
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.workspace-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 12px;
  overflow-x: hidden;
  overflow-y: auto;
}

.stack-detail-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 100%;
}

.workspace-headline,
.detail-hero,
.stack-header,
.section-heading,
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workspace-kicker {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workspace-headline h3,
.section-heading h3,
.panel-header h3 {
  margin: 3px 0 0;
  color: var(--text-primary);
}

.workspace-summary,
.section-heading span {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 12px;
}

.stack-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.stack-card,
.workspace-section,
.detail-panel {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-base);
}

.stack-card {
  padding: 12px;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  transition: border-color 200ms ease, box-shadow 300ms ease, background-color 200ms ease, transform 300ms cubic-bezier(0.34, 1.56, 0.64, 1);
  transform: translate3d(0, 0, 0);
}

.stack-card::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(
    180px circle at var(--shine-x, -500px) var(--shine-y, -500px),
    rgba(255, 255, 255, 0.08),
    transparent 80%
  );
  z-index: 1;
  transition: opacity 300ms ease;
  opacity: 0;
}

.stack-card:hover::after {
  opacity: 1;
}

.stack-card:hover {
  border-color: var(--border-strong);
  box-shadow: 0 6px 24px -4px rgba(99, 102, 241, 0.08),
              0 0 1px 1px rgba(99, 102, 241, 0.15);
}

.stack-card:not(.is-stopped):hover {
  box-shadow: 0 6px 24px -4px rgba(52, 211, 153, 0.08),
              0 0 1px 1px rgba(52, 211, 153, 0.15);
  border-color: rgba(52, 211, 153, 0.35);
}

.stack-card.is-stopped:hover {
  box-shadow: 0 6px 24px -4px rgba(148, 163, 184, 0.05),
              0 0 1px 1px rgba(148, 163, 184, 0.1);
  border-color: rgba(148, 163, 184, 0.25);
}

/* Processing Pulse & Scanner animation */
.stack-card.is-operating {
  animation: border-pulse 2s infinite ease-in-out;
}

@keyframes border-pulse {
  0% {
    border-color: rgba(99, 102, 241, 0.5) !important;
    box-shadow: 0 0 8px rgba(99, 102, 241, 0.25);
  }
  50% {
    border-color: rgba(6, 182, 212, 0.85) !important;
    box-shadow: 0 0 4px rgba(6, 182, 212, 0.4), 0 0 20px rgba(6, 182, 212, 0.38);
  }
  100% {
    border-color: rgba(99, 102, 241, 0.5) !important;
    box-shadow: 0 0 8px rgba(99, 102, 241, 0.25);
  }
}

.stack-card.is-stopped {
  border-style: dashed !important;
  opacity: 0.75;
  background: var(--surface-panel-raised, rgba(15, 23, 42, 0.2)) !important;
}

.stack-card.is-stopped:hover {
  opacity: 0.95;
}

.stack-card.is-stopped .stack-title-icon {
  color: var(--text-muted) !important;
}

.stack-card.is-stopped .stack-icon-img {
  filter: grayscale(100%);
  opacity: 0.55;
}

.stack-card.is-stopped .stack-name {
  color: var(--text-secondary);
}

.stack-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.stack-icon-img {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  object-fit: contain;
  flex-shrink: 0;
}

.stack-title-icon {
  flex-shrink: 0;
}

.stack-name {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-state-text {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.stack-card-actions,
.detail-actions,
.terminal-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stack-running-count {
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.compact-action-button {
  height: 28px;
  min-height: 28px;
  padding: 0 8px !important;
  border-radius: 7px !important;
}

.compact-action-button:not(.wide) {
  width: 28px;
  padding: 0 !important;
}

.service-strip,
.container-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}

.service-strip-row,
.container-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  border: 0;
  border-radius: 7px;
  background: var(--stack-service-bg, rgba(148, 163, 184, 0.08));
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.service-strip-row {
  padding: 0 10px;
}

.service-strip-row:hover,
.container-row:hover,
.container-row.active {
  background: var(--stack-service-hover-bg, rgba(96, 165, 250, 0.12));
}

.service-name,
.container-name {
  color: var(--text-primary);
  font-weight: 650;
}

.service-status,
.container-status,
.container-port,
.container-meta {
  color: var(--text-secondary);
  font-size: 12px;
}

.container-meta--mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.service-status {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.service-actions {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  gap: 2px;
  opacity: 0.72;
}

.service-strip-row:hover .service-actions,
.container-row:hover .service-actions {
  opacity: 1;
}

.container-service-actions {
  margin-left: auto;
}

.container-actions-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  justify-content: flex-end;
}

.service-actions :deep(.el-button) {
  width: 24px;
  height: 24px;
  min-height: 24px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-pill.large {
  min-height: 30px;
  padding: 0 14px;
  font-size: 16px;
}

.status-running {
  background: rgba(74, 222, 128, 0.16);
  color: var(--success);
}

.status-stopped {
  background: rgba(148, 163, 184, 0.14);
  color: var(--text-secondary);
}

.status-exited {
  background: rgba(248, 113, 113, 0.15);
  color: var(--danger);
}

.status-partial {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}

.dot-state {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.dot-running {
  background: var(--success);
  box-shadow: 0 0 7px var(--success);
}

.dot-stopped {
  background: var(--text-muted);
}

.dot-exited {
  background: var(--danger);
  box-shadow: 0 0 7px var(--danger);
}

.dot-partial {
  background: var(--warning);
}

.detail-hero {
  margin-bottom: 12px;
}

.detail-title-block {
  flex: 1 1 auto;
  min-width: 0;
}

.detail-actions {
  flex: 0 0 auto;
}

.detail-hero.is-stopped .detail-stack-icon {
  color: var(--text-muted) !important;
  filter: grayscale(100%);
  opacity: 0.55;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: nowrap;
  min-width: 0;
  min-height: 32px;
}

.detail-title-row h2 {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  margin: 0;
  color: var(--text-primary);
  font-size: 28px;
  line-height: 28px;
  overflow-wrap: anywhere;
  transform: translateY(-2px);
}

.detail-open-app {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  gap: 6px;
  min-height: 32px;
  padding: 0 11px;
  border: 1px solid color-mix(in srgb, var(--accent-blue) 36%, var(--border-subtle));
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent-blue) 7%, transparent);
  color: var(--accent-blue);
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease;
}

.detail-open-app:not(:disabled):hover {
  border-color: color-mix(in srgb, var(--accent-blue) 62%, var(--border-subtle));
  background: color-mix(in srgb, var(--accent-blue) 13%, transparent);
  color: var(--text-primary);
  transform: translateY(-1px);
}

.detail-open-app:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent-blue) 72%, white);
  outline-offset: 2px;
}

.detail-open-app:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  transform: none;
}

.detail-open-app :deep(.el-icon) {
  font-size: 15px;
}

.detail-status-dot {
  width: 12px;
  height: 12px;
  flex: 0 0 12px;
}

.detail-state-text {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding-right: 4px;
  font-size: 14px;
  line-height: 14px;
}

.detail-stack-icon {
  width: 28px;
  height: 28px;
  align-self: center;
}

.detail-stack-icon.stack-title-icon {
  font-size: 28px;
}

.detail-stack-icon.stack-icon-img {
  display: block;
}

.detail-update-badge {
  display: inline-flex;
  align-items: center;
  align-self: center;
  flex-shrink: 0;
  height: 22px;
}

.detail-compose-button {
  height: 32px;
  border-radius: 8px !important;
  font-weight: 700;
}

.stack-detail-grid {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  gap: 0;
}

.card-operation-dock {
  margin-top: 12px;
}

.detail-operation-dock {
  margin-bottom: 14px;
}

.detail-left-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

/* ── Draggable Resizer between left-column and detail-panel ── */
.detail-grid-resizer {
  flex: 0 0 6px;
  cursor: col-resize;
  position: relative;
  z-index: 2;
  margin: 0 2px;
  border-radius: 3px;
  transition: background 0.15s;
}

.detail-grid-resizer::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 3px;
  height: 32px;
  border-radius: 3px;
  background: var(--border-subtle);
  transition: background 0.18s, height 0.18s;
}

.detail-grid-resizer:hover::after,
.detail-grid-resizer:active::after {
  background: var(--accent-blue, #3b82f6);
  height: 48px;
}

.detail-grid-resizer:hover {
  background: rgba(59, 130, 246, 0.06);
}

.detail-grid-resizer:active {
  background: rgba(59, 130, 246, 0.10);
}

.workspace-section,
.workspace-section {
  padding: 16px;
  min-width: 0;
}

.detail-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  padding: 16px;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.container-row {
  display: grid;
  grid-template-columns: auto minmax(180px, 1fr) 180px max-content;
  padding: 8px 10px;
}

.container-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.container-name,
.container-meta,
.container-status,
.container-port {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.container-port {
  min-width: 0;
  max-width: 100%;
}

.terminal-section {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  border: 0;
  background: transparent;
  padding: 0;
}

.embedded-terminal {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
  overflow: auto;
  border-radius: 8px;
  background: #020609;
  color: #e5f2ff;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.45;
  padding: 10px;
}

:global([data-theme="light"] .embedded-terminal) {
  border: 1px solid rgba(60, 72, 88, 0.16);
  background: #f8fafc;
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.72);
}

.terminal-log-line {
  display: grid;
  grid-template-columns: minmax(76px, max-content) minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  padding: 2px 4px;
  border-radius: 5px;
  white-space: pre-wrap;
}

.terminal-log-line + .terminal-log-line {
  margin-top: 1px;
}

.terminal-log-line.level-error {
  background: rgba(248, 113, 113, 0.08);
  color: #fecaca;
}

.terminal-log-line.level-warn {
  background: rgba(251, 191, 36, 0.08);
  color: #fde68a;
}

.terminal-service {
  overflow: hidden;
  max-width: 15ch;
  border-right: 1px solid rgba(148, 163, 184, 0.20);
  color: #38bdf8;
  font-weight: 800;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-message {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.terminal-muted {
  color: #8aa0b7;
}

:global([data-theme="light"] .terminal-muted) {
  color: #64748b;
}

:global([data-theme="light"] .terminal-log-line.level-error) {
  background: rgba(220, 38, 38, 0.07);
  color: #991b1b;
}

:global([data-theme="light"] .terminal-log-line.level-warn) {
  background: rgba(217, 119, 6, 0.08);
  color: #92400e;
}

:global([data-theme="light"] .terminal-service) {
  border-right-color: rgba(60, 72, 88, 0.16);
  color: #2563eb;
}

.terminal-cursor {
  display: inline-block;
  color: #ffffff;
  animation: blink 1s step-end infinite;
}

:global([data-theme="light"] .terminal-cursor) {
  color: #0f172a;
}

.panel-header {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.panel-header-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: capitalize;
}

.status-badge.running {
  background: rgba(52, 211, 153, 0.12);
  color: var(--success);
  border: 1px solid rgba(52, 211, 153, 0.22);
}

.status-badge.stopped {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-secondary);
  border: 1px solid rgba(148, 163, 184, 0.22);
}

.status-badge-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.status-badge.running .status-badge-dot {
  background: var(--success);
  box-shadow: 0 0 8px var(--success);
  animation: pulse-breathing 2s infinite ease-in-out;
}

.status-badge.stopped .status-badge-dot {
  background: var(--text-secondary);
}

@keyframes pulse-breathing {
  0%, 100% {
    transform: scale(0.95);
    opacity: 0.7;
    box-shadow: 0 0 4px var(--success);
  }
  50% {
    transform: scale(1.15);
    opacity: 1;
    box-shadow: 0 0 10px var(--success);
  }
}

.compose-preview {
  display: flex;
  flex: 1;
  min-height: 0;
  margin-left: -16px;
  margin-right: -16px;
  margin-bottom: -16px;
  padding-left: 8px;
  padding-right: 8px;
}

.compose-preview :deep(.monaco-editor-container) {
  border: none;
  border-radius: 0;
  height: 100%;
  width: 100%;
  background-color: transparent !important;
}

.compose-preview :deep(.monaco-editor),
.compose-preview :deep(.monaco-editor-background),
.compose-preview :deep(.monaco-editor .margin) {
  background-color: transparent !important;
}

.panel-muted {
  color: var(--text-secondary);
  font-size: 13px;
}

.container-detail-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 12px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

/* ── Stats Dashboard ────────────────────────────── */

.stats-dashboard {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
  min-height: 82px;
  padding: 8px;
  border-radius: 10px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  transition: all 0.24s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.stat-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.10);
}

.stat-card-head {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.stat-card-head .el-icon {
  font-size: 11px;
  color: var(--accent-blue);
}

.stat-card-body {
  display: flex;
  flex-direction: column;
  margin-top: 2px;
  margin-bottom: auto;
}

.stat-card-value {
  font-family: var(--font-body);
  font-variant-numeric: tabular-nums;
  font-size: 17px;
  font-weight: 850;
  color: var(--text-primary);
  line-height: 1.1;
  white-space: nowrap;
}

.stat-card-value small {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-left: 0.5px;
}

.stat-card-value.net-val {
  font-size: 12px;
  font-weight: 750;
  letter-spacing: -0.02em;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-card-sub {
  font-family: var(--font-body);
  font-variant-numeric: tabular-nums;
  font-size: 9px;
  color: var(--text-secondary);
  margin-top: 1px;
  line-height: 1;
}

.stat-card :deep(.el-progress) {
  margin-top: 4px;
}

.stat-card-bar-spacer {
  height: 2px;
  margin-top: 4px;
}

.stat-card.cpu.critical {
  border-color: rgba(248, 113, 113, 0.32);
  background: linear-gradient(180deg, rgba(248, 113, 113, 0.04) 0%, rgba(248, 113, 113, 0.01) 100%);
}

.stat-card.cpu.warn {
  border-color: rgba(251, 191, 36, 0.32);
  background: linear-gradient(180deg, rgba(251, 191, 36, 0.04) 0%, rgba(251, 191, 36, 0.01) 100%);
}

.stat-card.mem.critical {
  border-color: rgba(248, 113, 113, 0.32);
  background: linear-gradient(180deg, rgba(248, 113, 113, 0.04) 0%, rgba(248, 113, 113, 0.01) 100%);
}

.stat-card.mem.warn {
  border-color: rgba(251, 191, 36, 0.32);
  background: linear-gradient(180deg, rgba(251, 191, 36, 0.04) 0%, rgba(251, 191, 36, 0.01) 100%);
}

.stat-na {
  color: var(--text-muted);
  font-size: 11px;
}

/* ── Basic Info List Card ────────────────────────────── */

.info-card-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  border-radius: 12px;
  background: var(--border-subtle);
  border: 1px solid var(--border-subtle);
  overflow: hidden;
  margin-top: 6px;
}

.info-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px;
  background: var(--surface-panel);
  transition: background-color 0.2s;
}

.info-row:hover {
  background: var(--surface-panel-raised);
}

.info-row-left {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 550;
  flex-shrink: 0;
}

.info-row-left .el-icon {
  font-size: 14px;
  color: var(--accent-blue);
}

.info-row-right {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 70%;
}

.info-row-value {
  font-size: 12px;
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.info-row-value.monospace {
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 500;
}

.row-copy-btn {
  opacity: 0.4;
  transition: opacity 0.2s;
}

.info-row:hover .row-copy-btn {
  opacity: 1;
}

/* ── Ports Section ────────────────────────────────── */

.ports-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel);
}

.ports-section-label {
  font-size: 11px;
  font-weight: 750;
  color: var(--text-secondary);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.ports-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 6px;
}

.port-row-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  border-radius: 8px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  transition: all 0.2s;
}

.port-row-item:hover {
  border-color: rgba(96, 165, 250, 0.4);
  background: rgba(96, 165, 250, 0.04);
}

.port-arrow-icon {
  font-size: 10px;
  color: var(--accent-blue);
  margin-right: 4px;
}

.port-mapping {
  display: flex;
  align-items: center;
  gap: 3px;
  font-family: var(--font-mono);
  font-size: 11px;
  min-width: 0;
  flex: 1;
}

.port-host-link {
  color: var(--accent-blue);
  font-weight: 600;
  cursor: pointer;
  border-bottom: 1px dashed transparent;
  transition: border-bottom-color 0.2s;
}

.port-host-link:hover {
  border-bottom-color: var(--accent-blue);
}

.port-host-none {
  color: var(--text-muted);
}

.port-arrow {
  font-size: 9px;
  color: var(--text-muted);
}

.port-target {
  color: var(--text-primary);
  font-weight: 600;
}

.port-protocol-tag {
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  font-weight: bold;
  transform: scale(0.9);
}

.port-action-btn {
  opacity: 0.4;
  margin-left: 2px;
}

.port-row-item:hover .port-action-btn {
  opacity: 1;
}

.ports-section.empty {
  align-items: center;
  justify-content: space-between;
  flex-direction: row;
}

.ports-empty-text {
  font-size: 12px;
  color: var(--text-muted);
}

/* ── Collapse ───────────────────────────────────── */

.detail-collapse {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 0;
}

.detail-collapse :deep(.el-collapse-item) {
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  background: var(--surface-panel);
  overflow: hidden;
  transition: border-color 0.18s;
}

.detail-collapse :deep(.el-collapse-item:hover) {
  border-color: var(--border-strong);
}

.detail-collapse :deep(.el-collapse-item.is-active) {
  border-color: rgba(96, 165, 250, 0.28);
}

.detail-collapse :deep(.el-collapse-item__header) {
  height: 42px;
  padding: 0 14px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border: 0;
  background: transparent;
  transition: color 0.15s, background 0.15s;
}

.detail-collapse :deep(.el-collapse-item__header:hover) {
  color: var(--text-primary);
}

.detail-collapse :deep(.el-collapse-item.is-active .el-collapse-item__header) {
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-subtle);
}

.detail-collapse :deep(.el-collapse-item__arrow) {
  color: var(--text-muted);
  font-size: 13px;
  transition: color 0.15s;
}

.detail-collapse :deep(.el-collapse-item__header:hover .el-collapse-item__arrow) {
  color: var(--text-secondary);
}

.detail-collapse :deep(.el-collapse-item__wrap) {
  border: 0;
  background: transparent;
}

.detail-collapse :deep(.el-collapse-item__content) {
  padding: 12px 14px 14px;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-title .el-icon {
  font-size: 15px;
  color: var(--accent-blue);
  flex-shrink: 0;
}

.collapse-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.collapse-field {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.field-label {
  font-size: 9px;
  font-weight: 800;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.field-value {
  font-size: 12.5px;
  font-weight: 650;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-value-wrapper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  min-width: 0;
}

.field-value-wrapper code {
  flex: 1;
  min-width: 0;
}

.field-copy-btn {
  opacity: 0.4;
}

.field-value-wrapper:hover .field-copy-btn {
  opacity: 1;
}

/* ── Command Collapse ───────────────────────────── */

.command-block-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.command-block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.command-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 750;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.command-block-header .el-button {
  height: auto !important;
  padding: 2px !important;
}

.command-terminal-box {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #020609;
  border: 1px solid var(--border-subtle);
  max-height: 120px;
  overflow: auto;
}

.command-terminal-box code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: #e5f2ff;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
}

:global([data-theme="light"] .command-terminal-box) {
  background: #f8fafc;
  border-color: rgba(60, 72, 88, 0.16);
}

:global([data-theme="light"] .command-terminal-box code) {
  color: #0f172a;
}

/* ── Networks Collapse ──────────────────────────── */

.network-row-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
}

.network-row-card + .network-row-card {
  margin-top: 6px;
}

.network-row-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.network-name-badge {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 750;
  color: var(--accent-blue);
}

.network-row-header .el-button {
  height: auto !important;
  padding: 2px !important;
}

.network-row-body {
  display: grid;
  grid-template-columns: 1.2fr 1.2fr;
  gap: 8px;
}

.network-metric-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.network-metric-label {
  font-size: 9px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
}

.network-metric-value {
  font-size: 11px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Mounts Collapse ────────────────────────────── */

.mount-row-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 10px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
}

.mount-row-card + .mount-row-card {
  margin-top: 6px;
}

.mount-row-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.mount-type-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 18px;
  padding: 0 6px;
  border-radius: 99px;
  font-size: 9.5px;
  font-weight: 800;
  text-transform: uppercase;
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue);
}

.mount-rw-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 4px;
}

.mount-rw-badge.rw {
  background: rgba(52, 211, 153, 0.1);
  color: var(--success);
}

.mount-rw-badge.ro {
  background: rgba(248, 113, 113, 0.1);
  color: var(--danger);
}

.mount-path-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mount-path-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 6px 10px;
  min-width: 0;
}

.path-icon {
  font-size: 13px;
  flex-shrink: 0;
}

.path-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.path-title {
  font-size: 8.5px;
  font-weight: 750;
  color: var(--text-muted);
  text-transform: uppercase;
}

.path-value {
  font-size: 11px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mount-path-divider {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  flex-shrink: 0;
  transform: rotate(90deg);
  margin: -2px 0;
}

.mount-path-divider .el-icon {
  font-size: 12px;
}

.mount-path-item .el-button {
  opacity: 0.3;
  padding: 2px !important;
  height: auto !important;
}

.mount-path-item:hover .el-button {
  opacity: 1;
}

/* ── Labels Collapse ────────────────────────────── */

.label-row-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  min-width: 0;
}

.label-row-card + .label-row-card {
  margin-top: 6px;
}

.label-key-wrap {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.label-key {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-blue);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.label-key-wrap .el-button {
  height: auto !important;
  padding: 1px !important;
  opacity: 0.3;
}

.label-row-card:hover .el-button {
  opacity: 1;
}

.label-value-wrap {
  min-width: 0;
}

.label-value {
  font-size: 11px;
  color: var(--text-primary);
  word-break: break-all;
  white-space: pre-wrap;
}

/* ── Animations & Commons ───────────────────────── */

@keyframes blink {
  50% { opacity: 0; }
}

@media (max-width: 1100px) {
  .host-workspace {
    grid-template-columns: 1fr;
  }

  .workspace-sidebar {
    max-height: none;
  }

  .stack-nav-list {
    max-height: 260px;
  }

  .stack-detail-grid {
    flex-direction: column;
  }

  .stack-detail-grid .detail-left-column {
    flex: none !important;
  }

  .detail-grid-resizer {
    display: none;
  }
}

@media (max-width: 720px) {
  .workspace-main,
  .workspace-sidebar,
  .stack-card,
  .workspace-section,
  .detail-panel {
    padding: 12px;
  }

  .stack-header,
  .detail-hero,
  .workspace-headline {
    align-items: flex-start;
    flex-direction: column;
  }

  .stack-card-actions,
  .detail-actions {
    justify-content: flex-start;
  }

  .detail-title-row {
    flex-wrap: wrap;
  }

  .detail-open-app span {
    display: none;
  }

  .detail-open-app {
    width: 32px;
    padding: 0;
  }

  .container-row {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .container-status {
    grid-column: 2;
  }

  .container-row .container-actions-wrap {
    grid-column: 3;
    grid-row: 1 / span 3;
    align-self: center;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
  }

  .stats-dashboard {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .collapse-grid {
    grid-template-columns: 1fr;
  }

  .mount-detail-row {
    grid-template-columns: 1fr 1fr;
  }
}
</style>

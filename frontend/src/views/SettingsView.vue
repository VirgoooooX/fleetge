<template>
  <div class="settings-layout">
    <nav class="settings-tabs" aria-label="Settings sections" role="tablist">
      <button
        v-for="section in settingSections"
        :key="section.id"
        type="button"
        class="settings-tab"
        :class="{ active: activeSection === section.id }"
        :aria-selected="activeSection === section.id"
        role="tab"
        @click="setSection(section.id)"
      >
        <el-icon><component :is="section.icon" /></el-icon>
        <span>{{ section.label }}</span>
      </button>
    </nav>

    <div class="settings-workspace">
      <main class="settings-main">
        <section v-if="activeSection === 'params'" class="settings-section" v-loading="store.loading">
          <div class="section-heading">
            <div>
              <h3>{{ t("settings.sections.params") }}</h3>
              <p>{{ t("settings.params.alert") }}</p>
            </div>
            <el-button
              type="primary"
              class="ui-button ui-button--primary"
              :loading="store.saving"
              @click="handleSaveParams"
            >
              {{ t("settings.params.save") }}
            </el-button>
          </div>

          <el-form
            ref="paramsFormRef"
            :model="paramsForm"
            label-position="top"
            class="settings-form params-settings-form"
            :rules="paramsRules"
          >
            <div class="form-cluster">
              <div class="cluster-title">{{ t("settings.params.group.runtime") }}</div>
              <div class="settings-field-list">
                <el-form-item prop="DOCKER_POLL_INTERVAL" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.dockerPoll") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.dockerPoll") }}</span>
                  </template>
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.DOCKER_POLL_INTERVAL" :min="5" :max="300" :step="5" />
                    <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
                  </div>
                </el-form-item>

                <el-form-item prop="METRICS_STREAM_INTERVAL" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.metricsStream") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.metricsStream") }}</span>
                  </template>
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.METRICS_STREAM_INTERVAL" :min="0.5" :max="10" :step="0.5" />
                    <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
                  </div>
                </el-form-item>

                <el-form-item prop="BACKGROUND_STRUCTURE_REFRESH_INTERVAL" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.structureRefresh") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.structureRefresh") }}</span>
                  </template>
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.BACKGROUND_STRUCTURE_REFRESH_INTERVAL" :min="60" :max="86400" :step="60" />
                    <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
                  </div>
                </el-form-item>

                <el-form-item prop="UPDATE_CHECK_INTERVAL" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.updateCheck") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.updateCheck") }}</span>
                  </template>
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.UPDATE_CHECK_INTERVAL" :min="3600" :max="172800" :step="3600" />
                    <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
                  </div>
                </el-form-item>
              </div>
            </div>

            <div class="form-cluster">
              <div class="cluster-title">{{ t("settings.params.group.account") }}</div>
              <div class="settings-field-list">
                <el-form-item prop="ADMIN_USERNAME" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.adminUsername") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.adminUsername") }}</span>
                  </template>
                  <el-input v-model="paramsForm.ADMIN_USERNAME" placeholder="admin" minlength="3" />
                </el-form-item>

                <el-form-item prop="JWT_EXPIRE_HOURS" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.jwtExpire") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.jwtExpire") }}</span>
                  </template>
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.JWT_EXPIRE_HOURS" :min="1" :max="720" :step="1" />
                    <span class="unit-text">{{ t("settings.params.unit.hours") }}</span>
                  </div>
                </el-form-item>
              </div>
            </div>

            <div class="form-cluster form-cluster--enrollment">
              <div class="cluster-title">{{ t("settings.params.group.enrollment") }}</div>
              <div class="settings-field-list">
                <el-form-item prop="ENROLLMENT_AGENT_IMAGE" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.agentImage") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.agentImage") }}</span>
                  </template>
                  <el-input v-model="paramsForm.ENROLLMENT_AGENT_IMAGE" class="mono-input" spellcheck="false" />
                </el-form-item>

                <el-form-item prop="ENROLLMENT_PROXY_IMAGE" class="settings-field-row">
                  <template #label>
                    <span class="settings-field-label">{{ t("settings.params.proxyImage") }}</span>
                    <span class="settings-field-help">{{ t("settings.params.help.proxyImage") }}</span>
                  </template>
                  <el-input v-model="paramsForm.ENROLLMENT_PROXY_IMAGE" class="mono-input" spellcheck="false" />
                </el-form-item>
              </div>
            </div>
          </el-form>

          <details class="settings-inline-details">
            <summary>
              <span>{{ t("settings.sections.security") }}</span>
              <small>{{ t("settings.security.alert") }}</small>
            </summary>
            <el-form label-position="top" class="settings-form inline-security-form">
              <div class="form-grid">
                <el-form-item :label="t('settings.security.jwtSecret')">
                  <el-input class="mono-input" v-model="readonlyForm.JWT_SECRET" disabled show-password />
                  <div class="form-help">{{ t("settings.security.help.jwtSecret") }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.security.credentialsKey')">
                  <el-input class="mono-input" v-model="readonlyForm.CREDENTIALS_KEY" disabled show-password />
                  <div class="form-help">{{ t("settings.security.help.credentialsKey") }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.security.adminPassword')">
                  <el-input class="mono-input" v-model="readonlyForm.ADMIN_PASSWORD" disabled show-password />
                  <div class="form-help">{{ t("settings.security.help.adminPassword") }}</div>
                </el-form-item>
              </div>
            </el-form>
          </details>
        </section>

        <section v-if="activeSection === 'hosts'" class="settings-section" v-loading="store.loading">
          <div class="section-heading">
            <div>
              <h3>{{ t("settings.sections.hosts") }}</h3>
              <p>{{ t("settings.hosts.count", { count: store.hosts.length }) }}</p>
            </div>
            <div class="section-actions">
              <el-button type="primary" class="ui-button ui-button--primary" :icon="Plus" @click="openAddHostChoiceDialog">
                {{ t("settings.hosts.add") }}
              </el-button>
            </div>
          </div>

          <div class="table-frame">
            <el-table :data="store.hosts" stripe style="width: 100%" class="host-table">
              <el-table-column :label="t('settings.hosts.col.sort')" prop="sort_order" width="70" align="center" class-name="mobile-hidden" label-class-name="mobile-hidden" />
              <el-table-column :label="t('settings.hosts.col.id')" prop="host_id" width="140" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="host-code-text">{{ row.host_id }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.name')" prop="display_name" width="170" />
              <el-table-column :label="t('settings.hosts.col.url')" min-width="220" prop="agent_url" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="host-code-text">{{ row.agent_url || "-" }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.status')" prop="enabled" width="90" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.enabled" @change="toggleHostEnabled(row)" :loading="store.saving" />
                </template>
              </el-table-column>
              <el-table-column
                :label="t('settings.hosts.col.appProfiles')"
                width="96"
                align="center"
                class-name="mobile-hidden app-profiles-column"
                label-class-name="mobile-hidden"
                :fixed="isMobile ? false : 'right'"
              >
                <template #default="{ row }">
                  <div class="app-profiles-cell">
                    <el-tooltip :content="t('settings.hosts.col.manageAppProfiles')" placement="top" :show-after="250">
                      <button
                        type="button"
                        class="app-profile-settings-btn"
                        :aria-label="t('settings.hosts.col.manageAppProfiles')"
                        @click="openAppProfilesDialog(row)"
                      >
                        <el-icon><SettingIcon /></el-icon>
                        <span>{{ t("settings.hosts.col.appProfilesSetup") }}</span>
                      </button>
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.actions')" :width="isMobile ? 150 : 224" align="center" :fixed="isMobile ? false : 'right'">
                <template #default="{ row }">
                  <div class="row-operations">
                    <el-button size="small" type="success" plain class="host-action-btn host-action-test" @click="testHostConnection(row)">
                      <el-icon v-if="isMobile"><Link /></el-icon>
                      <span v-else>{{ t("settings.hosts.action.test") }}</span>
                    </el-button>
                    <el-tooltip :content="t('settings.globalEnv.manage')" placement="top">
                      <el-button size="small" type="info" plain :icon="Document" class="host-action-btn host-icon-btn" @click="openGlobalEnvDialog(row)" />
                    </el-tooltip>
                    <el-button size="small" type="info" plain :icon="Edit" class="host-action-btn host-icon-btn" @click="openEditHostDialog(row)" />
                    <el-button size="small" type="danger" plain :icon="Delete" class="host-action-btn host-icon-btn" @click="confirmDeleteHost(row)" />
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <section v-if="activeSection === 'maintenance'" class="settings-section">
          <div class="section-heading">
            <div>
              <h3>{{ t("settings.sections.maintenance") }}</h3>
              <p>{{ t("settings.maintenance.description") }}</p>
            </div>
            <div class="section-actions">
              <el-button class="ui-button ui-button--muted" @click="setSection('params')">
                {{ t("settings.maintenance.editInterval") }}
              </el-button>
              <el-button
                type="primary"
                class="ui-button ui-button--primary"
                :loading="checkingUpdates"
                @click="runMaintenanceCheck"
              >
                <el-icon><RefreshCw /></el-icon>
                {{ t("updates.checkNow") }}
              </el-button>
            </div>
          </div>

          <el-alert
            v-if="dashboardStore.updateCheckRunning"
            :title="t('updates.runningTitle')"
            :description="t('updates.runningDesc')"
            type="info"
            show-icon
            :closable="false"
            class="section-alert"
          />

          <div class="table-toolbar">
            <el-input
              v-model="updateSearch"
              class="toolbar-input"
              :placeholder="t('settings.maintenance.searchPlaceholder')"
              clearable
              :prefix-icon="Search"
            />
            <el-select v-model="updateStatusFilter" class="toolbar-select" :placeholder="t('updates.status')">
              <el-option :label="t('apps.chip.all')" value="" />
              <el-option :label="t('update.status.updatable')" value="updatable" />
              <el-option :label="t('update.status.needsAuth')" value="needs_auth" />
              <el-option :label="t('update.status.rateLimited')" value="rate_limited" />
              <el-option :label="t('update.status.checkFailed')" value="check_failed" />
              <el-option :label="t('update.status.upToDate')" value="up_to_date" />
            </el-select>
            <el-button class="ui-button ui-button--muted" @click="openUpdatableApps">
              {{ t("settings.maintenance.openApps") }}
            </el-button>
          </div>

          <div class="table-frame" v-if="filteredUpdateResults.length > 0">
            <el-table :data="filteredUpdateResults" stripe style="width: 100%" v-loading="checkingUpdates">
              <el-table-column :label="t('updates.host')" prop="host_id" width="120">
                <template #default="{ row }">
                  <span class="host-code-text">{{ row.host_id }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('updates.image')" prop="image" min-width="300">
                <template #default="{ row }">
                  <code class="image-ref">{{ row.image }}</code>
                </template>
              </el-table-column>
              <el-table-column :label="t('updates.status')" width="130">
                <template #default="{ row }">
                  <UpdateBadge :status="displayStatus(row)" />
                </template>
              </el-table-column>
              <el-table-column :label="t('updates.currentDigest')" prop="current_digest" min-width="190" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="digest-text">{{ shortenDigest(row.current_digest) }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('updates.registryDigest')" prop="registry_digest" min-width="190" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="digest-text">{{ shortenDigest(row.registry_digest) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else :description="t('updates.noResults')" />
        </section>

        <section v-if="activeSection === 'audit'" class="settings-section">
          <div class="section-heading">
            <div>
              <h3>{{ t("settings.sections.audit") }}</h3>
              <p>{{ t("settings.audit.description") }}</p>
            </div>
            <el-button class="ui-button ui-button--muted" :loading="auditLoading" @click="fetchLogs">
              <el-icon><RefreshCw /></el-icon>
              {{ t("shell.refresh") }}
            </el-button>
          </div>

          <div class="table-toolbar">
            <el-input
              v-model="auditSearch"
              class="toolbar-input"
              :placeholder="t('settings.audit.searchPlaceholder')"
              clearable
              :prefix-icon="Search"
            />
            <el-select v-model="auditResultFilter" class="toolbar-select" :placeholder="t('audit.result')">
              <el-option :label="t('apps.chip.all')" value="" />
              <el-option :label="t('audit.success')" value="success" />
              <el-option :label="t('audit.failure')" value="failure" />
            </el-select>
            <el-select v-model="auditActionFilter" class="toolbar-select wide" :placeholder="t('audit.action')" clearable>
              <el-option :label="t('apps.chip.all')" value="" />
              <el-option
                v-for="action in auditActions"
                :key="action.value"
                :label="action.label"
                :value="action.value"
              />
            </el-select>
          </div>

          <div class="table-frame" v-if="filteredAuditLogs.length > 0">
            <el-table
              :data="filteredAuditLogs"
              stripe
              style="width: 100%"
              :default-sort="{ prop: 'timestamp', order: 'descending' }"
              v-loading="auditLoading"
              row-class-name="audit-row"
              @row-click="openAuditDrawer"
            >
              <el-table-column :label="t('audit.time')" prop="timestamp" width="170" sortable>
                <template #default="{ row }">
                  <span class="audit-time">{{ formatTime(row.timestamp) }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('audit.user')" prop="user" width="100" />
              <el-table-column :label="t('audit.action')" prop="action" width="150">
                <template #default="{ row }">
                  <el-tag :type="actionType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column :label="t('audit.host')" prop="host_id" width="120" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="audit-code">{{ row.host_id || "-" }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('audit.result')" prop="result" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
                    {{ row.result === "success" ? t("audit.success") : t("audit.failure") }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column :label="t('audit.detail')" prop="detail" min-width="240">
                <template #default="{ row }">
                  <span class="detail-text">{{ row.detail || "-" }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-empty v-else :description="t('audit.noRecords')" />
        </section>

        <section v-if="activeSection === 'about'" class="settings-section">
          <div class="section-heading">
            <div>
              <h3>{{ t("settings.sections.about") }}</h3>
              <p>{{ t("settings.about.description") }}</p>
            </div>
          </div>

          <div class="about-panel">
            <div class="about-version-row">
              <span>{{ t("settings.about.version") }}</span>
              <strong>v{{ appVersion }}</strong>
            </div>
            <div class="about-link-list">
              <a
                v-for="link in resourceLinks"
                :key="link.href"
                class="about-link-row"
                :href="link.href"
                target="_blank"
                rel="noreferrer noopener"
              >
                <el-icon><component :is="link.icon" /></el-icon>
                <span>
                  <strong>{{ link.label }}</strong>
                  <small>{{ link.description }}</small>
                </span>
              </a>
            </div>
          </div>
        </section>

      </main>
    </div>

    <!-- Choice Modal: 添加主机类型选择 -->
    <el-dialog
      v-model="addHostChoiceVisible"
      :title="t('settings.hosts.addChoiceTitle')"
      width="min(540px, calc(100vw - 28px))"
      class="ui-dialog add-host-choice-dialog"
    >
      <div class="add-host-choice-intro">
        <p>{{ t("settings.hosts.addChoiceSubtitle") }}</p>
      </div>
      <div class="add-host-choice-cards">
        <div
          class="add-host-choice-card choice-card--enrollment"
          tabindex="0"
          role="button"
          @click="chooseAddHostMode('enrollment')"
          @keydown.enter.prevent="chooseAddHostMode('enrollment')"
        >
          <div class="choice-card-icon">
            <Rocket :size="24" />
          </div>
          <div class="choice-card-body">
            <h4>{{ t("settings.hosts.modeEnrollmentTitle") }}</h4>
            <p>{{ t("settings.hosts.modeEnrollmentDesc") }}</p>
          </div>
          <ChevronRight class="choice-card-arrow" :size="18" />
        </div>

        <div
          class="add-host-choice-card choice-card--manual"
          tabindex="0"
          role="button"
          @click="chooseAddHostMode('manual')"
          @keydown.enter.prevent="chooseAddHostMode('manual')"
        >
          <div class="choice-card-icon">
            <Server :size="24" />
          </div>
          <div class="choice-card-body">
            <h4>{{ t("settings.hosts.modeManualTitle") }}</h4>
            <p>{{ t("settings.hosts.modeManualDesc") }}</p>
          </div>
          <ChevronRight class="choice-card-arrow" :size="18" />
        </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="enrollmentDialogVisible"
      title="Agent 一键入网"
      width="min(760px, calc(100vw - 28px))"
      class="ui-dialog enrollment-dialog"
      @closed="currentInstallCommand = ''"
    >
      <div class="enrollment-intro">
        <div class="enrollment-intro-icon"><Rocket :size="24" /></div>
        <div>
          <strong>一条命令，把 Linux Host 加入 Fleetge</strong>
          <p>先把下方子域名解析到目标 VPS。脚本会自动部署 Agent、Caddy、HTTPS 反代并等待主控完成配对。</p>
        </div>
      </div>

      <el-form label-position="top" class="enrollment-form">
        <el-form-item label="Agent 公网子域名">
          <el-input v-model="enrollmentForm.agent_public_host" class="mono-input" placeholder="agent-vps-01.example.com" />
          <div class="form-help">填写具体子域名，不要包含 https://、端口或路径；执行命令前需解析到目标 VPS。</div>
        </el-form-item>
        <el-form-item label="Dashboard URL">
          <el-input v-model="enrollmentForm.dashboard_url" class="mono-input" placeholder="https://fleetge.example.com" />
          <div v-if="enrollmentHttpWarning" class="enrollment-warning">公网 Dashboard 应使用 HTTPS；私网或本机 HTTP 可以继续。</div>
        </el-form-item>
        <el-collapse class="enrollment-advanced">
          <el-collapse-item title="高级选项" name="advanced">
            <div class="enrollment-option-grid">
              <el-form-item label="Stack 根目录">
                <el-input v-model="enrollmentForm.stack_root" class="mono-input" />
              </el-form-item>
              <el-form-item label="Agent 端口">
                <el-input-number v-model="enrollmentForm.agent_port" :min="1" :max="65535" controls-position="right" />
              </el-form-item>
              <el-form-item label="Agent 镜像">
                <el-input v-model="enrollmentForm.agent_image" class="mono-input" placeholder="使用服务端 ENROLLMENT_AGENT_IMAGE" />
              </el-form-item>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-form>

      <div v-if="currentInstallCommand" class="install-command-card">
        <div class="install-command-head">
          <span><ShieldCheck :size="16" />专属安装命令</span>
          <strong><Clock3 :size="15" />{{ currentInvite ? remainingTime(currentInvite.expires_at) : '--:--' }}</strong>
        </div>
        <code>{{ currentInstallCommand }}</code>
        <div class="install-command-actions">
          <el-button type="primary" @click="copyInstallCommand"><Copy :size="15" />复制命令</el-button>
          <el-button v-if="currentInvite && ['issued','downloaded','verifying','needs_url'].includes(currentInvite.status)" type="danger" plain @click="revokeInvite(currentInvite.invite_id)">撤销</el-button>
        </div>
      </div>

      <div v-if="store.enrollmentInvites.length" class="invite-list">
        <div class="invite-list-title">最近邀请</div>
        <article v-for="invite in store.enrollmentInvites.slice(0, 6)" :key="invite.invite_id" class="invite-row">
          <span class="invite-state" :class="invite.status"></span>
          <div>
            <strong>{{ enrollmentStatusLabel(invite.status) }}</strong>
            <small>{{ invite.agent_public_url || invite.agent_public_host }} · {{ remainingTime(invite.expires_at) }}</small>
            <p v-if="invite.failure_reason">{{ invite.failure_reason }}</p>
          </div>
          <div v-if="['needs_url','failed'].includes(invite.status)" class="invite-retry">
            <el-button size="small" :loading="retryingInviteId === invite.invite_id" @click="retryInvite(invite.invite_id)">
              <RotateCcw :size="14" />重新验证
            </el-button>
          </div>
          <span v-else-if="invite.status === 'verifying'" class="invite-verifying"><LoaderCircle class="spin" :size="14" />持续验证中</span>
          <el-button v-else-if="['issued','downloaded','verifying'].includes(invite.status)" size="small" type="danger" plain @click="revokeInvite(invite.invite_id)">撤销</el-button>
        </article>
      </div>

      <template #footer>
        <el-button @click="enrollmentDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="creatingInvite" @click="generateEnrollmentInvite">生成邀请</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="hostDialogVisible"
      :title="hostFormMode === 'create' ? t('settings.hosts.create') : t('settings.hosts.edit')"
      width="640px"
      class="ui-dialog"
      :before-close="closeHostDialog"
    >
      <el-form :model="hostForm" label-position="top" ref="hostFormRef" :rules="hostRules" v-loading="hostFormLoading">
        <div class="dialog-grid">
          <el-form-item :label="t('settings.hosts.form.id')" prop="host_id">
            <el-input
              class="mono-input"
              v-model="hostForm.host_id"
              :placeholder="t('settings.hosts.form.idPlaceholder')"
              :disabled="hostFormMode === 'edit'"
            />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.name')" prop="display_name">
            <el-input v-model="hostForm.display_name" :placeholder="t('settings.hosts.form.namePlaceholder')" />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.sort')" prop="sort_order">
            <el-input-number v-model="hostForm.sort_order" :min="0" />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.trafficBillingDay')" prop="traffic_billing_day">
            <el-input-number
              v-model="hostForm.traffic_billing_day"
              class="billing-day-input"
              :min="1"
              :max="31"
              :step="1"
            />
            <div class="form-help">{{ t("settings.hosts.form.trafficBillingDayHelp") }}</div>
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.enabled')" prop="enabled">
            <el-switch v-model="hostForm.enabled" />
          </el-form-item>
        </div>

        <el-divider>{{ t("settings.hosts.form.connection") }}</el-divider>

        <div class="mode-section">
          <el-form-item :label="t('settings.hosts.form.agentUrl')" prop="agent_url">
            <el-input class="mono-input" v-model="hostForm.agent_url" placeholder="http://your-host:8080/fleetge-random-path" />
            <div class="form-help">{{ t("settings.hosts.form.agentUrlHelp") }}</div>
          </el-form-item>
          <el-form-item :label="t('settings.hosts.form.agentToken')" prop="agent_token">
            <el-input
              class="mono-input"
              v-model="hostForm.agent_token"
              type="password"
              show-password
              :placeholder="hostFormMode === 'edit' ? t('settings.hosts.form.unchangedPlaceholder') : t('settings.hosts.form.agentTokenPlaceholder')"
            />
          </el-form-item>
        </div>

        <div class="dialog-actions-row">
          <el-button type="success" plain @click="testFormConnection" :loading="testConnectionLoading">
            {{ t("settings.hosts.action.test") }}
          </el-button>
          <div class="spacer"></div>
          <el-button @click="closeHostDialog">{{ t("compose.cancel") }}</el-button>
          <el-button type="primary" @click="saveHostForm">{{ t("compose.saveAction") }}</el-button>
        </div>
      </el-form>
    </el-dialog>

    <el-dialog
      v-model="appProfilesDialogVisible"
      :title="t('settings.appProfiles.title', { name: selectedHost?.display_name })"
      width="880px"
      class="ui-dialog"
    >
      <div class="icons-dialog-body" v-loading="appProfilesLoading">
        <div class="current-icons-section">
          <div class="section-kicker">{{ t("settings.appProfiles.existing") }}</div>
          <el-table :data="appProfilesList" stripe size="small" class="icons-table" :max-height="appProfilesTableMaxHeight">
            <el-table-column :label="t('settings.appProfiles.col.pattern')" prop="stack_pattern" width="130">
              <template #default="{ row }">
                <code class="pattern-code">{{ row.stack_pattern }}</code>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.title')" prop="title" width="130">
              <template #default="{ row }">
                <span>{{ row.title || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.url')" prop="app_url" min-width="150">
              <template #default="{ row }">
                <span class="url-text font-mono">{{ row.app_url || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.group')" prop="group" width="110" align="center">
              <template #default="{ row }">
                <div class="app-profile-group-cell">
                  <el-tag v-if="row.group" size="small">{{ row.group }}</el-tag>
                  <span v-else>-</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.icon')" width="80" align="center">
              <template #default="{ row }">
                <div class="app-profile-icon-cell">
                  <el-image v-if="getAppProfileIconValue(row)" :src="getIconUrl(getAppProfileIconValue(row))" class="icon-preview-cell" fit="contain">
                    <template #error>
                      <el-icon class="icon-placeholder-cell"><Picture /></el-icon>
                    </template>
                  </el-image>
                  <span v-else>-</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.actions')" width="98" align="center">
              <template #default="{ row, $index }">
                <div class="app-profile-row-actions">
                  <el-button size="small" type="info" plain :icon="Edit" @click="editAppProfile(row, $index)" />
                  <el-button size="small" type="danger" plain :icon="Delete" @click="removeAppProfile($index)" />
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-divider class="compact-divider">{{ t("settings.appProfiles.addNew") }}</el-divider>

        <el-form :model="appProfileForm" label-position="top" class="add-icon-form" ref="appProfileFormRef" :rules="appProfileRules">
          <div class="icon-form-grid">
            <el-form-item :label="t('settings.appProfiles.form.pattern')" prop="stack_pattern">
              <el-input v-model="appProfileForm.stack_pattern" :placeholder="t('settings.appProfiles.form.patternPlaceholder')" />
              <div class="form-help" v-html="t('settings.icons.form.patternHelp')"></div>
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.title')" prop="title">
              <el-input v-model="appProfileForm.title" :placeholder="t('settings.appProfiles.form.titlePlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.url')" prop="app_url">
              <el-input v-model="appProfileForm.app_url" :placeholder="t('settings.appProfiles.form.urlPlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.group')" prop="group">
              <el-input v-model="appProfileForm.group" :placeholder="t('settings.appProfiles.form.groupPlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.source')">
              <el-radio-group v-model="appProfileForm.sourceType" size="small">
                <el-radio-button label="none">{{ t("apps.chip.all") }} (None)</el-radio-button>
                <el-radio-button label="url">{{ t("settings.appProfiles.form.remoteUrl") }}</el-radio-button>
                <el-radio-button label="local">{{ t("settings.appProfiles.form.localFile") }}</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <el-form-item v-if="appProfileForm.sourceType === 'url'" :label="t('settings.appProfiles.form.remoteUrl')" prop="icon_url">
              <el-input v-model="appProfileForm.icon_url" placeholder="https://cdn.jsdelivr.net/.../logo.svg" />
            </el-form-item>

            <el-form-item v-else-if="appProfileForm.sourceType === 'local'" :label="t('settings.appProfiles.form.localFile')" prop="icon_file">
              <div class="local-file-picker">
                <el-select v-model="appProfileForm.icon_file" :placeholder="t('settings.appProfiles.form.localPlaceholder')" class="file-select">
                  <el-option v-for="file in availableFiles" :key="file" :label="file" :value="file" />
                </el-select>

                <el-upload
                  action="#"
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleIconFileSelected"
                  class="upload-trigger"
                >
                  <el-button type="info" :icon="Upload" class="ui-button ui-button--muted">{{ t("settings.appProfiles.form.upload") }}</el-button>
                </el-upload>
              </div>
            </el-form-item>
          </div>

          <div class="icon-form-action">
            <el-button v-if="editingAppProfileIndex !== null" class="ui-button ui-button--muted" @click="resetAppProfileForm">
              {{ t("compose.cancel") }}
            </el-button>
            <el-button type="primary" class="ui-button ui-button--compact" @click="addAppProfile">
              {{ editingAppProfileIndex === null ? t("settings.appProfiles.form.addBtn") : t("settings.appProfiles.form.updateBtn") }}
            </el-button>
          </div>
        </el-form>
      </div>

      <template #footer>
        <div class="dialog-actions-row">
          <el-button @click="appProfilesDialogVisible = false">{{ t("compose.cancel") }}</el-button>
          <el-button type="primary" @click="saveAppProfiles" :loading="store.saving">{{ t("settings.appProfiles.form.saveBtn") }}</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="globalEnvDialogVisible"
      :title="t('settings.globalEnv.title', { name: selectedHost?.display_name })"
      width="720px"
      class="ui-dialog"
    >
      <div class="global-env-dialog" v-loading="globalEnvLoading">
        <el-alert
          :title="t('settings.globalEnv.help')"
          type="info"
          show-icon
          :closable="false"
        />
        <el-input
          v-model="globalEnvContent"
          type="textarea"
          :rows="16"
          resize="vertical"
          spellcheck="false"
          placeholder="TZ=Asia/Shanghai"
          class="global-env-textarea"
        />
      </div>
      <template #footer>
        <div class="dialog-actions-row">
          <el-button @click="globalEnvDialogVisible = false">{{ t("compose.cancel") }}</el-button>
          <el-button type="primary" @click="saveGlobalEnv" :loading="store.saving">
            {{ t("settings.globalEnv.save") }}
          </el-button>
        </div>
      </template>
    </el-dialog>

    <el-drawer v-model="auditDrawerVisible" :title="t('settings.audit.detailTitle')" size="420px">
      <dl v-if="selectedAuditLog" class="audit-detail-list">
        <div>
          <dt>{{ t("audit.time") }}</dt>
          <dd>{{ formatTime(selectedAuditLog.timestamp) }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.user") }}</dt>
          <dd>{{ selectedAuditLog.user || "-" }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.action") }}</dt>
          <dd>{{ actionLabel(selectedAuditLog.action) }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.host") }}</dt>
          <dd>{{ selectedAuditLog.host_id || "-" }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.stack") }}</dt>
          <dd>{{ selectedAuditLog.stack_name || "-" }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.result") }}</dt>
          <dd>{{ selectedAuditLog.result === "success" ? t("audit.success") : t("audit.failure") }}</dd>
        </div>
        <div>
          <dt>{{ t("audit.ip") }}</dt>
          <dd>{{ selectedAuditLog.ip_address || "-" }}</dd>
        </div>
        <div class="wide">
          <dt>{{ t("audit.detail") }}</dt>
          <dd>{{ selectedAuditLog.detail || "-" }}</dd>
        </div>
      </dl>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { useConfirm } from "@/composables/useConfirm";
import {
  Plus,
  Edit,
  Delete,
  Picture,
  Upload,
  Setting as SettingIcon,
  Link,
  Document,
} from "@element-plus/icons-vue";
import {
  BookOpen,
  ChevronRight,
  GitBranch,
  History,
  MessageCircleQuestionMark,
  RefreshCw,
  Search,
  Server,
  SlidersHorizontal,
  Wrench,
  Clock3,
  Copy,
  Rocket,
  RotateCcw,
  ShieldCheck,
  LoaderCircle,
} from "@lucide/vue";
import dayjs from "dayjs";
import { apiClient } from "@/api/client";
import { useSettingsStore, type HostConfigResponse, type AppProfileEntry, type EnrollmentStatus } from "@/stores/settings";
import { useDashboardStore, type UpdateResult } from "@/stores/dashboard";
import { useMobile } from "@/composables/useMobile";
import UpdateBadge from "@/components/UpdateBadge.vue";

type SettingsSectionId = "params" | "hosts" | "maintenance" | "audit" | "about";

interface AuditEntry {
  id: number;
  timestamp: string;
  user: string;
  action: string;
  host_id: string;
  stack_name?: string;
  result: string;
  detail?: string;
  ip_address?: string;
}

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useSettingsStore();
const dashboardStore = useDashboardStore();
const { confirm, alert: confirmAlert } = useConfirm();
const { isMobile } = useMobile();
const appVersion = __APP_VERSION__;

const enrollmentDialogVisible = ref(false);
const addHostChoiceVisible = ref(false);

function openAddHostChoiceDialog() {
  addHostChoiceVisible.value = true;
}

function chooseAddHostMode(mode: "enrollment" | "manual") {
  addHostChoiceVisible.value = false;
  if (mode === "enrollment") {
    openEnrollmentDialog();
  } else {
    openCreateHostDialog();
  }
}
const creatingInvite = ref(false);
const currentInviteId = ref("");
const currentInstallCommand = ref("");
const retryingInviteId = ref("");
const enrollmentClock = ref(Date.now());
let enrollmentClockTimer: ReturnType<typeof setInterval> | null = null;
let enrollmentPollTimer: ReturnType<typeof setInterval> | null = null;
const enrollmentForm = reactive({
  dashboard_url: typeof window === "undefined" ? "" : window.location.origin,
  agent_public_host: "",
  stack_root: "/opt/stacks",
  agent_port: 8080,
  agent_image: "",
});

const currentInvite = computed(() =>
  store.enrollmentInvites.find((item) => item.invite_id === currentInviteId.value) || null,
);

const enrollmentHttpWarning = computed(() => {
  try {
    const url = new URL(enrollmentForm.dashboard_url);
    return url.protocol === "http:" && !["localhost", "127.0.0.1", "::1"].includes(url.hostname)
      && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(url.hostname);
  } catch {
    return false;
  }
});

function remainingTime(expiresAt: string) {
  void enrollmentClock.value;
  const left = Math.max(0, new Date(expiresAt).getTime() - Date.now());
  if (!left) return "已过期";
  const seconds = Math.ceil(left / 1000);
  return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
}

function enrollmentStatusLabel(status: EnrollmentStatus) {
  return ({
    issued: "等待下载", downloaded: "正在安装", verifying: "验证 DNS / HTTPS", active: "已启用",
    needs_url: "等待迁移", failed: "验证失败", expired: "已过期", revoked: "已撤销",
  } as Record<EnrollmentStatus, string>)[status];
}

async function openEnrollmentDialog() {
  enrollmentDialogVisible.value = true;
  enrollmentForm.dashboard_url = window.location.origin;
  try {
    await store.fetchEnrollmentInvites();
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || "邀请列表加载失败");
  }
}

async function generateEnrollmentInvite() {
  if (!/^https?:\/\//.test(enrollmentForm.dashboard_url)) {
    ElMessage.error("Dashboard URL 必须以 http:// 或 https:// 开头");
    return;
  }
  if (!enrollmentForm.stack_root.startsWith("/")) {
    ElMessage.error("Stack 根目录必须是 Linux 绝对路径");
    return;
  }
  const publicHost = enrollmentForm.agent_public_host.trim().toLowerCase().replace(/\.$/, "");
  if (!/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(publicHost)) {
    ElMessage.error("请填写具体的 Agent 公网子域名，不要包含协议、端口或路径");
    return;
  }
  creatingInvite.value = true;
  try {
    const invite = await store.createEnrollmentInvite({
      dashboard_url: enrollmentForm.dashboard_url,
      agent_public_host: publicHost,
      stack_root: enrollmentForm.stack_root,
      agent_port: enrollmentForm.agent_port,
      agent_image: enrollmentForm.agent_image || undefined,
    });
    currentInviteId.value = invite.invite_id;
    currentInstallCommand.value = invite.install_command || "";
    ElMessage.success("一次性邀请已生成");
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || "生成邀请失败");
  } finally {
    creatingInvite.value = false;
  }
}

async function copyInstallCommand() {
  if (!currentInstallCommand.value) return;
  try {
    await navigator.clipboard.writeText(currentInstallCommand.value);
    ElMessage.success("安装命令已复制");
  } catch {
    ElMessage.error("复制失败，请手动选择命令");
  }
}

async function revokeInvite(inviteId: string) {
  try {
    await store.revokeEnrollmentInvite(inviteId);
    if (currentInviteId.value === inviteId) currentInstallCommand.value = "";
    ElMessage.success("邀请已撤销");
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || "撤销失败");
  }
}

async function retryInvite(inviteId: string) {
  retryingInviteId.value = inviteId;
  try {
    const result = await store.retryEnrollmentInvite(inviteId);
    if (result.status === "active") ElMessage.success("Agent 已验证并启用");
    else ElMessage.info(result.message || "主控已重新开始验证");
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || error.message || "重试失败");
  } finally {
    retryingInviteId.value = "";
  }
}

const activeSection = ref<SettingsSectionId>("params");
const validSections: SettingsSectionId[] = ["params", "hosts", "maintenance", "audit", "about"];

const settingSections = computed(() => [
  {
    id: "params" as const,
    label: t("settings.sections.params"),
    description: t("settings.sections.paramsDesc"),
    icon: SlidersHorizontal,
  },
  {
    id: "hosts" as const,
    label: t("settings.sections.hosts"),
    description: t("settings.sections.hostsDesc"),
    icon: Server,
  },
  {
    id: "maintenance" as const,
    label: t("settings.sections.maintenance"),
    description: t("settings.sections.maintenanceDesc"),
    icon: Wrench,
  },
  {
    id: "audit" as const,
    label: t("settings.sections.audit"),
    description: t("settings.sections.auditDesc"),
    icon: History,
  },
  {
    id: "about" as const,
    label: t("settings.sections.about"),
    description: t("settings.sections.aboutDesc"),
    icon: GitBranch,
  },
]);

const resourceLinks = computed(() => [
  {
    label: t("settings.about.github"),
    description: t("settings.about.githubDesc"),
    href: "https://github.com/virgooooox/fleetge",
    icon: GitBranch,
  },
  {
    label: t("settings.about.docs"),
    description: t("settings.about.docsDesc"),
    href: "https://github.com/virgooooox/fleetge#readme",
    icon: BookOpen,
  },
  {
    label: t("settings.about.releases"),
    description: t("settings.about.releasesDesc"),
    href: "https://github.com/virgooooox/fleetge/releases",
    icon: History,
  },
  {
    label: t("settings.about.issues"),
    description: t("settings.about.issuesDesc"),
    href: "https://github.com/virgooooox/fleetge/issues",
    icon: MessageCircleQuestionMark,
  },
]);



function setSection(section: SettingsSectionId) {
  activeSection.value = section;
  void router.replace({ name: "settings", query: { section } });
}

const paramsForm = reactive<Record<string, any>>({
  DOCKER_POLL_INTERVAL: 10,
  METRICS_STREAM_INTERVAL: 2,
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: 3600,
  UPDATE_CHECK_INTERVAL: 43200,
  ADMIN_USERNAME: "admin",
  JWT_EXPIRE_HOURS: 24,
  ENROLLMENT_AGENT_IMAGE: "ghcr.io/virgooooox/fleetge-agent:latest",
  ENROLLMENT_PROXY_IMAGE: "caddy:2-alpine",
});

const paramsFormRef = ref<FormInstance>();
const paramsRules = reactive<FormRules>({
  DOCKER_POLL_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  METRICS_STREAM_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  UPDATE_CHECK_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  ADMIN_USERNAME: [
    { required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" },
    { min: 3, message: t("settings.hosts.form.required.id"), trigger: "blur" },
  ],
  JWT_EXPIRE_HOURS: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  ENROLLMENT_AGENT_IMAGE: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  ENROLLMENT_PROXY_IMAGE: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
});

const readonlyForm = reactive({
  JWT_SECRET: "",
  CREDENTIALS_KEY: "",
  ADMIN_PASSWORD: "",
});

async function loadSettings() {
  try {
    await store.fetchSettings();
    store.settings.forEach((item) => {
      if (item.is_writable) {
        paramsForm[item.key] = item.type === "number" ? Number(item.value) : item.value;
      } else if (item.key in readonlyForm) {
        (readonlyForm as any)[item.key] = item.value;
      }
    });
  } catch (err: any) {
    ElMessage.error(store.error || t("settings.params.saveError"));
  }
}

async function handleSaveParams() {
  if (!paramsFormRef.value) return;
  await paramsFormRef.value.validate(async (valid) => {
    if (!valid) return;
    try {
      const updates: Record<string, string> = {};
      Object.keys(paramsForm).forEach((key) => {
        updates[key] = String(paramsForm[key]);
      });
      await store.saveSettings(updates);
      ElMessage.success(t("settings.params.saveSuccess"));
    } catch (err: any) {
      ElMessage.error(store.error || t("settings.params.saveError"));
    }
  });
}

const hostDialogVisible = ref(false);
const hostFormMode = ref<"create" | "edit">("create");
const hostFormLoading = ref(false);
const testConnectionLoading = ref(false);
const hostFormRef = ref<FormInstance>();

const hostForm = reactive({
  host_id: "",
  display_name: "",
  enabled: true,
  sort_order: 0,
  traffic_billing_day: 1,
  agent_url: "",
  agent_token: "",
});

const validateHostId = (_rule: any, value: string, callback: any) => {
  if (!value) {
    callback(new Error(t("settings.hosts.form.required.id")));
  } else if (!/^[a-z0-9][a-z0-9-]*$/.test(value)) {
    callback(new Error(t("settings.hosts.form.invalid.id")));
  } else {
    callback();
  }
};

const validateHttpUrl = (_rule: any, value: string, callback: any) => {
  if (value && !/^https?:\/\//.test(value)) {
    callback(new Error(t("settings.hosts.form.invalid.url")));
  } else {
    callback();
  }
};

const hostRules = reactive<FormRules>({
  host_id: [{ required: true, validator: validateHostId, trigger: "blur" }],
  display_name: [{ required: true, message: t("settings.hosts.form.required.name"), trigger: "blur" }],
  agent_url: [
    { required: true, message: t("settings.hosts.form.required.agentUrl"), trigger: "blur" },
    { validator: validateHttpUrl, trigger: "blur" },
  ],
});

function openCreateHostDialog() {
  hostFormMode.value = "create";
  hostForm.host_id = "";
  hostForm.display_name = "";
  hostForm.enabled = true;
  hostForm.sort_order = store.hosts.length > 0 ? Math.max(...store.hosts.map((h) => h.sort_order)) + 10 : 10;
  hostForm.traffic_billing_day = 1;
  hostForm.agent_url = "";
  hostForm.agent_token = "";
  hostDialogVisible.value = true;
}

function openEditHostDialog(row: HostConfigResponse) {
  hostFormMode.value = "edit";
  hostForm.host_id = row.host_id;
  hostForm.display_name = row.display_name;
  hostForm.enabled = row.enabled;
  hostForm.sort_order = row.sort_order;
  hostForm.traffic_billing_day = row.traffic_billing_day || 1;
  hostForm.agent_url = row.agent_url || "";
  hostForm.agent_token = "";
  hostDialogVisible.value = true;
}

function closeHostDialog() {
  hostDialogVisible.value = false;
  hostFormRef.value?.clearValidate();
}

function prepareHostPayload() {
  const payload: any = {
    display_name: hostForm.display_name,
    enabled: hostForm.enabled,
    sort_order: hostForm.sort_order,
    traffic_billing_day: hostForm.traffic_billing_day,
    agent_url: hostForm.agent_url,
    agent_token: hostForm.agent_token || (hostFormMode.value === "edit" ? null : ""),
  };

  if (hostFormMode.value === "create") {
    payload.host_id = hostForm.host_id;
  }

  return payload;
}

async function saveHostForm() {
  if (!hostFormRef.value) return;
  await hostFormRef.value.validate(async (valid) => {
    if (!valid) return;
    hostFormLoading.value = true;
    try {
      const payload = prepareHostPayload();
      if (hostFormMode.value === "create") {
        await store.createHost(payload);
        ElMessage.success(t("settings.hosts.create.success"));
      } else {
        await store.updateHost(hostForm.host_id, payload);
        ElMessage.success(t("settings.hosts.update.success"));
      }
      closeHostDialog();
    } catch (err: any) {
      ElMessage.error(err || t("settings.hosts.save.error"));
    } finally {
      hostFormLoading.value = false;
    }
  });
}

async function toggleHostEnabled(row: HostConfigResponse) {
  try {
    const payload = {
      display_name: row.display_name,
      enabled: row.enabled,
      sort_order: row.sort_order,
      traffic_billing_day: row.traffic_billing_day,
      agent_url: row.agent_url,
      agent_token: null,
    };
    await store.updateHost(row.host_id, payload);
    ElMessage.success(
      t(row.enabled ? "settings.hosts.toggle.enabledSuccess" : "settings.hosts.toggle.disabledSuccess", { name: row.display_name }),
    );
  } catch (err: any) {
    row.enabled = !row.enabled;
    ElMessage.error(err || t("settings.hosts.toggle.error"));
  }
}

async function confirmDeleteHost(row: HostConfigResponse) {
  try {
    await confirm(
      t("settings.hosts.delete.confirm", { name: row.display_name }),
      t("settings.hosts.delete.title"),
      {
        tone: "danger",
        confirmButtonText: t("stack.action.delete"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      },
    );
    await store.deleteHost(row.host_id);
    ElMessage.success(t("settings.hosts.delete.success", { name: row.display_name }));
  } catch (err: any) {
    if (err !== "cancel") {
      ElMessage.error(err || t("settings.hosts.delete.error"));
    }
  }
}

async function testHostConnection(row: HostConfigResponse) {
  const loadingMsg = ElMessage({
    message: t("settings.hosts.action.testing", { name: row.display_name }),
    duration: 0,
    type: "info",
  });

  const res = await store.testConnection(row.host_id);
  loadingMsg.close();

  if (res.success) {
    confirmAlert(
      t("settings.hosts.test.successDetail", { time: res.response_time_ms, msg: res.message }),
      t("settings.hosts.test.successTitle"),
      { tone: "success", confirmButtonText: t("stack.confirm.ok") },
    );
  } else {
    confirmAlert(
      t("settings.hosts.test.failedDetail", { msg: res.message }),
      t("settings.hosts.test.failedTitle"),
      { tone: "error", confirmButtonText: t("stack.confirm.ok") },
    );
  }
}

async function testFormConnection() {
  if (!hostFormRef.value) return;
  let hasErrors = false;
  hostFormRef.value.validateField(["agent_url"], (valid) => {
    if (!valid) hasErrors = true;
  });
  if (hasErrors) return;

  testConnectionLoading.value = true;
  try {
    const payload = prepareHostPayload();
    if (hostFormMode.value === "create") {
      payload.host_id = hostForm.host_id;
    }
    const res = await store.testNewConnection(payload);
    if (res.success) {
      ElMessage.success(t("settings.hosts.test.newSuccess", { time: res.response_time_ms, msg: res.message }));
    } else {
      ElMessage.error(t("settings.hosts.action.testFailed") + ` ${res.message}`);
    }
  } catch (e: any) {
    ElMessage.error(t("settings.hosts.test.error", { msg: String(e) }));
  } finally {
    testConnectionLoading.value = false;
  }
}

const appProfilesDialogVisible = ref(false);
const selectedHost = ref<HostConfigResponse | null>(null);
const appProfilesLoading = ref(false);
const appProfilesList = ref<AppProfileEntry[]>([]);
const availableFiles = ref<string[]>([]);
const appProfilesTableMaxHeight = computed(() => (appProfilesList.value.length > 10 ? 460 : undefined));
const globalEnvDialogVisible = ref(false);
const globalEnvLoading = ref(false);
const globalEnvContent = ref("");

const appProfileForm = reactive({
  stack_pattern: "",
  title: "",
  app_url: "",
  group: "",
  sourceType: "none" as "none" | "url" | "local",
  icon_url: "",
  icon_file: "",
});

const appProfileFormRef = ref<FormInstance>();
const editingAppProfileIndex = ref<number | null>(null);
const appProfileRules = reactive<FormRules>({
  stack_pattern: [{ required: true, message: t("settings.icons.required.pattern"), trigger: "blur" }],
  app_url: [{ validator: validateHttpUrl, trigger: "blur" }],
  icon_url: [{ validator: validateHttpUrl, trigger: "blur" }],
});

function resetAppProfileForm() {
  appProfileForm.stack_pattern = "";
  appProfileForm.title = "";
  appProfileForm.app_url = "";
  appProfileForm.group = "";
  appProfileForm.sourceType = "none";
  appProfileForm.icon_url = "";
  appProfileForm.icon_file = "";
  editingAppProfileIndex.value = null;
  appProfileFormRef.value?.clearValidate();
}

function normalizeAppProfile(row: AppProfileEntry): AppProfileEntry {
  const legacyRow = row as AppProfileEntry & {
    icon?: string | null;
    icon_file?: string | null;
    icon_url?: string | null;
  };

  return {
    stack_pattern: row.stack_pattern,
    title: row.title || null,
    app_url: row.app_url || null,
    group: row.group || null,
    icon_value: row.icon_value || legacyRow.icon_url || legacyRow.icon_file || legacyRow.icon || null,
  };
}

async function openAppProfilesDialog(row: HostConfigResponse) {
  selectedHost.value = row;
  appProfilesList.value = [];
  availableFiles.value = [];
  resetAppProfileForm();
  appProfilesDialogVisible.value = true;

  appProfilesLoading.value = true;
  try {
    const res = await store.fetchAppProfiles(row.host_id);
    appProfilesList.value = (res.profiles || []).map(normalizeAppProfile);
    availableFiles.value = res.available_files || [];
  } catch (e: any) {
    ElMessage.error(e || t("settings.appProfiles.fetchError"));
  } finally {
    appProfilesLoading.value = false;
  }
}

function getIconUrl(value: string | null) {
  if (!value) return "";
  if (/^https?:\/\//.test(value)) return value;
  if (value.startsWith("/api/") || value.startsWith("/")) return value;
  return `/api/static/icons/${value}`;
}

function matchIconValue(name: string, mapping?: Record<string, string> | null): string | null {
  if (!mapping) return null;
  if (mapping[name]) return mapping[name];

  for (const [key, value] of Object.entries(mapping)) {
    if (key.endsWith("*") && !key.startsWith("*") && name.startsWith(key.slice(0, -1))) {
      return value;
    }
  }

  for (const [key, value] of Object.entries(mapping)) {
    if (key.startsWith("*") && !key.endsWith("*") && name.endsWith(key.slice(1))) {
      return value;
    }
  }

  return null;
}

function getAppProfileIconValue(row: AppProfileEntry): string | null {
  return row.icon_value || matchIconValue(row.stack_pattern, selectedHost.value?.stack_icons);
}

function removeAppProfile(index: number) {
  appProfilesList.value.splice(index, 1);
  if (editingAppProfileIndex.value === index) {
    resetAppProfileForm();
  } else if (editingAppProfileIndex.value !== null && editingAppProfileIndex.value > index) {
    editingAppProfileIndex.value -= 1;
  }
}

function editAppProfile(row: AppProfileEntry, index: number) {
  editingAppProfileIndex.value = index;
  appProfileForm.stack_pattern = row.stack_pattern;
  appProfileForm.title = row.title || "";
  appProfileForm.app_url = row.app_url || "";
  appProfileForm.group = row.group || "";

  if (!row.icon_value) {
    appProfileForm.sourceType = "none";
    appProfileForm.icon_url = "";
    appProfileForm.icon_file = "";
  } else if (/^https?:\/\//.test(row.icon_value) || row.icon_value.startsWith("/")) {
    appProfileForm.sourceType = "url";
    appProfileForm.icon_url = row.icon_value;
    appProfileForm.icon_file = "";
  } else {
    appProfileForm.sourceType = "local";
    appProfileForm.icon_url = "";
    appProfileForm.icon_file = row.icon_value;
  }
}

async function handleIconFileSelected(uploadFile: any) {
  if (!selectedHost.value) return;
  const rawFile = uploadFile.raw;
  if (!rawFile) return;

  if (rawFile.size > 2 * 1024 * 1024) {
    ElMessage.error(t("settings.icons.upload.tooLarge"));
    return;
  }

  const loadingMsg = ElMessage({
    message: t("settings.icons.upload.progress"),
    duration: 0,
    type: "info",
  });

  try {
    const filename = await store.uploadIcon(selectedHost.value.host_id, rawFile);
    loadingMsg.close();
    ElMessage.success(t("settings.icons.upload.success", { name: filename }));

    if (!availableFiles.value.includes(filename)) {
      availableFiles.value.push(filename);
      availableFiles.value.sort();
    }
    appProfileForm.icon_file = filename;
  } catch (e: any) {
    loadingMsg.close();
    ElMessage.error(e || t("settings.icons.upload.error"));
  }
}

async function addAppProfile() {
  if (!appProfileForm.stack_pattern.trim()) {
    ElMessage.error(t("settings.icons.required.pattern"));
    return;
  }

  let val: string | null = null;
  if (appProfileForm.sourceType === "url") {
    if (!appProfileForm.icon_url.trim()) {
      ElMessage.error(t("settings.icons.required.url"));
      return;
    }
    if (!/^https?:\/\//.test(appProfileForm.icon_url.trim())) {
      ElMessage.error(t("settings.hosts.form.invalid.url"));
      return;
    }
    val = appProfileForm.icon_url.trim();
  } else if (appProfileForm.sourceType === "local") {
    if (!appProfileForm.icon_file) {
      ElMessage.error(t("settings.icons.required.file"));
      return;
    }
    val = appProfileForm.icon_file;
  }

  const editingIndex = editingAppProfileIndex.value;
  const dupIndex = appProfilesList.value.findIndex((i) => i.stack_pattern === appProfileForm.stack_pattern.trim());

  const newProfile: AppProfileEntry = {
    stack_pattern: appProfileForm.stack_pattern.trim(),
    title: appProfileForm.title.trim() || null,
    app_url: appProfileForm.app_url.trim() || null,
    group: appProfileForm.group.trim() || null,
    icon_value: val,
  };

  if (editingIndex !== null && dupIndex > -1 && dupIndex !== editingIndex) {
    appProfilesList.value[dupIndex] = newProfile;
    appProfilesList.value.splice(editingIndex, 1);
    ElMessage.info(t("settings.icons.mapping.updated", { pattern: appProfileForm.stack_pattern.trim() }));
  } else if (editingIndex !== null) {
    appProfilesList.value[editingIndex] = newProfile;
    ElMessage.info(t("settings.icons.mapping.updated", { pattern: appProfileForm.stack_pattern.trim() }));
  } else if (dupIndex > -1) {
    appProfilesList.value[dupIndex] = newProfile;
    ElMessage.info(t("settings.icons.mapping.updated", { pattern: appProfileForm.stack_pattern.trim() }));
  } else {
    appProfilesList.value.push(newProfile);
  }

  resetAppProfileForm();
}

async function saveAppProfiles() {
  if (!selectedHost.value) return;
  try {
    await store.saveAppProfiles(selectedHost.value.host_id, appProfilesList.value);
    ElMessage.success(t("settings.appProfiles.saveSuccess", { name: selectedHost.value.display_name }));
    appProfilesDialogVisible.value = false;
    await store.fetchHosts();
  } catch (e: any) {
    ElMessage.error(e || t("settings.appProfiles.saveError"));
  }
}

async function openGlobalEnvDialog(row: HostConfigResponse) {
  selectedHost.value = row;
  globalEnvContent.value = "";
  globalEnvDialogVisible.value = true;
  globalEnvLoading.value = true;
  try {
    globalEnvContent.value = await store.fetchGlobalEnv(row.host_id);
  } catch (e: any) {
    ElMessage.error(e || t("settings.globalEnv.fetchError"));
  } finally {
    globalEnvLoading.value = false;
  }
}

async function saveGlobalEnv() {
  if (!selectedHost.value) return;
  try {
    await store.saveGlobalEnv(selectedHost.value.host_id, globalEnvContent.value);
    ElMessage.success(t("settings.globalEnv.saveSuccess", { name: selectedHost.value.display_name }));
    globalEnvDialogVisible.value = false;
  } catch (e: any) {
    ElMessage.error(e || t("settings.globalEnv.saveError"));
  }
}

const checkingUpdates = ref(false);
const updateSearch = ref("");
const updateStatusFilter = ref("");

const visibleUpdateResults = computed(() =>
  (dashboardStore.updateResults || []).filter((item) =>
    item.status === "updatable"
    || item.status === "up_to_date"
    || item.status === "needs_auth"
    || item.status === "rate_limited"
    || item.status === "check_failed"
    || item.last_failure_status === "needs_auth"
    || item.last_failure_status === "rate_limited"
    || item.last_failure_status === "check_failed",
  ),
);

const filteredUpdateResults = computed(() => {
  const q = updateSearch.value.trim().toLowerCase();
  return visibleUpdateResults.value.filter((item) => {
    const status = displayStatus(item);
    if (updateStatusFilter.value && status !== updateStatusFilter.value) return false;
    if (!q) return true;
    return item.host_id.toLowerCase().includes(q) || item.image.toLowerCase().includes(q);
  });
});

function displayStatus(item: UpdateResult) {
  return item.last_failure_status || item.status;
}

function shortenDigest(value?: string) {
  return value ? `${value.slice(0, 19)}...` : "-";
}

async function fetchUpdateResults() {
  checkingUpdates.value = true;
  try {
    await dashboardStore.fetchUpdateChecks(true);
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
  } finally {
    checkingUpdates.value = false;
  }
}

async function runMaintenanceCheck() {
  checkingUpdates.value = true;
  try {
    await dashboardStore.runUpdateCheck(true);
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    checkingUpdates.value = false;
  }
}

function openUpdatableApps() {
  void router.push({ name: "apps", query: { status: "updatable" } });
}

const auditLogs = ref<AuditEntry[]>([]);
const auditLoading = ref(false);
const auditSearch = ref("");
const auditResultFilter = ref("");
const auditActionFilter = ref("");
const selectedAuditLog = ref<AuditEntry | null>(null);
const auditDrawerVisible = ref(false);
const auditLimit = 50;

const auditActionKeys: Record<string, string> = {
  "stack.start": "audit.action.stack.start",
  "stack.stop": "audit.action.stack.stop",
  "stack.down": "audit.action.stack.down",
  "stack.restart": "audit.action.stack.restart",
  "stack.update": "audit.action.stack.update",
  "stack.delete": "audit.action.stack.delete",
  "stack.service.start": "audit.action.stack.serviceStart",
  "stack.service.stop": "audit.action.stack.serviceStop",
  "stack.service.restart": "audit.action.stack.serviceRestart",
  "stack.compose.save": "audit.action.stack.composeSave",
  "stack.compose.deploy": "audit.action.stack.composeDeploy",
  "update_checks.run": "audit.action.updateChecksRun",
  "settings.update": "audit.action.settings.update",
  "host.create": "audit.action.host.create",
  "host.update": "audit.action.host.update",
  "host.delete": "audit.action.host.delete",
  "host.stack_icons.update": "audit.action.host.stack_icons.update",
  "host.test_connection": "audit.action.host.test_connection",
};

const actionTypes: Record<string, string> = {
  "stack.start": "success",
  "stack.stop": "warning",
  "stack.down": "warning",
  "stack.restart": "",
  "stack.update": "primary",
  "stack.delete": "danger",
  "stack.service.start": "success",
  "stack.service.stop": "warning",
  "stack.service.restart": "",
  "stack.compose.save": "info",
  "stack.compose.deploy": "primary",
  "update_checks.run": "info",
  "settings.update": "warning",
  "host.create": "success",
  "host.update": "primary",
  "host.delete": "danger",
  "host.stack_icons.update": "info",
  "host.test_connection": "success",
};

const auditActions = computed(() =>
  Array.from(new Set(auditLogs.value.map((row) => row.action)))
    .filter(Boolean)
    .sort()
    .map((action) => ({ value: action, label: actionLabel(action) })),
);

const filteredAuditLogs = computed(() => {
  const q = auditSearch.value.trim().toLowerCase();
  return auditLogs.value.filter((row) => {
    if (auditResultFilter.value && row.result !== auditResultFilter.value) return false;
    if (auditActionFilter.value && row.action !== auditActionFilter.value) return false;
    if (!q) return true;
    return [
      row.user,
      row.action,
      row.host_id,
      row.stack_name,
      row.detail,
      row.ip_address,
    ].some((value) => String(value || "").toLowerCase().includes(q));
  });
});

function actionLabel(action: string): string {
  const key = auditActionKeys[action];
  return key ? t(key as any) : action;
}

function actionType(action: string): string {
  return actionTypes[action] || "info";
}

function formatTime(ts: string): string {
  return dayjs(ts).format("YYYY-MM-DD HH:mm:ss");
}

async function fetchLogs() {
  auditLoading.value = true;
  try {
    const res = await apiClient.get("/api/audit-logs", {
      params: { limit: auditLimit, offset: 0 },
    });
    auditLogs.value = res.data || [];
  } catch (e) {
    console.error("Failed to fetch audit logs:", e);
  } finally {
    auditLoading.value = false;
  }
}

function openAuditDrawer(row: AuditEntry) {
  selectedAuditLog.value = row;
  auditDrawerVisible.value = true;
}

watch(
  () => route.query,
  (query) => {
    const section = Array.isArray(query.section) ? query.section[0] : query.section;
    if (section && validSections.includes(section as SettingsSectionId)) {
      activeSection.value = section as SettingsSectionId;
    }
    const action = Array.isArray(query.action) ? query.action[0] : query.action;
    if (action === "add-host") {
      openAddHostChoiceDialog();
      void router.replace({ name: "settings", query: { section: "hosts" } });
    }
  },
  { immediate: true },
);

onMounted(() => {
  void loadSettings();
  void store.fetchHosts();
  void fetchUpdateResults();
  void fetchLogs();
  enrollmentClockTimer = setInterval(() => { enrollmentClock.value = Date.now(); }, 1000);
  enrollmentPollTimer = setInterval(() => {
    if (enrollmentDialogVisible.value) void store.fetchEnrollmentInvites().catch(() => undefined);
  }, 5000);
});

onBeforeUnmount(() => {
  if (enrollmentClockTimer) clearInterval(enrollmentClockTimer);
  if (enrollmentPollTimer) clearInterval(enrollmentPollTimer);
});
</script>

<style scoped>
.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-heading p {
  margin: 6px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.settings-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  padding: 6px;
}

.settings-tab {
  min-width: max-content;
  min-height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  padding: 0 14px;
  font: inherit;
  font-size: 13px;
  font-weight: 800;
  line-height: 1;
  text-decoration: none;
  cursor: pointer;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.settings-tab:hover,
.settings-tab.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--text-primary);
}

.settings-tab .el-icon {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent-blue);
  flex: 0 0 auto;
}

.settings-workspace {
  min-width: 0;
}

.settings-main {
  min-width: 0;
}

.settings-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  padding: 18px;
}

.section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.section-heading h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: 20px;
  line-height: 1.2;
}

.section-actions,
.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.settings-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.params-settings-form {
  gap: 12px;
}

.form-cluster {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
  padding: 16px;
}

.params-settings-form .form-cluster {
  overflow: hidden;
  padding: 0;
}

.cluster-title,
.section-kicker {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
  margin-bottom: 12px;
}

.params-settings-form .cluster-title {
  margin: 0;
  padding: 11px 16px;
  border-bottom: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-panel) 68%, transparent);
}

.settings-field-list {
  display: flex;
  flex-direction: column;
}

.settings-field-row {
  margin: 0;
  padding: 13px 16px;
  border-top: 1px solid var(--border-subtle);
}

.settings-field-row:first-child {
  border-top: 0;
}

.settings-field-row :deep(.el-form-item__label) {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  height: auto;
  padding: 0;
  margin: 0;
  line-height: 1.35;
  text-align: left;
}

.settings-field-row :deep(.el-form-item__content) {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}

.settings-field-label {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 700;
  white-space: normal;
}

.settings-field-help {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.45;
  white-space: normal;
}

.params-settings-form :deep(.el-input-number) {
  width: 148px;
}

.params-settings-form :deep(.el-input) {
  width: min(360px, 100%);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 18px 24px;
}

.input-with-unit,
.icons-preview-strip,
.local-file-picker {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unit-text,
.form-help {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.form-help {
  margin-top: 6px;
}

@media (min-width: 860px) {
  .settings-field-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(180px, auto);
    align-items: center;
    column-gap: 22px;
  }

  .settings-field-row :deep(.el-form-item__label) {
    grid-column: 1;
  }

  .settings-field-row :deep(.el-form-item__content) {
    grid-column: 2;
  }
}

@media (max-width: 859px) {
  .settings-field-row :deep(.el-form-item__content) {
    justify-content: flex-start;
    margin-top: 10px;
  }
}

.settings-inline-details {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
}

.settings-inline-details summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
}

.settings-inline-details summary span {
  flex: 0 0 auto;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 800;
}

.settings-inline-details summary small {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.inline-security-form {
  border-top: 1px solid var(--border-subtle);
  padding: 16px;
}

.table-frame {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
}

.host-table {
  border-radius: 8px;
  overflow: hidden;
}

.host-table :deep(.el-table__cell) {
  padding: 7px 0;
}

.host-table :deep(.cell) {
  padding-left: 8px;
  padding-right: 8px;
}

.host-code-text,
.audit-code,
.detail-text,
.digest-text,
.url-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  word-break: break-all;
}

.image-ref {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: rgba(5, 9, 20, 0.78);
  color: #e5edf8;
  border-radius: 4px;
  padding: 2px 6px;
}

.pattern-code {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  padding: 2px 6px;
}

.section-alert {
  border-radius: 8px;
}

.about-panel {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
  overflow: hidden;
}

.about-version-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  font-size: 13px;
}

.about-version-row strong {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 13px;
}

.about-link-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.about-link-row {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-top: 1px solid transparent;
  color: var(--text-secondary);
  text-decoration: none;
  transition: background 160ms ease, color 160ms ease;
}

.about-link-row:hover {
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

.about-link-row .el-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border-radius: 7px;
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue);
}

.about-link-row span {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.about-link-row strong {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.2;
}

.about-link-row small {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
}

.toolbar-input {
  flex: 1;
  min-width: 220px;
}

.toolbar-select {
  width: 160px;
}

.toolbar-select.wide {
  width: 220px;
}

.audit-time {
  font-variant-numeric: tabular-nums;
}

:deep(.audit-row) {
  cursor: pointer;
}

.dialog-grid,
.icon-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.billing-day-input {
  width: 100%;
}

.mode-section,
.add-icon-form {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
}

.dialog-actions-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}

.dialog-actions-row .spacer {
  flex: 1;
}

.icons-dialog-body,
.global-env-dialog {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.global-env-textarea :deep(textarea),
.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.global-env-textarea :deep(textarea) {
  font-size: 12px;
  line-height: 1.55;
}

.icon-preview-cell {
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  background: var(--surface-panel-raised);
  overflow: hidden;
  display: grid;
  place-items: center;
}

.icon-preview-cell {
  width: 32px;
  height: 32px;
  padding: 2px;
}

.icon-placeholder-cell {
  color: var(--text-muted);
}

.app-profile-group-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
}

.app-profile-icon-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
}

.app-profile-row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.app-profile-row-actions :deep(.el-button) {
  width: 28px;
  height: 28px;
  padding: 0;
}

.app-profile-row-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.app-profiles-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-profile-settings-btn {
  height: 28px;
  min-width: 58px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-shrink: 0;
  border: 1px solid var(--el-border-color);
  border-radius: 7px;
  background: var(--surface-panel);
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0 8px;
  position: relative;
  z-index: 1;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.app-profile-settings-btn:hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-hover);
  color: var(--text-primary);
}

.app-profile-settings-btn .el-icon {
  width: 14px;
  height: 14px;
  font-size: 14px;
  color: currentColor;
}

.app-profile-settings-btn :deep(svg) {
  width: 14px;
  height: 14px;
  display: block;
}

.row-operations {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: nowrap;
}

.row-operations :deep(.el-button + .el-button) {
  margin-left: 0;
}

.host-action-btn {
  height: 28px;
}

.host-action-test {
  padding: 0 8px;
}

.host-icon-btn {
  width: 28px;
  padding: 0;
}

.file-select {
  flex: 1;
}

.compact-divider {
  margin: 8px 0 2px;
}

.add-icon-form {
  padding: 12px;
}

.add-icon-form .icon-form-grid {
  gap: 8px 14px;
}

.add-icon-form :deep(.el-form-item) {
  margin-bottom: 6px;
}

.add-icon-form .form-help {
  margin-top: 4px;
}

.add-icon-form .local-file-picker {
  gap: 6px;
}

.icon-form-action {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.audit-detail-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  margin: 0;
}

.audit-detail-list div {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
  padding: 10px 12px;
}

.audit-detail-list dt {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 4px;
}

.audit-detail-list dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.enrollment-launch {
  border-color: rgba(96, 165, 250, 0.38);
  color: #bfdbfe;
  background: rgba(59, 130, 246, 0.1);
}

.enrollment-intro {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  margin-bottom: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-raised, rgba(59, 130, 246, 0.04));
}

.enrollment-intro-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--accent-blue, #3b82f6);
  background: color-mix(in srgb, var(--accent-blue, #3b82f6) 12%, transparent);
  flex-shrink: 0;
}

.enrollment-intro strong {
  display: block;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.enrollment-intro p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.enrollment-warning {
  margin-top: 6px;
  color: var(--warning, #fbbf24);
  font-size: 11px;
}

:deep(.enrollment-dialog .el-collapse) {
  margin-top: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow: hidden;
  background: transparent;
}

:deep(.enrollment-dialog .el-collapse-item__header) {
  padding: 0 16px;
  height: 44px;
  line-height: 44px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface-panel-raised, rgba(15, 23, 42, 0.03));
  border-bottom: none;
  transition: background 0.2s ease;
}

:deep(.enrollment-dialog .el-collapse-item__header.is-active) {
  border-bottom: 1px solid var(--border-subtle);
}

:deep(.enrollment-dialog .el-collapse-item__wrap) {
  background: var(--surface-panel, transparent);
  border-bottom: none;
}

:deep(.enrollment-dialog .el-collapse-item__content) {
  padding: 16px;
  color: var(--text-primary);
}

.enrollment-option-grid {
  display: grid;
  grid-template-columns: 1fr 140px;
  gap: 14px;
}

.enrollment-option-grid > :last-child {
  grid-column: 1 / -1;
  margin-bottom: 0;
}

:deep(.enrollment-dialog .el-input-number) {
  width: 100%;
}

.install-command-card {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid rgba(34, 211, 238, 0.24);
  border-radius: 10px;
  background: #07111e;
}

.install-command-head,
.install-command-head span,
.install-command-head strong {
  display: flex;
  align-items: center;
  gap: 7px;
}

.install-command-head { justify-content: space-between; margin-bottom: 11px; color: #a5f3fc; font-size: 12px; }
.install-command-head strong { color: #67e8f9; font-family: var(--font-mono); }
.install-command-card code { display: block; max-height: 125px; overflow: auto; padding: 12px; border-radius: 7px; color: #dbeafe; background: #030712; font: 11px/1.65 var(--font-mono); word-break: break-all; }
.install-command-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 11px; }

.invite-list { display: grid; gap: 7px; margin-top: 18px; }
.invite-list-title { margin-bottom: 2px; color: var(--text-muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.invite-row { display: grid; grid-template-columns: auto minmax(130px, 1fr) minmax(150px, auto); align-items: center; gap: 10px; padding: 10px 11px; border: 1px solid var(--border-subtle); border-radius: 8px; background: var(--surface-panel-raised); }
.invite-state { width: 8px; height: 8px; border-radius: 50%; background: #64748b; }
.invite-state.issued,.invite-state.downloaded,.invite-state.verifying { background: #60a5fa; box-shadow: 0 0 9px rgba(96,165,250,.75); }
.invite-state.active { background: #22d3ee; }.invite-state.needs_url { background: #fbbf24; }.invite-state.failed,.invite-state.expired,.invite-state.revoked { background: #f87171; }
.invite-row strong,.invite-row small,.invite-row p { display: block; }.invite-row strong { color: var(--text-primary); font-size: 12px; }.invite-row small { margin-top: 3px; color: var(--text-muted); font: 10px var(--font-mono); }.invite-row p { margin: 4px 0 0; color: #fbbf24; font-size: 10px; }
.invite-retry { display: flex; gap: 6px; min-width: 270px; }
.invite-verifying { display: inline-flex; align-items: center; justify-content: flex-end; gap: 6px; color: #93c5fd; font-size: 11px; white-space: nowrap; }

@media (max-width: 1100px) {
  .settings-tabs {
    scrollbar-width: thin;
  }
}

@media (max-width: 768px) {
  .dialog-grid,
  .icon-form-grid {
    grid-template-columns: 1fr;
  }

  .settings-tabs {
    padding: 5px;
  }

  .settings-tab {
    min-height: 34px;
    padding: 0 10px;
  }

  .section-heading {
    flex-direction: column;
  }

  .settings-section {
    padding: 14px;
  }

  .enrollment-option-grid,
  .invite-row { grid-template-columns: 1fr; }
  .enrollment-option-grid > :last-child { grid-column: auto; }
  .invite-state { display: none; }
  .invite-retry { min-width: 0; }

  :deep(.mobile-hidden) {
    display: none !important;
  }
}

.add-host-choice-intro p {
  margin: 0 0 16px;
  color: var(--text-secondary);
  font-size: 13px;
}
.add-host-choice-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.add-host-choice-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel);
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  outline: none;
  user-select: none;
}
.add-host-choice-card:hover,
.add-host-choice-card:focus-visible {
  border-color: var(--accent-blue, #3b82f6);
  background: color-mix(in srgb, var(--accent-blue, #3b82f6) 6%, var(--surface-panel));
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.12);
  transform: translateY(-1px);
}
.choice-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 10px;
  flex-shrink: 0;
}
.choice-card--enrollment .choice-card-icon {
  color: #3b82f6;
  background: color-mix(in srgb, #3b82f6 12%, transparent);
}
.choice-card--manual .choice-card-icon {
  color: #10b981;
  background: color-mix(in srgb, #10b981 12%, transparent);
}
.choice-card-body {
  flex: 1;
  min-width: 0;
}
.choice-card-body h4 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
}
.choice-card-body p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}
.choice-card-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease, color 0.2s ease;
}
.add-host-choice-card:hover .choice-card-arrow {
  color: var(--accent-blue, #3b82f6);
  transform: translateX(3px);
}
</style>

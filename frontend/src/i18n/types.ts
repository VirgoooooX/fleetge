/**
 * i18n translation key type definitions.
 * Every key in zh-CN.json must have a corresponding entry here.
 */

export interface I18nSchema {
  // ── Nav / Shell ────────────────────────────────────────────
  "nav.dashboard": string;
  "nav.updates": string;
  "nav.audit": string;
  "nav.hosts": string;
  "nav.hostsSection": string;
  "nav.settings": string;
  "shell.kicker": string;
  "shell.onlineCount": string;
  "shell.updateCount": string;
  "shell.refresh": string;
  "shell.logout": string;
  "shell.switchLight": string;
  "shell.switchDark": string;

  // ── Login ──────────────────────────────────────────────────
  "login.kicker": string;
  "login.title": string;
  "login.subtitle": string;
  "login.username": string;
  "login.password": string;
  "login.submit": string;
  "login.usernameRequired": string;
  "login.passwordRequired": string;
  "login.tooManyAttempts": string;
  "login.invalidCredentials": string;

  // ── Dashboard ──────────────────────────────────────────────
  "dashboard.kicker": string;
  "dashboard.title": string;
  "dashboard.description": string;
  "dashboard.onlineHosts": string;
  "dashboard.runningContainers": string;
  "dashboard.stoppedContainers": string;
  "dashboard.updatableImages": string;
  "dashboard.running": string;
  "dashboard.stopped": string;
  "dashboard.updates": string;
  "dashboard.noHosts": string;

  // ── Host Detail ────────────────────────────────────────────
  "hostDetail.metricsUnavailable": string;
  "hostDetail.memory": string;
  "hostDetail.disk": string;
  "hostDetail.load": string;
  "hostDetail.uptime": string;
  "hostDetail.network": string;
  "hostDetail.diskIO": string;
  "hostDetail.days": string;
  "hostDetail.hours": string;
  "hostDetail.minutes": string;
  "hostDetail.justRestarted": string;

  // ── Host Card ──────────────────────────────────────────────
  "hostCard.updates": string;
  "hostCard.metricsUnavailable": string;
  "hostCard.cpu": string;
  "hostCard.memory": string;
  "hostCard.disk": string;
  "hostCard.net": string;
  "hostCard.io": string;
  "hostCard.read": string;
  "hostCard.write": string;
  "hostCard.runningContainers": string;
  "hostCard.stoppedContainers": string;
  "hostCard.imageCount": string;
  "hostCard.dockerVersion": string;
  "hostCard.refreshIssue": string;

  // ── Container Table ────────────────────────────────────────
  "containerTable.name": string;
  "containerTable.image": string;
  "containerTable.status": string;
  "containerTable.ports": string;
  "containerTable.created": string;
  "containerTable.resources": string;

  // ── Container Stats ────────────────────────────────────────
  "containerStats.cpuUsage": string;
  "containerStats.memUsage": string;
  "containerStats.networkIO": string;

  // ── Status Icon ────────────────────────────────────────────
  "status.online": string;
  "status.offline": string;
  "status.degraded": string;
  "status.unknown": string;

  // ── Stack Actions ──────────────────────────────────────────
  "stack.action.start": string;
  "stack.action.stop": string;
  "stack.action.down": string;
  "stack.action.restart": string;
  "stack.action.update": string;
  "stack.action.startStack": string;
  "stack.action.stopStack": string;
  "stack.action.downStack": string;
  "stack.action.restartStack": string;
  "stack.action.updateStack": string;
  "stack.action.delete": string;
  "stack.action.deleteStack": string;
  "stack.delete.title": string;
  "stack.delete.message": string;
  "stack.delete.ok": string;
  "stack.delete.success": string;
  "stack.delete.failure": string;
  "stack.confirm.title": string;
  "stack.confirm.message": string;
  "stack.confirm.ok": string;
  "stack.confirm.cancel": string;
  "stack.confirm.cancelled": string;
  "stack.confirm.running": string;
  "stack.confirm.timeout": string;
  "stack.confirm.success": string;
  "stack.confirm.failure": string;
  "stack.confirm.unknownError": string;
  "stack.risk.start": string;
  "stack.risk.stop": string;
  "stack.risk.down": string;
  "stack.risk.restart": string;
  "stack.risk.update": string;

  // ── Stack Operation Dock ───────────────────────────────────
  "stackOp.starting": string;
  "stackOp.stopping": string;
  "stackOp.restarting": string;
  "stackOp.updating": string;
  "stackOp.deploying": string;
  "stackOp.pruning": string;
  "stackOp.deleting": string;
  "stackOp.serviceStarting": string;
  "stackOp.serviceStopping": string;
  "stackOp.serviceRestarting": string;
  "stackOp.operation": string;
  "stackOp.completed": string;
  "stackOp.failed": string;
  "stackOp.finished": string;
  "stackOp.copied": string;
  "stackOp.copy": string;
  "stackOp.copyFailed": string;
  "stackOp.waitingOutput": string;

  // ── Stack Status Labels ────────────────────────────────────
  "stackStatus.running": string;
  "stackStatus.exited": string;
  "stackStatus.stopped": string;
  "stackStatus.partial": string;
  "stackStatus.unknown": string;

  // ── Update Badge ───────────────────────────────────────────
  "update.status.upToDate": string;
  "update.status.updatable": string;
  "update.status.needsAuth": string;
  "update.status.checkFailed": string;
  "update.hint.rateLimited": string;
  "update.status.rateLimited": string;
  "update.hint.upToDate": string;
  "update.hint.updatable": string;
  "update.hint.needsAuth": string;
  "update.hint.checkFailed": string;

  // ── Updates View ───────────────────────────────────────────
  "updates.kicker": string;
  "updates.title": string;
  "updates.back": string;
  "updates.checkNow": string;
  "updates.checking": string;
  "updates.host": string;
  "updates.image": string;
  "updates.status": string;
  "updates.currentDigest": string;
  "updates.registryDigest": string;
  "updates.runningTitle": string;
  "updates.runningDesc": string;
  "updates.noResults": string;

  // ── Audit View ─────────────────────────────────────────────
  "audit.kicker": string;
  "audit.title": string;
  "audit.back": string;
  "audit.time": string;
  "audit.user": string;
  "audit.action": string;
  "audit.host": string;
  "audit.stack": string;
  "audit.result": string;
  "audit.ip": string;
  "audit.detail": string;
  "audit.success": string;
  "audit.failure": string;
  "audit.noRecords": string;
  "audit.action.stack.start": string;
  "audit.action.stack.stop": string;
  "audit.action.stack.down": string;
  "audit.action.stack.restart": string;
  "audit.action.stack.update": string;
  "audit.action.stack.delete": string;
  "audit.action.stack.serviceStart": string;
  "audit.action.stack.serviceStop": string;
  "audit.action.stack.serviceRestart": string;
  "audit.action.stack.composeSave": string;
  "audit.action.stack.composeDeploy": string;
  "audit.action.updateChecksRun": string;

  // ── Host Stack Workspace ───────────────────────────────────
  "workspace.newStack": string;
  "workspace.recheckUpdates": string;
  "workspace.searchPlaceholder": string;
  "workspace.loadingStructure": string;
  "workspace.allStacks": string;
  "workspace.stacksKicker": string;
  "workspace.allStacksTitle": string;
  "workspace.stacksCount": string;
  "workspace.runningCount": string;
  "workspace.running": string;
  "workspace.stackManaged": string;
  "workspace.stackDeployed": string;
  "workspace.stackFileOnly": string;
  "workspace.stackUnmanaged": string;
  "workspace.editCompose": string;
  "workspace.viewDetail": string;
  "workspace.pruneDocker": string;
  "workspace.pruneConfirm": string;
  "workspace.pruneMessage": string;
  "workspace.updateAll": string;
  "workspace.updateAllConfirm": string;
  "workspace.updateAllMessage": string;
  "workspace.updateAllSuccess": string;
  "workspace.updateAllPartial": string;
  "workspace.serviceStart": string;
  "workspace.serviceStop": string;
  "workspace.serviceRestart": string;
  "workspace.noMatchingStack": string;
  "workspace.containerGroup": string;
  "workspace.containers": string;
  "workspace.noContainers": string;
  "workspace.terminal": string;
  "workspace.refresh": string;
  "workspace.loadingLogs": string;
  "workspace.noLogs": string;
  "workspace.containerDetail": string;
  "workspace.composePreview": string;
  "workspace.showCompose": string;
  "workspace.containerId": string;
  "workspace.containerStatus": string;
  "workspace.containerImage": string;
  "workspace.containerPorts": string;
  "workspace.containerMemory": string;
  "workspace.runtime": string;
  "workspace.restart": string;
  "workspace.restarts": string;
  "workspace.networkMode": string;
  "workspace.privileged": string;
  "workspace.user": string;
  "workspace.workdir": string;
  "workspace.command": string;
  "workspace.networks": string;
  "workspace.mounts": string;
  "workspace.repoDigests": string;
  "workspace.labels": string;
  "workspace.loadingCompose": string;
  "workspace.noComposeFromAgent": string;
  "workspace.composeLoadFailed": string;
  "workspace.yes": string;
  "workspace.no": string;
  "workspace.default": string;

  // ── Compose Drawer ─────────────────────────────────────────
  "compose.kicker": string;
  "compose.stackNamePlaceholder": string;
  "compose.managedByStackService": string;
  "compose.close": string;
  "compose.saveDraft": string;
  "compose.saveAndDeploy": string;
  "compose.emptyNameAlert": string;
  "compose.invalidNameAlert": string;
  "compose.emptyYamlAlert": string;
  "compose.noComposeAlert": string;
  "compose.deployOutput": string;
  "compose.createAction": string;
  "compose.saveAction": string;
  "compose.confirmDeploy": string;
  "compose.confirmSave": string;
  "compose.confirmDeployTitle": string;
  "compose.confirmSaveTitle": string;
  "compose.cancel": string;
  "compose.saving": string;
  "compose.deploying": string;
  "compose.draftSaved": string;
  "compose.draftCreated": string;
  "compose.saveFailed": string;
  "compose.deployedAndSaved": string;
  "compose.createdAndDeployed": string;
  "compose.deploySuccess": string;
  "compose.deployFailed": string;
  "compose.deployTimeout": string;
  "compose.deployCompleted": string;
  "compose.unknownError": string;
  "compose.nameRequired": string;
  "compose.nameInvalid": string;
  "compose.readFailed": string;

  // ── Log Drawer ─────────────────────────────────────────────
  "log.title": string;
  "log.refresh": string;
  "log.lines": string;
  "log.loading": string;
  "log.noLogs": string;

  // ── Terminal Drawer ────────────────────────────────────────
  "terminal.title": string;
  "terminal.copied": string;
  "terminal.copyOutput": string;
  "terminal.copyFailed": string;

  // ── Stack Group ────────────────────────────────────────────
  "stackGroup.running": string;
  "stackGroup.openApp": string;
  "stackGroup.editCompose": string;
  "stackGroup.viewLogs": string;
  "stackGroup.viewOutput": string;
  "stackGroup.terminalTitle": string;

  // ── SSE / Network ──────────────────────────────────────────
  "sse.streamNotSupported": string;
}

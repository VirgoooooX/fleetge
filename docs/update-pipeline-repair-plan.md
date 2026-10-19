# Fleetge 更新链路修复计划与开发指导

状态：待实施。本文保存方案，不代表相关功能已经修复。

适用基线：当前工作区 v1.6.2。NAS 上实际运行的 App、Agent 版本及部署内容，需要在后续部署前另行核实。

## 1. 目标与已确认的决策

本次修复围绕四个实际问题展开：

1. 手动单次和批量更新由后端独立执行，离开页面、切换主机、刷新或关闭浏览器不会取消升级。
2. 批量更新固定提交时的主机和 Stack 列表，正确处理失败、未知结果、重复提交和停止剩余项目。
3. 正确区分远程镜像、本地标签指向的镜像和运行容器使用的镜像，解决多架构摘要误判及只拉取未重建的问题。
4. 前端状态、运行记录、审计和通知使用同一个最终执行结论，消除假成功。

用户已确认：

- 批量遇到明确失败后继续处理其他 Stack；遇到结果未知时停止该批次剩余项目。
- 批量跳过 Fleetge／Agent 自身所在的 Stack，并明确显示原因；自身更新保留单独入口。
- 遵循最小必要变更，复用已有组件和执行能力，避免过度设计。

本轮默认边界：

- 后台执行保证覆盖浏览器和页面的生命周期，不承诺后端进程重启后自动续跑。
- 后端重启后，运行中的记录标为 `uncertain`，尚未执行的记录标为 `skipped`；不自动重放更新命令。
- 不引入 Redis、Celery、消息中间件、通用工作流引擎或新的任务表。
- 不增加自动回滚，不自动修改用户 Compose 中的镜像标签或固定摘要。
- 不改造启动、停止、重启、删除、清理等非更新操作的整体执行模型；仅补充必要的互斥保护。
- 不新增应用 HTTP 探活配置。已有 Docker healthcheck 继续作为健康验证依据。

## 2. 已确认的问题与依据

| 问题 | 源码依据 | 实际影响 |
| --- | --- | --- |
| 手动更新依赖页面连接 | `frontend/src/components/StackActions.vue` 卸载时 abort；`backend/app/routers/stacks.py` 在流结束时取消任务；`fleetge-agent/compose_runner.py` 在连接异常时终止命令 | 切页可能打断 pull 或 up，留下部分完成状态 |
| 批量更新由浏览器循环调度 | `HostStackWorkspace.vue` 的 `confirmUpdateAll`、`runStackUpdate` | 页面消失后批次不可靠；中断当前项后仍可能发起下一项 |
| 批量没有固定主机 | `runStackUpdate` 每次读取 `props.hostId` | 已隔离复现第一项发往 host-a，切换后第二项发往 host-b |
| 缺少最终结果仍算成功 | 更新相关前端分支在流结束且未收到 complete 时兜底成功 | 批量成功数量和单次结果失真 |
| 检查本地标签代替运行版本 | `backend/app/services/snapshot.py` 优先使用 `tag_image_id`，RepoDigests 来自标签 inspect | 已复现容器仍运行旧镜像，但检查显示 up_to_date |
| 摘要比较和最终验证不一致 | `update_check.py` 的多候选比较与 `finalize_stack_update` 的单个 RepoDigest 比较不同 | 已复现有效匹配存在但验证失败，缓存却已改为最新 |
| 平台不匹配时退到其他架构 | `_resolve_registry_digests_from_response` 的 amd64／首个平台回退 | 已复现请求 arm64 却选择 amd64 |
| 手动验证失败仍返回成功 | `_run_finalize` 只输出日志，不改变外层最终结果 | 已复现旧镜像验证失败，但 complete 和审计均为成功 |
| 自身更新审计无条件成功 | 自身更新流结束后的外层审计分支 | 已复现内层检查失败，外层仍写成功 |
| 整栈执行与验证范围不同 | 整栈 pull/up，仅验证原先标记 updatable 的镜像 | 已复现其他服务 unhealthy 时目标验证仍通过 |
| 一个 Stack 清除共享标签状态 | 镜像缓存按 host/image 共用 | 已复现 Stack A 更新后，仍运行旧镜像的 Stack B 被共同显示为最新 |
| 后台 Agent job 提前释放锁 | 启动后台任务后退出 WebSocket 的锁作用域 | 任务执行期间可能接受保存、删除或再次更新 |
| 自更新终态被交接端覆盖 | `_start_self_updater_container` 启动后再次写 handoff | 已复现 success 被覆盖回 handoff |
| 健康证据可能缺失 | 容器 inspect 失败后仍构建摘要，health 为空被视为无检查 | 这是源码确认的风险，尚未做 Docker 实机故障注入 |

已有验证基线：后端相关测试 68 项通过，Agent 相关测试 40 项通过，共 108 项。上述隔离复现说明现有测试缺少相应边界；通过基线测试不等于这些问题已经修复。复现未操作 NAS 的实际容器。

## 3. 最小实现结构

### 3.1 后端接管调度

扩展现有 `AutoUpdateManager`，继续使用每个主机一个 worker 的结构，不另建平行调度系统。

- 手动单次、批量和自动更新统一进入按主机串行的队列。
- 队列保存已经落库的运行记录 ID，不保存对页面对象、请求连接或可变前端参数的引用。
- 同一主机逐个执行，上一项完成验证后才启动下一项；不同主机沿用现有独立 worker。
- 对 queued 和 running 的 `(host_id, stack_name)` 一起去重，防止手动与自动更新重复执行同一个 Stack。
- 将现有普通 Stack 的升级与验证部分提取成共用执行函数，留在现有更新服务中；自动更新额外保留开关检查、确认规则和通知逻辑。
- worker 自行持有 AgentClient，并在执行结束后释放。浏览器断开只影响进度读取，不取消 worker，也不关闭它持有的 Agent 连接。
- 任务从服务生命周期启动，退出时统一清理，保留强引用并处理异常，不能通过无引用的 create_task 当作可靠后台执行。

### 3.2 保留并兼容旧 SSE 入口

新增后台提交与查询接口供当前前端使用。旧的 `POST /api/hosts/{host_id}/stacks/{stack_name}/update` 保留：

1. 在返回 StreamingResponse 之前提交后台运行记录。
2. SSE 只读取已有任务的日志与状态，继续输出原有 chunk、complete 事件。
3. SSE 断开不取消更新任务。
4. 只有验证通过才输出 `status: success`。失败、未知、跳过通过 outcome 和 message 给出真实含义，不以缺少结果推定成功。

其他非更新 action 暂时保留原执行方式，避免扩大改造范围。

### 3.3 Fleetge 自身更新

- 批量提交中识别并跳过控制 Stack，保留 skipped 记录和明确原因。
- 自动更新继续不处理控制 Stack。
- 手动单次自身更新沿用现有 Agent job／临时 updater；由后端后台任务跟踪，不由页面请求拥有执行生命周期。
- 控制端自身重启导致跟踪中断时，运行记录按既定边界标为 uncertain；Agent 任务保留实际结果供查看，不自动再次执行。

## 4. 数据与接口约定

### 4.1 复用现有运行表

复用 `AutoUpdateRun` / `auto_update_run`，不为了命名统一重建或重命名表。增加必要字段：

| 字段 | 用途 |
| --- | --- |
| `request_id`，可空并索引 | 同一次提交共用的 UUID；单次和自动更新也有自己的 request_id |
| `source`，默认 auto | auto、manual、bulk，历史记录按 auto 处理 |
| `requested_by`，默认 system | 用于最终审计；手动记录真实发起用户 |
| `log_tail`，Text | 已脱敏日志尾部，最多 6000 字符 |
| `targets_json`，Text，默认空对象 | 本次参与验证的服务、原实例数、镜像引用、平台和拉取后目标身份 |
| `agent_job_id`，可空 | 自身更新或已有 Agent job 的关联标识 |

沿用 attempts、stage、detail、started_at、finished_at、通知字段。日志最多每秒落库一次，阶段变化和任务结束立即刷新，不逐个输出块写数据库。

增加 `(host_id, request_id, stack_name)` 唯一索引，历史 request_id 为空的记录不受影响。新任务状态为：

- `queued`：已接受，等待执行。
- `running`：执行中，stage 为 preflight、pull、up、verify 等具体阶段。
- `success`：执行和必要验证均通过。
- `failed`：获得明确失败证据。
- `uncertain`：执行效果缺少必要证据或连接／进程中断。
- `skipped`：未执行，例如无需更新、停止剩余项目、控制 Stack 或 busy。

`auto_updates.py` 的 last_run 查询限定 source=auto，避免手动记录覆盖“上次自动更新”的历史。现有通知仍仅针对自动更新，不顺带新增手动通知功能；手动和批量也不改变自动更新开关。

### 4.2 新增接口

所有接口沿用现有认证规则。

**提交**：`POST /api/hosts/{host_id}/update-runs`

```json
{
  "request_id": "客户端为本次提交生成的 UUID",
  "mode": "bulk",
  "stack_names": ["homepage", "other-app"]
}
```

- mode 仅允许 manual、bulk；manual 只接受一个 Stack，auto 只能从服务内部提交。
- Stack 列表去重并保留提交顺序；服务端保存固定 host_id 和名称。
- 验证请求结构、主机和 Stack 存在性后，在同一事务中创建批次记录，再启动 worker，返回 HTTP 202。
- 同 request_id、相同主机、mode 和规范化列表的重试返回已有记录；参数不同返回 409。请求 ID 不能跨主机复用。
- 单次目标已 queued/running 时返回 409 并携带已有任务标识；批量中相同目标记录为 skipped/busy，不重复执行。
- 控制 Stack、停止状态或不可管理 Stack 在批量中记录 skipped，不静默丢弃。
- 提交超时后前端使用原 request_id 查询状态，不生成新请求 ID 盲目重发。

**查询批次**：`GET /api/hosts/{host_id}/update-runs/{request_id}`

返回固定主机、request_id、各项记录、阶段、日志尾部、原因、finished 布尔值，以及 queued/running/success/failed/uncertain/skipped 计数。批次汇总由明细计算，不另存一份批次状态。

**恢复页面状态**：`GET /api/hosts/{host_id}/update-runs`

返回该主机所有活动任务和最近 50 条终态记录。前端据此恢复当前任务及最近结果；需要完整批次时按 request_id 查询。

**停止剩余项目**：`POST /api/hosts/{host_id}/update-runs/{request_id}/stop-pending`

只把该批次尚未执行的项目改为 skipped，重复调用保持幂等。当前已经开始的 pull/up/verify 继续执行；不关闭 Agent 连接或杀 Docker 命令。

### 4.3 批量执行规则

- 普通 Stack 按提交顺序执行。
- preflight 重新检查可管理性、运行状态和目标，不依赖提交时的旧页面缓存。
- 明确失败：记录失败，继续下一项。
- 结果未知：保留当前项 uncertain，该批次其余 queued 项全部 skipped，原因说明上一项执行结果未确认。
- 无需更新、busy、已停止、不可管理、自身更新：明确跳过，并分别展示原因。
- 整批完成不主动再触发一次全局“检查更新”，避免全局检查意外入队其他自动更新；只刷新相关主机状态和必要缓存。

## 5. 镜像检查、执行和验证

### 5.1 统一镜像身份

在现有 RegistryDigests、UpdateCheckResult 和缓存字段上补充有类型的远程身份：

- registry_index_digest：多架构索引摘要。
- registry_manifest_digest：所选平台 manifest 摘要。
- registry_config_digest：镜像配置摘要，可与 Docker Image ID 比较。
- error_message：平台或身份解析失败的可读原因。

原 current_digest、registry_digest、matched_field 保留供兼容显示，但不再单独承担部署验证依据。

比较规则固定为：

1. 有目标 config digest 时，优先比较实际运行 Image ID 与 config digest；不能用一个相同的索引摘要掩盖 config 不同。
2. manifest 摘要只与同仓库、同平台的 manifest 证据比较；遍历全部有效 RepoDigests，不取第一条碰运气。
3. 索引摘要用于追溯和解析，不单独证明运行容器已更新。
4. 缺少同类可比较证据时返回检查失败／结果未确认，不能把不同种类摘要直接比较。
5. 按实际平台选择 manifest；同 OS、同架构允许现有必要的 variant 兼容，明确平台不存在时停止解析，禁止回退到 amd64 或其他架构。
6. 平台来源依次核对 Compose 显式配置、实际运行镜像、主机；无法确认时不默认猜 amd64。

### 5.2 运行镜像与本地标签分开读取

调整 snapshot 镜像采集：

- 按容器实际 image_id inspect，取得运行镜像的 RepoDigests 和完整平台；repo_digests 的语义统一为运行镜像证据。
- 标签 inspect 继续独立提供 tag_image_id、tag_platform，供判断“已下载但未部署”。
- 同标签存在不同运行 Image ID 时不能合并成一个“最新”的本地身份；远程查询按镜像和平台复用，本地判定逐个容器进行。
- 主机镜像状态按所有相关实例汇总：只要仍有旧实例，就保留待更新状态；一个 Stack 的验证不能清除其他 Stack 的待更新标记。
- 健康和版本状态分别表达：镜像同版本不自动等于部署成功，任务结果必须独立验证健康。

继续使用 host/image 作为现有缓存的汇总键，不扩张成新的部署状态表。各服务与实例的部署状态由运行快照和本次验证结果计算。

### 5.3 在 pull 与 up 之间记录目标

为避免验证时追着可变标签猜测，本次更新在 Agent 中增加少量目标元数据，复用已有 update action：

1. 后端 preflight 固定本次应验证的原运行 Compose 服务及实例数，排除 one-off 容器。
2. Agent pull 成功后、up 之前，使用与实际命令相同的 Compose 配置和 env 参数，获取相关服务的有效镜像引用及 platform。
3. 对这些镜像读取本地 Image ID、RepoDigests、平台，记录为 pulled_images。
4. 目标身份无法读取时不进入 up，返回明确阶段和错误；不启动一轮缺少验证目标的重建。
5. 成功后随 exit 返回 stage、up_executed、pulled_images；AgentClient 原样保留这些元数据。已有 job 写入同一结构，自身 updater 也使用相同目标字段。

只共享这一小段身份采集逻辑，不建立通用执行器框架。同步 updater 与异步 Agent 可通过一个小型标准库 helper 复用，不新增依赖。Compose 插值、env 和 profiles 继续交给 Docker Compose，不自行实现 YAML 解释器。

镜像引用与目标身份存入 targets_json；不保存 env、凭证或完整 Compose 文本。旧 Agent 没有 pulled_images 时，仅在新鲜的同平台 Registry 身份和运行证据足以证明结果时通过验证，否则标为 uncertain，不以缺字段假定成功。

### 5.4 最终成功条件

普通更新流程统一为：

```text
preflight → pull → 记录目标镜像 → up → 新鲜快照 → 验证 → 写入最终结果
```

success 必须同时满足：

- Agent 获得明确的命令结果，确实执行了 up。
- 取得完成于命令之后的新鲜容器快照。
- 本次参与更新的所有服务都存在，实例数没有低于更新前的应运行数量。
- 所有目标实例都使用相应的目标 Image ID／同平台身份。
- 容器处于 running；配置了 healthcheck 的容器为 healthy。
- 验证目标覆盖整栈更新的所有参与服务，不只覆盖原先带 updatable 标签的镜像。

验证采用 180 秒总等待上限、2 秒刷新间隔，不新增可调配置。明确失败按 failed 处理；必要 inspect 信息缺失、无法获得新鲜快照、目标身份不明或超时仍不能确认健康时按 uncertain 处理。没有配置 healthcheck 与读取 healthcheck 失败必须区分，增加必要的采集完整性标志。

容器列表、inspect 和镜像身份采集完成后再推进 containers_updated，不能提前更新时间戳。刷新失败不得把旧快照当作本次更新证据。

Registry 的补充确认只能返回证据，不能在最终验证完成之前顺手改写部署结论。确需更新远程检查缓存时，保留清晰的类型和失败信息；UI、审计和任务结论始终读取统一的运行结果。

显式 up_executed=false 记为 skipped；EOF、超时和缺少终态都不等于成功。现有“明确 pull 失败等待 10 秒后最多再试一次”的策略保留在共用执行函数里；up 失败和未知结果不自动重试。

## 6. Agent 并发与自身更新修复

- 普通 update 仍通过后端持有的连接执行，Stack 锁覆盖 pull、目标采集和 up。
- 保存 Compose／env、删除和执行命令使用相同 Stack 互斥检查；global.env 保存遇到相关活动更新时返回 busy，避免更新中改变命令配置。
- 后台 updateServicesJob 从排队到结束保留活动 job 占用；命令端除检查 asyncio 锁外，还检查该 Stack 的非终态 job，避免后台任务尚未拿锁时插入其他操作。
- 自更新交接后仍以现有 job 文件保留占用，新 Agent 启动时先核对关联 updater 容器是否仍运行。仍运行则保持占用；已不在运行且没有明确终态时标为 uncertain，不自动重放。
- 自更新启动端在 docker run 前写 handoff；启动后只补充容器标识等元数据，不再覆写 status/phase。执行端负责推进阶段，终态不能退回 queued/running/handoff。
- job 捕获异常、设置命令超时并回收自己启动的子进程；pull 失败与 up 执行效果未知分别记录，不能永久挂在 running。
- Agent job 的 success 表示命令成功；Dashboard 的最终 success 还必须经过统一的运行镜像与健康验证。

## 7. 前端行为与接入

复用 dashboard store、现有工作区和 StackOperationDock，不新建任务中心页面。

- 单次和批量更新均改为提交后台任务；删除浏览器逐个 POST 更新的循环。
- dashboard store 按 `(host_id, request_id)` 保存跟踪信息，Stack 操作键使用 `(host_id, stack_name)`，避免不同主机同名 Stack 串状态。
- 有已知活动任务时每 2 秒查询一次；轮询归 store 管理，页面卸载只解除该页面的监听。
- 页面切换、关闭终端面板、网络超时和浏览器关闭均不发停止请求。
- 刷新或重新进入主机工作区后查询活动任务和最近结果，恢复 running/queued 状态及日志尾部。
- 显示 queued、running、success、failed、uncertain、skipped；查询暂时失败显示“进度暂不可用，后台继续执行”，不能改成升级失败或成功。
- 单次已开始的升级不提供杀进程式取消；批量按钮使用“停止剩余项目”。终端关闭按钮只关闭查看。
- 批量汇总分别显示成功、失败、未知、跳过；控制 Stack 必须显示“请使用单独更新入口”。
- 更新后的状态刷新只影响对应主机。异步回调在展示前核对所属主机和任务，不能把旧主机结果写进新页面。
- 更新入口及兼容 SSE 分支都删除“没有收到 complete 就成功”的兜底。
- 中英文文案及现有类型定义一起更新，保留原有终端外观和滚动方式；不进行 UI 重设计。

## 8. 审计、通知与恢复

- 阶段日志、最终 DTO、审计和自动更新通知从同一个结构化结果生成，不分别推断成功。
- 记录 request_id、run ID、主机、Stack、发起用户、阶段、尝试次数、失败原因和脱敏日志尾部。
- 修复自身更新外层无条件写 success 的分支。
- 自动更新失败或 uncertain 后继续暂停开关并保留原因；手动重新开启时清空暂停原因，历史失败记录保留。
- 手动和批量不会隐式开启自动更新，也不改写用户的自动更新开关。
- 通知继续沿用现有可选配置、幂等 event key、重试和过期规则；通知失败不改变升级结果。
- 后端退出或重启不重放命令：running 记录 uncertain，queued 记录 skipped，说明需要重新检查后再次提交。

## 9. 数据迁移与兼容

沿用现有 SQLite 启动迁移方式，增加运行记录字段、镜像身份字段和必要索引。迁移必须可重复执行。

- source 为历史记录补默认 auto，其余新增字段允许缺失或给出明确默认值。
- 旧镜像缓存缺少有类型身份时视为需要重查；可保留历史展示，但不能作为自动执行的充分证据。
- 保留现有自动更新开关、暂停原因、通知配置及历史审计，不清库。
- 新前端使用新任务 API；旧 SSE 更新入口改成后台任务的订阅适配，避免缓存中的旧前端继续取消任务。
- App 和 Agent 的新增目标元数据采用可选协议字段；新后端对缺少证据的旧 Agent 明确报告 uncertain。
- 发布时同时包含 App 与 Agent；不只更新前端。

## 10. 实施顺序与代码落点

按依赖顺序实现，每步只做本次需求所需变更：

1. **统一结果与镜像身份**：修改 `backend/app/services/update_check.py`、`snapshot.py`、`schemas.py`；先补充已复现误判的回归，再修比较、运行镜像采集及验证。
2. **补充 Agent 目标证据与锁**：修改 `fleetge-agent/compose_runner.py`、`self_updater.py`，增加 pulled_images，修复后台 job 锁和交接终态覆盖；必要时只新增一个小型身份采集 helper，并核对 Dockerfile 打包。
3. **后端后台单次更新**：扩展 `auto_update.py` 和运行模型、迁移，把执行从请求生成器中移出；接入新接口和旧 SSE 适配；修改 `main.py` 生命周期。
4. **后端批量调度**：实现固定目标、提交去重、失败继续、未知停止、控制 Stack 跳过和 stop-pending。
5. **前端接入与恢复**：修改 `StackActions.vue`、`HostStackWorkspace.vue`、`stores/dashboard.ts`、`StackOperationDock.vue` 及相关类型和文案；删除旧批量循环和成功兜底。
6. **统一收尾**：调整 `routers/auto_updates.py` 的历史来源过滤，统一审计和通知结论，检查迁移与兼容路径。
7. **回归与发布检查**：运行必要测试、构建和隔离浏览器验证，修复发布脚本对 Agent 更新测试的遗漏和外部命令失败退出码检查。

开发时先读取当前文件和工作区状态；存在其他未提交修改时保留并合并，不覆盖。仓库有 `.codegraph/`，代码定位继续先用 CodeGraph，再按需搜索。

## 11. 测试与验收

继续使用现有 pytest、Vitest 和浏览器工具，不新增测试框架。单元与集成测试使用临时数据库和模拟 Registry／Agent；真实 Docker 验收使用隔离测试 Stack，不操作 NAS 的生产 Homepage。

### 后端执行与 API

- 提交后不消费 SSE，任务仍执行；订阅断开后任务继续，另一个客户端可查询结果。
- 同主机串行、不同主机独立；手动与自动提交同一 Stack 不重复执行。
- 相同 request_id 重试不重复创建／执行；不同参数返回 409。
- 批量第二项明确失败后第三项继续；第二项 uncertain 后剩余项 skipped。
- stop-pending 不终止当前项，只停止尚未启动的项目。
- 批量包含控制 Stack 时保留明确跳过项。
- 后端重启后不重放 running 或 queued 的命令。
- 手动记录不覆盖 last_run 自动更新历史，不新增手动通知。

### 镜像与最终验证

- OCI index、Docker manifest list、单平台 manifest 和 config digest 正确区分。
- RepoDigests 顺序、多个仓库关联摘要不改变结论。
- 明确请求平台不存在时不回退其他架构；必要的同架构 variant 兼容仍通过。
- 只 pull 未重建时仍识别旧运行镜像，不能显示部署成功。
- 两个 Stack 共用标签，只更新一个，另一个仍待更新。
- 同标签存在新旧实例时不能因其中一个匹配而全部显示最新。
- pull 后保存的目标与更新后运行 Image ID 一致才通过；缓存或标签变化不能代替该证据。
- 命令成功但旧镜像、其他参与服务 unhealthy、实例缺失时不报告完整成功。
- inspect 失败与没有 healthcheck 分开处理；健康从 starting 收敛到 healthy 时可通过，超时无法确认时为 uncertain。
- Registry 确认查询不会在最终判定前覆写部署结果。
- up_executed=false、连接 EOF、无最终结果均不计成功。

### Agent 与自身更新

- pull 失败不执行 up；目标身份采集失败不执行 up。
- 活动 job 阻止同时更新、保存 Compose／env 或删除同一 Stack。
- updater 快速完成时，success/error/uncertain 不被启动端改回 handoff。
- 后台任务异常或命令超时会形成终态，不永久 running。
- 旧 Agent 缺少新元数据时按真实证据处理，不误报成功。

### 前端与浏览器

- 单次更新时切页、切主机、刷新、关闭页面，任务继续；返回可恢复进度和结果。
- 批量开始后切换 host-a 到 host-b，所有已提交目标仍属于 host-a。
- 同名 Stack 在不同主机不串状态，重复点击不会重复执行。
- 缺少 complete、轮询失败、超时不计成功；批次各类计数准确。
- 关闭终端只停止查看；停止剩余项目不终止当前升级。
- 旧 SSE 调用断开后，新接口仍能查询到继续执行的任务。

必要检查命令：

```powershell
# 在 backend 目录
python -m pytest tests

# 在 fleetge-agent 目录
python -m pytest test_agent.py test_update_stage.py

# 在项目根目录
npm --prefix frontend test
npm --prefix frontend run build
```

发布脚本必须检查每条外部命令的退出码；任一必需测试或构建失败时不得继续创建发布提交／标签。Agent 发布检查必须包含 test_update_stage.py，不能只执行 test_agent.py。

## 12. 完成标准与交付

满足以下条件后才可认定修复完成：

1. 页面生命周期不再控制升级执行生命周期，普通单次和批量更新均可在后台完成。
2. 批量不会切错主机、重复执行或把断流当成功，用户选择的失败／未知策略得到验证。
3. 运行镜像身份、平台、实例范围和健康共同支持最终结果，前端、审计和自动通知一致。
4. Agent job 的并发保护和终态单向推进通过回归。
5. 旧库迁移、旧 SSE 入口与旧 Agent 的保守兼容通过验证。
6. 相关测试和前端构建通过，并完成隔离测试 Stack 的页面切换验收。

交付说明需要包含：具体行为变化、测试结果、兼容限制、App／Agent 发布范围，以及“后端重启后不自动续跑”的明确边界。文档保存本身不意味着已实施或已发布。

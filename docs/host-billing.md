# Host 套餐、续费与流量接口

所有接口复用 Dashboard 登录鉴权。套餐与通知状态保存在 Dashboard 数据库，Agent 无需升级。

## 配置入口

在「设置 → 主机管理 → 编辑主机 → 套餐、流量与告警」中维护套餐；流量重置日沿用主机的 `traffic_billing_day`。Notify Hub 设置中的套餐告警开关控制全部主机，各主机还可单独停用告警。

## API

| 方法与路径 | 行为 |
| --- | --- |
| `GET /api/hosts/{id}/subscription` | 返回套餐配置与 `configured`；没有配置时返回默认值 |
| `PUT /api/hosts/{id}/subscription` | 替换套餐配置；省略的字段恢复对应默认值 |
| `GET /api/hosts/{id}/billing` | 返回付款/到期日期、剩余天数、状态与 `recommendedNextPaymentDate` |
| `GET /api/hosts/{id}/traffic/quota?sync=true` | 同步账本后返回配额、周期、RX/TX 与完整性；`sync=false` 使用本地账本并读取当前流量 |
| `POST /api/hosts/{id}/renewal` | 保存用户确认的付款及实际到期日期 |
| `GET/PUT /api/admin/billing-alerts` | 读取或保存全局告警开关 `{ "enabled": true }` |

配置接口的字段、取值与校验规则见 `/api/docs` 的 `HostSubscriptionUpdate`。流量额度支持 `GB`、`TB`、`GiB`、`TiB`；方向为 `upload`（TX）、`download`（RX）、`both`（TX + RX）或 `max`（整个周期 RX/TX 累计值取较大者）。

## 续费确认

先通过账单接口读取建议日期，允许用户调整，确认后提交明确日期：

```json
{
  "paid_on": "2026-01-31",
  "next_payment_date": "2026-02-28",
  "service_expiry_date": "2027-01-31"
}
```

`paid_on` 可省略，此时按账单时区取当天。`next_payment_date` 字段必须提交，允许显式为 `null`，表示清除下次付款日期；一次性付款套餐保存为 `null`。`service_expiry_date` 必须由用户填写。付款和服务到期日期均不得早于确认付款日期。

建议日期只在查询时计算；保存时不会再次根据已有日期向后推进。同一组确认日期重复提交会保存相同结果。自动续费开关只记录状态。

## 计算结果与数据完整性

账单 `status`：`unconfigured`、`normal`、`expiring_soon`、`overdue`、`expired`。`paymentStatus`、`serviceStatus` 另行返回日期状态；未填日期时为 `not_scheduled`。

流量接口保留以下状态：

- `status`：`unconfigured`、`normal`、`over_quota`、`incomplete`。
- `coverageComplete`：本周期起点至统计时刻是否具有连续账本覆盖，包括当前未封账桶。缺少周期开始、中间或末尾数据时为 `false`。
- `hasGap`：已有账本缺口、当前 Agent 缺口或周期覆盖不完整。
- `estimated`：存在缺口、同步异常、持久化异常或过旧的采集样本时为 `true`。
- `collectionWarnings`、`syncError`、`currentError`、`cursorError`：保留异常原因。
- `overQuota`：独立表示已观察到的累计流量是否达到额度，可与 `incomplete` 同时存在。

未启用额度时仍返回 RX/TX 累计值；配额、剩余、已计费流量及百分比为 `null`。百分比保留两位小数供展示；告警按原始字节数比较阈值。每日聚合无法精确切分的 UTC 日边界按估算处理。结果用于管理与提醒，不等同于服务商账单。

## 后台通知

每日执行日期检查，每 45 分钟同步账本并检查 80%、90%、95%、100% 阈值，每分钟投递待发通知。日期检查可在对应提醒窗口补发，例如剩余 6 天且尚未通知时补发 7 天提醒。

事件 key、内容和重试状态先落库，再调用 Notify Hub；重试沿用同一 key，最多尝试 5 次，24 小时后停止补发。已被 Notify Hub 确认接收的事件重启后不再投递。

每次投递前核对日期、周期、额度与计费方向。已续费、跨周期或规则失效的待发事件取消；没有成功发送的取消事件可在相同条件再次成立时重新排队。额度提醒保留触发时的原始用量，避免忽略当前未封账桶已达到的阈值。未配置 Notify Hub 时不发送通知。

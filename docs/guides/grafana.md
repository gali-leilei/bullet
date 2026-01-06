# Grafana 告警接入指南

本文档介绍如何将 Grafana 告警接入 Bullet 系统。

## 配置步骤

### 1. 创建联络点（Contact Point）

在 Grafana 中配置一个 Webhook 联络点：

1. 进入 **Alerting → Contact points**
2. 点击 **Add contact point**
3. 选择 **Webhook** 类型
4. 配置 URL：
   ```
   http://your-bullet-server/webhook/{namespace_slug}/{project_id}?source=grafana
   ```
   - `namespace_slug`：Bullet 中的命名空间 slug
   - `project_id`：Bullet 中的项目 ID
5. 保存

### 2. 配置通知策略（Notification Policy）

1. 进入 **Alerting → Notification policies**
2. 配置默认或特定标签的通知策略，指向上面创建的联络点

### 3. 创建告警规则（Alert Rule）

在告警规则中配置 labels，Bullet 会自动解析这些信息。

## 告警字段映射

Bullet 从 Grafana 告警 payload 中提取以下字段：

| Bullet 字段 | Grafana 来源 | 默认值 |
|-------------|-------------|--------|
| `title` | `labels.alertname` | `"Unknown"` |
| `severity` | `labels.severity` | `"warning"` |
| `description` | `annotations.description` | `""` |
| `summary` | `annotations.summary` | `""` |

## 配置告警严重程度（Severity）

`severity` 用于标识告警的严重程度，在**告警规则**上配置，不是在联络点上。

### 在 Grafana UI 中配置

1. 进入 **Alerting → Alert rules**
2. 编辑或创建告警规则
3. 在 **Labels** 部分添加：
   ```
   severity = critical
   ```
4. 保存

### 常见的 severity 值

| 值 | 含义 |
|----|------|
| `critical` | 紧急/严重 |
| `warning` | 警告 |
| `notice` | 提示 |
| `info` | 信息 |

你可以根据需要自定义其他值。

### 示例：不同告警规则配置不同 severity

```
告警规则 A（CPU 高）       → labels: { severity: "warning" }
告警规则 B（磁盘满了）     → labels: { severity: "critical" }
告警规则 C（服务健康检查） → labels: { severity: "notice" }
```

所有告警都发送到同一个联络点，Bullet 会从 payload 中解析出各自的 severity：

```
┌─────────────────────┐
│  告警规则 A         │──┐
│  severity: warning  │  │
└─────────────────────┘  │
                         │    ┌─────────────┐    ┌─────────────┐
┌─────────────────────┐  ├───▶│  联络点     │───▶│   Bullet    │
│  告警规则 B         │──┤    │  (webhook)  │    │             │
│  severity: critical │  │    └─────────────┘    └─────────────┘
└─────────────────────┘  │
                         │
┌─────────────────────┐  │
│  告警规则 C         │──┘
│  severity: notice   │
└─────────────────────┘
```

## 自动解决工单

当 Grafana 告警恢复（resolved）时，会自动发送 `status: "resolved"` 的 webhook。Bullet 收到后会自动将该项目下所有 `pending` 状态的工单标记为已解决。

## Grafana Webhook Payload 示例

```json
{
  "status": "firing",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "HighCPUUsage",
        "severity": "critical",
        "instance": "server-1"
      },
      "annotations": {
        "summary": "CPU 使用率过高",
        "description": "服务器 server-1 的 CPU 使用率超过 90%"
      },
      "startsAt": "2024-01-15T10:00:00Z",
      "endsAt": "0001-01-01T00:00:00Z",
      "generatorURL": "http://grafana/alerting/...",
      "fingerprint": "abc123"
    }
  ],
  "commonLabels": {
    "alertname": "HighCPUUsage",
    "severity": "critical"
  },
  "externalURL": "http://grafana/",
  "receiver": "bullet-webhook"
}
```


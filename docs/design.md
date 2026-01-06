# Bullet 系统设计文档

Bullet 是一个报警 Tickets 管理平台，专注于 OnCall 和 Duty 场景。支持接收各类监控系统告警、多渠道通知分发、升级策略、值班响应和告警生命周期管理。

## 平台定位

**核心场景**：报警接收 → 通知 → 响应 → 升级 → 解决

**支持的告警源**：
- Grafana Unified Alerting
- Prometheus Alertmanager
- 自定义 Webhook

**类似产品**：PagerDuty、OpsGenie

## 核心概念

### 数据模型关系

```
Namespace (命名空间)
    └── Project (项目)
            └── binds → NotificationGroup[] (通知组列表，有序)
            └── uses → NotificationTemplate (通知模板)

NotificationGroup (通知组) - 全局资源
    └── ChannelConfig[] (渠道配置)
            └── Contact[] (联系人)

NotificationTemplate (通知模板) - 全局资源
    └── feishu_card (飞书卡片 Jinja2 模板)
    └── email_subject/body (邮件模板)
    └── sms_message (短信模板)

Ticket (工单)
    └── belongs to → Project
    └── payload (原始数据)
    └── parsed_data (解析后的结构化数据)
    └── events[] (事件时间线)
```

### 命名空间 (Namespace)

- 用于组织和隔离项目
- 每个命名空间有唯一的 slug，用于 Webhook URL
- 字段：`name`, `slug`, `description`

### 项目 (Project)

- 接收 Webhook 的目标
- 绑定有序的通知组列表，定义升级路径
- Webhook URL 格式：`/webhook/{namespace_slug}/{project_id}?source=grafana`

**字段：**
- `namespace_id` - 所属命名空间
- `name`, `description`
- `notification_group_ids` - 有序的通知组 ID 列表（升级路径）
- `notification_template_id` - 通知模板 ID（可选，默认使用 default 模板）
- `escalation_config` - 升级配置
  - `enabled` - 是否启用升级
  - `timeout_minutes` - 超时时间（分钟）
- `is_active` - 是否启用
- `silenced_until` - 静默截止时间
- `notify_on_ack` - 确认后是否发送通知给所有已通知的组

### 通知组 (NotificationGroup)

- **全局资源**，可被多个项目绑定
- 项目通过绑定通知组列表定义升级路径
- 列表顺序 = 升级顺序（索引 0 = 第一级，索引 1 = 第二级...）

**字段：**
- `name` - 唯一名称
- `description`
- `repeat_interval` - 未确认时重复发送间隔（分钟），可选值：`None`, `1`, `5`, `10`, `30`
- `channel_configs` - 渠道配置列表

### 渠道配置 (ChannelConfig)

- 定义通知发送方式和目标联系人
- 渠道类型：`feishu`, `email`, `sms`

**字段：**
- `type` - 渠道类型
- `contact_ids` - 联系人 ID 列表

### 联系人 (Contact)

- 通知目标的地址簿
- 不与系统用户关联

**字段：**
- `name`
- `phones` - 手机号列表（用于 SMS）
- `emails` - 邮箱列表（用于 Email）
- `feishu_webhook_url` - 飞书 Webhook Bot URL

### 通知模板 (NotificationTemplate)

- **全局资源**，可被多个项目使用
- 使用 Jinja2 模板语法
- 支持内置模板（不可删除）和自定义模板

**字段：**
- `name` - 唯一名称（如 `default`, `grafana`, `my-custom`）
- `description`
- `is_builtin` - 是否为内置模板
- `feishu_card` - 飞书卡片 JSON 模板
- `email_subject` - 邮件主题模板
- `email_body` - 邮件正文 HTML 模板
- `sms_message` - 短信内容模板

**内置模板：**
- `default` - 默认通用模板
- `grafana` - Grafana 告警专用模板（展示告警详情、状态、链接）

### 工单 (Ticket)

- 每次 Webhook 调用创建一个工单
- 跟踪状态、升级历史、事件时间线

**状态：**
- `pending` - 待处理
- `escalated` - 已升级
- `acknowledged` - 已确认
- `resolved` - 已解决

**字段：**
- `project_id`, `source`
- `status`, `escalation_level`
- `payload` - 原始 Webhook 数据
- `parsed_data` - Source 解析器解析后的结构化数据（用于模板渲染）
- `labels`, `title`, `description`, `severity`
- `ack_token` - 确认令牌（用于回调链接）
- `acknowledged_at`, `acknowledged_by`
- `notification_count`, `last_notified_at`
- `events` - 事件时间线

## 事件时间线

每个工单记录完整的事件历史：

| 事件类型 | 说明 |
|---------|------|
| `created` | 工单创建 |
| `notified` | 发送通知（记录级别、通知组、成功/失败）|
| `notified_silenced` | 通知被静默跳过 |
| `repeated` | 重复发送通知 |
| `escalated` | 升级到下一级通知组 |
| `max_level_reached` | 到达最高级别，不再升级 |
| `acknowledged` | 工单被确认 |
| `resolved` | 工单被解决 |

## 升级流程

> ⚠️ **重要提示**：只有 **severity 为 `critical`** 的工单才能触发升级。其他级别的工单（如 warning、error、info 等）不会自动升级到下一通知组。

```
Project.notification_group_ids = ["groupA", "groupB", "groupC"]
                                     ↓          ↓          ↓
                                  index=0     index=1     index=2
                                 (level=1)   (level=2)   (level=3)

Ticket 创建 ──────────────────► 通知 groupA (level=1)
         │
         ▼ (timeout_minutes 后未确认 且 severity=critical)
升级 ─────────────────────────► 通知 groupB (level=2)
         │
         ▼ (timeout_minutes 后未确认 且 severity=critical)
升级 ─────────────────────────► 通知 groupC (level=3)
         │
         ▼ (无更多级别)
到达最高级别 ─────────────────► 停止升级（如有 repeat_interval 则继续重复）
```

### 重复通知

如果通知组配置了 `repeat_interval`：
- 在升级超时前，按间隔重复发送通知给当前通知组
- 到达最高级别后，继续按间隔重复发送

### 升级调度器

- 使用 APScheduler 定期检查（默认 60 秒）
- 检查所有启用升级策略的活跃项目
- 跳过被静默的项目
- 处理每个未确认的工单

## 静默功能

项目级别的静默控制：

- 静默期间仍接收 Webhook 并创建工单
- 但不发送任何通知（首次通知和升级通知）
- 静默到期后自动恢复

**支持的静默时长：**
- 5 分钟、10 分钟、15 分钟、30 分钟
- 1 小时、2 小时、6 小时、12 小时、24 小时

## 测试消息

项目详情页提供发送测试消息功能，用于验证通知配置是否正确：

- 填写测试告警内容（标题、描述、严重级别）
- 发送到项目的第一级通知组
- 使用项目配置的通知模板渲染
- 不创建实际工单，仅用于测试

**支持的严重级别：**
- `critical` - 严重
- `error` - 错误
- `warning` - 警告
- `info` - 信息
- `notice` - 通知

## 确认机制

工单可通过两种方式确认：

1. **WebUI 确认** - 登录后在工单详情页点击确认
   - 记录确认人为当前登录用户名
2. **回调链接确认** - 通过通知中嵌入的链接一键确认
   - URL 格式：`/ack/{ticket_id}?token={ack_token}`
   - 使用随机 token 验证（32 字节 `secrets.token_urlsafe`），无需登录
   - 支持响应格式：`redirect`, `json`, `html`
   - 记录确认人为"链接确认"

### 确认后通知

如果项目启用了 `notify_on_ack`，工单被确认后会向所有已通知过的通知组发送确认通知：
- 通知内容显示"已确认"状态和确认人
- 飞书卡片使用绿色主题
- 不显示"确认处理"按钮（已确认无需再确认）

## API 端点

### Webhook

```
POST /webhook/{namespace_slug}/{project_id}?source=grafana
```

接收报警并创建工单。

**响应状态：**
- `ok` - 工单创建并发送通知
- `silenced` - 工单创建但通知被静默
- `resolved` - 收到 resolved 状态，自动解决相关工单
- `ignored` - 项目被禁用

### 确认回调

```
GET /ack/{ticket_id}?token={ack_token}&format=redirect
```

通过链接确认工单。

## 技术栈

- **后端**: FastAPI + Beanie (MongoDB ODM)
- **数据库**: MongoDB
- **前端**: Jinja2 + htmx + Alpine.js + Tailwind CSS
- **调度**: APScheduler
- **认证**: Session-based (itsdangerous)

## 通知渠道

| 渠道 | 实现 | 联系人字段 |
|-----|------|-----------|
| 飞书 | FeishuChannel | `feishu_webhook_url` |
| 邮件 | ResendEmailChannel | `emails` |
| 短信 | TwilioSMSChannel | `phones` |

## 通知模板系统

### 模板变量

模板使用 Jinja2 语法，以下变量可在模板中使用：

| 变量 | 说明 | 示例 |
|------|------|------|
| `ticket.id` | 工单 ID | `678abc...` |
| `ticket.title` | 标题 | `CPU 使用率过高` |
| `ticket.description` | 描述 | `服务器负载超过阈值` |
| `ticket.severity` | 严重级别 | `critical` |
| `ticket.source` | 来源 | `grafana` |
| `ticket.labels` | 标签 | `{"env": "prod"}` |
| `source` | 来源类型 | `grafana` |
| `payload.*` | 原始 Webhook 数据 | 任意字段 |
| `parsed.*` | 解析后的结构化数据 | `parsed.alerts[0].labels.alertname` |
| `ack_url` | 确认回调链接 | `https://...` |
| `detail_url` | 工单详情链接 | `https://...` |
| `is_escalated` | 是否是升级通知 | `true` / `false` |
| `is_repeated` | 是否是重复通知 | `true` / `false` |
| `notification_count` | 当前通知次数（1起）| `3` |
| `notification_label` | 通知状态标签 | `已升级到 L2` / `第3次通知` |
| `is_ack_notification` | 是否是确认后通知 | `true` / `false` |
| `acknowledged_by_name` | 确认人名称 | `admin` / `链接确认` |

### Source 解析器

不同的 `source` 类型对应不同的解析器：

| Source | 解析器 | 说明 |
|--------|--------|------|
| `grafana` | GrafanaSource | 解析 Grafana Unified Alerting 格式 |
| `custom` | - | 无解析，直接使用原始 payload |

解析器将原始 payload 转换为结构化数据，存储在 `ticket.parsed_data` 中，供模板使用。

### 模板渲染流程

```
Webhook 接收 ──► Source 解析 ──► 保存到 Ticket.parsed_data
                                        │
                                        ▼
发送通知时 ◄── Jinja2 渲染 ◄── 获取项目模板 + 构建上下文
```

### 自定义过滤器

模板中可以使用以下自定义 Jinja2 过滤器：

| 过滤器 | 别名 | 说明 | 用法 |
|--------|------|------|------|
| `json_escape` | `je` | 转义 JSON 字符串中的特殊字符 | `{{ ticket.title\|je }}` |

**重要**: 在飞书卡片模板中，对于可能包含换行、引号等特殊字符的变量，必须使用 `|je` 过滤器转义，否则会导致 JSON 解析失败。

### Severity 颜色映射

内置模板根据 severity 级别自动变色（飞书卡片 header template 颜色）：

| Severity | 颜色 | 飞书 template 值 |
|----------|------|------------------|
| `critical` | 深红 | `carmine` |
| `error` | 红色 | `red` |
| `warning` | 黄色 | `yellow` |
| `info` | 蓝色 | `blue` |
| `notice` | 灰色 | `grey` |
| 其他/未设置 | 红色 | `red` |
| 已升级 | 橙色 | `orange` |
| 已恢复 | 绿色 | `green` |

### 飞书卡片模板示例

推荐使用飞书卡片 2.0 schema 格式：

```json
{
  "schema": "2.0",
  "header": {
    "title": {
      "tag": "plain_text",
      "content": "[待处理] {{ ticket.title|je }}"
    },
    "template": "red"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px",
    "elements": [
      {
        "tag": "markdown",
        "content": "<font color='grey'>告警内容</font>\\n{{ ticket.description|je }}"
      },
      {
        "tag": "hr"
      },
      {
        "tag": "column_set",
        "columns": [
          {
            "tag": "column",
            "width": "auto",
            "elements": [{
              "tag": "button",
              "text": {"tag": "plain_text", "content": "确认处理"},
              "type": "primary",
              "url": "{{ ack_url }}"
            }]
          }
        ]
      }
    ]
  }
}
```

**注意**: markdown 内容中的换行符需要写成 `\\n`（双反斜杠）。

## 配置项

环境变量（`.env`）：

```bash
# MongoDB
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=bullet

# Session
SECRET_KEY=your-secret-key
SESSION_COOKIE_NAME=bullet_session
SESSION_MAX_AGE=604800

# 初始管理员
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-password
ADMIN_EMAIL=admin@example.com

# 升级调度
ESCALATION_CHECK_INTERVAL=60

# 飞书（可选）
# 飞书 Webhook URL 配置在联系人中

# Resend 邮件（可选）
RESEND_API_KEY=
RESEND_FROM_EMAIL=

# Twilio SMS（可选）
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
```

## 待办事项

- [ ] 自动停止通知机制（最大通知次数/最大通知时长）
  - 目前只有一级且配置重复间隔时会永远重复发送
  - 当前靠静默功能或确认/解决来停止

- [ ] 项目级回调链接鉴权配置
  - 项目可配置 ack 回调链接是否需要登录鉴权
  - 需要鉴权时，点击链接后跳转登录页，登录后完成确认
  - 确认记录显示"xxx 通过回调链接确认"（xxx 为登录用户名）
  - 不需要鉴权时保持现有 token 验证方式，记录为"链接确认"


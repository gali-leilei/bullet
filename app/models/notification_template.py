"""NotificationTemplate model - customizable notification message templates."""

from datetime import datetime
from typing import Annotated

from beanie import Document, Indexed
from pydantic import Field


class NotificationTemplate(Document):
    """Notification template for customizing message format.

    Templates use Jinja2 syntax and have access to:
    - ticket: Ticket object (id, title, description, severity, source, labels, etc.)
    - payload: Raw webhook payload dict
    - parsed: Parsed data from source parser (e.g., Grafana alerts)
    - source: Source type string
    - ack_url: Acknowledgement callback URL
    - detail_url: Ticket detail page URL
    - is_escalated: Whether this is an escalation notification (bool)
    - is_repeated: Whether this is a repeat notification (bool)
    - notification_count: Current notification count (int, 1-based)
    - notification_label: Human-readable label like "第3次通知" or "已升级到 L2"
    """

    name: Annotated[str, Indexed(str, unique=True)]
    description: str = ""
    is_builtin: bool = False  # Built-in templates cannot be deleted

    # Channel-specific templates (Jinja2)
    feishu_card: str = ""  # Feishu card JSON template
    email_subject: str = ""
    email_body: str = ""
    sms_message: str = ""

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "notification_templates"
        use_state_management = True

    class Config:
        json_schema_extra = {
            "example": {
                "name": "default",
                "description": "Default notification template",
                "is_builtin": True,
                "feishu_card": '{"header": {"title": "{{ ticket.title }}"}}',
                "email_subject": "[{{ source }}] {{ ticket.title }}",
                "email_body": "{{ ticket.description }}",
                "sms_message": "[{{ source }}] {{ ticket.title }}",
            }
        }


# Built-in template definitions
BUILTIN_TEMPLATES = {
    "default": {
        "name": "default",
        "description": "默认通知模板",
        "is_builtin": True,
        "feishu_card": """{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "style": {
      "text_size": {
        "normal_v2": {
          "default": "normal",
          "pc": "normal",
          "mobile": "heading"
        }
      }
    }
  },
  "header": {
    "title": {
      "tag": "plain_text",
      "content": "[{% if is_ack_notification %}已确认{% elif is_escalated %}已升级{% elif is_repeated %}第{{ notification_count }}次{% else %}待处理{% endif %}] {{ (ticket.title or '新通知')|je }}"
    },
    "subtitle": {
      "tag": "plain_text",
      "content": "{% if is_ack_notification and acknowledged_by_name %}确认人: {{ acknowledged_by_name }}{% else %}来源: {{ source }}{% endif %}"
    },
    "template": "{% if is_ack_notification %}green{% elif is_escalated %}orange{% elif ticket.severity == 'critical' %}carmine{% elif ticket.severity == 'error' %}red{% elif ticket.severity == 'warning' %}yellow{% elif ticket.severity == 'info' %}blue{% elif ticket.severity == 'notice' %}grey{% else %}red{% endif %}",
    "icon": {
      "tag": "standard_icon",
      "token": "{% if is_ack_notification %}done_filled{% elif ticket.severity == 'critical' or ticket.severity == 'error' %}warning-hollow_filled{% elif ticket.severity == 'warning' %}info-circle_filled{% else %}bell_filled{% endif %}"
    },
    "padding": "12px 12px 12px 12px"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 12px 12px",
    "elements": [
      {% if is_ack_notification %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>确认人</font>\\n**{{ acknowledged_by_name or '未知' }}**",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>原通知</font>\\n{{ (ticket.title or ticket.description or '无描述')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {% else %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>通知内容</font>\\n{{ (ticket.description or '无描述')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {% endif %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>级别</font>\\n{{ (ticket.severity or 'info')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>通知状态</font>\\n第 {{ notification_count }} 次{% if is_escalated %} · 已升级至 L{{ ticket.escalation_level }}{% endif %}{% if is_repeated %} · 重复通知{% endif %}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {
        "tag": "hr"
      },
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {% if not is_ack_notification %}
          {
            "tag": "column",
            "width": "auto",
            "elements": [
              {
                "tag": "button",
                "text": {
                  "tag": "plain_text",
                  "content": "确认"
                },
                "type": "primary",
                "width": "default",
                "url": "{{ ack_url }}"
              }
            ],
            "vertical_align": "top"
          },
          {% endif %}
          {
            "tag": "column",
            "width": "auto",
            "elements": [
              {
                "tag": "button",
                "text": {
                  "tag": "plain_text",
                  "content": "查看详情"
                },
                "type": "default",
                "width": "default",
                "url": "{{ detail_url }}"
              }
            ],
            "vertical_align": "top"
          }
        ]
      },
      {
        "tag": "markdown",
        "content": "<font color='grey'>工单ID: {{ ticket.id }}</font>",
        "text_size": "notation"
      }
    ]
  }
}""",
        "email_subject": "[{{ source }}]{% if notification_label %} [{{ notification_label }}]{% endif %} {{ ticket.title or '新通知' }}",
        "email_body": """<h2>{{ ticket.title or '新通知' }}</h2>
{% if notification_label %}<p><strong>{{ notification_label }}</strong></p>{% endif %}
{% if is_ack_notification and acknowledged_by_name %}<p><strong>确认人:</strong> {{ acknowledged_by_name }}</p>{% endif %}
<p>{{ ticket.description or '无描述' }}</p>
<hr>
<p><strong>来源:</strong> {{ source }}</p>
<p><strong>级别:</strong> {{ ticket.severity or 'unknown' }}</p>
<p><strong>工单ID:</strong> {{ ticket.id }}</p>
{% if not is_ack_notification %}<p><strong>通知次数:</strong> {{ notification_count }}</p>{% endif %}
<p>
  {% if not is_ack_notification %}<a href="{{ ack_url }}">确认</a> | {% endif %}
  <a href="{{ detail_url }}">查看详情</a>
</p>""",
        "sms_message": "[{{ source }}]{% if notification_label %}[{{ notification_label }}]{% endif %} {{ ticket.title or '新通知' }}",
    },
    "grafana": {
        "name": "grafana",
        "description": "Grafana 告警专用模板",
        "is_builtin": True,
        "feishu_card": """{
  "schema": "2.0",
  "config": {
    "update_multi": true,
    "style": {
      "text_size": {
        "normal_v2": {
          "default": "normal",
          "pc": "normal",
          "mobile": "heading"
        }
      }
    }
  },
  "header": {
    "title": {
      "tag": "plain_text",
      "content": "[{% if is_ack_notification %}已确认{% elif is_escalated %}已升级{% elif is_repeated %}第{{ notification_count }}次{% elif parsed.status == 'resolved' %}已恢复{% else %}待处理{% endif %}] {{ (parsed.alerts[0].annotations.summary if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.summary else ticket.title or '告警通知')|je }}"
    },
    "subtitle": {
      "tag": "plain_text",
      "content": "{% if is_ack_notification and acknowledged_by_name %}确认人: {{ acknowledged_by_name }}{% else %}{{ (parsed.alerts[0].labels.alertname if parsed.alerts else '')|je }}{% endif %}"
    },
    "template": "{% set sev = parsed.alerts[0].labels.severity|lower if parsed.alerts and parsed.alerts[0].labels.severity else ticket.severity %}{% if is_ack_notification %}green{% elif parsed.status == 'resolved' %}green{% elif is_escalated %}orange{% elif sev == 'critical' %}carmine{% elif sev == 'error' %}red{% elif sev == 'warning' %}yellow{% elif sev == 'info' %}blue{% elif sev == 'notice' %}grey{% else %}red{% endif %}",
    "icon": {
      "tag": "standard_icon",
      "token": "{% set sev = parsed.alerts[0].labels.severity|lower if parsed.alerts and parsed.alerts[0].labels.severity else ticket.severity %}{% if is_ack_notification %}done_filled{% elif parsed.status == 'resolved' %}done_filled{% elif sev == 'critical' or sev == 'error' %}warning-hollow_filled{% elif sev == 'warning' %}info-circle_filled{% else %}bell_filled{% endif %}"
    },
    "padding": "12px 12px 12px 12px"
  },
  "body": {
    "direction": "vertical",
    "padding": "12px 12px 12px 12px",
    "elements": [
      {% if is_ack_notification %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>确认人</font>\\n**{{ acknowledged_by_name or '未知' }}**",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>告警规则</font>\\n{{ (parsed.alerts[0].labels.alertname if parsed.alerts else '无')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {% else %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>告警详情</font>\\n{{ (parsed.alerts[0].annotations.description if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.description else ticket.description or '无描述')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>告警规则</font>\\n{{ (parsed.alerts[0].labels.alertname if parsed.alerts else '无')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {% endif %}
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>告警级别</font>\\n{{ (parsed.alerts[0].labels.severity|upper if parsed.alerts and parsed.alerts[0].labels.severity else ticket.severity or 'unknown')|je }}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          },
          {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [
              {
                "tag": "markdown",
                "content": "<font color='grey'>通知状态</font>\\n第 {{ notification_count }} 次{% if is_escalated %} · 已升级至 L{{ ticket.escalation_level }}{% endif %}{% if is_repeated %} · 重复通知{% endif %}",
                "text_align": "left",
                "text_size": "normal_v2"
              }
            ],
            "vertical_spacing": "8px",
            "vertical_align": "top"
          }
        ]
      },
      {
        "tag": "hr"
      },
      {
        "tag": "column_set",
        "horizontal_spacing": "8px",
        "horizontal_align": "left",
        "columns": [
          {% if not is_ack_notification %}
          {
            "tag": "column",
            "width": "auto",
            "elements": [
              {
                "tag": "button",
                "text": {
                  "tag": "plain_text",
                  "content": "确认"
                },
                "type": "primary",
                "width": "default",
                "url": "{{ ack_url }}"
              }
            ],
            "vertical_align": "top"
          },
          {% endif %}
          {
            "tag": "column",
            "width": "auto",
            "elements": [
              {
                "tag": "button",
                "text": {
                  "tag": "plain_text",
                  "content": "查看详情"
                },
                "type": "default",
                "width": "default",
                "url": "{{ detail_url }}"
              }
            ],
            "vertical_align": "top"
          }
          {% if parsed.alerts and parsed.alerts[0].generatorURL %},
          {
            "tag": "column",
            "width": "auto",
            "elements": [
              {
                "tag": "button",
                "text": {
                  "tag": "plain_text",
                  "content": "Grafana"
                },
                "type": "default",
                "width": "default",
                "url": "{{ parsed.alerts[0].generatorURL }}"
              }
            ],
            "vertical_align": "top"
          }
          {% endif %}
        ]
      },
      {
        "tag": "markdown",
        "content": "<font color='grey'>工单ID: {{ ticket.id }}</font>",
        "text_size": "notation"
      }
    ]
  }
}""",
        "email_subject": "[Grafana]{% if notification_label %} [{{ notification_label }}]{% endif %} {{ '🔴' if parsed.status == 'firing' else '🟢' }} {{ parsed.alerts[0].annotations.summary if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.summary else ticket.title }}",
        "email_body": """<h2>{{ parsed.alerts[0].annotations.summary if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.summary else ticket.title }}</h2>
{% if notification_label %}<p><strong>{{ notification_label }}</strong></p>{% endif %}
{% if is_ack_notification and acknowledged_by_name %}<p><strong>确认人:</strong> {{ acknowledged_by_name }}</p>{% endif %}
<p><strong>状态:</strong> {% if is_ack_notification %}已确认{% else %}{{ parsed.status or 'unknown' }}{% endif %}</p>
<p><strong>告警规则:</strong> {{ parsed.alerts[0].labels.alertname if parsed.alerts else '-' }}</p>
{% if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.description %}
<p><strong>详情:</strong> {{ parsed.alerts[0].annotations.description }}</p>
{% endif %}
<hr>
<p><strong>级别:</strong> {{ parsed.alerts[0].labels.severity if parsed.alerts else ticket.severity or 'unknown' }}</p>
<p><strong>工单ID:</strong> {{ ticket.id }}</p>
{% if not is_ack_notification %}<p><strong>通知次数:</strong> {{ notification_count }}</p>{% endif %}
<p>
  {% if not is_ack_notification %}<a href="{{ ack_url }}">确认</a> | {% endif %}
  <a href="{{ detail_url }}">查看详情</a>
  {% if parsed.alerts and parsed.alerts[0].generatorURL %}
  | <a href="{{ parsed.alerts[0].generatorURL }}">Grafana</a>
  {% endif %}
</p>""",
        "sms_message": "[Grafana]{% if notification_label %}[{{ notification_label }}]{% endif %} {{ '🔴' if parsed.status == 'firing' else '🟢' }} {{ parsed.alerts[0].annotations.summary if parsed.alerts and parsed.alerts[0].annotations and parsed.alerts[0].annotations.summary else ticket.title }}",
    },
}

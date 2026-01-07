"""Aliyun PAI DLC task notification webhook parser."""

from datetime import datetime
from typing import Any

from app.models.alert import Alert, AlertGroup, AlertStatus
from app.sources.base import BaseSource


class AliyunSource(BaseSource):
    """Parser for Aliyun PAI DLC task notifications (Feishu post format)."""

    # Task statuses that indicate the job is complete/resolved
    RESOLVED_STATUSES = {"Succeeded", "Failed", "Stopped"}

    @property
    def name(self) -> str:
        return "aliyun_pai"

    def parse(self, payload: dict[str, Any]) -> AlertGroup:
        # Extract the post content from Feishu format
        post_content = payload.get("content", {}).get("post", {}).get("zh_cn", {})

        title = post_content.get("title", "Aliyun PAI Notification")
        content_items = post_content.get("content", [])

        # Parse structured content fields
        fields = self._parse_content_fields(content_items)

        task_name = fields.get("任务名称", "Unknown")
        task_id = fields.get("任务ID", "")
        task_status = fields.get("任务状态", "")
        start_time_str = fields.get("开始时间", "")
        workspace = fields.get("工作空间", "")
        region = fields.get("所属区域", "")
        creator = fields.get("创建者", "")
        creator_uid = fields.get("创建者UID", "")
        event = fields.get("相关事件", "")
        message = fields.get("消息内容", "")
        url = fields.get("_url", "")

        # Determine alert status based on task status
        alert_status = self._map_status(task_status)

        # Map task status to severity
        severity = self._map_severity(task_status)

        # Parse start time
        starts_at = self._parse_timestamp(start_time_str)

        # Build labels
        labels = {
            "task_name": task_name,
            "task_id": task_id,
            "task_status": task_status,
            "workspace": workspace,
            "region": region,
            "creator": creator,
        }
        # Filter out empty values
        labels = {k: v for k, v in labels.items() if v}

        # Build annotations
        annotations = {
            "event": event,
            "message": message,
            "creator_uid": creator_uid,
        }
        annotations = {k: v for k, v in annotations.items() if v}

        alert = Alert(
            source=self.name,
            status=alert_status,
            name=task_name,
            severity=severity,
            summary=f"{title}: {event}",
            description=message,
            labels=labels,
            annotations=annotations,
            starts_at=starts_at,
            ends_at=datetime.now() if alert_status == "resolved" else None,
            generator_url=url,
            fingerprint=task_id,
            raw=payload,
        )

        return AlertGroup(
            source=self.name,
            status=alert_status,
            alerts=[alert],
            labels=labels,
            external_url=url,
            receiver="",
            raw=payload,
        )

    def _parse_content_fields(self, content_items: list) -> dict[str, str]:
        """Parse Feishu post content items into key-value pairs."""
        fields: dict[str, str] = {}

        for item_list in content_items:
            if not item_list:
                continue

            for item in item_list:
                tag = item.get("tag", "")

                if tag == "text":
                    text = item.get("text", "")
                    # Parse "key：value" or "key： value" format
                    if "：" in text:
                        key, value = text.split("：", 1)
                        fields[key.strip()] = value.strip()
                    elif ":" in text:
                        key, value = text.split(":", 1)
                        fields[key.strip()] = value.strip()

                elif tag == "a":
                    # Store the URL from anchor tags
                    fields["_url"] = item.get("href", "")

        return fields

    def _parse_timestamp(self, ts_str: str) -> datetime:
        """Parse ISO 8601 timestamp string."""
        if not ts_str:
            return datetime.now()

        ts_str = ts_str.strip()
        try:
            return datetime.fromisoformat(ts_str)
        except ValueError:
            return datetime.now()

    def _map_severity(self, task_status: str) -> str:
        """Map Aliyun task status to alert severity."""
        severity_map = {
            "Failed": "critical",
            "Stopped": "warning",
            "Succeeded": "info",
            "Running": "info",
            "Queuing": "info",
            "EnvPreparing": "info",
        }
        return severity_map.get(task_status, "warning")

    def _map_status(self, task_status: str) -> AlertStatus:
        """Map Aliyun task status to alert status."""
        status_map: dict[str, AlertStatus] = {
            "Succeeded": "ignored",
            "Running": "ignored",
            "Queuing": "ignored",
            "EnvPreparing": "ignored",
            "": "ignored",
        }
        return status_map.get(task_status, "firing")

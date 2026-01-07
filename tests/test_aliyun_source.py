"""Unit tests for AliyunSource parser."""

import ast
from datetime import datetime
from pathlib import Path

import pytest

from app.sources.aliyun_pai import AliyunSource

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def load_payloads() -> dict[str, dict]:
    """Load test payloads from aliyun.jsonl, indexed by task status."""
    payloads = {}
    with open(ARTIFACTS_DIR / "aliyun.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            payload = ast.literal_eval(line)
            # Extract task status from payload
            content = payload["content"]["post"]["zh_cn"]["content"]
            for item_list in content:
                for item in item_list:
                    if item.get("tag") == "text" and "任务状态：" in item.get(
                        "text", ""
                    ):
                        status = item["text"].split("：")[1]
                        payloads[status] = payload
                        break
    return payloads


@pytest.fixture(scope="module")
def payloads() -> dict[str, dict]:
    """Load all test payloads from artifacts."""
    return load_payloads()


@pytest.fixture
def aliyun_source() -> AliyunSource:
    """Create an AliyunSource instance for testing."""
    return AliyunSource()


class TestAliyunSourceName:
    """Tests for the name property."""

    def test_name_returns_aliyun_pai(self, aliyun_source: AliyunSource):
        assert aliyun_source.name == "aliyun_pai"


class TestAliyunSourceParse:
    """Tests for the parse method."""

    def test_parse_running_task(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test parsing a running task notification."""
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        assert result.source == "aliyun_pai"
        assert result.status == "ignored"
        assert len(result.alerts) == 1

        alert = result.alerts[0]
        assert alert.name == "debug-webhook_clone"
        assert alert.status == "ignored"
        assert alert.severity == "info"
        assert alert.fingerprint == "dlc1gbd4p5lft9tx"
        assert "开始运行" in alert.summary
        assert alert.description == "任务已开始运行"
        assert alert.ends_at is None

    def test_parse_succeeded_task(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test parsing a succeeded task notification."""
        payload = payloads["Succeeded"]
        result = aliyun_source.parse(payload)

        assert result.status == "ignored"
        alert = result.alerts[0]
        assert alert.status == "ignored"
        assert alert.severity == "info"
        assert alert.ends_at is None

    def test_parse_queuing_task(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test parsing a queuing task notification."""
        payload = payloads["Queuing"]
        result = aliyun_source.parse(payload)

        assert result.status == "ignored"
        alert = result.alerts[0]
        assert alert.severity == "info"

    def test_parse_env_preparing_task(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test parsing an env preparing task notification."""
        payload = payloads["EnvPreparing"]
        result = aliyun_source.parse(payload)

        assert result.status == "ignored"
        alert = result.alerts[0]
        assert alert.severity == "info"

    def test_parse_labels(self, aliyun_source: AliyunSource, payloads: dict[str, dict]):
        """Test that labels are correctly extracted."""
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        alert = result.alerts[0]
        assert alert.labels["task_name"] == "debug-webhook_clone"
        assert alert.labels["task_id"] == "dlc1gbd4p5lft9tx"
        assert alert.labels["task_status"] == "Running"
        assert alert.labels["workspace"] == "pre_train"
        assert alert.labels["region"] == "ap-southeast-1"
        assert alert.labels["creator"] == "leilei"

    def test_parse_annotations(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test that annotations are correctly extracted."""
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        alert = result.alerts[0]
        assert alert.annotations["event"] == "开始运行"
        assert alert.annotations["message"] == "任务已开始运行"
        assert alert.annotations["creator_uid"] == "211790764591639068"

    def test_parse_url(self, aliyun_source: AliyunSource, payloads: dict[str, dict]):
        """Test that URL is correctly extracted."""
        expected_url = "https://pai.console.aliyun.com/?regionId=ap-southeast-1&workspaceId=249407#/job/detail?jobId=dlc1gbd4p5lft9tx&page=jobs"
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        assert result.external_url == expected_url
        assert result.alerts[0].generator_url == expected_url

    def test_parse_start_time(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test that start time is correctly parsed."""
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        alert = result.alerts[0]
        assert alert.starts_at.year == 2026
        assert alert.starts_at.month == 1
        assert alert.starts_at.day == 6
        assert alert.starts_at.hour == 15
        assert alert.starts_at.minute == 18

    def test_parse_raw_payload_preserved(
        self, aliyun_source: AliyunSource, payloads: dict[str, dict]
    ):
        """Test that raw payload is preserved."""
        payload = payloads["Running"]
        result = aliyun_source.parse(payload)

        assert result.raw == payload
        assert result.alerts[0].raw == payload

    def test_parse_empty_payload(self, aliyun_source: AliyunSource):
        """Test parsing an empty payload uses defaults."""
        result = aliyun_source.parse({})

        assert result.source == "aliyun_pai"
        assert result.status == "ignored"
        assert len(result.alerts) == 1
        alert = result.alerts[0]
        assert alert.name == "Unknown"
        assert alert.severity == "warning"  # default for unknown status

    def test_parse_partial_payload(self, aliyun_source: AliyunSource):
        """Test parsing a payload with missing fields."""
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": "DLC任务通知",
                        "content": [
                            [{"tag": "text", "text": "任务名称：test-job"}],
                            [{"tag": "text", "text": "任务状态：Running"}],
                        ],
                    }
                }
            },
        }
        result = aliyun_source.parse(payload)

        alert = result.alerts[0]
        assert alert.name == "test-job"
        assert alert.labels["task_name"] == "test-job"
        assert "task_id" not in alert.labels  # Empty values filtered out


class TestParseContentFields:
    """Tests for the _parse_content_fields method."""

    def test_parse_chinese_colon(self, aliyun_source: AliyunSource):
        """Test parsing with Chinese colon (：)."""
        content = [[{"tag": "text", "text": "任务名称：test-job"}]]
        result = aliyun_source._parse_content_fields(content)
        assert result["任务名称"] == "test-job"

    def test_parse_ascii_colon(self, aliyun_source: AliyunSource):
        """Test parsing with ASCII colon (:)."""
        content = [[{"tag": "text", "text": "task_name:test-job"}]]
        result = aliyun_source._parse_content_fields(content)
        assert result["task_name"] == "test-job"

    def test_parse_with_spaces(self, aliyun_source: AliyunSource):
        """Test parsing with spaces around values."""
        content = [[{"tag": "text", "text": "工作空间： pre_train"}]]
        result = aliyun_source._parse_content_fields(content)
        assert result["工作空间"] == "pre_train"

    def test_parse_anchor_tag(self, aliyun_source: AliyunSource):
        """Test parsing anchor tags for URL."""
        content = [[{"tag": "a", "text": "请查看", "href": "https://example.com"}]]
        result = aliyun_source._parse_content_fields(content)
        assert result["_url"] == "https://example.com"

    def test_parse_empty_content(self, aliyun_source: AliyunSource):
        """Test parsing empty content."""
        result = aliyun_source._parse_content_fields([])
        assert result == {}

    def test_parse_empty_item_list(self, aliyun_source: AliyunSource):
        """Test parsing with empty item lists."""
        content = [[], [{"tag": "text", "text": "key：value"}], []]
        result = aliyun_source._parse_content_fields(content)
        assert result["key"] == "value"

    def test_parse_value_with_colon(self, aliyun_source: AliyunSource):
        """Test parsing values that contain colons."""
        content = [[{"tag": "text", "text": "URL：https://example.com:8080/path"}]]
        result = aliyun_source._parse_content_fields(content)
        assert result["URL"] == "https://example.com:8080/path"


class TestParseTimestamp:
    """Tests for the _parse_timestamp method."""

    def test_parse_valid_timestamp(self, aliyun_source: AliyunSource):
        """Test parsing a valid ISO timestamp."""
        result = aliyun_source._parse_timestamp("2026-01-06T15:18:21+08:00")
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 6

    def test_parse_empty_timestamp(self, aliyun_source: AliyunSource):
        """Test parsing empty timestamp returns current time."""
        before = datetime.now()
        result = aliyun_source._parse_timestamp("")
        after = datetime.now()
        assert before <= result <= after

    def test_parse_invalid_timestamp(self, aliyun_source: AliyunSource):
        """Test parsing invalid timestamp returns current time."""
        before = datetime.now()
        result = aliyun_source._parse_timestamp("not-a-timestamp")
        after = datetime.now()
        assert before <= result <= after

    def test_parse_timestamp_with_whitespace(self, aliyun_source: AliyunSource):
        """Test parsing timestamp with surrounding whitespace."""
        result = aliyun_source._parse_timestamp(" 2026-01-06T15:18:21+08:00 ")
        assert result.year == 2026


class TestMapSeverity:
    """Tests for the _map_severity method."""

    def test_failed_is_critical(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("Failed") == "critical"

    def test_stopped_is_warning(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("Stopped") == "warning"

    def test_succeeded_is_info(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("Succeeded") == "info"

    def test_running_is_info(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("Running") == "info"

    def test_queuing_is_info(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("Queuing") == "info"

    def test_env_preparing_is_info(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("EnvPreparing") == "info"

    def test_unknown_status_is_warning(self, aliyun_source: AliyunSource):
        assert aliyun_source._map_severity("UnknownStatus") == "warning"
        assert aliyun_source._map_severity("") == "warning"

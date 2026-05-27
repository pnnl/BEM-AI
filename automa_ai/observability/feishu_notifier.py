from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from automa_ai.observability.notifier import AgentEvent, EventNotifier, NoOpEventNotifier

logger = logging.getLogger(__name__)

_TRUNCATE_LIMIT = 500
_DEFAULT_TIMEZONE = "Asia/Shanghai"
_AGENT_WEBHOOK_ENV_KEYS = {
    "orchestrator": ("Orchestrator Agent",),
    "planner": ("Planner Agent",),
    "simulation": ("Energy Simulation Agent", "Simulation Agent"),
    "output": ("Energy Output Agent", "Output Agent"),
    "template": ("Energy Model Generator Agent", "Template Agent"),
    "envelope": ("Energy Model Envelope Agent", "Envelope Agent"),
    "lighting": ("Energy Model Lighting Agent", "Lighting Agent"),
}
_AGENT_DISPLAY_NAMES = {
    "Orchestrator Agent": "编排代理",
    "Planner Agent": "规划代理",
    "Energy Simulation Agent": "能耗仿真代理",
    "Simulation Agent": "仿真代理",
    "Energy Output Agent": "结果提取代理",
    "Output Agent": "结果代理",
    "Energy Model Generator Agent": "能耗模型生成代理",
    "Template Agent": "模板代理",
    "Energy Model Envelope Agent": "围护结构代理",
    "Envelope Agent": "围护结构代理",
    "Energy Model Lighting Agent": "照明代理",
    "Lighting Agent": "照明代理",
}
_STATUS_DISPLAY_NAMES = {
    "submitted": "已提交",
    "working": "处理中",
    "input-required": "需要补充信息",
    "completed": "已完成",
    "failed": "失败",
    "canceled": "已取消",
}


def _truncate(value: Any, limit: int = _TRUNCATE_LIMIT) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _short_id(value: str | None, length: int = 8) -> str:
    if not value:
        return "-"
    return value[:length]


def _safe_md(value: Any, limit: int = _TRUNCATE_LIMIT) -> str:
    text = _truncate(value, limit)
    return text.replace("\n", "  \n")


def _display_agent_name(name: str | None) -> str:
    if not name:
        return "-"
    return _AGENT_DISPLAY_NAMES.get(name, name)


def _display_status(state: Any) -> str:
    text = str(state or "-")
    return _STATUS_DISPLAY_NAMES.get(text, text)


def _format_event_time(timestamp: str, timezone_name: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
        local_dt = dt.astimezone(ZoneInfo(timezone_name))
        return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return timestamp


def _compact_kv_lines(data: dict[str, Any], value_limit: int = 120) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            inner = ", ".join(
                f"{sub_key}={_truncate(sub_value, value_limit)}"
                for sub_key, sub_value in value.items()
            )
            lines.append(f"- **{key}**: {_safe_md(inner, value_limit)}")
        elif isinstance(value, list):
            joined = ", ".join(_truncate(item, value_limit) for item in value)
            lines.append(f"- **{key}**: {_safe_md(joined, value_limit)}")
        else:
            lines.append(f"- **{key}**: `{_truncate(value, value_limit)}`")
    return "\n".join(lines)


def _render_tasks(tasks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, task in enumerate(tasks, start=1):
        description = task.get("description") or task
        lines.append(f"{idx}. {_safe_md(description, 200)}")
    return "\n".join(lines)


def _build_note(event: AgentEvent, timezone_name: str) -> str:
    return (
        f"会话 `{_short_id(event.session_id)}` | "
        f"任务 `{_short_id(event.task_id)}` | "
        f"{_format_event_time(event.timestamp, timezone_name)}"
    )


def _should_skip_event(event: AgentEvent) -> bool:
    if event.event_type in {"agent_selected", "artifact_emitted"}:
        return True

    if event.event_type == "agent_status":
        state = event.metadata.get("state")
        status_message = str(event.metadata.get("status_message") or "").strip()
        if state == "working" and status_message in {"", "..."}:
            return True

    return False


def _build_card_content(event: AgentEvent, timezone_name: str) -> tuple[str, str, str] | None:
    note = _build_note(event, timezone_name)

    if event.event_type == "session_started":
        title = "工作流已启动"
        template = "blue"
        body = (
            f"**用户请求**  \n{_safe_md(event.metadata.get('query') or event.message, 300)}"
        )
        return title, template, f"{body}\n\n{note}"

    if event.event_type == "session_resumed":
        title = "工作流已恢复"
        template = "wathet"
        body = f"**新的用户输入**  \n{_safe_md(event.metadata.get('query') or event.message, 300)}"
        return title, template, f"{body}\n\n{note}"

    if event.event_type == "planner_tasks_generated":
        tasks = event.metadata.get("tasks") or []
        title = "规划代理已生成任务"
        template = "turquoise"
        body = _render_tasks(tasks) if tasks else _safe_md(event.message)
        return title, template, f"{body}\n\n{note}"

    if event.event_type == "agent_request_sent":
        title = f"任务已交给{_display_agent_name(event.target)}"
        template = "indigo"
        body_parts = [
            f"**来源**: `{_display_agent_name(event.source)}`",
            f"**目标**: `{_display_agent_name(event.target)}`",
            f"**任务**  \n{_safe_md(event.metadata.get('query') or event.message, 280)}",
        ]
        blackboard = event.metadata.get("blackboard")
        if isinstance(blackboard, dict) and blackboard:
            body_parts.append(
                f"**共享上下文**  \n{_compact_kv_lines(blackboard, 100)}"
            )
        return title, template, "\n\n".join(body_parts + [note])

    if event.event_type == "agent_status":
        state = event.metadata.get("state") or "-"
        status_message = event.metadata.get("status_message") or ""
        source_name = _display_agent_name(event.source)
        status_name = _display_status(state)
        if state == "input-required":
            title = f"{source_name}需要补充信息"
            template = "orange"
            body = (
                f"**状态**: `{status_name}`  \n"
                f"**提示**  \n{_safe_md(status_message or '代理需要更多信息。', 280)}"
            )
        elif state == "completed":
            title = f"{source_name}已完成"
            template = "green"
            body = f"**状态**: `{status_name}`"
            if status_message:
                body += f"  \n**详情**  \n{_safe_md(status_message, 240)}"
        else:
            title = f"{source_name}状态更新"
            template = "grey"
            body = f"**状态**: `{status_name}`"
            if status_message:
                body += f"  \n**详情**  \n{_safe_md(status_message, 240)}"
        return title, template, f"{body}\n\n{note}"

    if event.event_type == "blackboard_updated":
        delta = event.metadata.get("delta")
        title = "共享状态已更新"
        template = "purple"
        body = _compact_kv_lines(delta, 150) if isinstance(delta, dict) else _safe_md(event.message)
        return title, template, f"{body}\n\n{note}"

    if event.event_type == "workflow_completed":
        title = "工作流已完成"
        template = "green"
        body = f"**总结**  \n{_safe_md(event.metadata.get('summary') or event.message, 380)}"
        return title, template, f"{body}\n\n{note}"

    title = event.event_type.replace("_", " ").title()
    template = "grey"
    body = _safe_md(event.message, 300)
    if event.metadata:
        body = f"{body}\n\n{_compact_kv_lines(event.metadata, 120)}"
    return title, template, f"{body}\n\n{note}"


def build_feishu_payload(event: AgentEvent, timezone_name: str) -> dict[str, Any] | None:
    if _should_skip_event(event):
        return None

    card_content = _build_card_content(event, timezone_name)
    if card_content is None:
        return None

    title, template, body = card_content
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": body,
                    },
                }
            ],
        },
    }


@dataclass(slots=True)
class FeishuWebhookNotifier(EventNotifier):
    webhook_url: str
    webhook_secret: str | None = None
    timeout_seconds: float = 10.0
    timezone_name: str = _DEFAULT_TIMEZONE
    _seen_keys: set[tuple[str, str, str, str, str]] = field(default_factory=set)

    def _build_signature(self) -> dict[str, str]:
        if not self.webhook_secret:
            return {}

        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{self.webhook_secret}".encode("utf-8")
        signature = base64.b64encode(
            hmac.new(
                string_to_sign,
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return {"timestamp": timestamp, "sign": signature}

    def _dedupe_key(self, event: AgentEvent) -> tuple[str, str, str, str, str]:
        state = str(event.metadata.get("state") or "")
        message = str(
            event.metadata.get("status_message")
            or event.metadata.get("query")
            or event.message
            or ""
        )
        return (
            event.session_id or "",
            event.event_type,
            event.source,
            event.target or "",
            f"{state}:{message[:120]}",
        )

    async def emit(self, event: AgentEvent) -> None:
        dedupe_key = self._dedupe_key(event)
        if dedupe_key in self._seen_keys:
            return

        payload = build_feishu_payload(event, self.timezone_name)
        if payload is None:
            return

        self._seen_keys.add(dedupe_key)
        payload.update(self._build_signature())

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.webhook_url, json=payload)
                response.raise_for_status()
        except Exception:
            logger.exception(
                "Failed to publish event '%s' to Feishu webhook.",
                event.event_type,
            )


@dataclass(slots=True)
class FeishuWebhookRouter(EventNotifier):
    default_notifier: FeishuWebhookNotifier
    notifiers_by_agent: dict[str, FeishuWebhookNotifier]

    def _route_agent_name(self, event: AgentEvent) -> str | None:
        if event.event_type == "agent_request_sent" and event.target:
            return event.target
        return event.source or event.target

    async def emit(self, event: AgentEvent) -> None:
        agent_name = self._route_agent_name(event)
        notifier = self.notifiers_by_agent.get(agent_name or "")
        if notifier is None:
            notifier = self.default_notifier
        await notifier.emit(event)


def _build_agent_webhook_map(
    *,
    webhook_secret: str | None,
    timezone_name: str,
) -> dict[str, FeishuWebhookNotifier]:
    notifiers_by_agent: dict[str, FeishuWebhookNotifier] = {}
    for env_suffix, agent_names in _AGENT_WEBHOOK_ENV_KEYS.items():
        env_key = f"FEISHU_WEBHOOK_{env_suffix.upper()}"
        webhook_url = os.getenv(env_key, "").strip()
        if not webhook_url:
            continue

        notifier = FeishuWebhookNotifier(
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            timezone_name=timezone_name,
        )
        for agent_name in agent_names:
            notifiers_by_agent[agent_name] = notifier
    return notifiers_by_agent


def create_feishu_notifier_from_env() -> EventNotifier:
    enabled = os.getenv("FEISHU_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return NoOpEventNotifier()

    webhook_url = (
        os.getenv("FEISHU_WEBHOOK_DEFAULT", "").strip()
        or os.getenv("FEISHU_WEBHOOK_URL", "").strip()
        or os.getenv("FEISHU_WEBHOOK_ORCHESTRATOR", "").strip()
    )
    if not webhook_url:
        logger.warning(
            "FEISHU_ENABLED is set but no Feishu webhook URL is configured. Feishu notifications are disabled."
        )
        return NoOpEventNotifier()

    webhook_secret = os.getenv("FEISHU_WEBHOOK_SECRET", "").strip() or None
    timezone_name = (
        os.getenv("FEISHU_TIMEZONE", "").strip() or _DEFAULT_TIMEZONE
    )
    default_notifier = FeishuWebhookNotifier(
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        timezone_name=timezone_name,
    )
    notifiers_by_agent = _build_agent_webhook_map(
        webhook_secret=webhook_secret,
        timezone_name=timezone_name,
    )
    if not notifiers_by_agent:
        return default_notifier

    return FeishuWebhookRouter(
        default_notifier=default_notifier,
        notifiers_by_agent=notifiers_by_agent,
    )

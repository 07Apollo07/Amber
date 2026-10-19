"""Builds the admin query trace for one chat turn from the LangGraph `updates` stream.

A trace says what the agent did, not what it read: tool names, shortened inputs, outcomes, timings, token
usage and source metadata with scores. Passage text and Amber's answer are never recorded (DECISION.MD §3).
"""

import json
import time
from typing import Any

_MAX_STEPS = 60
_MAX_ARG_CHARS = 160
_MAX_ERROR_CHARS = 300
_MAX_SOURCES = 10


def _short(value: Any) -> Any:
    """A readable, bounded preview of one tool argument."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_ARG_CHARS else value[: _MAX_ARG_CHARS - 1] + "…"
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(item, str) for item in value) and len(", ".join(value)) <= _MAX_ARG_CHARS:
            return ", ".join(value)
        return f"{len(value)} item{'s' if len(value) != 1 else ''}"
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return text if len(text) <= _MAX_ARG_CHARS else f"{len(value)} field{'s' if len(value) != 1 else ''}"
    return _short(str(value))


def _source(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    allowed = ("document_id", "title", "file_type", "page", "origin", "vector_distance", "text_rank")
    return {key: item.get(key) for key in allowed if item.get(key) is not None}


class TurnTrace:
    """Collects one chat turn. Feed it every `updates` chunk, then call `finish`."""

    def __init__(self, *, query: str, kind: str, model: str | None) -> None:
        self.query = query
        self.kind = kind
        self.model = model
        self.steps: list[dict[str, Any]] = []
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tools_used: list[str] = []
        self.awaiting_approval = False
        self._started = time.monotonic()
        self._last_event = self._started
        self._open_calls: dict[str, dict[str, Any]] = {}

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def _add(self, step: dict[str, Any]) -> None:
        if len(self.steps) < _MAX_STEPS:
            self.steps.append(step)

    def observe_update(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        now = time.monotonic()
        since_last = int((now - self._last_event) * 1000)
        self._last_event = now
        for node, output in data.items():
            if node == "__interrupt__":
                self.awaiting_approval = True
                continue
            messages = output.get("messages", []) if isinstance(output, dict) else []
            for message in messages if isinstance(messages, list) else []:
                kind = getattr(message, "type", None)
                if kind == "ai":
                    self._observe_model(message, since_last)
                elif kind == "tool":
                    self._observe_tool(message, since_last)

    def _observe_model(self, message: Any, duration_ms: int) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        prompt, completion = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        calls = getattr(message, "tool_calls", None) or []
        self._add(
            {
                "type": "model",
                "at_ms": self._elapsed_ms(),
                "duration_ms": duration_ms,
                "decision": "tools" if calls else "answer",
                "prompt_tokens": prompt or None,
                "completion_tokens": completion or None,
            }
        )
        for call in calls:
            name = call.get("name") or "unknown"
            step = {
                "type": "tool",
                "tool": name,
                "input": {key: _short(value) for key, value in (call.get("args") or {}).items()},
                "status": "running",
                "at_ms": self._elapsed_ms(),
                "duration_ms": None,
            }
            self._add(step)
            if call.get("id"):
                self._open_calls[call["id"]] = step
            if name not in self.tools_used:
                self.tools_used.append(name)

    def _observe_tool(self, message: Any, duration_ms: int) -> None:
        step = self._open_calls.pop(getattr(message, "tool_call_id", ""), None)
        if step is None:
            step = {"type": "tool", "tool": getattr(message, "name", None) or "unknown", "input": {}}
            self._add(step)
        content = message.content if isinstance(message.content, str) else json.dumps(message.content, default=str)
        failed = getattr(message, "status", "success") == "error"
        step["status"] = "failed" if failed else "completed"
        step["duration_ms"] = duration_ms
        step["result_chars"] = len(content)
        if failed:
            step["error"] = content[:_MAX_ERROR_CHARS]
        artifact = getattr(message, "artifact", None)
        if isinstance(artifact, dict) and isinstance(artifact.get("sources"), list):
            sources = [source for source in map(_source, artifact["sources"][:_MAX_SOURCES]) if source]
            step["sources"] = sources

    def finish(self, *, error: str | None = None, stopped: bool = False) -> dict[str, Any]:
        """The fields for `repository.insert_query_trace`, minus user and conversation."""
        for step in self._open_calls.values():
            step["status"] = "stopped"
        if error:
            status = "failed"
        elif stopped:
            status, error = "failed", "Stopped before Amber finished answering"
        elif self.awaiting_approval:
            status = "awaiting_approval"
        else:
            status = "completed"
        return {
            "kind": self.kind,
            "status": status,
            "query": self.query,
            "model": self.model,
            "steps": self.steps,
            "prompt_tokens": self.prompt_tokens or None,
            "completion_tokens": self.completion_tokens or None,
            "latency_ms": self._elapsed_ms(),
            "error": error[:_MAX_ERROR_CHARS] if error else None,
        }

"""Admin query traces and audit log: trace capture, the admin endpoints and the CSV export."""

import csv
import io
import time
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from amber.agent.trace import TurnTrace
from amber.api import admin
from amber.util.security import get_db, require_admin

ADMIN = {"id": uuid.uuid4(), "email": "admin@example.com", "role": "admin", "status": "active"}


def test_turn_trace_records_tools_sources_and_tokens_but_no_text() -> None:
    turn = TurnTrace(query="What is our leave policy?", kind="chat", model="model-a")
    turn.observe_update(
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "c1", "name": "vector_search", "args": {"query": "leave policy"}}],
                        usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
                    )
                ]
            }
        }
    )
    turn.observe_update(
        {
            "tools": {
                "messages": [
                    ToolMessage(
                        content="[Source: HR Handbook]\nSECRET PASSAGE TEXT",
                        tool_call_id="c1",
                        name="vector_search",
                        artifact={
                            "sources": [
                                {"document_id": "d1", "title": "HR Handbook", "page": 4, "vector_distance": 0.2},
                            ]
                        },
                    )
                ]
            }
        }
    )
    turn.observe_update(
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="Answer with SECRET PASSAGE TEXT",
                        usage_metadata={"input_tokens": 300, "output_tokens": 50, "total_tokens": 350},
                    )
                ]
            }
        }
    )

    outcome = turn.finish()

    assert outcome["status"] == "completed"
    assert (outcome["prompt_tokens"], outcome["completion_tokens"]) == (400, 60)
    assert [step["type"] for step in outcome["steps"]] == ["model", "tool", "model"]
    tool = outcome["steps"][1]
    assert tool["tool"] == "vector_search"
    assert tool["input"] == {"query": "leave policy"}
    assert tool["status"] == "completed"
    assert tool["sources"] == [{"document_id": "d1", "title": "HR Handbook", "page": 4, "vector_distance": 0.2}]
    assert "SECRET" not in repr(outcome)
    assert turn.tools_used == ["vector_search"]


def test_turn_trace_marks_failures_stops_and_approvals() -> None:
    turn = TurnTrace(query="Rename the doc", kind="chat", model=None)
    turn.observe_update(
        {
            "agent": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"id": "c1", "name": "drive_get_file", "args": {"file_id": "x" * 500, "rows": [1, 2, 3]}}
                        ],
                    )
                ]
            }
        }
    )
    assert turn.steps[1]["input"]["file_id"].endswith("…")
    assert len(turn.steps[1]["input"]["file_id"]) == 160
    assert turn.steps[1]["input"]["rows"] == "3 items"

    turn.observe_update(
        {"tools": {"messages": [ToolMessage(content="Tool execution failed", tool_call_id="c1", status="error")]}}
    )
    assert turn.steps[1]["status"] == "failed"
    assert turn.steps[1]["error"] == "Tool execution failed"

    assert turn.finish(stopped=True)["status"] == "failed"
    failed = turn.finish(error="ValueError: boom")
    assert (failed["status"], failed["error"]) == ("failed", "ValueError: boom")

    waiting = TurnTrace(query="Share it", kind="chat", model=None)
    waiting.observe_update({"__interrupt__": ({"type": "workspace_approval"},)})
    assert waiting.finish()["status"] == "awaiting_approval"


@pytest.mark.parametrize(
    "action,category",
    [
        ("auth.login", "sign_in"),
        ("agent.chat_message", "chat"),
        ("upload_document", "documents"),
        ("share_collection", "sharing"),
        ("update_document_access", "sharing"),
        ("organize_collection_document", "collections"),
        ("drive.disconnect", "drive"),
        ("admin.audit_export", "admin"),
        ("something_new", "other"),
    ],
)
def test_audit_categories(action: str, category: str) -> None:
    assert admin.audit_category(action) == category


def test_csv_cells_cannot_become_spreadsheet_formulas() -> None:
    assert admin._csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert admin._csv_cell("@sum") == "'@sum"
    assert admin._csv_cell("hello") == "hello"
    assert admin._csv_cell(None) == ""


@pytest.fixture
def admin_client(client, monkeypatch):
    client.app.dependency_overrides[require_admin] = lambda: ADMIN
    client.app.dependency_overrides[get_db] = lambda: SimpleConn()
    yield client
    client.app.dependency_overrides.clear()


class SimpleConn:
    committed = False

    def commit(self) -> None:
        SimpleConn.committed = True


def _trace_row(index: int) -> dict:
    return {
        "id": uuid.UUID(int=index),
        "user_id": uuid.UUID(int=99),
        "user_email": "ada@example.com",
        "user_name": "Ada",
        "conversation_id": None,
        "query": f"question {index}",
        "kind": "chat",
        "status": "completed",
        "model": "m",
        "latency_ms": 1200,
        "tokens": 10,
        "prompt_tokens": 8,
        "completion_tokens": 2,
        "error": None,
        "created_at": datetime(2026, 10, 19, 10, index % 60, tzinfo=UTC),
        "steps": [
            {
                "type": "tool",
                "tool": "vector_search",
                "status": "completed",
                "sources": [{"document_id": "d1"}, {"document_id": "d2"}],
            },
            {"type": "tool", "tool": "vector_search", "status": "failed", "sources": [{"document_id": "d1"}]},
        ],
    }


def test_admin_traces_list_paginates_and_summarizes(admin_client, monkeypatch) -> None:
    calls = []

    def fake_list(_conn, **kwargs):
        calls.append(kwargs)
        return [_trace_row(i) for i in range(kwargs["limit"])]

    monkeypatch.setattr(admin.repository, "list_query_traces", fake_list)

    body = admin_client.get("/api/admin/traces?status=completed&q=leave").json()

    assert len(body["traces"]) == admin.PAGE_SIZE
    first = body["traces"][0]
    assert first["tools"] == ["vector_search"]
    assert (first["tool_calls"], first["failed_tools"], first["source_count"]) == (2, 1, 2)
    assert (
        body["next"]
        == f"{_trace_row(admin.PAGE_SIZE - 1)['created_at'].isoformat()}|{uuid.UUID(int=admin.PAGE_SIZE - 1)}"
    )
    assert calls[0]["status"] == "completed" and calls[0]["search"] == "leave"

    admin_client.get("/api/admin/traces", params={"before": body["next"]})
    assert calls[1]["before"] == (_trace_row(admin.PAGE_SIZE - 1)["created_at"], uuid.UUID(int=admin.PAGE_SIZE - 1))
    assert admin_client.get("/api/admin/traces?status=bogus").status_code == 400
    assert admin_client.get("/api/admin/traces?before=nonsense").status_code == 400


def _audit_row(index: int, action: str, target: str | None) -> dict:
    return {
        "id": index,
        "at": datetime(2026, 10, 19, 9, 0, tzinfo=UTC),
        "actor_user_id": uuid.UUID(int=7),
        "actor_email": "ada@example.com",
        "actor_name": "Ada",
        "action": action,
        "target": target,
        "detail": {"note": "=cmd"},
        "ip": "10.0.0.1",
    }


def test_admin_audit_names_targets_and_filters_by_category(admin_client, monkeypatch) -> None:
    conversation = uuid.uuid4()
    calls = []

    def fake_list(_conn, **kwargs):
        calls.append(kwargs)
        return [_audit_row(5, "agent.chat_message", str(conversation)), _audit_row(4, "upload_document", "notes.pdf")]

    monkeypatch.setattr(admin.repository, "list_audit_events", fake_list)
    monkeypatch.setattr(
        admin.repository,
        "resolve_audit_targets",
        lambda _conn, ids: (
            {str(conversation): {"id": str(conversation), "kind": "conversation", "label": "Leave"}}
            if ids == [conversation]
            else {}
        ),
    )
    monkeypatch.setattr(
        admin.repository,
        "list_audit_actors",
        lambda _conn: [{"actor_user_id": uuid.UUID(int=7), "email": "ada@example.com", "name": "Ada"}],
    )

    body = admin_client.get("/api/admin/audit?category=documents").json()

    assert calls[0]["action_prefixes"] == ["document."]
    assert "upload_document" in calls[0]["actions"]
    chat, upload = body["events"]
    assert (chat["category"], chat["target_label"], chat["target_kind"]) == ("chat", "Leave", "conversation")
    assert (upload["category"], upload["target_label"]) == ("documents", None)
    assert body["actors"] == [{"id": str(uuid.UUID(int=7)), "email": "ada@example.com", "name": "Ada"}]
    assert body["next"] is None
    assert admin_client.get("/api/admin/audit?category=bogus").status_code == 400


def test_admin_audit_export_is_csv_and_is_itself_audited(admin_client, monkeypatch) -> None:
    recorded = []
    monkeypatch.setattr(admin.repository, "list_audit_events", lambda _conn, **_kw: [_audit_row(1, "auth.login", None)])
    monkeypatch.setattr(admin.repository, "resolve_audit_targets", lambda _conn, _ids: {})
    monkeypatch.setattr(
        admin.audit, "record", lambda _conn, _req, action, **kw: recorded.append((action, kw["detail"]))
    )

    response = admin_client.get("/api/admin/audit/export?category=sign_in")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:5] == ["time_utc", "user_email", "user_name", "category", "action"]
    assert rows[1][3:5] == ["sign_in", "auth.login"]
    assert rows[1][7] == '{"note": "=cmd"}'
    assert recorded == [
        (
            "admin.audit_export",
            {"rows": 1, "category": "sign_in", "actor": None, "search": None, "from": None, "to": None},
        )
    ]
    assert SimpleConn.committed


@pytest.mark.parametrize(
    "path", ["/api/admin/traces", f"/api/admin/traces/{uuid.uuid4()}", "/api/admin/audit", "/api/admin/audit/export"]
)
def test_trace_and_audit_endpoints_reject_anonymous(client, path) -> None:
    assert client.get(path).status_code in (401, 403)


def test_chat_stream_saves_a_trace_and_an_audit_event(client, monkeypatch) -> None:
    from amber.api import agent as agent_api
    from amber.util.security import current_user, require_csrf

    user = {"id": uuid.uuid4(), "email": "ada@example.com", "domain": "example.com", "role": "member"}
    saved: dict = {}
    audited: list = []

    class FakeGraph:
        checkpointer = None

        async def astream(self, *_args, **_kwargs):
            yield {
                "type": "updates",
                "ns": (),
                "data": {
                    "agent": {
                        "messages": [
                            AIMessage(
                                content="", tool_calls=[{"id": "c1", "name": "web_search", "args": {"query": "news"}}]
                            )
                        ]
                    }
                },
            }
            yield {
                "type": "updates",
                "ns": (),
                "data": {"tools": {"messages": [ToolMessage(content="results", tool_call_id="c1", name="web_search")]}},
            }
            yield {"type": "updates", "ns": (), "data": {"agent": {"messages": [AIMessage(content="Here you go")]}}}

    class Conn:
        def commit(self) -> None:
            saved["committed"] = True

    client.app.state.agent_graph = FakeGraph()
    client.app.dependency_overrides[current_user] = lambda: user
    client.app.dependency_overrides[require_csrf] = lambda: None
    client.app.dependency_overrides[get_db] = lambda: Conn()
    monkeypatch.setattr(agent_api.repository, "ensure_agent_conversation", lambda *_a: {"id": "x"})
    monkeypatch.setattr(agent_api.agent_settings, "load_chat", lambda _c: agent_api.agent_settings.ChatSettings())
    monkeypatch.setattr(agent_api.db, "connect", lambda _settings: nullcontext(Conn()))
    monkeypatch.setattr(
        agent_api.repository, "insert_query_trace", lambda _conn, **kw: saved.update(kw) or {"id": uuid.UUID(int=1)}
    )
    monkeypatch.setattr(agent_api.audit, "record", lambda _c, _r, action, **kw: audited.append((action, kw)))
    try:
        thread = str(uuid.uuid4())
        response = client.post("/api/agent/v2/stream", json={"message": " What's new? ", "thread_id": thread})
        assert response.status_code == 200
        assert "event: end" in response.text
        for _ in range(100):  # the trace is written on a worker thread after the stream ends
            if saved.get("committed"):
                break
            time.sleep(0.01)
    finally:
        client.app.dependency_overrides.clear()

    assert saved["query"] == "What's new?"
    assert saved["status"] == "completed"
    assert saved["conversation_id"] == uuid.UUID(thread)
    assert [step.get("tool") for step in saved["steps"] if step["type"] == "tool"] == ["web_search"]
    assert audited[0][0] == "agent.chat_message"
    assert audited[0][1]["target"] == thread
    assert audited[0][1]["detail"]["tools"] == ["web_search"]
    assert saved["committed"]


def test_chat_stream_error_hides_internals_from_the_browser(client, monkeypatch, caplog) -> None:
    from amber.api import agent as agent_api
    from amber.util.security import current_user, require_csrf

    saved: dict = {}

    class FailingGraph:
        checkpointer = None

        async def astream(self, *_args, **_kwargs):
            raise RuntimeError("SELECT secret FROM documents WHERE text = 'confidential passage'")
            yield  # makes this an async generator

    class Conn:
        def commit(self) -> None:
            saved["committed"] = True

    client.app.state.agent_graph = FailingGraph()
    client.app.dependency_overrides[current_user] = lambda: {
        "id": uuid.uuid4(),
        "email": "a@example.com",
        "domain": None,
    }
    client.app.dependency_overrides[require_csrf] = lambda: None
    client.app.dependency_overrides[get_db] = lambda: Conn()
    monkeypatch.setattr(agent_api.repository, "ensure_agent_conversation", lambda *_a: {"id": "x"})
    monkeypatch.setattr(agent_api.agent_settings, "load_chat", lambda _c: agent_api.agent_settings.ChatSettings())
    monkeypatch.setattr(agent_api.db, "connect", lambda _settings: nullcontext(Conn()))
    monkeypatch.setattr(
        agent_api.repository, "insert_query_trace", lambda _conn, **kw: saved.update(kw) or {"id": uuid.UUID(int=1)}
    )
    monkeypatch.setattr(agent_api.audit, "record", lambda *_a, **_kw: None)
    try:
        with caplog.at_level("ERROR", logger="amber.api.agent"):
            response = client.post("/api/agent/v2/stream", json={"message": "hi", "thread_id": str(uuid.uuid4())})
        for _ in range(100):
            if saved.get("committed"):
                break
            time.sleep(0.01)
    finally:
        client.app.dependency_overrides.clear()

    assert "event: error" in response.text
    assert "confidential" not in response.text and "Traceback" not in response.text and "SELECT" not in response.text
    reference = response.text.split("Reference ")[1][:8]
    assert any(reference in record.getMessage() for record in caplog.records)
    assert saved["status"] == "failed"
    assert saved["error"].startswith(f"[{reference}] RuntimeError")

"""Tests for the agent chat and conversation history endpoints."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from amber.agent import graph as agent_graph
from amber.api import agent as agent_api


def test_litellm_models_are_loaded_from_proxy_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, dict[str, str]]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "provider/model-a"}, {"id": "provider/model-a"}, {"id": "provider/model-b"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, headers: dict[str, str]) -> FakeResponse:
            requests.append((url, headers))
            return FakeResponse()

    monkeypatch.setattr(agent_api.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    settings = SimpleNamespace(
        litellm_base_url="https://litellm.example/v1/",
        litellm_api_key=SecretStr("proxy-key"),
    )

    models = asyncio.run(agent_api._available_models(request, settings))
    cached_models = asyncio.run(agent_api._available_models(request, settings))

    assert models == ["provider/model-a", "provider/model-b"]
    assert cached_models == models
    assert requests == [("https://litellm.example/v1/models", {"Authorization": "Bearer proxy-key"})]


def test_agent_graph_uses_model_from_run_config(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked_models: list[str] = []

    class FakeModel:
        def __init__(self, name: str):
            self.name = name

        def bind_tools(self, _tools):
            return self

        def invoke(self, _messages):
            invoked_models.append(self.name)
            return AIMessage(content="done")

    monkeypatch.setattr(
        agent_graph,
        "get_agent_model",
        lambda _settings=None, model_name=None: FakeModel(model_name or "default-model"),
    )
    graph = agent_graph.create_agent_graph(settings=object())

    graph.invoke(
        {"messages": [("user", "hello")], "tasks": [], "visuals": {}},
        config={"configurable": {"thread_id": "model-test", "model_name": "chosen-model"}},
    )

    assert invoked_models == ["chosen-model"]


def test_agent_chat_unauthenticated(client: TestClient) -> None:
    resp = client.post("/api/agent/chat", json={"message": "Hello"})
    assert resp.status_code in (401, 403)


def test_agent_v2_stream_unauthenticated(client: TestClient) -> None:
    resp = client.post("/api/agent/v2/stream", json={"message": "Hello"})
    assert resp.status_code in (401, 403)


def test_get_conversation_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/agent/conversations/some-thread-id")
    assert resp.status_code in (401, 403)

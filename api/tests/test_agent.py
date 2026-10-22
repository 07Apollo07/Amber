"""Tests for the agent chat and conversation history endpoints."""

import asyncio
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from amber.agent import graph as agent_graph
from amber.agent import tools as agent_tools
from amber.api import agent as agent_api
from amber.util.config import Settings


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


@pytest.fixture
def default_agent_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_api.agent_settings, "load_voice", lambda _conn: agent_api.agent_settings.VoiceSettings())
    monkeypatch.setattr(agent_api.agent_settings, "load_chat", lambda _conn: agent_api.agent_settings.ChatSettings())


def test_agent_live_config_exposes_only_the_configured_model(default_agent_settings) -> None:
    settings = Settings(env="test", gemini_live_api_key=SecretStr("live-key"), gemini_live_model="gemini-live")

    config = agent_api.get_live_config({"id": "user-id"}, settings, None)

    assert config == {"enabled": True, "model": "gemini-live"}


def test_agent_live_key_falls_back_to_gemini_key_and_is_disabled_without_one(default_agent_settings) -> None:
    fallback = Settings(env="test", gemini_api_key=SecretStr("shared-key"), gemini_live_api_key=SecretStr(""))
    assert agent_api._live_api_key(fallback) == "shared-key"

    missing = Settings(env="test", gemini_api_key=SecretStr(""), gemini_live_api_key=SecretStr(""))
    assert agent_api.get_live_config({"id": "user-id"}, missing, None) == {"enabled": False, "model": None}


def test_agent_live_config_puts_chat_context_in_the_server_owned_prompt() -> None:
    settings = Settings(env="test", gemini_live_voice="Puck")

    config = agent_api._live_connect_config(settings, "User: what is our leave policy?", "resume-handle")

    instruction = config.system_instruction.parts[0].text
    assert instruction.startswith(agent_api._LIVE_PROMPT)
    assert instruction.endswith("User: what is our leave policy?")
    assert config.tools[0].function_declarations[0].name == "draft_agent_message"
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert config.session_resumption.handle == "resume-handle"


class _FakeLiveSocket:
    def __init__(self, incoming: list[dict]):
        self.incoming = [agent_api.json.dumps(item) for item in incoming]
        self.sent: list[dict] = []
        self.tool_call_sent = asyncio.Event()

    async def receive_text(self) -> str:
        if self.incoming:
            if '"tool_result"' in self.incoming[0]:
                await self.tool_call_sent.wait()  # a browser only answers a call it has seen
            return self.incoming.pop(0)
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def send_text(self, text: str) -> None:
        self.sent.append(agent_api.json.loads(text))
        if self.sent[-1]["type"] == "tool_call":
            self.tool_call_sent.set()


def _live_message(**fields):
    return agent_api.types.LiveServerMessage(**fields)


def test_agent_live_session_relays_audio_context_and_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    types = agent_api.types
    sent_to_gemini: list[tuple[str, object]] = []
    connects: list[tuple[str, types.LiveConnectConfig]] = []
    socket = _FakeLiveSocket(
        [
            {"type": "start", "context": "User: hi"},
            {"type": "audio", "data": "AAAB"},
            {"type": "context", "context": "User: hi\nAmber: hello"},
            {"type": "tool_result", "id": "call-1", "drafted": True},
            {"type": "tool_result", "id": "unknown", "drafted": True},
        ]
    )

    class FakeSession:
        turns_left = 1

        async def send_realtime_input(self, *, audio):
            sent_to_gemini.append(("audio", audio))

        async def send_client_content(self, *, turns, turn_complete):
            sent_to_gemini.append(("content", (turns.parts[0].text, turn_complete)))

        async def send_tool_response(self, *, function_responses):
            sent_to_gemini.append(("tool", function_responses))

        async def receive(self):
            if self.turns_left == 0:
                return  # Gemini ended the session
            self.turns_left -= 1
            yield _live_message(
                tool_call=types.LiveServerToolCall(
                    function_calls=[
                        types.FunctionCall(id="call-1", name="draft_agent_message", args={"message": "Find X"})
                    ]
                )
            )
            yield _live_message(
                server_content=types.LiveServerContent(
                    output_transcription=types.Transcription(text="Sure."),
                    model_turn=types.Content(parts=[types.Part(inline_data=types.Blob(data=b"\x01\x02"))]),
                    turn_complete=True,
                )
            )
            await asyncio.sleep(0.05)  # let the browser side drain before Gemini ends the session

    class FakeConnect:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *_args):
            return None

    class FakeClient:
        def __init__(self, api_key: str):
            assert api_key == "live-key"
            self.aio = SimpleNamespace(live=SimpleNamespace(connect=self.connect))

        def connect(self, *, model, config):
            connects.append((model, config))
            return FakeConnect()

    monkeypatch.setattr(agent_api.genai, "Client", FakeClient)
    settings = Settings(env="test", gemini_live_api_key=SecretStr("live-key"), gemini_live_model="gemini-live")

    asyncio.run(agent_api._run_live_session(socket, settings, "user-1"))

    assert connects[0][0] == "gemini-live"
    assert connects[0][1].system_instruction.parts[0].text.endswith("User: hi")
    assert socket.sent == [
        {"type": "ready", "model": "gemini-live"},
        {"type": "tool_call", "id": "call-1", "name": "draft_agent_message", "message": "Find X"},
        {"type": "output_transcript", "text": "Sure."},
        {"type": "audio", "data": "AQI="},
        {"type": "turn_complete"},
    ]
    assert sent_to_gemini[0][0] == "audio"
    assert sent_to_gemini[0][1].mime_type == "audio/pcm;rate=16000"
    assert sent_to_gemini[1] == ("content", ("[Amber chat context update]\nUser: hi\nAmber: hello", False))
    assert sent_to_gemini[2][0] == "tool"
    assert sent_to_gemini[2][1].id == "call-1"
    assert sent_to_gemini[2][1].response == {"drafted": True, "sent": False}
    assert len(sent_to_gemini) == 3  # the unknown tool result was dropped


def test_agent_live_session_must_start_with_context() -> None:
    socket = _FakeLiveSocket([{"type": "audio", "data": ""}])
    with pytest.raises(agent_api._LiveSessionEnded):
        asyncio.run(agent_api._run_live_session(socket, Settings(env="test"), "user-1"))


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


def test_vector_search_passes_selected_collection_to_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    collection_id = uuid.uuid4()
    search_args: dict = {}
    monkeypatch.setattr(agent_tools, "_emit_task", lambda *_args: None)
    monkeypatch.setattr(agent_tools, "get_settings", lambda: object())
    monkeypatch.setattr(agent_tools, "generate_embeddings", lambda _texts: [[0.1]])
    monkeypatch.setattr(agent_tools, "connect", lambda _settings: nullcontext(object()))
    monkeypatch.setattr(
        agent_tools.agent_settings,
        "load_chat",
        lambda _conn: agent_tools.agent_settings.ChatSettings(passages_per_search=7),
    )

    def fake_search(_conn, **kwargs):
        search_args.update(kwargs)
        return []

    monkeypatch.setattr(agent_tools.repository, "hybrid_search_chunks", fake_search)

    result = agent_tools.vector_search.func(
        "find this",
        "user@example.com",
        None,
        str(collection_id),
    )

    assert result == ("No relevant internal documents found.", {"sources": []})
    assert search_args["collection_ids"] == [collection_id]
    assert search_args["limit"] == 7


def test_agent_chat_unauthenticated(client: TestClient) -> None:
    resp = client.post("/api/agent/chat", json={"message": "Hello"})
    assert resp.status_code in (401, 403)


def test_agent_v2_stream_unauthenticated(client: TestClient) -> None:
    resp = client.post("/api/agent/v2/stream", json={"message": "Hello"})
    assert resp.status_code in (401, 403)


def test_agent_live_config_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/agent/live/config")
    assert resp.status_code in (401, 403)


def test_agent_live_websocket_rejects_anonymous_connection(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as disconnect:
        with client.websocket_connect("/api/agent/live", headers={"origin": "https://amber.test"}):
            pytest.fail("Anonymous websocket unexpectedly connected")
    assert disconnect.value.code == 4401


def test_get_conversation_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/agent/conversations/some-thread-id")
    assert resp.status_code in (401, 403)

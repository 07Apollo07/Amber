"""Admin settings: validation, the sectioned endpoints, and where chat and voice settings take effect."""

import uuid

import pytest
from pydantic import SecretStr

from amber.agent import settings as agent_settings
from amber.api import admin
from amber.api import agent as agent_api
from amber.util.config import Settings
from amber.util.security import get_db, require_admin, require_csrf

ADMIN = {"id": uuid.uuid4(), "email": "admin@example.com", "role": "admin", "status": "active"}


class Conn:
    committed = False

    def commit(self) -> None:
        self.committed = True


@pytest.fixture
def admin_client(client, monkeypatch):
    conn = Conn()
    client.app.dependency_overrides[require_admin] = lambda: ADMIN
    client.app.dependency_overrides[require_csrf] = lambda: None
    client.app.dependency_overrides[get_db] = lambda: conn
    saved: dict = {}
    audited: list = []
    monkeypatch.setattr(admin.repository, "list_settings_with_editors", lambda _c, _keys: {})
    monkeypatch.setattr(admin.indexing_settings.repository, "get_setting", lambda _c, _k: None)
    monkeypatch.setattr(admin.indexing_settings.repository, "set_setting", lambda _c, k, v, _by: saved.update({k: v}))
    monkeypatch.setattr(admin.audit, "record", lambda _c, _r, action, **kw: audited.append((action, kw)))
    client.saved, client.audited, client.conn = saved, audited, conn
    yield client
    client.app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "values",
    [
        {"default_model": None, "passages_per_search": 0, "web_search_enabled": True},
        {"default_model": None, "passages_per_search": 21, "web_search_enabled": True},
        {"default_model": None, "passages_per_search": 5, "web_search_enabled": "yes"},
        {"default_model": "  ", "passages_per_search": 5, "web_search_enabled": True},
        {"default_model": None, "passages_per_search": True, "web_search_enabled": True},
    ],
)
def test_chat_validation_rejects_bad_values(values) -> None:
    with pytest.raises(ValueError):
        agent_settings.validate_chat(values)


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": True, "voice": "Robot", "max_session_minutes": 30},
        {"enabled": True, "voice": None, "max_session_minutes": 4},
        {"enabled": 1, "voice": None, "max_session_minutes": 30},
    ],
)
def test_voice_validation_rejects_bad_values(values) -> None:
    with pytest.raises(ValueError):
        agent_settings.validate_voice(values)


def test_saved_settings_fall_back_to_defaults_when_invalid(monkeypatch) -> None:
    monkeypatch.setattr(agent_settings.repository, "get_setting", lambda _c, _k: {"value": {"passages_per_search": 99}})
    assert agent_settings.load_chat(object()) == agent_settings.ChatSettings()
    monkeypatch.setattr(agent_settings.repository, "get_setting", lambda _c, _k: {"value": {"voice": "Puck"}})
    assert agent_settings.load_voice(object()) == agent_settings.VoiceSettings(voice="Puck")


def test_get_settings_returns_every_section(admin_client, monkeypatch) -> None:
    body = admin_client.get("/api/admin/settings").json()

    assert set(body) == {"indexing", "chat", "voice"}
    assert body["chat"]["values"] == {"default_model": None, "passages_per_search": 5, "web_search_enabled": True}
    assert body["chat"]["limits"] == {"passages_per_search": {"min": 1, "max": 20}}
    assert body["chat"]["options"]["model_choice_available"] is False
    assert body["voice"]["options"]["voices"] == list(agent_settings.VOICES)
    assert body["indexing"]["defaults"]["chunk_size_tokens"] == 800
    assert body["indexing"]["edited"] is None


def test_put_saves_one_section_and_audits_the_change(admin_client) -> None:
    values = {"enabled": False, "voice": "Kore", "max_session_minutes": 15}

    response = admin_client.put("/api/admin/settings/voice", json=values)

    assert response.status_code == 200
    assert admin_client.saved == {"voice": values}
    action, kw = admin_client.audited[0]
    assert action == "admin.update_settings" and kw["target"] == "voice"
    assert kw["detail"]["from"]["enabled"] is True and kw["detail"]["to"] == values
    assert admin_client.conn.committed


def test_put_rejects_unknown_sections_and_bad_values(admin_client) -> None:
    assert admin_client.put("/api/admin/settings/billing", json={}).status_code == 404
    bad = {"chunk_size_tokens": 10, "chunk_overlap_pct": 15, "max_upload_mb": 50}
    assert admin_client.put("/api/admin/settings/indexing", json=bad).status_code == 400
    assert admin_client.saved == {}


def test_default_model_must_come_from_the_proxy(admin_client, monkeypatch) -> None:
    chat = {"default_model": "vertex_ai/gemini-x", "passages_per_search": 5, "web_search_enabled": True}
    assert admin_client.put("/api/admin/settings/chat", json=chat).status_code == 400  # no proxy configured

    admin_client.app.state.settings = admin_client.app.state.settings.model_copy(
        update={"litellm_base_url": "https://litellm.example/v1"}
    )
    monkeypatch.setattr(agent_api, "_available_models", lambda *_a: _async(["vertex_ai/gemini-y"]))
    assert admin_client.put("/api/admin/settings/chat", json=chat).status_code == 400
    monkeypatch.setattr(agent_api, "_available_models", lambda *_a: _async(["vertex_ai/gemini-x"]))
    assert admin_client.put("/api/admin/settings/chat", json=chat).status_code == 200
    assert admin_client.saved["chat"]["default_model"] == "vertex_ai/gemini-x"


async def _async(value):
    return value


def test_default_model_falls_back_when_the_proxy_drops_it(monkeypatch) -> None:
    import asyncio

    settings = Settings(env="test", litellm_base_url="https://litellm.example/v1", agent_model_name="server-model")
    monkeypatch.setattr(
        agent_api.agent_settings, "load_chat", lambda _c: agent_settings.ChatSettings(default_model="gone")
    )
    monkeypatch.setattr(agent_api, "_available_models", lambda *_a: _async(["other"]))
    assert asyncio.run(agent_api._default_model(None, settings, None)) == "server-model"

    monkeypatch.setattr(agent_api, "_available_models", lambda *_a: _async(["gone"]))
    assert asyncio.run(agent_api._default_model(None, settings, None)) == "gone"


def test_voice_switch_turns_opal_off(monkeypatch) -> None:
    settings = Settings(env="test", gemini_live_api_key=SecretStr("k"), gemini_live_model="live")
    monkeypatch.setattr(agent_api.agent_settings, "load_voice", lambda _c: agent_settings.VoiceSettings(enabled=False))
    assert agent_api.get_live_config({"id": "u"}, settings, None) == {"enabled": False, "model": None}


def test_web_search_reports_when_it_is_turned_off(monkeypatch) -> None:
    from contextlib import nullcontext

    from amber.agent import tools as agent_tools

    monkeypatch.setattr(agent_tools, "connect", lambda _s: nullcontext(object()))
    monkeypatch.setattr(
        agent_tools.agent_settings, "load_chat", lambda _c: agent_settings.ChatSettings(web_search_enabled=False)
    )
    monkeypatch.setattr(agent_tools.httpx, "Client", lambda **_kw: pytest.fail("web search ran while turned off"))

    assert "turned off" in agent_tools.web_search("news")

"""Chat and Opal voice settings an admin can change at runtime (Admin > Settings). Stored in `settings`."""

from dataclasses import asdict, dataclass
from typing import Any

from amber import repository
from amber.util.db import Connection

CHAT_KEY = "chat"
VOICE_KEY = "voice"

# Gemini Live's prebuilt voices.
VOICES = ("Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr")


@dataclass(frozen=True)
class ChatSettings:
    default_model: str | None = None  # None: the server's AMBER_AGENT_MODEL_NAME
    passages_per_search: int = 5
    web_search_enabled: bool = True


@dataclass(frozen=True)
class VoiceSettings:
    enabled: bool = True
    voice: str | None = None  # None: the server's AMBER_GEMINI_LIVE_VOICE
    max_session_minutes: int = 30


# (min, max) for the numeric fields; the Admin form uses the same ranges.
CHAT_LIMITS: dict[str, tuple[int, int]] = {"passages_per_search": (1, 20)}
VOICE_LIMITS: dict[str, tuple[int, int]] = {"max_session_minutes": (5, 60)}


def _whole(values: dict[str, Any], name: str, low: int, high: int) -> int:
    value = values.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return value


def _flag(values: dict[str, Any], name: str) -> bool:
    value = values.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def validate_chat(values: dict[str, Any]) -> ChatSettings:
    """Raises ValueError naming the first invalid field. Whether the model exists is checked by the caller."""
    model = values.get("default_model")
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 255):
        raise ValueError("default_model must be a model name, or empty for the server default")
    return ChatSettings(
        default_model=model.strip() if isinstance(model, str) else None,
        passages_per_search=_whole(values, "passages_per_search", *CHAT_LIMITS["passages_per_search"]),
        web_search_enabled=_flag(values, "web_search_enabled"),
    )


def validate_voice(values: dict[str, Any]) -> VoiceSettings:
    voice = values.get("voice")
    if voice is not None and voice not in VOICES:
        raise ValueError(f"voice must be one of: {', '.join(VOICES)}, or empty for the server default")
    return VoiceSettings(
        enabled=_flag(values, "enabled"),
        voice=voice,
        max_session_minutes=_whole(values, "max_session_minutes", *VOICE_LIMITS["max_session_minutes"]),
    )


def _load(conn: Connection, key: str, default: Any, validate: Any) -> Any:
    """The saved settings, with defaults for anything missing or no longer valid."""
    row = repository.get_setting(conn, key)
    if row is None:
        return default
    try:
        return validate({**asdict(default), **row["value"]})
    except (ValueError, TypeError):
        return default


def load_chat(conn: Connection) -> ChatSettings:
    return _load(conn, CHAT_KEY, ChatSettings(), validate_chat)


def load_voice(conn: Connection) -> VoiceSettings:
    return _load(conn, VOICE_KEY, VoiceSettings(), validate_voice)


def save(conn: Connection, key: str, settings: ChatSettings | VoiceSettings, updated_by: Any) -> None:
    repository.set_setting(conn, key, asdict(settings), updated_by)

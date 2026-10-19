"""Admin API: users, every document's access settings, indexing settings, chat query traces and the audit log.

Admins see document metadata and who can open each file, never the text inside it."""

import csv
import io
import json
import re
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from amber import repository
from amber.agent import settings as agent_settings
from amber.api import agent as agent_api
from amber.ingest import settings as indexing_settings
from amber.util import audit
from amber.util.security import AdminUser, CsrfProtected, DbDep, SettingsDep

router = APIRouter(prefix="/api/admin", tags=["admin"])

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PUBLIC_MAIL_DOMAINS = {"gmail.com", "googlemail.com"}  # personal accounts have no organization domain


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


PAGE_SIZE = 50


def _page_cursor(row: dict[str, Any]) -> str:
    """Keyset cursor for lists ordered by (created_at, id) descending."""
    return f"{row['created_at'].isoformat()}|{row['id']}"


def _parse_page_cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not value:
        return None
    try:
        at, row_id = value.split("|", 1)
        return datetime.fromisoformat(at), uuid.UUID(row_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid page cursor") from None


def _serialize_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "status": row["status"],
        "pending": bool(row["pending"]),
        "created_at": _iso(row["created_at"]),
        "last_login_at": _iso(row["last_login_at"]),
        "document_count": int(row["document_count"]),
    }


class NewUser(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=255)
    role: str = Field(default="member", pattern="^(admin|member)$")


class UserUpdate(BaseModel):
    role: str = Field(pattern="^(admin|member)$")
    status: str = Field(pattern="^(active|deactivated)$")


def _get_user(conn: Any, user_id: uuid.UUID) -> dict[str, Any]:
    target = repository.get_user(conn, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    return target


def _removes_last_admin(conn: Any, target: dict[str, Any], *, role: str, status: str) -> bool:
    """True when this change would leave the app with no active admin."""
    was_active_admin = target["role"] == "admin" and target["status"] == "active"
    still_active_admin = role == "admin" and status == "active"
    return was_active_admin and not still_active_admin and repository.count_active_admins(conn) <= 1


@router.get("/users")
def list_users(admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    return {"users": [_serialize_user(r) for r in repository.list_users_with_counts(conn)]}


@router.post("/users", dependencies=[CsrfProtected])
def add_user(admin: AdminUser, conn: DbDep, request: Request, req: NewUser) -> dict[str, Any]:
    email = req.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if repository.get_user_by_email(conn, email):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    domain = email.split("@", 1)[1]
    created = repository.insert_pending_user(
        conn,
        email=email,
        name=req.name.strip() or email.split("@", 1)[0],
        domain=None if domain in PUBLIC_MAIL_DOMAINS else domain,
        role=req.role,
    )
    audit.record(conn, request, "admin.add_user", user=admin, target=email, detail={"role": req.role})
    conn.commit()
    row = next(r for r in repository.list_users_with_counts(conn) if r["id"] == created["id"])
    return {"user": _serialize_user(row)}


@router.put("/users/{user_id}", dependencies=[CsrfProtected])
def update_user(admin: AdminUser, conn: DbDep, request: Request, user_id: uuid.UUID, req: UserUpdate) -> dict[str, Any]:
    target = _get_user(conn, user_id)
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't change your own role or status")
    if _removes_last_admin(conn, target, role=req.role, status=req.status):
        raise HTTPException(status_code=400, detail="At least one active admin is required")
    repository.set_user_role_status(conn, user_id, role=req.role, status=req.status)
    audit.record(
        conn,
        request,
        "admin.update_user",
        user=admin,
        target=target["email"],
        detail={"role": req.role, "status": req.status, "was": {"role": target["role"], "status": target["status"]}},
    )
    conn.commit()
    return {"success": True}


@router.delete("/users/{user_id}", dependencies=[CsrfProtected])
def delete_user(admin: AdminUser, conn: DbDep, request: Request, user_id: uuid.UUID) -> dict[str, Any]:
    target = _get_user(conn, user_id)
    if target["id"] == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't delete your own account")
    if _removes_last_admin(conn, target, role="member", status="deactivated"):
        raise HTTPException(status_code=400, detail="At least one active admin is required")
    owned = next((r["document_count"] for r in repository.list_users_with_counts(conn) if r["id"] == user_id), 0)
    repository.delete_user(conn, user_id)
    audit.record(
        conn, request, "admin.delete_user", user=admin, target=target["email"], detail={"documents_removed": int(owned)}
    )
    conn.commit()
    return {"success": True, "documents_removed": int(owned)}


DOCUMENT_ORIGINS = {"desktop_upload", "drive_sync"}
DOCUMENT_SHARING = {"private", "specific_people", "domain"}


def _serialize_document(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "title": r["title"],
        "file_type": r["file_type"],
        "origin": r["origin"],
        "status": r["status"],
        "status_message": r["status_message"],
        "sharing_option": r["sharing_option"],
        "file_size_bytes": r["file_size_bytes"] or 0,
        "chunk_count": int(r["chunk_count"]),
        "owner": {"name": r["owner_name"], "email": r["owner_email"]},
        "imported_by": {"name": r["importer_name"], "email": r["importer_email"]},
        "drive_url": f"https://drive.google.com/file/d/{r['drive_file_id']}/view" if r["drive_file_id"] else None,
        "tags": list(r["tags"] or []),
        "access": r["access"] or [],
        "created_at": _iso(r["created_at"]),
        "updated_at": _iso(r["updated_at"]),
    }


def _counts(row: dict[str, Any]) -> dict[str, int]:
    keys = ("total", "ready", "processing", "failed", "from_drive", "uploaded", "total_bytes")
    return {key: int(row.get(key) or 0) for key in keys}


@router.get("/documents")
def list_documents(
    admin: AdminUser,
    conn: DbDep,
    status: str | None = None,
    origin: str | None = None,
    sharing: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    before: str | None = None,
) -> dict[str, Any]:
    if status is not None and status not in repository.DOCUMENT_STATUS_GROUPS:
        raise HTTPException(status_code=400, detail="Unknown document status")
    if origin is not None and origin not in DOCUMENT_ORIGINS:
        raise HTTPException(status_code=400, detail="Unknown document source")
    if sharing is not None and sharing not in DOCUMENT_SHARING:
        raise HTTPException(status_code=400, detail="Unknown sharing option")
    rows = repository.list_admin_documents(
        conn,
        limit=PAGE_SIZE + 1,
        before=_parse_page_cursor(before),
        status_group=status,
        origin=origin,
        sharing=sharing,
        search=(q or "").strip() or None,
    )
    page = rows[:PAGE_SIZE]
    return {
        "documents": [_serialize_document(r) for r in page],
        "next": _page_cursor(page[-1]) if len(rows) > PAGE_SIZE else None,
        "counts": _counts(repository.admin_document_counts(conn)),
    }


@router.get("/documents/{document_id}")
def get_document(document_id: uuid.UUID, admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    row = repository.get_admin_document(conn, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    usage = repository.document_source_usage(conn, document_id)
    return {
        **_serialize_document(row),
        "usage": {
            "answers": int(usage.get("answers") or 0),
            "people": int(usage.get("people") or 0),
            "last_used": _iso(usage.get("last_used")),
        },
    }


def _limits(limits: dict[str, tuple[int, int]]) -> dict[str, dict[str, int]]:
    return {name: {"min": low, "max": high} for name, (low, high) in limits.items()}


def _edited(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    return {
        "at": _iso(meta["updated_at"]),
        "by": {"name": meta["updated_by_name"], "email": meta["updated_by_email"]} if meta["updated_by_email"] else None,
    }


@router.get("/settings")
async def get_settings_endpoint(request: Request, admin: AdminUser, conn: DbDep, settings: SettingsDep) -> dict[str, Any]:
    meta = repository.list_settings_with_editors(
        conn, [indexing_settings.KEY, agent_settings.CHAT_KEY, agent_settings.VOICE_KEY]
    )
    models: list[str] = []
    models_error = None
    if settings.litellm_base_url:
        try:
            models = await agent_api._available_models(request, settings)
        except HTTPException as exc:
            models_error = str(exc.detail)
    return {
        "indexing": {
            "values": asdict(indexing_settings.load(conn)),
            "defaults": asdict(indexing_settings.IndexingSettings()),
            "limits": _limits(indexing_settings.LIMITS),
            "edited": _edited(meta.get(indexing_settings.KEY)),
        },
        "chat": {
            "values": asdict(agent_settings.load_chat(conn)),
            "defaults": asdict(agent_settings.ChatSettings()),
            "limits": _limits(agent_settings.CHAT_LIMITS),
            "edited": _edited(meta.get(agent_settings.CHAT_KEY)),
            "options": {
                "models": models,
                "models_error": models_error,
                "model_choice_available": bool(settings.litellm_base_url),
                "server_default_model": settings.agent_model_name,
            },
        },
        "voice": {
            "values": asdict(agent_settings.load_voice(conn)),
            "defaults": asdict(agent_settings.VoiceSettings()),
            "limits": _limits(agent_settings.VOICE_LIMITS),
            "edited": _edited(meta.get(agent_settings.VOICE_KEY)),
            "options": {
                "voices": list(agent_settings.VOICES),
                "server_default_voice": settings.gemini_live_voice,
                "configured": agent_api._live_enabled(settings),
                "server_max_minutes": settings.gemini_live_max_session_seconds // 60,
            },
        },
    }


SETTINGS_SECTIONS = {
    "indexing": (indexing_settings.KEY, indexing_settings.validate, indexing_settings.load),
    "chat": (agent_settings.CHAT_KEY, agent_settings.validate_chat, agent_settings.load_chat),
    "voice": (agent_settings.VOICE_KEY, agent_settings.validate_voice, agent_settings.load_voice),
}


@router.put("/settings/{section}", dependencies=[CsrfProtected])
async def update_settings(
    section: str,
    body: dict[str, Any],
    request: Request,
    admin: AdminUser,
    conn: DbDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    if section not in SETTINGS_SECTIONS:
        raise HTTPException(status_code=404, detail="Unknown settings section")
    key, validate, load = SETTINGS_SECTIONS[section]
    try:
        cfg = validate(body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if section == "chat" and cfg.default_model is not None:
        if not settings.litellm_base_url:
            raise HTTPException(status_code=400, detail="Choosing a default model needs a LiteLLM proxy")
        if cfg.default_model not in await agent_api._available_models(request, settings):
            raise HTTPException(status_code=400, detail="That model isn't offered by the LiteLLM proxy")

    before = load(conn)
    if section == "indexing":
        indexing_settings.save(conn, cfg, admin["id"])
    else:
        agent_settings.save(conn, key, cfg, admin["id"])
    audit.record(
        conn,
        request,
        "admin.update_settings",
        user=admin,
        target=key,
        detail={"from": asdict(before), "to": asdict(cfg)},
    )
    conn.commit()
    return {"values": asdict(cfg)}


# ---- query traces (one row per chat turn) ----

TRACE_STATUSES = {"completed", "failed", "awaiting_approval"}


def _trace_summary(row: dict[str, Any]) -> dict[str, Any]:
    steps = row["steps"] or []
    tools = [step for step in steps if step.get("type") == "tool"]
    return {
        "id": str(row["id"]),
        "at": _iso(row["created_at"]),
        "user": {"id": str(row["user_id"]), "email": row["user_email"], "name": row["user_name"]},
        "conversation_id": str(row["conversation_id"]) if row["conversation_id"] else None,
        "question": row["query"],
        "kind": row["kind"],
        "status": row["status"],
        "model": row["model"],
        "latency_ms": row["latency_ms"],
        "tokens": row["tokens"],
        "tools": list(dict.fromkeys(step.get("tool") for step in tools if step.get("tool"))),
        "tool_calls": len(tools),
        "failed_tools": sum(1 for step in tools if step.get("status") == "failed"),
        "source_count": len(
            {source.get("document_id") for step in tools for source in step.get("sources") or [] if source}
        ),
        "error": row["error"],
    }


@router.get("/traces")
def list_traces(
    admin: AdminUser,
    conn: DbDep,
    user: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    before: str | None = None,
) -> dict[str, Any]:
    if status is not None and status not in TRACE_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown trace status")
    rows = repository.list_query_traces(
        conn,
        limit=PAGE_SIZE + 1,
        before=_parse_page_cursor(before),
        user_id=user,
        status=status,
        search=(q or "").strip() or None,
    )
    page = rows[:PAGE_SIZE]
    return {
        "traces": [_trace_summary(r) for r in page],
        "next": _page_cursor(page[-1]) if len(rows) > PAGE_SIZE else None,
    }


@router.get("/traces/{trace_id}")
def get_trace(trace_id: uuid.UUID, admin: AdminUser, conn: DbDep) -> dict[str, Any]:
    row = repository.get_query_trace(conn, trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Trace not found")
    return {
        **_trace_summary(row),
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "steps": row["steps"] or [],
    }


# ---- audit log ----

# Category -> (action prefixes, exact actions). Older actions predate the "area.verb" naming.
AUDIT_CATEGORIES: dict[str, tuple[list[str], list[str]]] = {
    "sign_in": (["auth."], []),
    "chat": (["agent."], []),
    "documents": (["document."], ["upload_document", "delete_document", "import_drive_files"]),
    "collections": (["collection."], ["organize_collection_document", "delete_collection", "create_collection"]),
    "sharing": (["sharing."], ["update_document_access", "share_collection"]),
    "drive": (["drive."], []),
    "admin": (["admin."], []),
}


def audit_category(action: str) -> str:
    for name, (prefixes, actions) in AUDIT_CATEGORIES.items():
        if action in actions or any(action.startswith(prefix) for prefix in prefixes):
            return name
    return "other"


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _audit_rows(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = list({target for row in rows if (target := _as_uuid(row["target"]))})
    names = repository.resolve_audit_targets(conn, ids)
    events = []
    for row in rows:
        named = names.get(row["target"] or "")
        events.append(
            {
                "id": str(row["id"]),
                "at": _iso(row["at"]),
                "actor": {
                    "id": str(row["actor_user_id"]) if row["actor_user_id"] else None,
                    "email": row["actor_email"],
                    "name": row["actor_name"],
                },
                "action": row["action"],
                "category": audit_category(row["action"]),
                "target": row["target"],
                "target_label": named["label"] if named else None,
                "target_kind": named["kind"] if named else None,
                "detail": row["detail"] or {},
                "ip": row["ip"],
            }
        )
    return events


def _audit_query(
    *,
    actor: uuid.UUID | None,
    category: str | None,
    q: str | None,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any]:
    if category is not None and category not in AUDIT_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown audit category")
    prefixes, actions = AUDIT_CATEGORIES[category] if category else ([], [])
    return {
        "actor_user_id": actor,
        "action_prefixes": prefixes or None,
        "actions": actions or None,
        "search": (q or "").strip() or None,
        "start": start,
        "end": end,
    }


@router.get("/audit")
def list_audit(
    admin: AdminUser,
    conn: DbDep,
    actor: uuid.UUID | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    before: int | None = None,
) -> dict[str, Any]:
    filters = _audit_query(actor=actor, category=category, q=q, start=start, end=end)
    rows = repository.list_audit_events(conn, limit=PAGE_SIZE + 1, before_id=before, **filters)
    page = rows[:PAGE_SIZE]
    return {
        "events": _audit_rows(conn, page),
        "next": int(page[-1]["id"]) if len(rows) > PAGE_SIZE else None,
        "actors": [
            {"id": str(r["actor_user_id"]), "email": r["email"], "name": r["name"]}
            for r in sorted(repository.list_audit_actors(conn), key=lambda r: (r["name"] or r["email"] or "").lower())
        ],
    }


EXPORT_LIMIT = 10_000


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Spreadsheets run cells that start with these characters as formulas.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/audit/export")
def export_audit(
    request: Request,
    admin: AdminUser,
    conn: DbDep,
    actor: uuid.UUID | None = None,
    category: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
) -> Response:
    filters = _audit_query(actor=actor, category=category, q=q, start=start, end=end)
    events = _audit_rows(conn, repository.list_audit_events(conn, limit=EXPORT_LIMIT, **filters))
    audit.record(
        conn,
        request,
        "admin.audit_export",
        user=admin,
        detail={
            "rows": len(events),
            "category": category,
            "actor": str(actor) if actor else None,
            "search": filters["search"],
            "from": _iso(start),
            "to": _iso(end),
        },
    )
    conn.commit()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["time_utc", "user_email", "user_name", "category", "action", "target", "target_name", "detail", "ip"]
    )
    for e in events:
        writer.writerow(
            _csv_cell(v)
            for v in (
                e["at"],
                e["actor"]["email"],
                e["actor"]["name"],
                e["category"],
                e["action"],
                e["target"],
                e["target_label"],
                json.dumps(e["detail"], ensure_ascii=False, sort_keys=True) if e["detail"] else "",
                e["ip"],
            )
        )
    filename = f"amber-audit-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv"
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


# ---- analytics ----

ANALYTICS_RANGES = {7, 30, 90}


def _number(value: Any) -> float | None:
    return float(value) if value is not None else None


def _window_summary(row: dict[str, Any]) -> dict[str, Any]:
    completed, failed = int(row.get("completed") or 0), int(row.get("failed") or 0)
    finished = completed + failed
    return {
        "questions": int(row.get("questions") or 0),
        "people": int(row.get("people") or 0),
        "completed": completed,
        "failed": failed,
        "awaiting_approval": int(row.get("awaiting_approval") or 0),
        # Share of finished answers that succeeded; turns still waiting for approval aren't finished yet.
        "success_rate": completed / finished if finished else None,
        "median_ms": _number(row.get("median_ms")),
        "p95_ms": _number(row.get("p95_ms")),
    }


@router.get("/analytics")
def analytics(
    admin: AdminUser,
    conn: DbDep,
    days: int = 30,
    tz: str = Query(default="UTC", max_length=64),
) -> dict[str, Any]:
    if days not in ANALYTICS_RANGES:
        raise HTTPException(status_code=400, detail="Choose a 7, 30 or 90 day range")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        tz = "UTC"
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    previous_start = start - timedelta(days=days)

    library = _counts(repository.admin_document_counts(conn))
    return {
        "range": {"days": days, "start": _iso(start), "end": _iso(end), "tz": tz},
        "current": _window_summary(repository.trace_window_stats(conn, start, end)),
        "previous": _window_summary(repository.trace_window_stats(conn, previous_start, start)),
        "per_day": [
            {"day": r["day"].isoformat(), "questions": int(r["questions"]), "failed": int(r["failed"])}
            for r in repository.traces_per_day(conn, start, end, tz)
        ],
        "tools": [
            {
                "tool": r["tool"],
                "calls": int(r["calls"]),
                "failed": int(r["failed"]),
                "median_ms": _number(r["median_ms"]),
            }
            for r in repository.tool_usage(conn, start, end)
        ],
        "sources": [
            {
                "document_id": r["document_id"],
                "title": r["title"],
                "answers": int(r["answers"]),
                "people": int(r["people"]),
            }
            for r in repository.top_sources(conn, start, end)
        ],
        "people": [
            {
                "id": str(r["id"]),
                "email": r["email"],
                "name": r["name"],
                "questions": int(r["questions"]),
                "failed": int(r["failed"]),
                "last_asked": _iso(r["last_asked"]),
            }
            for r in repository.top_askers(conn, start, end)
        ],
        "library": {
            **library,
            "recent_failures": [
                {
                    "id": str(r["id"]),
                    "title": r["title"],
                    "file_type": r["file_type"],
                    "message": r["status_message"],
                    "updated_at": _iso(r["updated_at"]),
                }
                for r in repository.recent_failed_documents(conn)
            ],
        },
    }

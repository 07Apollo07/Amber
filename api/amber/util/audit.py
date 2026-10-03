"""Append-only audit trail."""

from typing import Any

from fastapi import Request

from amber import repository
from amber.util.db import Connection
from amber.util.net import client_ip


def record(
    conn: Connection,
    request: Request,
    action: str,
    *,
    user: dict[str, Any] | None = None,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Writes an audit row in the caller's transaction (it lands when the caller commits)."""
    repository.insert_audit(
        conn,
        actor_user_id=user["id"] if user else None,
        actor_email=user["email"] if user else None,
        action=action,
        target=target,
        detail=detail,
        ip=client_ip(request, request.app.state.settings),
    )

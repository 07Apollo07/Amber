import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from amber import repository
from amber.models import can_import_folders, can_manage_drive_sharing, drive_connected
from amber.util import drive_sync
from amber.util.security import CurrentUser, DbDep, SettingsDep

router = APIRouter(prefix="/api", tags=["me"])
log = logging.getLogger(__name__)


@router.get("/me")
def me(user: CurrentUser, conn: DbDep, settings: SettingsDep) -> dict[str, Any]:
    """The signed-in user's profile, role and Drive status. Only these fields leave the API."""
    token = repository.get_token(conn, user["id"])
    scopes = token["scopes"] if token else ""
    sync_warning = None
    sync_state = repository.get_drive_sync_state(conn, user["id"])
    if sync_state and drive_connected(token is not None, scopes):
        try:
            drive_sync.ensure_drive_watch(user["id"], conn, settings)
        except drive_sync.DriveSyncError as exc:
            sync_warning = str(exc)
        sync_state = repository.get_drive_sync_state(conn, user["id"])
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "name": user["name"],
        "picture": user["picture_url"],
        "domain": user["domain"],
        "role": user["role"],
        "drive": {
            "connected": drive_connected(token is not None, scopes),
            "can_share": can_manage_drive_sharing(scopes),
            "can_import_folders": can_import_folders(scopes),
            "scopes": sorted(set(scopes.split())),
            "permission_sync": {
                "active": bool(sync_state and sync_state["channel_expires"] > datetime.now(UTC)),
                "expires_at": sync_state["channel_expires"].isoformat() if sync_state else None,
                "warning": sync_warning,
            },
        },
    }

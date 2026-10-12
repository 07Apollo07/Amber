from typing import Any

from fastapi import APIRouter

from amber import repository
from amber.models import can_manage_drive_sharing, drive_connected
from amber.util.security import CurrentUser, DbDep

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(user: CurrentUser, conn: DbDep) -> dict[str, Any]:
    """The signed-in user's profile, role and Drive status. Only these fields leave the API."""
    token = repository.get_token(conn, user["id"])
    scopes = token["scopes"] if token else ""
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
            "scopes": sorted(set(scopes.split())),
        },
    }

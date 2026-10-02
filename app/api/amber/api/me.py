from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from amber import repository
from amber.util.security import CurrentUser, DbDep

router = APIRouter(prefix="/api", tags=["me"])


class DriveStatus(BaseModel):
    connected: bool
    scopes: list[str]


class MeOut(BaseModel):
    id: str
    email: str
    name: str
    picture: str | None
    domain: str | None
    role: Literal["admin", "member"]
    drive: DriveStatus


@router.get("/me")
def me(user: CurrentUser, db: DbDep) -> MeOut:
    token = repository.get_token(db, user.id)
    return MeOut(
        id=str(user.id),
        email=user.email,
        name=user.name,
        picture=user.picture_url,
        domain=user.domain,
        role=user.role,
        drive=DriveStatus(
            connected=token is not None and token.drive_connected,
            scopes=sorted(token.scope_set) if token else [],
        ),
    )

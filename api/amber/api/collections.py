"""Collections API router: folders of documents the user owns, shared as a unit."""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from amber import repository
from amber.api.documents import AccessRequest, apply_access, build_access
from amber.util.security import CsrfProtected, CurrentUser, DbDep

router = APIRouter(prefix="/api/collections", tags=["collections"], dependencies=[CsrfProtected])


class CollectionName(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def _unique_name(conn: Any, user: dict[str, Any], name: str, *, except_id: uuid.UUID | None = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Collection name can't be empty")
    clash = repository.get_collection_by_name(conn, user["id"], name)
    if clash and clash["id"] != except_id:
        raise HTTPException(status_code=409, detail=f"You already have a collection called “{clash['name']}”")
    return name


def _owned(conn: Any, user: dict[str, Any], collection_id: uuid.UUID) -> dict[str, Any]:
    repository.set_app_user_context(conn, user["email"], user["domain"])
    collection = repository.get_collection(conn, user["id"], collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


@router.post("")
def create_collection(user: CurrentUser, conn: DbDep, req: CollectionName) -> dict[str, Any]:
    name = _unique_name(conn, user, req.name)
    row = repository.create_collection(conn, user["id"], name)
    conn.commit()
    return {"id": str(row["id"]), "name": row["name"]}


@router.put("/{collection_id}")
def rename_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID, req: CollectionName) -> dict[str, Any]:
    _owned(conn, user, collection_id)
    name = _unique_name(conn, user, req.name, except_id=collection_id)
    repository.rename_collection(conn, collection_id, name)
    conn.commit()
    return {"id": str(collection_id), "name": name}


@router.delete("/{collection_id}")
def delete_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID) -> dict[str, Any]:
    """Deletes the folder. The documents inside are kept and become ungrouped."""
    _owned(conn, user, collection_id)
    repository.delete_collection(conn, collection_id)
    conn.commit()
    return {"success": True}


@router.put("/{collection_id}/access")
def share_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID, req: AccessRequest) -> dict[str, Any]:
    """Sets who can access every document currently in the collection."""
    collection = _owned(conn, user, collection_id)
    access = build_access(user, req.kind, req.emails)
    document_ids = repository.list_collection_document_ids(conn, user["id"], collection_id)
    for document_id in document_ids:
        apply_access(conn, document_id, access)
    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action="share_collection",
        target=str(collection_id),
        detail={"name": collection["name"], "sharing": access[0], "people": len(access[1]) - 1, "documents": len(document_ids)},
        ip=None,
    )
    conn.commit()
    return {"success": True, "updated": len(document_ids)}

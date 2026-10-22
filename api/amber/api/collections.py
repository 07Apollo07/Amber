"""Collections: collaborative file lists whose members receive Drive access to their files."""

import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from amber import repository
from amber.util import drive
from amber.util.posthog import get_posthog_client
from amber.util.security import CsrfProtected, CurrentUser, DbDep

router = APIRouter(prefix="/api/collections", tags=["collections"])
EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class CollectionName(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class CollectionAccess(BaseModel):
    kind: str
    emails: list[str] = Field(default_factory=list, max_length=100)
    domain: str | None = None


class CollectionDocumentChange(BaseModel):
    included: bool


def _owned(conn: Any, user: dict[str, Any], collection_id: uuid.UUID) -> dict[str, Any]:
    collection = repository.get_collection(conn, user["id"], collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _editable(conn: Any, user: dict[str, Any], collection_id: uuid.UUID) -> dict[str, Any]:
    collection = repository.get_accessible_collection(
        conn, collection_id, user_email=user["email"], user_domain=user.get("domain")
    )
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _requested_members(req: CollectionAccess, owner_email: str) -> list[dict[str, str]]:
    if req.kind == "private":
        if req.emails or req.domain:
            raise HTTPException(status_code=400, detail="Private collections cannot include members")
        return []
    if req.kind == "people":
        clean = list(
            dict.fromkeys(email.strip().lower() for email in req.emails if email.strip().lower() != owner_email.lower())
        )
        if any(not EMAIL.match(email) for email in clean):
            raise HTTPException(status_code=400, detail="Enter valid email addresses for collection members")
        return [
            {"principal_type": "user", "principal_value": email, "drive_role": "reader"}
            for email in clean
        ]
    if req.kind == "domain" and req.domain:
        return [
            {
                "principal_type": "domain",
                "principal_value": req.domain.strip().lower(),
                "drive_role": "reader",
            }
        ]
    raise HTTPException(status_code=400, detail="Choose private access, specific people, or a domain")


def _drive_service_for(user: dict[str, Any], conn: Any) -> Any:
    service = drive.build_drive_service(user["id"], conn)
    if service is None:
        raise HTTPException(status_code=400, detail="Google Drive isn't connected. Reconnect it to share files.")
    return service


def _grant_principal(
    conn: Any,
    service: Any,
    document: dict[str, Any],
    member: dict[str, str],
) -> None:
    if not document.get("drive_file_id"):
        raise drive.DriveSharingError("This file has no Google Drive source to share.")
    permission_id = drive.ensure_drive_permission(
        service,
        document["drive_file_id"],
        member["principal_type"],
        member["principal_value"],
        member.get("drive_role", "reader"),
    )
    if permission_id:
        repository.save_collection_drive_grant(
            conn,
            document["id"],
            member["principal_type"],
            member["principal_value"],
            permission_id,
        )
    _sync_local_document_acl(conn, service, document)


def _sync_local_document_acl(conn: Any, service: Any, document: dict[str, Any]) -> None:
    if not document.get("drive_file_id"):
        return
    try:
        grants = drive.fetch_drive_permissions(service, document["drive_file_id"])
    except Exception as exc:
        raise drive.DriveSharingError(
            f"Google Drive permissions couldn't be refreshed for {document['title']}."
        ) from exc
    owner_email = (document.get("drive_owner_email") or "").lower()
    if owner_email and not any(
        grant.get("grant_type") == "user" and grant.get("grantee", "").lower() == owner_email
        for grant in grants
    ):
        grants.append({"grant_type": "user", "grantee": owner_email})
    repository.set_document_access(
        conn,
        document["id"],
        [
            {
                "principal_type": grant["grant_type"],
                "principal_value": grant["grantee"],
                "origin": "drive_sync",
            }
            for grant in grants
            if grant.get("grant_type") in ("user", "domain") and grant.get("grantee")
        ],
    )
    sharing_option = drive.sharing_option_for_grants(grants, owner_email)
    if sharing_option:
        repository.set_document_sharing_option(conn, document["id"], sharing_option)


def _revoke_unused_grant(
    conn: Any,
    service: Any,
    document: dict[str, Any],
    member: dict[str, str],
) -> None:
    principal_type = member["principal_type"]
    principal_value = member["principal_value"]
    if repository.count_collection_grant_references(conn, document["id"], principal_type, principal_value):
        return
    grant = repository.get_collection_drive_grant(conn, document["id"], principal_type, principal_value)
    if grant is None:
        return
    if document.get("drive_file_id"):
        drive.remove_drive_permission(service, document["drive_file_id"], grant["permission_id"])
        _sync_local_document_acl(conn, service, document)
    repository.delete_collection_drive_grant(conn, document["id"], principal_type, principal_value)


def _audit(conn: Any, user: dict[str, Any], action: str, collection_id: uuid.UUID, detail: dict[str, Any]) -> None:
    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action=action,
        target=str(collection_id),
        detail=detail,
        ip=None,
    )


@router.post("", dependencies=[CsrfProtected])
def create_collection(user: CurrentUser, conn: DbDep, req: CollectionName) -> dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Collection name can't be empty")
    if repository.get_collection_by_name(conn, user["id"], name):
        raise HTTPException(status_code=409, detail=f"You already have a collection called “{name}”")
    row = repository.create_collection(conn, user["id"], name)
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture("collection_created")
    return {"id": str(row["id"]), "name": row["name"], "is_owner": True, "role": "owner"}


@router.get("")
def list_collections(user: CurrentUser, conn: DbDep) -> dict[str, Any]:
    return {
        "collections": [
            {"id": str(row["id"]), "name": row["name"]}
            for row in repository.list_collections(conn, user["id"])
        ]
    }


@router.put("/{collection_id}", dependencies=[CsrfProtected])
def rename_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID, req: CollectionName) -> dict[str, Any]:
    _owned(conn, user, collection_id)
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Collection name can't be empty")
    clash = repository.get_collection_by_name(conn, user["id"], name)
    if clash and clash["id"] != collection_id:
        raise HTTPException(status_code=409, detail=f"You already have a collection called “{clash['name']}”")
    repository.rename_collection(conn, collection_id, name)
    conn.commit()
    return {"id": str(collection_id), "name": name}


@router.delete("/{collection_id}", dependencies=[CsrfProtected])
def delete_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID) -> dict[str, Any]:
    """Deletes the collection and removes grants Amber created for its members when no other collection needs them."""
    collection = _owned(conn, user, collection_id)
    documents = [
        document
        for document_id in repository.list_collection_document_ids(conn, user["id"], collection_id)
        if (document := repository.get_document(conn, document_id)) is not None
    ]
    members = repository.list_collection_members(conn, collection_id)
    service = _drive_service_for(user, conn) if members and any(d.get("drive_file_id") for d in documents) else None
    failures = []
    for member in members:
        principal = {
            "principal_type": member["principal_type"],
            "principal_value": member["principal_value"],
        }
        repository.remove_collection_member(
            conn, collection_id, principal["principal_type"], principal["principal_value"]
        )
        for document in documents:
            try:
                _revoke_unused_grant(conn, service, document, principal)
            except drive.DriveSharingError as exc:
                failures.append({"title": document["title"], "member": principal["principal_value"], "error": str(exc)})
    repository.delete_collection(conn, collection_id)
    _audit(conn, user, "delete_collection", collection_id, {"name": collection["name"], "failed": len(failures)})
    conn.commit()
    return {"success": True, "failed": failures}


@router.put("/{collection_id}/access", dependencies=[CsrfProtected])
def share_collection(user: CurrentUser, conn: DbDep, collection_id: uuid.UUID, req: CollectionAccess) -> dict[str, Any]:
    """Adds/removes collection members and propagates their Drive access to every current collection file."""
    collection = _owned(conn, user, collection_id)
    requested = _requested_members(req, user["email"])
    existing = repository.list_collection_members(conn, collection_id)
    existing_by_key = {(m["principal_type"], m["principal_value"]): dict(m) for m in existing}
    requested_by_key = {
        (m["principal_type"], m["principal_value"]): m for m in requested
    }
    documents = [
        document
        for document_id in repository.list_collection_document_ids(conn, user["id"], collection_id)
        if (document := repository.get_document(conn, document_id)) is not None
    ]
    has_membership_changes = set(requested_by_key) != set(existing_by_key)
    service = (
        _drive_service_for(user, conn)
        if has_membership_changes and any(document.get("drive_file_id") for document in documents)
        else None
    )
    failed: list[dict[str, str]] = []
    added = 0
    removed = 0

    for key, member in requested_by_key.items():
        if key in existing_by_key:
            continue
        member_failures = []
        for document in documents:
            try:
                _grant_principal(conn, service, document, member)
            except drive.DriveSharingError as exc:
                member_failures.append({"title": document["title"], "error": str(exc)})
        if member_failures:
            for document in documents:
                try:
                    _revoke_unused_grant(conn, service, document, member)
                except drive.DriveSharingError as exc:
                    failed.append({"title": document["title"], "error": str(exc)})
            failed.extend(
                {"title": item["title"], "error": f"{member['principal_value']}: {item['error']}"}
                for item in member_failures
            )
            continue
        repository.add_collection_member(conn, collection_id, member)
        added += 1

    for key, member in existing_by_key.items():
        if key in requested_by_key:
            continue
        repository.remove_collection_member(conn, collection_id, member["principal_type"], member["principal_value"])
        removed += 1
        for document in documents:
            try:
                _revoke_unused_grant(conn, service, document, member)
            except drive.DriveSharingError as exc:
                failed.append(
                    {"title": document["title"], "error": f"{member['principal_value']}: {exc}"}
                )

    _audit(
        conn,
        user,
        "share_collection",
        collection_id,
        {"name": collection["name"], "added": added, "removed": removed, "failed": len(failed)},
    )
    conn.commit()
    client = get_posthog_client()
    if client:
        client.capture(
            "collection_shared",
            properties={
                "access_kind": req.kind,
                "added_count": added,
                "removed_count": removed,
                "failed_count": len(failed),
                "document_count": len(documents),
            },
        )
    return {"success": True, "added": added, "removed": removed, "failed": failed}


@router.put("/{collection_id}/documents/{document_id}", dependencies=[CsrfProtected])
def change_collection_document(
    user: CurrentUser,
    conn: DbDep,
    collection_id: uuid.UUID,
    document_id: uuid.UUID,
    req: CollectionDocumentChange,
) -> dict[str, Any]:
    """Adds/removes a file in a collection; collection member grants are applied additively in Drive."""
    _editable(conn, user, collection_id)
    repository.set_app_user_context(conn, user["email"], user.get("domain"))
    document = repository.get_document(conn, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if not document.get("drive_file_id"):
        raise HTTPException(status_code=400, detail="Only Google Drive files can be added to shared collections.")

    members = repository.list_collection_members(conn, collection_id)
    service = _drive_service_for(user, conn) if members else None
    failed = []
    if req.included:
        for member in members:
            try:
                _grant_principal(conn, service, document, dict(member))
            except drive.DriveSharingError as exc:
                failed.append({"member": member["principal_value"], "error": str(exc)})
        if failed:
            for member in members:
                try:
                    _revoke_unused_grant(conn, service, document, dict(member))
                except drive.DriveSharingError as exc:
                    failed.append({"member": member["principal_value"], "error": str(exc)})
            conn.commit()
            return {"success": False, "failed": failed}
        repository.add_document_to_collection(conn, collection_id, document_id)
    else:
        repository.remove_document_from_collection(conn, collection_id, document_id)
        for member in members:
            try:
                _revoke_unused_grant(conn, service, document, dict(member))
            except drive.DriveSharingError as exc:
                failed.append({"member": member["principal_value"], "error": str(exc)})

    _audit(
        conn,
        user,
        "organize_collection_document",
        collection_id,
        {"document_id": str(document_id), "included": req.included, "failed": len(failed)},
    )
    conn.commit()
    return {"success": not failed, "failed": failed}

"""Google Drive API router: importing files from Drive Picker and syncing changes."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from amber import repository
from amber.api.documents import apply_organization
from amber.util import drive
from amber.util.security import CsrfProtected, CurrentUser, DbDep

router = APIRouter(prefix="/api/drive", tags=["drive"])


class DriveImportRequest(BaseModel):
    file_ids: list[str]
    collection: str | None = None
    tags: list[str] = []


@router.get("/files")
def list_drive_files(
    user: CurrentUser,
    conn: DbDep,
    q: str | None = None,
    folder_id: str | None = "root",
) -> dict[str, Any]:
    """Lists files and folders from the user's Google Drive for the picker, including vector store sync status."""
    drive_service = drive.build_drive_service(user["id"], conn)
    if not drive_service:
        raise HTTPException(status_code=400, detail="Google Drive is not connected for this user")

    if q:
        query = f"trashed = false and name contains '{q}'"
    else:
        target_folder = folder_id or "root"
        query = f"'{target_folder}' in parents and trashed = false"

    try:
        response = (
            drive_service.files()
            .list(
                q=query,
                pageSize=100,
                fields="files(id, name, mimeType, size, webViewLink, modifiedTime, parents)",
                orderBy="folder,name",
            )
            .execute()
        )
        files = response.get("files", [])

        # Fetch current folder name if not root and no search query
        current_folder_name = "My Drive"
        if not q and folder_id and folder_id != "root":
            try:
                folder_meta = drive_service.files().get(fileId=folder_id, fields="name").execute()
                current_folder_name = folder_meta.get("name", "Folder")
            except Exception:
                pass

        enriched_files = []
        for f in files:
            file_id = f["id"]
            mime_type = f.get("mimeType", "")
            is_folder = mime_type == "application/vnd.google-apps.folder"
            
            doc = None
            if not is_folder:
                doc = repository.get_document_by_drive_file_id(conn, user["id"], file_id)

            synced = doc is not None and doc.get("status") == "indexed"
            enriched_files.append({
                **f,
                "is_folder": is_folder,
                "synced": synced,
                "document_id": str(doc["id"]) if doc else None,
            })

        return {
            "files": enriched_files,
            "current_folder_id": folder_id or "root",
            "current_folder_name": current_folder_name,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list Google Drive files: {exc}") from exc


@router.post("/import", dependencies=[CsrfProtected])
def import_drive_files(user: CurrentUser, conn: DbDep, req: DriveImportRequest) -> dict[str, Any]:
    """Imports files selected from Google Drive Picker, downloads content, fetches ACLs, and indexes them."""
    drive_service = drive.build_drive_service(user["id"], conn)
    if not drive_service:
        raise HTTPException(status_code=400, detail="Google Drive is not connected for this user")

    imported = []
    for file_id in req.file_ids:
        try:
            # Get file metadata
            file_meta = (
                drive_service.files()
                .get(fileId=file_id, fields="id, name, mimeType, size, webViewLink")
                .execute()
            )
            filename = file_meta.get("name", "Untitled")
            mime_type = file_meta.get("mimeType", "application/octet-stream")

            # Export Google Docs/Sheets/Slides to export formats if needed, or get media content
            if mime_type.startswith("application/vnd.google-apps."):
                if mime_type == "application/vnd.google-apps.document":
                    mime_type = "application/pdf"
                    request_obj = drive_service.files().export_media(fileId=file_id, mimeType=mime_type)
                    filename += ".pdf"
                elif mime_type == "application/vnd.google-apps.spreadsheet":
                    mime_type = "application/pdf"
                    request_obj = drive_service.files().export_media(fileId=file_id, mimeType=mime_type)
                    filename += ".pdf"
                else:
                    continue  # Skip unsupported google apps types for now
            else:
                request_obj = drive_service.files().get_media(fileId=file_id)

            file_bytes = request_obj.execute()

            # Fetch file permissions
            grants = drive.fetch_drive_permissions(drive_service, file_id)
            if not grants:
                grants = [{"grant_type": "user", "grantee": user["email"].lower()}]

            # Process upload without re-uploading to Drive (since it's already in Drive)
            # We can invoke pipeline steps directly or via process_document_upload with sync_to_drive=False
            import hashlib

            checksum = hashlib.sha256(file_bytes).hexdigest()
            size_bytes = len(file_bytes)

            doc_row = repository.upsert_document(
                conn,
                owner_id=user["id"],
                origin="drive_sync",
                drive_file_id=file_id,
                title=filename,
                file_type=filename.split(".")[-1].lower() if "." in filename else "unknown",
                file_size_bytes=size_bytes,
                mime_type=mime_type,
                sha256=checksum,
                status="indexing",
                sharing_option="private",
            )
            doc_id = doc_row["id"]

            repository.set_document_access(
                conn,
                doc_id,
                [
                    {
                        "principal_type": g.get("grant_type", "user"),
                        "principal_value": g.get("grantee", user["email"].lower()),
                        "origin": "drive_sync",
                    }
                    for g in grants
                ],
            )

            from amber.ingest.chunker import chunk_document_blocks
            from amber.ingest.embedder import generate_embeddings
            from amber.ingest.parser import parse_document

            blocks = parse_document(file_bytes, mime_type, filename)
            chunks_data = chunk_document_blocks(blocks)
            texts = [c["content"] for c in chunks_data]
            embeddings = generate_embeddings(texts)

            repository.delete_chunks_for_document(conn, doc_id)
            for idx, chunk in enumerate(chunks_data):
                emb = embeddings[idx] if idx < len(embeddings) else None
                repository.insert_chunk(
                    conn,
                    document_id=doc_id,
                    ord=idx,
                    text=chunk["content"],
                    page=chunk.get("metadata", {}).get("page"),
                    embedding=emb,
                )

            # Mark as successfully indexed
            repository.update_document_status(conn, doc_id, "indexed")

            apply_organization(conn, user, doc_id, collection=req.collection, tags=req.tags)

            imported.append({"document_id": str(doc_id), "file_id": file_id, "title": filename})
        except Exception as exc:
            # Log error per file and mark as failed in db if doc_id was created
            print(f"Error importing Drive file {file_id}: {exc}")
            if 'doc_id' in locals() and doc_id:
                try:
                    repository.update_document_status(conn, doc_id, "failed", status_message=str(exc))
                except Exception:
                    pass
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    repository.insert_audit(
        conn,
        actor_user_id=user["id"],
        actor_email=user["email"],
        action="import_drive_files",
        target=str(req.file_ids),
        detail={"imported_count": len(imported)},
        ip=None,
    )
    conn.commit()
    return {"success": True, "imported": imported}

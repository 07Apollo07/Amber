"""Ingestion pipeline orchestrator: parsing, Drive upload/ACL sync, chunking, embedding, and database storage."""

import hashlib
import uuid
from typing import Any

from amber import repository
from amber.ingest.chunker import chunk_document_blocks
from amber.ingest.embedder import generate_embeddings
from amber.ingest.parser import parse_document
from amber.util import db, drive
from amber.util.config import get_settings


def process_document_upload(
    user_id: uuid.UUID,
    file_bytes: bytes,
    filename: str,
    mime_type: str,
    sync_to_drive: bool = True,
    initial_grants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Orchestrates local/desktop file upload, Drive backup/sync, parsing, chunking, embedding, and DB insertion."""
    checksum = hashlib.sha256(file_bytes).hexdigest()
    size_bytes = len(file_bytes)

    with db.connect(get_settings()) as conn:
        drive_file_id = None
        source_url = None
        grants = initial_grants or [{"grant_type": "user", "grantee": None}]  # default private to uploader

        if sync_to_drive:
            drive_service = drive.build_drive_service(user_id, conn)
            if drive_service:
                try:
                    folder_id = drive.get_or_create_amber_uploads_folder(drive_service)
                    drive_file = drive.upload_file_to_drive(drive_service, file_bytes, filename, mime_type, folder_id)
                    drive_file_id = drive_file.get("id")
                    source_url = drive_file.get("webViewLink")

                    # Fetch permissions from Drive to keep ACLs in sync
                    if drive_file_id:
                        drive_perms = drive.fetch_drive_permissions(drive_service, drive_file_id)
                        if drive_perms:
                            grants = drive_perms
                except Exception as exc:
                    # If Drive upload fails, raise error per PLAN.md:
                    # "Every desktop upload is also saved to the uploader's Google Drive... If failed, status failed."
                    raise RuntimeError(f"Failed to save file to Google Drive: {exc}") from exc

        origin = "drive_sync" if drive_file_id else "desktop_upload"

        # 1. Upsert document record
        doc_row = repository.upsert_document(
            conn,
            owner_id=user_id,
            origin=origin,
            drive_file_id=drive_file_id,
            title=filename,
            file_type=filename.split(".")[-1].lower() if "." in filename else "unknown",
            file_size_bytes=size_bytes,
            mime_type=mime_type,
            sha256=checksum,
            status="indexed",
            sharing_option="private",
        )
        doc_id = doc_row["id"]

        # 2. Set document access ACL
        formatted_grants = [
            {
                "principal_type": g.get("grant_type", "user"),
                "principal_value": g.get("grantee"),
                "origin": "drive_sync" if drive_file_id else "manual",
            }
            for g in grants
            if g.get("grantee") is not None or g.get("grant_type") == "domain"
        ]
        if not formatted_grants:
            # Fallback to user email if available
            user_row = repository.get_user(conn, user_id)
            if user_row:
                formatted_grants = [{"principal_type": "user", "principal_value": user_row["email"].lower(), "origin": "manual"}]

        repository.set_document_access(conn, doc_id, formatted_grants)

        # 3. Parse document into blocks
        blocks = parse_document(file_bytes, mime_type, filename)

        # 4. Chunk blocks
        chunks_data = chunk_document_blocks(blocks)

        # 5. Generate embeddings in batches
        texts = [c["content"] for c in chunks_data]
        embeddings = generate_embeddings(texts)

        # 6. Delete existing chunks and insert new ones
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

        conn.commit()
        return {
            "document_id": str(doc_id),
            "external_id": external_id,
            "title": filename,
            "chunks_count": len(chunks_data),
            "drive_file_id": drive_file_id,
        }

"""Ingestion pipeline orchestrator: parsing, Drive upload/ACL sync, chunking, embedding, and database storage."""

import hashlib
import uuid
from typing import Any

from amber import repository
from amber.ingest import settings as indexing_settings
from amber.ingest.chunker import chunk_document_blocks
from amber.ingest.embedder import generate_embeddings
from amber.ingest.parser import parse_document
from amber.util import db, drive
from amber.util.config import get_settings


class IndexingError(Exception):
    """Indexing a document failed. The message says which step and why, and is stored on the document."""


def index_document_content(conn: Any, doc_id: uuid.UUID, file_bytes: bytes, mime_type: str, filename: str) -> int:
    """Parses, chunks, embeds and stores the document's text. Returns the number of chunks stored."""
    stage = "reading the file"
    try:
        blocks = parse_document(file_bytes, mime_type, filename)
        stage = "splitting the text into chunks"
        cfg = indexing_settings.load(conn)
        chunks_data = chunk_document_blocks(blocks, cfg.chunk_size_tokens, cfg.chunk_overlap_tokens)
        if not chunks_data:
            raise IndexingError(
                "No readable text was found in this file. It may be a scan or image-only document, or it may be empty."
            )
        stage = "generating embeddings"
        embeddings = generate_embeddings([c["content"] for c in chunks_data])
        stage = "saving the chunks to the database"
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
    except IndexingError:
        raise
    except Exception as exc:
        raise IndexingError(f"Failed while {stage}: {type(exc).__name__}: {exc}") from exc
    return len(chunks_data)


def mark_document_failed(conn: Any, doc_id: uuid.UUID, message: str) -> None:
    """Discards the half-finished work and keeps the document, flagged failed, so the user can see why."""
    conn.rollback()
    repository.delete_chunks_for_document(conn, doc_id)
    repository.update_document_status(conn, doc_id, "failed", status_message=message[:2000])
    conn.commit()


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
        user_row = repository.get_user(conn, user_id)

        # 1. Upsert document record
        doc_row = repository.upsert_document(
            conn,
            owner_id=user_id,
            imported_by_user_id=user_id,
            drive_owner_email=user_row["email"] if drive_file_id and user_row else None,
            drive_owner_name=user_row["name"] if drive_file_id and user_row else None,
            origin=origin,
            drive_file_id=drive_file_id,
            title=filename,
            file_type=filename.split(".")[-1].lower() if "." in filename else "unknown",
            file_size_bytes=size_bytes,
            mime_type=mime_type,
            sha256=checksum,
            status="indexing",
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
            # Files without a Drive source retain the uploader's access.
            if user_row and not drive_file_id:
                formatted_grants = [{"principal_type": "user", "principal_value": user_row["email"].lower(), "origin": "manual"}]

        repository.set_document_access(conn, doc_id, formatted_grants)

        conn.commit()  # keep the document even if indexing fails below, so its error can be shown

        # 3-6. Parse, chunk, embed and store
        try:
            chunks_count = index_document_content(conn, doc_id, file_bytes, mime_type, filename)
        except IndexingError as exc:
            mark_document_failed(conn, doc_id, str(exc))
            raise
        repository.update_document_status(conn, doc_id, "indexed")
        conn.commit()
        return {
            "document_id": str(doc_id),
            "title": filename,
            "chunks_count": chunks_count,
            "drive_file_id": drive_file_id,
        }

"""Agent tools: user-scoped document search, source retrieval, and web search."""

import base64
import binascii
import hashlib
import io
import json
import logging
import math
import re
import uuid
from typing import Annotated, Literal
from urllib.parse import urlparse

import httpx
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command, interrupt

from amber import repository
from amber.ingest import settings as indexing_settings
from amber.ingest.embedder import generate_embeddings
from amber.ingest.parser import parse_document
from amber.models import DRIVE_SCOPE
from amber.util import drive
from amber.util.config import get_settings
from amber.util.db import connect

MAX_SOURCE_CHARS = 80_000
MAX_WORKSPACE_CELLS = 2_000
MAX_API_OPERATIONS = 50
MAX_APPROVAL_PREVIEW_CHARS = 12_000
MAX_DRIVE_UPLOAD_BYTES = 10 * 1024 * 1024
log = logging.getLogger(__name__)


def _emit_task(task_id: str, title: str, status: str) -> None:
    from langgraph.config import get_stream_writer

    get_stream_writer()({"type": "task_update", "id": task_id, "title": title, "status": status})


def _normalize_agent_tasks(tasks: list[dict]) -> list[dict]:
    if not isinstance(tasks, list) or len(tasks) > 20:
        raise ValueError("The task plan must contain no more than 20 tasks.")
    normalized = []
    seen_ids = set()
    allowed_statuses = {"pending", "in_progress", "completed", "failed"}
    for task in tasks:
        if not isinstance(task, dict):
            raise ValueError("Each task must be an object with id, title, and status.")
        task_id = task.get("id")
        title = task.get("title")
        status = task.get("status")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", task_id):
            raise ValueError("Task IDs must be 1-64 letters, numbers, underscores, or hyphens.")
        if task_id in seen_ids:
            raise ValueError(f"Task ID {task_id!r} appears more than once.")
        if not isinstance(title, str) or not title.strip() or len(title) > 160:
            raise ValueError("Task titles must contain 1-160 characters.")
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError(f"Task status must be one of: {', '.join(sorted(allowed_statuses))}.")
        seen_ids.add(task_id)
        normalized.append({"id": task_id, "title": title.strip(), "status": status})
    return normalized


@tool
def update_task_list(
    tasks: list[dict],
    update_summary: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Create or update the visible task plan for multi-step work.

    Pass the full current plan. Each task needs id, title, and status:
    [{"id":"find-source","title":"Find the relevant source","status":"in_progress"},
     {"id":"review-data","title":"Review the source data","status":"pending"}]
    Use stable IDs when updating tasks; statuses are pending, in_progress, completed, or failed.
    """
    if not isinstance(update_summary, str) or not update_summary.strip() or len(update_summary) > 240:
        raise ValueError("Provide a brief explanation of this task-plan update.")
    normalized = _normalize_agent_tasks(tasks)
    from langgraph.config import get_stream_writer

    get_stream_writer()(
        {
            "type": "task_plan",
            "tasks": normalized,
            "update_summary": update_summary.strip(),
        }
    )
    return Command(
        update={
            "tasks": normalized,
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "updated": True,
                            "update_summary": update_summary.strip(),
                            "tasks": normalized,
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


def _validate_visual_rows(rows: list[dict], *, max_rows: int = 100) -> list[dict]:
    if not isinstance(rows, list) or not rows or len(rows) > max_rows:
        raise ValueError(f"Visual data must contain between 1 and {max_rows} rows.")
    normalized_rows = []
    for row in rows:
        if not isinstance(row, dict) or not row or len(row) > 20:
            raise ValueError("Each visual data row must be a non-empty object with at most 20 fields.")
        normalized = {}
        for key, value in row.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 80:
                raise ValueError("Visual data field names must contain 1-80 characters.")
            if isinstance(value, (dict, list)) or not isinstance(value, (str, int, float, bool, type(None))):
                raise ValueError("Visual data values must be strings, numbers, booleans, or null.")
            if isinstance(value, str) and len(value) > 2000:
                raise ValueError("Visual data text values must be no longer than 2,000 characters.")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("Visual data numbers must be finite.")
            normalized[key.strip()] = value
        normalized_rows.append(normalized)
    return normalized_rows


def _publish_visual(
    *,
    tool_call_id: str,
    kind: str,
    title: str,
    description: str,
    content: dict,
) -> Command:
    if not title.strip() or len(title) > 160:
        raise ValueError("Visual titles must contain 1-160 characters.")
    if len(description) > 500:
        raise ValueError("Visual descriptions must be no longer than 500 characters.")
    visual = {
        "id": tool_call_id,
        "kind": kind,
        "title": title.strip(),
        "description": description.strip(),
        **content,
    }
    from langgraph.config import get_stream_writer

    get_stream_writer()({"type": "generative_ui", "visual": visual})
    return Command(
        update={
            "visuals": {tool_call_id: visual},
            "messages": [
                ToolMessage(
                    content=f"Rendered {kind} visual: {title.strip()}",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def render_chart(
    title: str,
    chart_type: Literal["bar", "line", "area", "donut"],
    category_key: str,
    series: list[str],
    rows: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render an interactive chart, especially when the user explicitly asks for a chart.

    Supply rows as objects keyed by category_key and series names, for example:
    [{"month":"Jan","revenue":120,"cost":80},{"month":"Feb","revenue":150,"cost":95}].
    For explicit chart requests, call this tool instead of returning a text/ASCII chart.
    Use only values returned by a data/source tool or provided by the user; do not invent data.
    If no reliable data is available, ask the user for the data before rendering.
    """
    normalized_rows = _validate_visual_rows(rows)
    if not category_key or len(category_key) > 80:
        raise ValueError("Provide a valid category_key for the chart.")
    if not isinstance(series, list) or not 1 <= len(series) <= 6:
        raise ValueError("Charts must include 1-6 numeric series.")
    if chart_type == "donut" and len(series) != 1:
        raise ValueError("Donut charts require exactly one numeric series.")
    if any(not isinstance(key, str) or not key.strip() for key in series):
        raise ValueError("Chart series names must be non-empty strings.")
    if len(set(series)) != len(series) or category_key in series:
        raise ValueError("Chart series must be unique and distinct from the category key.")
    for row in normalized_rows:
        if category_key not in row:
            raise ValueError(f"Chart row is missing the category field {category_key!r}.")
        for key in series:
            value = row.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"Chart field {key!r} must contain finite numbers in every row.")
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="chart",
        title=title,
        description=description,
        content={
            "chart_type": chart_type,
            "category_key": category_key,
            "series": series,
            "rows": normalized_rows,
        },
    )


@tool
def render_table(
    title: str,
    columns: list[str],
    rows: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render a compact table for structured source data, search results, or comparisons."""
    normalized_rows = _validate_visual_rows(rows)
    if not isinstance(columns, list) or not 1 <= len(columns) <= 12:
        raise ValueError("Tables must have 1-12 columns.")
    if any(not isinstance(column, str) or not column.strip() for column in columns):
        raise ValueError("Table column names must be non-empty strings.")
    if len(set(columns)) != len(columns):
        raise ValueError("Table column names must be non-empty and unique.")
    if any(column not in row for row in normalized_rows for column in columns):
        raise ValueError("Every table row must contain all declared columns.")
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="table",
        title=title,
        description=description,
        content={"columns": [column.strip()[:80] for column in columns], "rows": normalized_rows},
    )


@tool
def render_metric_cards(
    title: str,
    metrics: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render KPI cards for a few important values and optional changes or context."""
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 8:
        raise ValueError("Provide between 1 and 8 metrics.")
    normalized = []
    for metric in metrics:
        if not isinstance(metric, dict):
            raise ValueError("Each metric must be an object.")
        label, value = metric.get("label"), metric.get("value")
        if not isinstance(label, str) or not label.strip() or len(label) > 80:
            raise ValueError("Each metric needs a label of 1-80 characters.")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError("Metric values must be strings or numbers.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Metric numbers must be finite.")
        item = {"label": label.strip(), "value": value}
        for key in ("change", "detail"):
            field_value = metric.get(key)
            if field_value is not None:
                if not isinstance(field_value, str) or len(field_value) > 160:
                    raise ValueError(f"Metric {key} must be a string of at most 160 characters.")
                item[key] = field_value
        trend = metric.get("trend")
        if trend is not None:
            if trend not in ("up", "down", "neutral"):
                raise ValueError("Metric trend must be up, down, or neutral.")
            item["trend"] = trend
        normalized.append(item)
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="metrics",
        title=title,
        description=description,
        content={"metrics": normalized},
    )


@tool
def render_comparison(
    title: str,
    columns: list[str],
    rows: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render a side-by-side comparison of source-backed documents, options, or data."""
    normalized_rows = _validate_visual_rows(rows, max_rows=30)
    if not isinstance(columns, list) or not 2 <= len(columns) <= 5:
        raise ValueError("Comparisons must have 2-5 columns.")
    if any(not isinstance(column, str) or not column.strip() for column in columns):
        raise ValueError("Comparison column names must be non-empty strings.")
    if len(set(columns)) != len(columns):
        raise ValueError("Comparison column names must be non-empty and unique.")
    if any(column not in row for row in normalized_rows for column in columns):
        raise ValueError("Every comparison row must contain all declared columns.")
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="comparison",
        title=title,
        description=description,
        content={"columns": [column.strip()[:80] for column in columns], "rows": normalized_rows},
    )


@tool
def render_timeline(
    title: str,
    events: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render a timeline of events extracted from sources.

    Each event should provide a date or date label and an event name/title.
    Dates may be ISO dates, years, month names, or other concise source labels;
    they are displayed as supplied and are not parsed or required to match a format.
    Accepted date keys: date, date_label, timestamp, or time.
    Accepted event-name keys: event, title, or label. Details are optional.
    Example: {"date":"Q1 2024","title":"Company launched","details":"Source-backed context"}.
    """
    if not isinstance(events, list) or not 1 <= len(events) <= 50:
        raise ValueError("Timelines must contain 1-50 events.")
    normalized = []
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Each timeline event must be an object.")
        date = next(
            (event[key] for key in ("date", "date_label", "timestamp", "time") if event.get(key) is not None),
            None,
        )
        label = next(
            (event[key] for key in ("event", "title", "label") if event.get(key) is not None),
            None,
        )
        details = next(
            (event[key] for key in ("details", "description", "summary") if event.get(key) is not None),
            "",
        )
        if isinstance(date, bool) or not isinstance(date, (str, int, float)) or not str(date).strip():
            raise ValueError("Each timeline event needs a date or date label.")
        if len(str(date)) > 200:
            raise ValueError("Timeline date labels must be no longer than 200 characters.")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Each timeline event needs a non-empty event title.")
        if len(label) > 500:
            raise ValueError("Timeline event titles must be no longer than 500 characters.")
        if not isinstance(details, str):
            raise ValueError("Timeline event details must be text.")
        if len(details) > 2000:
            raise ValueError("Timeline event details must be no longer than 2,000 characters.")
        normalized.append(
            {
                "date": str(date).strip(),
                "event": label.strip(),
                "details": details.strip(),
            }
        )
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="timeline",
        title=title,
        description=description,
        content={"events": normalized},
    )


@tool
def render_source_cards(
    title: str,
    sources: list[dict],
    description: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Render source cards with relevant excerpts for documents found by Amber."""
    if not isinstance(sources, list) or not 1 <= len(sources) <= 10:
        raise ValueError("Provide between 1 and 10 source cards.")
    normalized = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Each source must be an object.")
        name, excerpt = source.get("title"), source.get("excerpt")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Each source needs a title of 1-200 characters.")
        if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 1000:
            raise ValueError("Each source needs an excerpt of 1-1,000 characters.")
        item = {"title": name.strip(), "excerpt": excerpt.strip()}
        url = source.get("url")
        if url is not None:
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError("Source URLs must be valid HTTPS Google Workspace URLs.")
            parsed_url = urlparse(url)
            if parsed_url.scheme != "https" or parsed_url.hostname not in {
                "drive.google.com",
                "docs.google.com",
            }:
                raise ValueError("Source URLs must be valid HTTPS Google Workspace URLs.")
            item["url"] = url
        normalized.append(item)
    return _publish_visual(
        tool_call_id=tool_call_id,
        kind="sources",
        title=title,
        description=description,
        content={"sources": normalized},
    )


@tool
def vector_search(
    query: str,
    user_email: Annotated[str, InjectedState("user_email")],
    user_domain: Annotated[str | None, InjectedState("user_domain")],
    collection_id: Annotated[str | None, InjectedState("collection_id")],
) -> str:
    """Search internal documents using hybrid vector cosine distance and full-text search."""
    _emit_task("find-files", "Find relevant files", "in_progress")
    settings = get_settings()
    embeddings = generate_embeddings([query])
    if not embeddings:
        _emit_task("find-files", "Find relevant files", "failed")
        return "No internal embeddings generated."

    with connect(settings) as conn:
        results = repository.hybrid_search_chunks(
            conn,
            user_email=user_email,
            user_domain=user_domain,
            query_embedding=embeddings[0],
            query_text=query,
            limit=5,
            collection_ids=[uuid.UUID(collection_id)] if collection_id else None,
        )

    if not results:
        _emit_task("find-files", "Find relevant files", "completed")
        return "No relevant internal documents found."

    formatted = []
    for r in results:
        content = r.get("content", "")
        doc_id = r.get("document_id", "unknown")
        doc_title = r.get("document_title", "Untitled")
        file_type = r.get("file_type", "unknown")
        page = r.get("page")
        drive_file_id = r.get("drive_file_id")
        drive_url = f"https://drive.google.com/file/d/{drive_file_id}/view" if drive_file_id else None

        source_header = f"[Source: {doc_title} (Document ID: {doc_id}, Type: {file_type}"
        if page is not None:
            source_header += f", Page: {page}"
        if drive_url:
            source_header += f", Drive Link: {drive_url}"
        source_header += "]"

        formatted.append(f"{source_header}\n{content}")
    _emit_task("find-files", "Find relevant files", "completed")
    return "\n\n".join(formatted)


@tool
def drive_search_files(
    name_contains: str = "",
    mime_type: str = "",
    parent_id: str = "",
    owner_email: str = "",
    full_text_contains: str = "",
    modified_after: str = "",
    page_size: int = 20,
    page_token: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Search files and folders available to Amber through the signed-in user's drive.file grant."""
    _emit_task("find-files", "Search selected Drive files", "in_progress")
    try:
        if not 1 <= page_size <= 50:
            raise ValueError("Page size must be between 1 and 50.")
        clauses = ["trashed = false"]
        if name_contains:
            clauses.append(f"name contains '{_drive_query_literal(name_contains[:200])}'")
        if mime_type:
            clauses.append(f"mimeType = '{_drive_query_literal(mime_type[:200])}'")
        if parent_id:
            clauses.append(f"'{_drive_query_literal(parent_id[:200])}' in parents")
        if owner_email:
            clauses.append(f"'{_drive_query_literal(owner_email[:320].lower())}' in owners")
        if full_text_contains:
            clauses.append(f"fullText contains '{_drive_query_literal(full_text_contains[:200])}'")
        if modified_after:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", modified_after):
                raise ValueError("modified_after must be an ISO 8601 UTC timestamp ending in Z.")
            clauses.append(f"modifiedTime > '{modified_after}'")
        service = _drive_service(user_id)
        result = (
            service.files()
            .list(
                q=" and ".join(clauses),
                pageSize=page_size,
                pageToken=page_token or None,
                orderBy="modifiedTime desc",
                fields="nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime,size,parents,owners(displayName,emailAddress),capabilities(canEdit,canShare,canDownload))",
                spaces="drive",
            )
            .execute()
        )
        _emit_task("find-files", "Search selected Drive files", "completed")
        return json.dumps(
            {
                "files": result.get("files", []),
                "next_page_token": result.get("nextPageToken"),
                "scope_note": "Results are limited to Drive files selected for Amber or created by Amber.",
            },
            default=str,
        )
    except Exception:
        log.exception("Drive file search failed")
        _emit_task("find-files", "Search selected Drive files", "failed")
        raise


@tool
def drive_get_file(
    file_id: str,
    include_content: bool = False,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Read metadata and optionally parsed text content for a Drive file available to Amber."""
    _emit_task("read-source", "Read Drive file details", "in_progress")
    try:
        service = _drive_service(user_id)
        metadata = _require_file(service, file_id)
        output: dict = {"file": metadata}
        if include_content:
            if metadata.get("capabilities", {}).get("canDownload") is not True:
                raise ValueError("Google Drive does not allow this file to be downloaded.")
            max_bytes = _workspace_max_upload_bytes()
            if metadata.get("size") and int(metadata["size"]) > max_bytes:
                raise ValueError("This file exceeds the administrator's configured size limit.")
            mime_type = metadata.get("mimeType", "application/octet-stream")
            filename = metadata.get("name", "Drive file")
            if mime_type in drive.GOOGLE_EXPORTS:
                export_mime = drive.GOOGLE_EXPORTS[mime_type][1]
                data = service.files().export_media(fileId=file_id, mimeType=export_mime).execute()
                parse_name = filename + drive.GOOGLE_EXPORTS[mime_type][2]
                parse_mime = export_mime
            else:
                data = service.files().get_media(fileId=file_id).execute()
                parse_name = filename
                parse_mime = mime_type
            if len(data) > max_bytes:
                raise ValueError("This file exceeds the administrator's configured size limit.")
            blocks = parse_document(data, parse_mime, parse_name)
            text = "\n\n".join(block.get("content", "") for block in blocks).strip()
            output["content"] = text[:MAX_SOURCE_CHARS]
            output["truncated"] = len(text) > MAX_SOURCE_CHARS
        _emit_task("read-source", "Read Drive file details", "completed")
        return json.dumps(output, ensure_ascii=False, default=str)
    except Exception:
        log.exception("Drive file read failed for %s", file_id)
        _emit_task("read-source", "Read Drive file details", "failed")
        raise


@tool
def drive_export_file(
    file_id: str,
    export_mime_type: str,
    export_name: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose exporting a Google Doc or Sheet into a new downloadable Drive file."""
    service = _drive_service(user_id)
    metadata = _require_file(service, file_id)
    allowed_exports = {
        "application/vnd.google-apps.document": {
            "application/pdf",
            "text/plain",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        "application/vnd.google-apps.spreadsheet": {
            "application/pdf",
            "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
    }
    if export_mime_type not in allowed_exports.get(metadata.get("mimeType"), set()):
        raise ValueError("Choose a supported PDF, text/CSV, DOCX, or XLSX export for this Google file.")
    data = service.files().export_media(fileId=file_id, mimeType=export_mime_type).execute()
    if len(data) > MAX_DRIVE_UPLOAD_BYTES:
        raise ValueError("The export is larger than Amber's 10 MB workspace export limit.")
    title = export_name.strip()[:255]
    if not title:
        raise ValueError("Provide a name for the exported copy.")
    after = (
        f"Create {title} as {export_mime_type} ({len(data)} bytes) in the Amber Uploads Drive folder. "
        "If that folder does not exist, it will also be created."
    )
    operation_id = _approval_id(
        user_id, "drive_export", file_id, f"{export_mime_type}\0{title}\0{len(data)}", _drive_revision(metadata)
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="drive_export",
        title=title,
        url=metadata.get("webViewLink"),
        before=None,
        after=after,
    ):
        return "The user rejected this export. No Drive file was created."
    latest = _require_file(service, file_id)
    if _drive_revision(latest) != _drive_revision(metadata):
        _emit_task("drive-write", "Create the approved export", "failed")
        return "The source file changed after the export proposal. No copy was created; export it again."
    _emit_task("drive-write", "Create the approved export", "in_progress")
    try:
        uploaded = drive.upload_file_to_drive(
            service,
            data,
            title,
            export_mime_type,
        )
    except Exception:
        log.exception("Failed to create approved export for %s", file_id)
        _emit_task("drive-write", "Create the approved export", "failed")
        raise
    _emit_task("drive-write", "Create the approved export", "completed")
    return json.dumps(
        {
            "file": uploaded,
            "source_file_id": file_id,
            "exported_from": metadata.get("name"),
            "bytes": len(data),
        },
        default=str,
    )


@tool
def drive_create_folder(
    title: str,
    parent_id: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose creating a Drive folder, optionally inside a selected parent folder."""
    name = title.strip()[:255]
    if not name:
        raise ValueError("Provide a folder name.")
    service = _drive_service(user_id)
    parent_metadata = None
    if parent_id:
        parent_metadata = _require_file(
            service,
            parent_id,
            expected_mime="application/vnd.google-apps.folder",
            capability="canAddChildren",
        )
    after = json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder", "parent_id": parent_id or None})
    operation_id = _approval_id(user_id, "drive_create_folder", parent_id or "root", after)
    if not _approved_operation(
        operation_id=operation_id, kind="drive_create_folder", title=name, url=None, before=None, after=after
    ):
        return "The user rejected this folder creation. No folder was created."
    _emit_task("drive-write", "Create the approved Drive folder", "in_progress")
    try:
        body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            latest_parent = _require_file(
                service,
                parent_id,
                expected_mime="application/vnd.google-apps.folder",
                capability="canAddChildren",
            )
            if latest_parent.get("modifiedTime") != parent_metadata.get("modifiedTime"):
                _emit_task("drive-write", "Create the approved Drive folder", "failed")
                return "The destination folder changed after the proposal. No folder was created; inspect it and propose again."
            body["parents"] = [parent_id]
        created = service.files().create(
            body=body,
            fields="id,name,mimeType,webViewLink,parents",
        ).execute()
    except Exception:
        log.exception("Failed to create approved Drive folder %s", name)
        _emit_task("drive-write", "Create the approved Drive folder", "failed")
        raise
    _emit_task("drive-write", "Create the approved Drive folder", "completed")
    return json.dumps(created)


@tool
def drive_upload_text_file(
    title: str,
    content: str,
    mime_type: str = "text/plain",
    parent_id: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose uploading a UTF-8 text file to Drive."""
    title = title.strip()[:255]
    if not title or not content:
        raise ValueError("Provide a file name and non-empty text content.")
    data = content.encode("utf-8")
    if len(data) > MAX_DRIVE_UPLOAD_BYTES:
        raise ValueError("Text uploads are limited to 10 MB.")
    if not (mime_type.startswith("text/") or mime_type in {"application/json", "application/xml"}):
        raise ValueError("Text uploads support text/*, application/json, or application/xml MIME types.")
    if mime_type.startswith("application/vnd.google-apps."):
        raise ValueError("Use the Google Docs or Sheets creation tools for native Workspace files.")
    after = json.dumps(
        {"name": title[:255], "mimeType": mime_type, "bytes": len(data), "parent_id": parent_id or None}
    )
    operation_id = _approval_id(user_id, "drive_upload", title, f"{mime_type}\0{content}", parent_id)
    if not _approved_operation(
        operation_id=operation_id, kind="drive_upload", title=title[:255], url=None, before=None, after=after
    ):
        return "The user rejected this upload. No Drive file was created."
    _emit_task("drive-write", "Upload the approved text file", "in_progress")
    try:
        service = _drive_service(user_id)
        body = {"name": title[:255], "mimeType": mime_type}
        if parent_id:
            _require_file(
                service,
                parent_id,
                expected_mime="application/vnd.google-apps.folder",
                capability="canAddChildren",
            )
            body["parents"] = [parent_id]
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=True)
        created = service.files().create(
            body=body,
            media_body=media,
            fields="id,name,mimeType,webViewLink,size,parents",
        ).execute()
    except Exception:
        log.exception("Failed to upload approved text file %s", title)
        _emit_task("drive-write", "Upload the approved text file", "failed")
        raise
    _emit_task("drive-write", "Upload the approved text file", "completed")
    return json.dumps(created, default=str)


@tool
def drive_upload_file(
    title: str,
    mime_type: str,
    content_base64: str,
    parent_id: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose uploading a base64-encoded file of a supported MIME type to Drive, up to 10 MB."""
    title = title.strip()[:255]
    if not title or not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", mime_type):
        raise ValueError("Provide a file name and a valid MIME type.")
    if mime_type.startswith("application/vnd.google-apps."):
        raise ValueError("Use the Google Docs or Sheets creation tools for native Workspace files.")
    max_encoded_bytes = (MAX_DRIVE_UPLOAD_BYTES * 4 // 3) + 8
    if len(content_base64) > max_encoded_bytes:
        raise ValueError("File uploads are limited to 10 MB.")
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("content_base64 must be valid base64-encoded file content.") from exc
    if not data or len(data) > MAX_DRIVE_UPLOAD_BYTES:
        raise ValueError("Provide non-empty file content no larger than 10 MB.")
    after = {
        "name": title,
        "mime_type": mime_type,
        "bytes": len(data),
        "parent_id": parent_id or None,
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    operation_id = _approval_id(
        user_id, "drive_upload", title, json.dumps(after, sort_keys=True), parent_id
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="drive_upload",
        title=title,
        url=None,
        before=None,
        after=_json_preview(after),
    ):
        return "The user rejected this upload. No Drive file was created."
    _emit_task("drive-write", "Upload the approved Drive file", "in_progress")
    try:
        service = _drive_service(user_id)
        if parent_id:
            _require_file(
                service,
                parent_id,
                expected_mime="application/vnd.google-apps.folder",
                capability="canAddChildren",
            )
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=True)
        body = {"name": title, "mimeType": mime_type}
        if parent_id:
            body["parents"] = [parent_id]
        created = service.files().create(
            body=body,
            media_body=media,
            fields="id,name,mimeType,webViewLink,size,parents",
        ).execute()
    except Exception:
        log.exception("Failed to upload approved Drive file %s", title)
        _emit_task("drive-write", "Upload the approved Drive file", "failed")
        raise
    _emit_task("drive-write", "Upload the approved Drive file", "completed")
    return json.dumps(created, default=str)


@tool
def drive_manage_file(
    file_id: str,
    action: str,
    new_name: str = "",
    destination_folder_id: str = "",
    description: str | None = None,
    starred: bool | None = None,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose renaming, updating metadata, moving, copying, trashing, restoring, or deleting a selected Drive file."""
    if action not in {"rename", "update_metadata", "move", "copy", "trash", "restore", "permanent_delete"}:
        raise ValueError("Choose rename, update_metadata, move, copy, trash, restore, or permanent_delete.")
    new_name = new_name.strip()[:255]
    service = _drive_service(user_id)
    required_capability = {
        "rename": "canRename",
        "update_metadata": "canEdit",
        "move": "",
        "copy": "canCopy",
        "trash": "canTrash",
        "restore": "canUntrash",
        "permanent_delete": "canDelete",
    }[action]
    metadata = _require_file(service, file_id)
    if action in {"rename", "copy"} and not new_name.strip():
        raise ValueError("Provide a new file name.")
    if action == "update_metadata" and description is not None and len(description) > 10_000:
        raise ValueError("Descriptions must be no longer than 10,000 characters.")
    if action == "update_metadata" and description is None and starred is None:
        raise ValueError("Provide a description or starred value to update.")
    if action in {"move", "copy"} and not destination_folder_id and action == "move":
        raise ValueError("Provide the destination folder ID.")
    destination = None
    if action in {"move", "copy"} and destination_folder_id:
        destination = _require_file(
            service,
            destination_folder_id,
            expected_mime="application/vnd.google-apps.folder",
            capability="canAddChildren",
        )
        if action == "move":
            same_drive = metadata.get("driveId") == destination.get("driveId")
            required_capability = "canMoveItemWithinDrive" if same_drive else "canMoveItemOutOfDrive"
    if required_capability:
        metadata = _require_file(service, file_id, capability=required_capability)
    after = {
        "action": action,
        "file_id": file_id,
        "current_name": metadata.get("name"),
        "current_description": metadata.get("description"),
        "current_starred": metadata.get("starred"),
        "new_name": new_name[:255] if new_name else None,
        "destination_folder_id": destination_folder_id or None,
        "description": description if action == "update_metadata" else None,
        "starred": starred if action == "update_metadata" else None,
        "warning": (
            "Permanent deletion cannot be undone."
            if action == "permanent_delete"
            else "Moving this file changes its folder location."
            if action == "move"
            else "This file will be moved to Drive trash and can be restored."
            if action == "trash"
            else None
        ),
    }
    operation_id = _approval_id(
        user_id, f"drive_{action}", file_id, json.dumps(after, sort_keys=True), _drive_revision(metadata)
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind=f"drive_{action}",
        title=f"{action.replace('_', ' ').title()}: {metadata.get('name', 'Drive file')}",
        url=metadata.get("webViewLink"),
        before=json.dumps(
            {
                "name": metadata.get("name"),
                "description": metadata.get("description"),
                "starred": metadata.get("starred"),
                "parents": metadata.get("parents"),
            }
        ),
        after=_json_preview(after),
    ):
        return f"The user rejected this {action.replace('_', ' ')}. The file was not changed."
    latest = _require_file(service, file_id, capability=required_capability or None)
    if _drive_revision(latest) != _drive_revision(metadata):
        _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "failed")
        return "The Drive file changed after the proposal. Nothing was changed; inspect it and propose again."

    _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "in_progress")
    try:
        if action == "rename":
            result = service.files().update(
                fileId=file_id,
                body={"name": new_name[:255]},
                fields="id,name,mimeType,webViewLink,parents",
            ).execute()
        elif action == "move":
            old_parents = ",".join(metadata.get("parents", []))
            destination_latest = _require_file(
                service,
                destination_folder_id,
                expected_mime="application/vnd.google-apps.folder",
                capability="canAddChildren",
            )
            if destination_latest.get("modifiedTime") != destination.get("modifiedTime"):
                _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "failed")
                return "The destination folder changed after the proposal. Nothing was moved; inspect it and propose again."
            if old_parents == destination_folder_id:
                _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "failed")
                return "The file is already in that folder; nothing was changed."
            result = service.files().update(
                fileId=file_id,
                addParents=destination_folder_id,
                removeParents=old_parents or None,
                fields="id,name,mimeType,webViewLink,parents",
            ).execute()
        elif action == "copy":
            body = {"name": new_name[:255]}
            if destination_folder_id:
                destination_latest = _require_file(
                    service,
                    destination_folder_id,
                    expected_mime="application/vnd.google-apps.folder",
                    capability="canAddChildren",
                )
                if destination_latest.get("modifiedTime") != destination.get("modifiedTime"):
                    _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "failed")
                    return "The destination folder changed after the proposal. Nothing was copied; inspect it and propose again."
                body["parents"] = [destination_folder_id]
            result = service.files().copy(
                fileId=file_id,
                body=body,
                fields="id,name,mimeType,webViewLink,parents",
            ).execute()
        elif action == "update_metadata":
            body = {}
            if description is not None:
                body["description"] = description
            if starred is not None:
                body["starred"] = starred
            result = service.files().update(
                fileId=file_id,
                body=body,
                fields="id,name,mimeType,webViewLink,description,starred",
            ).execute()
        elif action in {"trash", "restore"}:
            result = service.files().update(
                fileId=file_id,
                body={"trashed": action == "trash"},
                fields="id,name,mimeType,webViewLink,trashed",
            ).execute()
        else:
            service.files().delete(fileId=file_id).execute()
            result = {"id": file_id, "deleted": True}
    except Exception:
        log.exception("Failed to apply approved Drive %s for %s", action, file_id)
        _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "failed")
        raise
    _emit_task("drive-write", f"Apply approved Drive {action.replace('_', ' ')}", "completed")
    return json.dumps(result, default=str)


@tool
def drive_list_permissions(
    file_id: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """List sharing permissions on a selected Drive file."""
    _emit_task("read-sharing", "Read Drive sharing permissions", "in_progress")
    try:
        service = _drive_service(user_id)
        _require_file(service, file_id)
        result = _list_drive_permissions(service, file_id)
    except Exception:
        log.exception("Failed to list Drive permissions for %s", file_id)
        _emit_task("read-sharing", "Read Drive sharing permissions", "failed")
        raise
    _emit_task("read-sharing", "Read Drive sharing permissions", "completed")
    return json.dumps(result, default=str)


def _list_drive_permissions(service: object, file_id: str) -> list[dict]:
    permissions: list[dict] = []
    page_token = None
    while True:
        result = service.permissions().list(
            fileId=file_id,
            fields=(
                "nextPageToken,permissions(id,type,role,emailAddress,domain,displayName,"
                "expirationTime,pendingOwner)"
            ),
            pageSize=100,
            pageToken=page_token,
        ).execute()
        permissions.extend(result.get("permissions", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return sorted(permissions, key=lambda permission: permission.get("id", ""))


@tool
def drive_set_permission(
    file_id: str,
    action: str,
    principal_type: str = "",
    principal: str = "",
    role: str = "",
    permission_id: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose adding, changing, or removing an explicit user, group, or domain Drive permission; public links are disabled."""
    if action not in {"add", "update", "remove"}:
        raise ValueError("Choose add, update, or remove.")
    if action == "add":
        if principal_type not in {"user", "group", "domain"}:
            raise ValueError("Only user, group, or domain permissions are supported; public link access is disabled.")
        if role not in {"reader", "commenter", "writer"}:
            raise ValueError("Choose reader, commenter, or writer.")
        if not principal.strip():
            raise ValueError("Provide the user's/group's email address or the domain.")
        if principal_type in {"user", "group"} and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", principal):
            raise ValueError("Provide a valid email address.")
        if principal_type == "domain" and not re.fullmatch(r"[A-Za-z0-9.-]+", principal):
            raise ValueError("Provide a valid domain name.")
    if action == "update" and role not in {"reader", "commenter", "writer"}:
        raise ValueError("Choose reader, commenter, or writer.")
    if action in {"update", "remove"} and not permission_id:
        raise ValueError("Provide a permission ID from drive_list_permissions.")
    service = _drive_service(user_id)
    metadata = _require_file(service, file_id, capability="canShare")
    permissions = _list_drive_permissions(service, file_id)
    target_permission = next(
        (permission for permission in permissions if permission.get("id") == permission_id),
        None,
    )
    if action in {"update", "remove"} and target_permission is None:
        raise ValueError("That permission ID is not present on this file; list permissions again.")
    if action == "add" and any(
        permission.get("type") == principal_type
        and permission.get("emailAddress", permission.get("domain", "")).lower() == principal.lower()
        for permission in permissions
    ):
        raise ValueError("That principal already has a permission on this file; update the existing permission instead.")
    after = {
        "action": action,
        "principal_type": principal_type or (target_permission or {}).get("type"),
        "principal": (
            principal.lower()
            if principal
            else (target_permission or {}).get("emailAddress", (target_permission or {}).get("domain"))
        ),
        "role": role or None,
        "permission_id": permission_id or None,
        "warning": "This changes who can access the file.",
    }
    operation_id = _approval_id(
        user_id, "drive_permission", file_id, json.dumps(after, sort_keys=True), _drive_revision(metadata)
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="drive_permission",
        title=f"Change sharing: {metadata.get('name', 'Drive file')}",
        url=metadata.get("webViewLink"),
        before=_json_preview(permissions),
        after=_json_preview(after),
    ):
        return "The user rejected this sharing change. Permissions were not changed."
    latest = _require_file(service, file_id, capability="canShare")
    if _drive_revision(latest) != _drive_revision(metadata):
        _emit_task("drive-sharing", "Apply the approved sharing change", "failed")
        return "The file changed after the sharing proposal. No permission was changed; inspect it and propose again."
    latest_permissions = _list_drive_permissions(service, file_id)
    if latest_permissions != permissions:
        _emit_task("drive-sharing", "Apply the approved sharing change", "failed")
        return "Sharing permissions changed after the proposal. No permission was changed; list them again and propose anew."
    _emit_task("drive-sharing", "Apply the approved sharing change", "in_progress")
    try:
        if action == "add":
            body = {"type": principal_type, "role": role}
            body["domain" if principal_type == "domain" else "emailAddress"] = principal.lower()
            result = service.permissions().create(
                fileId=file_id,
                body=body,
                sendNotificationEmail=principal_type in {"user", "group"},
                fields="id,type,role,emailAddress,domain",
            ).execute()
        elif action == "update":
            result = service.permissions().update(
                fileId=file_id,
                permissionId=permission_id,
                body={"role": role},
                fields="id,type,role,emailAddress,domain",
            ).execute()
        else:
            service.permissions().delete(
                fileId=file_id, permissionId=permission_id
            ).execute()
            result = {"permission_id": permission_id, "removed": True}
    except Exception:
        log.exception("Failed to apply approved Drive permission change on %s", file_id)
        _emit_task("drive-sharing", "Apply the approved sharing change", "failed")
        raise
    _emit_task("drive-sharing", "Apply the approved sharing change", "completed")
    return json.dumps(result, default=str)


@tool
def drive_list_comments(
    file_id: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """List Drive comments and replies attached to a selected file."""
    _emit_task("read-comments", "Read Drive comments", "in_progress")
    try:
        service = _drive_service(user_id)
        _require_file(service, file_id)
        result = _list_drive_comments(service, file_id)
    except Exception:
        log.exception("Failed to list Drive comments for %s", file_id)
        _emit_task("read-comments", "Read Drive comments", "failed")
        raise
    _emit_task("read-comments", "Read Drive comments", "completed")
    return json.dumps(result, default=str)


def _list_drive_comments(service: object, file_id: str) -> list[dict]:
    comments: list[dict] = []
    page_token = None
    while True:
        result = service.comments().list(
            fileId=file_id,
            includeDeleted=False,
            fields=(
                "nextPageToken,comments(id,content,htmlContent,author(displayName,emailAddress),"
                "createdTime,modifiedTime,resolved,anchor,quotedFileContent,"
                "replies(id,content,action,author(displayName,emailAddress),createdTime,modifiedTime))"
            ),
            pageSize=100,
            pageToken=page_token,
        ).execute()
        comments.extend(result.get("comments", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            return comments


@tool
def drive_manage_comment(
    file_id: str,
    action: str,
    content: str = "",
    comment_id: str = "",
    reply_id: str = "",
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose creating, editing, deleting, replying to, resolving, or reopening a Drive comment."""
    allowed_actions = {"create", "update", "delete", "reply", "resolve", "reopen", "delete_reply"}
    if action not in allowed_actions:
        raise ValueError(f"Choose one of: {', '.join(sorted(allowed_actions))}.")
    if action in {"create", "update", "reply"} and (not content.strip() or len(content) > 10_000):
        raise ValueError("Comment text must be non-empty and no longer than 10,000 characters.")
    if action != "create" and not comment_id:
        raise ValueError("Provide a comment ID.")
    if action == "delete_reply" and not reply_id:
        raise ValueError("Provide a reply ID.")
    service = _drive_service(user_id)
    metadata = _require_file(service, file_id, capability="canComment")
    comments = _list_drive_comments(service, file_id)
    comment = next((item for item in comments if item.get("id") == comment_id), None)
    if action != "create" and comment is None:
        raise ValueError("That comment is not present on this file; list comments again.")
    reply = next(
        (
            item
            for item in (comment or {}).get("replies", [])
            if item.get("id") == reply_id
        ),
        None,
    )
    if action == "delete_reply" and reply is None:
        raise ValueError("That reply is not present in the selected comment; list comments again.")
    after = {
        "action": action,
        "comment_id": comment_id or None,
        "reply_id": reply_id or None,
        "content": content if content else None,
        "warning": "This removes an existing comment or reply." if action in {"delete", "delete_reply"} else None,
    }
    operation_id = _approval_id(
        user_id, "drive_comment", file_id, json.dumps(after, sort_keys=True), _drive_revision(metadata)
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="drive_comment",
        title=f"{action.title()} comment: {metadata.get('name', 'Drive file')}",
        url=metadata.get("webViewLink"),
        before=_json_preview(comment) if comment else None,
        after=_json_preview(after),
    ):
        return "The user rejected this comment change. No comment was changed."
    latest = _require_file(service, file_id, capability="canComment")
    if _drive_revision(latest) != _drive_revision(metadata):
        _emit_task("drive-comments", "Apply the approved comment change", "failed")
        return "The file changed after the comment proposal. Nothing was changed; inspect it and propose again."
    latest_comments = _list_drive_comments(service, file_id)
    if latest_comments != comments:
        _emit_task("drive-comments", "Apply the approved comment change", "failed")
        return "Comments changed after the proposal. Nothing was changed; list comments again and propose anew."
    _emit_task("drive-comments", "Apply the approved comment change", "in_progress")
    try:
        if action == "create":
            result = service.comments().create(
                fileId=file_id,
                body={"content": content},
                fields="id,content,createdTime",
            ).execute()
        elif action == "update":
            result = service.comments().update(
                fileId=file_id,
                commentId=comment_id,
                body={"content": content},
                fields="id,content,modifiedTime",
            ).execute()
        elif action == "delete":
            service.comments().delete(fileId=file_id, commentId=comment_id).execute()
            result = {"comment_id": comment_id, "deleted": True}
        elif action == "reply":
            result = service.replies().create(
                fileId=file_id,
                commentId=comment_id,
                body={"content": content},
                fields="id,content,createdTime",
            ).execute()
        elif action in {"resolve", "reopen"}:
            result = service.replies().create(
                fileId=file_id,
                commentId=comment_id,
                body={"action": "resolve" if action == "resolve" else "reopen"},
                fields="id,action,createdTime",
            ).execute()
        else:
            service.replies().delete(
                fileId=file_id, commentId=comment_id, replyId=reply_id
            ).execute()
            result = {"reply_id": reply_id, "deleted": True}
    except Exception:
        log.exception("Failed to apply approved Drive comment change on %s", file_id)
        _emit_task("drive-comments", "Apply the approved comment change", "failed")
        raise
    _emit_task("drive-comments", "Apply the approved comment change", "completed")
    return json.dumps(result, default=str)


def _workspace_max_upload_bytes() -> int:
    settings = get_settings()
    with connect(settings) as conn:
        return indexing_settings.load(conn).max_upload_bytes


@tool
def get_file(
    document_id: str,
    user_email: Annotated[str, InjectedState("user_email")],
    user_domain: Annotated[str | None, InjectedState("user_domain")],
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Retrieve the full indexed source file after vector_search identifies its document ID."""
    _emit_task("read-source", "Read the full source file", "in_progress")
    try:
        parsed_id = uuid.UUID(document_id)
    except ValueError:
        _emit_task("read-source", "Read the full source file", "failed")
        return "Invalid document ID."

    settings = get_settings()
    with connect(settings) as conn:
        repository.set_app_user_context(conn, user_email, user_domain)
        document = repository.get_document(conn, parsed_id)
        if not document or not document.get("drive_file_id") or document["status"] != "indexed":
            _emit_task("read-source", "Read the full source file", "failed")
            return "That file is not available in your Amber workspace."

        service = drive.build_drive_service(user_id, conn)
        if service is None:
            _emit_task("read-source", "Read the full source file", "failed")
            return "Reconnect Google Drive to read the full source file."
        metadata = (
            service.files()
            .get(fileId=document["drive_file_id"], fields="id,name,mimeType,size")
            .execute()
        )
        max_bytes = indexing_settings.load(conn).max_upload_bytes
        if metadata.get("size") and int(metadata["size"]) > max_bytes:
            _emit_task("read-source", "Read the full source file", "failed")
            return "This source file exceeds the administrator's configured size limit."
        mime_type = metadata.get("mimeType", document.get("mime_type") or "application/octet-stream")
        filename = metadata.get("name", document["title"])

        if mime_type == "application/vnd.google-apps.document":
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            file_bytes = service.files().export_media(fileId=document["drive_file_id"], mimeType=content_type).execute()
            parse_name = filename + ".docx"
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            file_bytes = service.files().export_media(fileId=document["drive_file_id"], mimeType=content_type).execute()
            parse_name = filename + ".xlsx"
        else:
            file_bytes = service.files().get_media(fileId=document["drive_file_id"]).execute()
            content_type = mime_type
            parse_name = filename
        if len(file_bytes) > max_bytes:
            _emit_task("read-source", "Read the full source file", "failed")
            return "This source file exceeds the administrator's configured size limit."

    blocks = parse_document(file_bytes, content_type, parse_name)
    full_text = "\n\n".join(block.get("content", "") for block in blocks).strip()
    truncated = len(full_text) > MAX_SOURCE_CHARS
    if truncated:
        full_text = full_text[:MAX_SOURCE_CHARS]
    _emit_task("read-source", "Read the full source file", "completed")
    return json.dumps(
        {
            "document_id": str(parsed_id),
            "title": filename,
            "mime_type": mime_type,
            "drive_file_id": document["drive_file_id"],
            "drive_url": f"https://drive.google.com/open?id={document['drive_file_id']}",
            "content": full_text,
            "truncated": truncated,
        }
    )


def _drive_services(user_id: str) -> tuple[object, object, object]:
    settings = get_settings()
    with connect(settings) as conn:
        # drive.file only: the user's drive.readonly grant is for folder import, not for the agent to browse Drive.
        credentials = drive.get_drive_credentials(uuid.UUID(user_id), conn, scopes=[DRIVE_SCOPE])
    if credentials is None:
        raise ValueError("Connect Google Drive before using the document workspace.")
    return (
        build("drive", "v3", credentials=credentials, cache_discovery=False),
        build("docs", "v1", credentials=credentials, cache_discovery=False),
        build("sheets", "v4", credentials=credentials, cache_discovery=False),
    )


def _require_editable_file(drive_service: object, file_id: str, expected_mime: str) -> dict:
    metadata = _require_file(drive_service, file_id, expected_mime=expected_mime, capability="canEdit")
    return metadata


def _approval_id(
    user_id: str,
    kind: str,
    target: str,
    content: str,
    revision: str = "",
) -> str:
    return hashlib.sha256(f"{user_id}:{kind}:{target}:{revision}:{content}".encode()).hexdigest()


def _approved_operation(
    *,
    operation_id: str,
    kind: str,
    title: str,
    url: str | None,
    before: str | None,
    after: str,
) -> bool:
    _emit_task("approve-change", "Review and approve the document change", "in_progress")
    decision = interrupt(
        {
            "type": "workspace_approval",
            "operation_id": operation_id,
            "kind": kind,
            "title": title,
            "url": url,
            "before": before,
            "after": after,
        }
    )
    approved = (
        isinstance(decision, dict)
        and decision.get("approved") is True
        and decision.get("operation_id") == operation_id
    )
    _emit_task(
        "approve-change",
        "Review and approve the document change",
        "completed" if approved else "failed",
    )
    return approved


def _doc_text(document: dict) -> str:
    text: list[str] = []

    def collect_elements(elements: list[dict]) -> None:
        for element in elements:
            for paragraph_element in element.get("paragraph", {}).get("elements", []):
                run = paragraph_element.get("textRun", {})
                if run.get("content"):
                    text.append(run["content"])
            for row in element.get("table", {}).get("tableRows", []):
                for cell in row.get("tableCells", []):
                    collect_elements(cell.get("content", []))

    tabs = document.get("tabs", [])
    if tabs:
        def collect_tab(tab: dict) -> None:
            doc_tab = tab.get("documentTab", {})
            collect_elements(doc_tab.get("body", {}).get("content", []))
            for segment in ("headers", "footers", "footnotes"):
                for value in doc_tab.get(segment, {}).values():
                    collect_elements(value.get("content", []))

            for child_tab in tab.get("childTabs", []):
                collect_tab(child_tab)

        for tab in tabs:
            collect_tab(tab)
    else:
        collect_elements(document.get("body", {}).get("content", []))
        for segment in ("headers", "footers", "footnotes"):
            for value in document.get(segment, {}).values():
                collect_elements(value.get("content", []))
    return "".join(text)


_DOCS_BATCH_REQUESTS = {
    "insertText", "deleteContentRange", "replaceAllText", "updateTextStyle",
    "updateParagraphStyle", "createParagraphBullets", "deleteParagraphBullets",
    "insertTable", "insertTableRow", "deleteTableRow", "insertTableColumn",
    "deleteTableColumn", "updateTableCellStyle", "updateTableColumnProperties",
    "updateTableRowStyle", "insertInlineImage", "insertPageBreak",
    "insertSectionBreak", "updateDocumentStyle", "createNamedRange",
    "deleteNamedRange", "replaceNamedRangeContent", "createHeader",
    "createFooter", "createFootnote", "deleteHeader", "deleteFooter",
    "deletePositionedObject",
    "updatePositionedObjectProperties", "createTab", "deleteTab", "updateTabProperties",
}


def _validate_docs_requests(requests: list[dict]) -> None:
    if not requests or len(requests) > MAX_API_OPERATIONS:
        raise ValueError(f"Provide between 1 and {MAX_API_OPERATIONS} Docs update requests.")
    for request in requests:
        if not isinstance(request, dict) or len(request) != 1:
            raise ValueError("Each Docs request must contain exactly one operation.")
        operation = next(iter(request))
        if operation not in _DOCS_BATCH_REQUESTS:
            raise ValueError(f"Docs operation {operation!r} is not allowed.")
        if operation == "insertInlineImage":
            image = request[operation]
            if not isinstance(image, dict) or not str(image.get("uri", "")).startswith("https://"):
                raise ValueError("Images must use a publicly reachable HTTPS URL.")
    if len(json.dumps(requests, ensure_ascii=False)) > MAX_APPROVAL_PREVIEW_CHARS * 4:
        raise ValueError("The Docs update request is too large to review.")


def _skip_first_section_break(document: dict, requests: list[dict]) -> list[dict]:
    def first_section_break_end(content: list[dict]) -> int | None:
        for element in content:
            if "sectionBreak" in element:
                return element.get("endIndex")
        return None

    first_tab_ends: dict[str, int | None] = {}

    def collect_tabs(tabs: list[dict]) -> None:
        for tab in tabs:
            tab_id = tab.get("tabProperties", {}).get("tabId")
            document_tab = tab.get("documentTab", {})
            if tab_id:
                first_tab_ends[tab_id] = first_section_break_end(
                    document_tab.get("body", {}).get("content", [])
                )
            collect_tabs(tab.get("childTabs", []))

    tabs = document.get("tabs", [])
    if tabs:
        collect_tabs(tabs)
        default_tab_id = tabs[0].get("tabProperties", {}).get("tabId")
        default_end = first_tab_ends.get(default_tab_id) if default_tab_id else None
    else:
        default_end = first_section_break_end(document.get("body", {}).get("content", []))

    adjusted_requests = json.loads(json.dumps(requests))
    for request in adjusted_requests:
        if "updateParagraphStyle" not in request:
            continue
        style_request = request["updateParagraphStyle"]
        range_value = style_request.get("range")
        if not isinstance(range_value, dict):
            continue
        tab_id = range_value.get("tabId")
        first_break_end = first_tab_ends.get(tab_id) if tab_id else default_end
        if first_break_end is None:
            continue
        start_index = range_value.get("startIndex", 0)
        end_index = range_value.get("endIndex")
        if not isinstance(start_index, int) or not isinstance(end_index, int):
            continue
        if start_index < first_break_end:
            if end_index <= first_break_end:
                raise ValueError(
                    "Paragraph formatting cannot target the document's first section break. "
                    "Choose a paragraph range after the section break."
                )
            range_value["startIndex"] = first_break_end
    return adjusted_requests


def _docs_change_preview(summary: str, requests: list[dict]) -> dict:
    effects = []
    for request in requests:
        operation, details = next(iter(request.items()))
        if operation == "replaceAllText":
            contains = details.get("containsText", {})
            effect = f"Replace text matching {contains.get('text', '')!r} with {details.get('replaceText', '')!r}."
        elif operation == "insertText":
            effect = f"Insert text {details.get('text', '')!r} at index {details.get('location', {}).get('index')}."
        elif operation == "deleteContentRange":
            range_value = details.get("range", {})
            effect = (
                f"Delete content from index {range_value.get('startIndex')} "
                f"to {range_value.get('endIndex')}."
            )
        else:
            effect = f"Apply {operation} with these parameters: {_json_preview(details, max_chars=1500)}"
        effects.append(effect)
    high_impact_operations = {
        "deleteContentRange", "deleteTableRow", "deleteTableColumn",
        "deleteHeader", "deleteFooter", "deletePositionedObject", "deleteTab",
    }
    warnings = [
        f"{operation} may remove document content or structure."
        for request in requests
        for operation in request
        if operation in high_impact_operations
    ]
    return {
        "summary": summary,
        "proposed_effects": effects,
        "risk_warnings": warnings,
        "api_requests": requests,
    }


@tool
def read_google_doc(
    document_id: str,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Read a Google Doc's structure, tabs, styles, tables, headers, footers, and text."""
    _emit_task("read-source", "Read Google Doc structure", "in_progress")
    try:
        drive_service, docs_service, _ = _drive_services(user_id)
        metadata = _require_file(
            drive_service, document_id, expected_mime="application/vnd.google-apps.document"
        )
        document = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()
        encoded_document = json.dumps(document, ensure_ascii=False, default=str)
        _emit_task("read-source", "Read Google Doc structure", "completed")
        return json.dumps(
            {
                "document_id": document_id,
                "title": metadata.get("name"),
                "drive_url": metadata.get("webViewLink"),
                "revision_id": document.get("revisionId"),
                "text": _doc_text(document)[:MAX_SOURCE_CHARS],
                "structure": encoded_document[:MAX_SOURCE_CHARS],
                "truncated": len(encoded_document) > MAX_SOURCE_CHARS,
            },
            ensure_ascii=False,
        )
    except Exception:
        log.exception("Failed to read Google Doc %s", document_id)
        _emit_task("read-source", "Read Google Doc structure", "failed")
        raise


@tool
def apply_google_doc_updates(
    document_id: str,
    summary: str,
    requests: list[dict],
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose an approval-gated Docs batch update for text, formatting, tables, images, page elements, tabs, or named ranges."""
    _validate_docs_requests(requests)
    if not summary.strip() or len(summary) > 1000:
        raise ValueError("Provide a short plain-language summary of the proposed changes.")
    drive_service, docs_service, _ = _drive_services(user_id)
    metadata = _require_file(
        drive_service,
        document_id,
        expected_mime="application/vnd.google-apps.document",
        capability="canEdit",
    )
    document = docs_service.documents().get(
        documentId=document_id, includeTabsContent=True
    ).execute()
    requests = _skip_first_section_break(document, requests)
    before = _doc_text(document)
    operation_id = _approval_id(
        user_id,
        "docs_batch_update",
        document_id,
        json.dumps({"summary": summary, "requests": requests}, sort_keys=True, ensure_ascii=False),
        str(document.get("revisionId") or ""),
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="docs_batch_update",
        title=metadata.get("name", "Google Doc"),
        url=metadata.get("webViewLink"),
        before=before[:MAX_APPROVAL_PREVIEW_CHARS],
        after=_json_preview(_docs_change_preview(summary, requests)),
    ):
        return "The user rejected the proposed Docs updates. The document was not changed."
    _emit_task("edit-document", "Apply approved Docs updates", "in_progress")
    try:
        result = docs_service.documents().batchUpdate(
            documentId=document_id,
            body={
                "writeControl": {"requiredRevisionId": document["revisionId"]},
                "requests": requests,
            },
        ).execute()
        updated = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()
    except Exception:
        log.exception("Failed to apply approved Docs update %s", document_id)
        _emit_task("edit-document", "Apply approved Docs updates", "failed")
        raise
    _emit_task("edit-document", "Apply approved Docs updates", "completed")
    return json.dumps(
        {
            "document_id": document_id,
            "title": metadata.get("name"),
            "drive_url": metadata.get("webViewLink"),
            "revision_id": updated.get("revisionId"),
            "text": _doc_text(updated)[:MAX_SOURCE_CHARS],
            "request_replies": result.get("replies", []),
        },
        ensure_ascii=False,
        default=str,
    )


def _drive_service(user_id: str) -> object:
    settings = get_settings()
    with connect(settings) as conn:
        credentials = drive.get_drive_credentials(uuid.UUID(user_id), conn, scopes=[DRIVE_SCOPE])  # see _drive_services
    if credentials is None:
        raise ValueError("Connect Google Drive before using workspace file tools.")
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _require_file(
    drive_service: object,
    file_id: str,
    *,
    expected_mime: str | None = None,
    capability: str | None = None,
) -> dict:
    fields = (
        "id,name,mimeType,webViewLink,modifiedTime,parents,driveId,description,starred,"
        "owners(displayName,emailAddress),size,"
        "capabilities(canEdit,canShare,canComment,canDownload,canRename,canCopy,"
        "canMoveItemWithinDrive,canMoveItemOutOfDrive,canAddChildren,canTrash,canUntrash,canDelete)"
    )
    metadata = drive_service.files().get(
        fileId=file_id,
        fields=fields,
    ).execute()
    if expected_mime and metadata.get("mimeType") != expected_mime:
        raise ValueError("This operation only supports the matching Google Workspace file type.")
    if capability and metadata.get("capabilities", {}).get(capability) is not True:
        raise ValueError(f"Your Google account does not have the required {capability[3:]} access to this file.")
    return metadata


def _drive_revision(metadata: dict) -> str:
    return str(metadata.get("modifiedTime") or "")


def _json_preview(value: object, *, max_chars: int = MAX_APPROVAL_PREVIEW_CHARS) -> str:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(rendered) > max_chars:
        return rendered[:max_chars] + "\n… (preview truncated)"
    return rendered


def _drive_query_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@tool
def create_google_doc(
    title: str,
    content: str,
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Propose creating a Google Doc; the user must approve before it is created."""
    if not title.strip() or not content.strip() or len(content) > MAX_SOURCE_CHARS:
        return "Provide a title and document content under 80,000 characters."
    operation_id = _approval_id(user_id, "create_doc", title, content)
    if not _approved_operation(
        operation_id=operation_id,
        kind="create_doc",
        title=title,
        url=None,
        before=None,
        after=content,
    ):
        return "The user rejected this change. No document was created."

    _emit_task("edit-document", "Create the approved Google Doc", "in_progress")
    drive_service, docs_service, _ = _drive_services(user_id)
    created = docs_service.documents().create(body={"title": title}).execute()
    document_id = created["documentId"]
    try:
        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
        ).execute()
        metadata = drive_service.files().get(
            fileId=document_id,
            fields="id,name,mimeType,webViewLink",
        ).execute()
    except Exception:
        log.exception("Failed to create approved Google Doc %s", document_id)
        _emit_task("edit-document", "Create the approved Google Doc", "failed")
        try:
            drive_service.files().delete(fileId=document_id).execute()
        except Exception:
            log.exception("Failed to remove incomplete Google Doc %s", document_id)
        raise
    _emit_task("edit-document", "Create the approved Google Doc", "completed")
    return json.dumps(
        {
            "document_id": document_id,
            "title": metadata.get("name", title),
            "mime_type": metadata.get("mimeType"),
            "drive_url": metadata.get("webViewLink"),
            "content": content,
        }
    )


@tool
def edit_google_doc(
    document_id: str,
    find_text: str,
    replace_with: str,
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Propose replacing one exact, unique text passage in a Google Doc; approval is required."""
    if not find_text.strip() or len(find_text) > 10_000 or len(replace_with) > 10_000:
        return "Provide a non-empty exact passage and replacement text, each under 10,000 characters."
    drive_service, docs_service, _ = _drive_services(user_id)
    try:
        metadata = _require_editable_file(
            drive_service, document_id, "application/vnd.google-apps.document"
        )
        current = docs_service.documents().get(documentId=document_id).execute()
    except Exception as exc:
        log.exception("Failed to read or verify Google Doc %s", document_id)
        return f"Could not read or verify this Google Doc: {type(exc).__name__}."
    before = _doc_text(current)
    occurrences = before.count(find_text)
    if occurrences != 1:
        return (
            f"The exact text must occur once in the document; it currently occurs {occurrences} times. "
            "Read the source again and choose a more specific passage."
        )
    after = before.replace(find_text, replace_with, 1)
    revision = metadata.get("modifiedTime", "")
    operation_id = _approval_id(
        user_id,
        "edit_doc",
        document_id,
        f"{find_text}\0{replace_with}\0{before}",
        revision,
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="edit_doc",
        title=metadata.get("name", "Google Doc"),
        url=metadata.get("webViewLink"),
        before=before,
        after=after,
    ):
        return "The user rejected this change. The Google Doc was not modified."

    latest_metadata = _require_editable_file(
        drive_service, document_id, "application/vnd.google-apps.document"
    )
    if latest_metadata.get("modifiedTime") != metadata.get("modifiedTime"):
        _emit_task("edit-document", "Apply the approved Google Doc edit", "failed")
        return "The Google Doc changed after the proposal was prepared. Nothing was modified; read it again and propose an updated edit."
    latest_doc = docs_service.documents().get(documentId=document_id).execute()
    if _doc_text(latest_doc) != before:
        _emit_task("edit-document", "Apply the approved Google Doc edit", "failed")
        return "The Google Doc changed after the proposal was prepared. Nothing was modified; read it again and propose an updated edit."
    _emit_task("edit-document", "Apply the approved Google Doc edit", "in_progress")
    try:
        docs_service.documents().batchUpdate(
            documentId=document_id,
            body={
                "writeControl": {"requiredRevisionId": latest_doc["revisionId"]},
                "requests": [
                    {
                        "replaceAllText": {
                            "containsText": {"text": find_text, "matchCase": True},
                            "replaceText": replace_with,
                        }
                    }
                ],
            },
        ).execute()
    except Exception:
        log.exception("Failed to apply approved Google Doc edit %s", document_id)
        _emit_task("edit-document", "Apply the approved Google Doc edit", "failed")
        raise
    _emit_task("edit-document", "Apply the approved Google Doc edit", "completed")
    return json.dumps(
        {
            "document_id": document_id,
            "title": metadata.get("name", "Google Doc"),
            "mime_type": metadata["mimeType"],
            "drive_url": metadata.get("webViewLink"),
            "content": after,
        }
    )


def _validate_sheet_values(values: list[list[object]]) -> None:
    if not values or any(not isinstance(row, list) for row in values):
        raise ValueError("Provide a non-empty two-dimensional array of cell values.")
    if not values[0] or any(len(row) != len(values[0]) for row in values):
        raise ValueError("Every spreadsheet row must contain the same non-zero number of cells.")
    if sum(len(row) for row in values) > MAX_WORKSPACE_CELLS:
        raise ValueError(f"A single operation is limited to {MAX_WORKSPACE_CELLS} cells.")
    if any(not isinstance(value, (str, int, float, bool, type(None))) for row in values for value in row):
        raise ValueError("Sheet cells must be plain text, numbers, booleans, or empty.")


@tool
def create_google_sheet(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Propose creating a Google Sheet; the user must approve before it is created."""
    values = [headers, *rows]
    try:
        _validate_sheet_values(values)
    except ValueError as exc:
        return str(exc)
    if not title.strip():
        return "Provide a title for the spreadsheet."
    preview = json.dumps(values, ensure_ascii=False)
    operation_id = _approval_id(user_id, "create_sheet", title, preview)
    if not _approved_operation(
        operation_id=operation_id,
        kind="create_sheet",
        title=title,
        url=None,
        before=None,
        after=preview,
    ):
        return "The user rejected this change. No spreadsheet was created."

    _emit_task("edit-document", "Create the approved Google Sheet", "in_progress")
    drive_service, _, sheets_service = _drive_services(user_id)
    created = sheets_service.spreadsheets().create(
        body={"properties": {"title": title}}
    ).execute()
    spreadsheet_id = created["spreadsheetId"]
    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
        metadata = drive_service.files().get(
            fileId=spreadsheet_id,
            fields="id,name,mimeType,webViewLink",
        ).execute()
    except Exception:
        log.exception("Failed to create approved Google Sheet %s", spreadsheet_id)
        _emit_task("edit-document", "Create the approved Google Sheet", "failed")
        try:
            drive_service.files().delete(fileId=spreadsheet_id).execute()
        except Exception:
            log.exception("Failed to remove incomplete Google Sheet %s", spreadsheet_id)
        raise
    _emit_task("edit-document", "Create the approved Google Sheet", "completed")
    return json.dumps(
        {
            "document_id": spreadsheet_id,
            "title": metadata.get("name", title),
            "mime_type": metadata.get("mimeType"),
            "drive_url": metadata.get("webViewLink"),
            "values": values,
        }
    )


@tool
def edit_google_sheet(
    spreadsheet_id: str,
    range_a1: str,
    values: list[list[str]],
    user_id: Annotated[str, InjectedState("user_id")],
) -> str:
    """Propose updating a bounded cell range in a Google Sheet; approval is required before writing."""
    match = re.fullmatch(
        r"(?:'[^']+'|[A-Za-z0-9_]+)!\$?([A-Z]{1,3})\$?([1-9]\d*)"
        r"(?::\$?([A-Z]{1,3})\$?([1-9]\d*))?",
        range_a1,
    )
    if not match:
        return "Use a bounded A1 range, for example Sheet1!A1:C4."
    try:
        _validate_sheet_values(values)
    except ValueError as exc:
        return str(exc)
    start_col = _column_number(match.group(1))
    start_row = int(match.group(2))
    end_col = _column_number(match.group(3) or match.group(1))
    end_row = int(match.group(4) or match.group(2))
    if (
        end_row < start_row
        or end_col < start_col
        or len(values) != end_row - start_row + 1
        or len(values[0]) != end_col - start_col + 1
    ):
        return "The values must exactly fit the approved A1 range."
    drive_service, _, sheets_service = _drive_services(user_id)
    try:
        metadata = _require_editable_file(
            drive_service, spreadsheet_id, "application/vnd.google-apps.spreadsheet"
        )
        before = sheets_service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_a1
        ).execute().get("values", [])
    except Exception as exc:
        log.exception("Failed to read or verify Google Sheet %s", spreadsheet_id)
        return f"Could not read or verify this Google Sheet: {type(exc).__name__}."
    proposed = json.dumps(values, ensure_ascii=False)
    revision = metadata.get("modifiedTime", "")
    operation_id = _approval_id(
        user_id,
        "edit_sheet",
        f"{spreadsheet_id}:{range_a1}",
        f"{json.dumps(before, ensure_ascii=False)}\0{proposed}",
        revision,
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="edit_sheet",
        title=f"{metadata.get('name', 'Google Sheet')} · {range_a1}",
        url=metadata.get("webViewLink"),
        before=json.dumps(before, ensure_ascii=False),
        after=proposed,
    ):
        return "The user rejected this change. The Google Sheet was not modified."

    latest_metadata = _require_editable_file(
        drive_service, spreadsheet_id, "application/vnd.google-apps.spreadsheet"
    )
    if latest_metadata.get("modifiedTime") != metadata.get("modifiedTime"):
        _emit_task("edit-document", "Apply the approved Google Sheet edit", "failed")
        return "The Google Sheet changed after the proposal was prepared. Nothing was modified; read it again and propose an updated edit."
    latest_values = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=range_a1
    ).execute().get("values", [])
    if latest_values != before:
        _emit_task("edit-document", "Apply the approved Google Sheet edit", "failed")
        return "The approved cell range changed after the proposal was prepared. Nothing was modified; read it again and propose an updated edit."
    _emit_task("edit-document", "Apply the approved Google Sheet edit", "in_progress")
    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_a1,
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
    except Exception:
        log.exception("Failed to apply approved Google Sheet edit %s", spreadsheet_id)
        _emit_task("edit-document", "Apply the approved Google Sheet edit", "failed")
        raise
    _emit_task("edit-document", "Apply the approved Google Sheet edit", "completed")
    return json.dumps(
        {
            "document_id": spreadsheet_id,
            "title": metadata.get("name", "Google Sheet"),
            "mime_type": metadata["mimeType"],
            "drive_url": metadata.get("webViewLink"),
            "values": values,
        }
    )


def _parse_bounded_sheet_range(range_a1: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(
        r"(?:'[^']+'|[A-Za-z0-9_]+)!\$?([A-Z]{1,3})\$?([1-9]\d*)"
        r":\$?([A-Z]{1,3})\$?([1-9]\d*)",
        range_a1,
    )
    if not match:
        raise ValueError("Use a bounded A1 range, for example 'Budget 2025'!A1:D20.")
    start_col, start_row, end_col, end_row = (
        _column_number(match.group(1)),
        int(match.group(2)),
        _column_number(match.group(3)),
        int(match.group(4)),
    )
    if end_col < start_col or end_row < start_row:
        raise ValueError("The A1 range end must not precede its start.")
    if (end_col - start_col + 1) * (end_row - start_row + 1) > MAX_WORKSPACE_CELLS:
        raise ValueError(f"Each spreadsheet range is limited to {MAX_WORKSPACE_CELLS} cells.")
    return start_row, start_col, end_row, end_col


def _validate_sheet_batch_requests(requests: list[dict]) -> None:
    allowed = {
        "updateCells", "repeatCell", "addSheet", "deleteSheet", "updateSheetProperties",
        "addDimension", "deleteDimension", "updateDimensionProperties", "mergeCells",
        "unmergeCells", "updateSpreadsheetProperties", "addNamedRange",
        "updateNamedRange", "deleteNamedRange", "setDataValidation", "sortRange",
        "addFilterView", "updateFilterView", "deleteFilterView", "addProtectedRange",
        "updateProtectedRange", "deleteProtectedRange", "addChart", "updateChartSpec",
        "deleteEmbeddedObject", "addPivotTable", "updateBorders", "addBanding",
        "updateBanding", "deleteBanding", "addSlicer", "updateSlicerSpec", "deleteSlicer",
        "addTable", "updateTable", "deleteTable", "addConditionalFormatRule",
        "updateConditionalFormatRule", "deleteConditionalFormatRule", "insertDimension",
        "appendDimension", "moveDimension", "insertRange", "deleteRange", "autoFill",
        "copyPaste", "cutPaste", "pasteData", "randomizeRange", "findReplace",
        "trimWhitespace", "textToColumns", "appendCells", "setBasicFilter", "clearBasicFilter",
        "duplicateSheet", "duplicateFilterView", "updateDataSource",
        "addDataSource", "addDataSourceTable", "deleteDataSource", "refreshDataSource",
    }
    if not requests or len(requests) > MAX_API_OPERATIONS:
        raise ValueError(f"Provide between 1 and {MAX_API_OPERATIONS} Sheets batch requests.")
    for request in requests:
        if not isinstance(request, dict) or len(request) != 1:
            raise ValueError("Each Sheets request must contain exactly one operation.")
        operation = next(iter(request))
        if operation not in allowed:
            raise ValueError(f"Sheets operation {operation!r} is not allowed.")
        _validate_sheet_request_bounds(operation, request[operation])
    if len(json.dumps(requests, ensure_ascii=False)) > MAX_APPROVAL_PREVIEW_CHARS * 4:
        raise ValueError("The Sheets update request is too large to review.")


def _validate_sheet_request_bounds(operation: str, details: object) -> None:
    def check_grid_range(value: dict) -> None:
        coordinates = {
            "startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex"
        }
        if not coordinates.issubset(value):
            raise ValueError(
                f"{operation} must use a fully bounded cell range; whole-sheet edits are not allowed."
            )
        if any(type(value[key]) is not int for key in coordinates):
            raise ValueError(f"{operation} cell range coordinates must be integers.")
        height = value["endRowIndex"] - value["startRowIndex"]
        width = value["endColumnIndex"] - value["startColumnIndex"]
        if height <= 0 or width <= 0 or height * width > MAX_WORKSPACE_CELLS:
            raise ValueError(
                f"{operation} cell ranges must cover between 1 and {MAX_WORKSPACE_CELLS} cells."
            )

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if "gridRange" in value:
                grid_range = value["gridRange"]
                if not isinstance(grid_range, dict):
                    raise ValueError(f"{operation} gridRange must be an object.")
                check_grid_range(grid_range)
            elif "sheetId" in value and any(
                key in value
                for key in ("startRowIndex", "endRowIndex", "startColumnIndex", "endColumnIndex")
            ):
                check_grid_range(value)
            if {"sheetId", "dimension", "startIndex", "endIndex"}.issubset(value):
                if type(value["startIndex"]) is not int or type(value["endIndex"]) is not int:
                    raise ValueError(f"{operation} dimension range coordinates must be integers.")
                dimension_size = value["endIndex"] - value["startIndex"]
                if dimension_size <= 0 or dimension_size > MAX_WORKSPACE_CELLS:
                    raise ValueError(
                        f"{operation} dimension ranges must not exceed {MAX_WORKSPACE_CELLS} rows or columns."
                    )
            if operation == "appendDimension" and "length" in value:
                length = value["length"]
                if type(length) is not int or length < 1 or length > MAX_WORKSPACE_CELLS:
                    raise ValueError("appendDimension can add between 1 and 2,000 rows or columns at once.")
            if operation in {"updateCells", "appendCells"} and "rows" in value:
                rows = value["rows"]
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError(f"{operation} rows must be a list of row objects.")
                cell_count = sum(
                    len(row.get("values", []))
                    for row in rows
                    if isinstance(row.get("values", []), list)
                )
                if any(not isinstance(row.get("values", []), list) for row in rows):
                    raise ValueError(f"{operation} row values must be lists.")
                if cell_count > MAX_WORKSPACE_CELLS:
                    raise ValueError(f"{operation} is limited to 2,000 cells per operation.")
            if operation == "addSheet":
                properties = value.get("properties", {})
                if not isinstance(properties, dict):
                    raise ValueError("addSheet properties must be an object.")
                grid = properties.get("gridProperties", {})
                if not isinstance(grid, dict):
                    raise ValueError("addSheet gridProperties must be an object.")
                rows = grid.get("rowCount", 1000)
                columns = grid.get("columnCount", 26)
                if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
                    raise ValueError("New sheet row and column counts must be positive integers.")
                if rows * columns > MAX_WORKSPACE_CELLS and (
                    "rowCount" in grid or "columnCount" in grid
                ):
                    raise ValueError("New sheet dimensions may not exceed 2,000 explicitly allocated cells.")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    if not isinstance(details, dict):
        raise ValueError(f"{operation} request details must be an object.")
    bounded_range_operations = {
        "repeatCell", "mergeCells", "unmergeCells", "updateBorders",
        "setDataValidation", "sortRange", "randomizeRange", "deleteRange",
        "insertRange", "trimWhitespace", "textToColumns",
    }
    if operation in bounded_range_operations:
        range_value = details.get("range")
        if not isinstance(range_value, dict):
            raise ValueError(f"{operation} requires a fully bounded cell range.")
        check_grid_range(range_value)
    elif operation == "updateCells":
        range_value = details.get("range")
        if isinstance(range_value, dict):
            check_grid_range(range_value)
        elif not (
            isinstance(details.get("start"), dict)
            and isinstance(details.get("rows"), list)
            and type(details["start"].get("rowIndex")) is int
            and type(details["start"].get("columnIndex")) is int
        ):
            raise ValueError("updateCells requires a bounded range or a start cell and bounded rows.")
    visit(details)


def _normalize_sheet_operation(operation: dict) -> tuple[str, dict]:
    valid_kinds = {"values_update", "values_append", "values_clear", "batch_update"}
    if not isinstance(operation, dict):
        raise ValueError("operation must be an object describing one Sheets update.")
    if len(operation) == 1:
        kind, payload = next(iter(operation.items()))
        if kind in valid_kinds and isinstance(payload, dict):
            payload = dict(payload)
        elif kind in {"action", "type", "operation"} and isinstance(payload, str):
            kind = payload
            payload = {key: value for key, value in operation.items() if key != next(iter(operation))}
        else:
            raise ValueError(
                "Use one operation object, such as "
                '{"values_update":{"rangeA1":"Sheet1!A1:B2","values":[["x","y"],["z","w"]]}}.'
            )
    elif operation.get("action", operation.get("type", operation.get("operation"))) in valid_kinds:
        kind_key = next(
            key for key in ("action", "type", "operation") if operation.get(key) in valid_kinds
        )
        kind = operation[kind_key]
        payload = {key: value for key, value in operation.items() if key != kind_key}
    else:
        raise ValueError(
            "Provide exactly one operation: values_update, values_append, values_clear, or batch_update. "
            "Use a one-key object with that operation name."
        )

    if kind not in valid_kinds:
        raise ValueError("Choose values_update, values_append, values_clear, or batch_update.")
    if not isinstance(payload, dict):
        raise ValueError(f"{kind} details must be an object.")

    if kind in {"values_update", "values_append"}:
        range_value = payload.get("rangeA1", payload.get("range_a1", payload.get("range")))
        values = payload.get("values")
        if range_value is not None:
            for key in ("rangeA1", "range_a1", "range"):
                payload.pop(key, None)
            if kind == "values_update":
                if "ranges" in payload:
                    raise ValueError("Provide either rangeA1 plus values or ranges, not both.")
                if values is None:
                    raise ValueError("Provide values alongside rangeA1 for values_update.")
                payload["ranges"] = [{"range": range_value, "values": values}]
                payload.pop("values", None)
            else:
                payload["range"] = range_value
        elif kind == "values_update" and "ranges" not in payload and values is not None:
            raise ValueError("Provide rangeA1 alongside values for values_update.")
    elif kind == "values_clear" and "ranges" not in payload:
        range_value = payload.pop("rangeA1", payload.pop("range_a1", payload.pop("range", None)))
        if range_value is not None:
            payload["ranges"] = [range_value] if isinstance(range_value, str) else range_value

    return kind, payload


_SHEETS_READ_FIELDS = (
    "spreadsheetId,properties(title,locale,timeZone,autoRecalc,defaultFormat),namedRanges,"
    "sheets(properties(sheetId,title,index,hidden,gridProperties),merges,basicFilter,"
    "filterViews,protectedRanges,charts,tables,slicers,"
    "conditionalFormats,data(startRow,startColumn,rowData(values(userEnteredValue,"
    "effectiveValue,userEnteredFormat,note,dataValidation,textFormatRuns,pivotTable))))"
)


@tool
def read_google_sheet(
    spreadsheet_id: str,
    ranges: list[str],
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Read a Google Sheet using bounded A1 ranges.

    Pass ranges as a list, such as ["Sales!A1:D20"]; use [] for workbook metadata only.
    The JSON result contains spreadsheet_id, title, drive_url, modified_time,
    workbook metadata/grid data, and range_values_and_formulas.
    """
    _emit_task("read-source", "Read Google Sheet", "in_progress")
    try:
        if len(ranges) > 20:
            raise ValueError("Read no more than 20 ranges at once.")
        total_cells = 0
        for range_a1 in ranges:
            if not isinstance(range_a1, str):
                raise ValueError("Each spreadsheet range must be a string.")
            start_row, start_col, end_row, end_col = _parse_bounded_sheet_range(range_a1)
            total_cells += (end_row - start_row + 1) * (end_col - start_col + 1)
        if total_cells > MAX_WORKSPACE_CELLS:
            raise ValueError(f"A single read is limited to {MAX_WORKSPACE_CELLS} cells total.")

        drive_service, _, sheets_service = _drive_services(user_id)
        file_metadata = _require_file(
            drive_service, spreadsheet_id, expected_mime="application/vnd.google-apps.spreadsheet"
        )
        workbook = sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            includeGridData=bool(ranges),
            ranges=ranges or None,
            fields=_SHEETS_READ_FIELDS,
        ).execute()
        _emit_task("read-source", "Read Google Sheet", "completed")
        return json.dumps(
            {
                "spreadsheet_id": spreadsheet_id,
                "title": file_metadata.get("name"),
                "drive_url": file_metadata.get("webViewLink"),
                "modified_time": file_metadata.get("modifiedTime"),
                "workbook": workbook,
                "range_values_and_formulas": (
                    sheets_service.spreadsheets().values().batchGet(
                        spreadsheetId=spreadsheet_id,
                        ranges=ranges,
                        valueRenderOption="FORMULA",
                    ).execute().get("valueRanges", [])
                    if ranges
                    else []
                ),
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception:
        log.exception("Failed to read Google Sheet %s", spreadsheet_id)
        _emit_task("read-source", "Read Google Sheet", "failed")
        raise


@tool
def apply_google_sheet_updates(
    spreadsheet_id: str,
    summary: str,
    operation: dict,
    user_id: Annotated[str, InjectedState("user_id")] = "",
) -> str:
    """Propose one approval-gated Google Sheets update.

    Values example (pass this object as the operation argument):
    operation={"values_update":{"rangeA1":"Sheet1!A1:B2","values":[["Name","Count"],["Apples",3]]}}
    Append example:
    operation={"values_append":{"rangeA1":"Sheet1!A1:B1","values":[["Apples",3]]}}
    Clear example:
    operation={"values_clear":{"ranges":["Sheet1!A1:B2"]}}
    Formatting/layout example:
    operation={"batch_update":{"requests":[{"repeatCell":{"range":{"sheetId":0,"startRowIndex":0,"endRowIndex":1,"startColumnIndex":0,"endColumnIndex":2},"cell":{"userEnteredFormat":{"textFormat":{"bold":true}}},"fields":"userEnteredFormat.textFormat.bold"}}]}}

    Ranges must be bounded and updates must exactly fit them. Use RAW unless formulas are explicitly needed.
    After approval, success returns JSON containing spreadsheet_id, title, drive_url,
    operation_kind, and the Google API result. Rejection returns a message confirming
    that no change was made. Validation or Google API errors are sent back to the agent
    as tool results so it can correct the request or explain the failure.
    """
    if not summary.strip() or len(summary) > 1000:
        raise ValueError("Provide a short plain-language summary of the proposed changes.")
    kind, payload = _normalize_sheet_operation(operation)
    allowed_payload_keys = {
        "values_update": {"ranges", "input_option"},
        "values_append": {"range", "values", "input_option"},
        "values_clear": {"ranges"},
        "batch_update": {"requests"},
    }[kind]
    if set(payload) - allowed_payload_keys:
        raise ValueError(f"Unsupported fields for {kind}: {', '.join(sorted(set(payload) - allowed_payload_keys))}.")
    affected_ranges: list[str] = []
    if kind == "values_update":
        ranges = payload.get("ranges")
        input_option = payload.get("input_option", "RAW")
        if not isinstance(ranges, list) or not ranges or len(ranges) > MAX_API_OPERATIONS:
            raise ValueError(f"Provide between 1 and {MAX_API_OPERATIONS} cell ranges.")
        if input_option not in {"RAW", "USER_ENTERED"}:
            raise ValueError("input_option must be RAW or USER_ENTERED.")
        updates = []
        total_cells = 0
        for item in ranges:
            if not isinstance(item, dict) or not isinstance(item.get("values"), list):
                raise ValueError("Each update range must contain a range and a two-dimensional values array.")
            if set(item) - {"range", "values"}:
                raise ValueError("Update ranges may contain only range and values fields.")
            range_a1 = item.get("range", "")
            start_row, start_col, end_row, end_col = _parse_bounded_sheet_range(range_a1)
            values = item["values"]
            _validate_sheet_values(values)
            if (
                len(values) != end_row - start_row + 1
                or any(len(row) != end_col - start_col + 1 for row in values)
            ):
                raise ValueError(f"The values must exactly fit {range_a1}.")
            total_cells += sum(len(row) for row in values)
            updates.append({"range": range_a1, "values": values})
            affected_ranges.append(range_a1)
        if total_cells > MAX_WORKSPACE_CELLS:
            raise ValueError(f"A single update is limited to {MAX_WORKSPACE_CELLS} cells.")
        payload = {"ranges": updates, "input_option": input_option}
    elif kind == "values_append":
        range_a1 = payload.get("range", "")
        _, start_col, _, end_col = _parse_bounded_sheet_range(range_a1)
        values = payload.get("values")
        _validate_sheet_values(values)
        if any(len(row) != end_col - start_col + 1 for row in values):
            raise ValueError("Each appended row must fit the range's column count.")
        input_option = payload.get("input_option", "RAW")
        if input_option not in {"RAW", "USER_ENTERED"}:
            raise ValueError("input_option must be RAW or USER_ENTERED.")
        affected_ranges.append(range_a1)
        payload = {"range": range_a1, "values": values, "input_option": input_option}
    elif kind == "values_clear":
        affected_ranges = payload.get("ranges")
        if not isinstance(affected_ranges, list) or not affected_ranges or len(affected_ranges) > MAX_API_OPERATIONS:
            raise ValueError(f"Provide between 1 and {MAX_API_OPERATIONS} ranges to clear.")
        total_cells = 0
        for range_a1 in affected_ranges:
            if not isinstance(range_a1, str):
                raise ValueError("Each spreadsheet range must be a string.")
            start_row, start_col, end_row, end_col = _parse_bounded_sheet_range(range_a1)
            total_cells += (end_row - start_row + 1) * (end_col - start_col + 1)
        if total_cells > MAX_WORKSPACE_CELLS:
            raise ValueError(f"A single clear operation is limited to {MAX_WORKSPACE_CELLS} cells total.")
        payload = {"ranges": affected_ranges}
    else:
        requests = payload.get("requests")
        if not isinstance(requests, list):
            raise ValueError("batch_update requires a list of Google Sheets API requests.")
        _validate_sheet_batch_requests(requests)
        payload = {"requests": requests}

    drive_service, _, sheets_service = _drive_services(user_id)
    metadata = _require_file(
        drive_service,
        spreadsheet_id,
        expected_mime="application/vnd.google-apps.spreadsheet",
        capability="canEdit",
    )
    before: dict = {"modified_time": metadata.get("modifiedTime")}
    if affected_ranges:
        values = sheets_service.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=affected_ranges,
            valueRenderOption="FORMULA",
        ).execute().get("valueRanges", [])
        before["ranges"] = values
    warnings = []
    if kind == "values_clear":
        warnings.append("This operation clears cell contents in the listed ranges.")
    if kind == "batch_update":
        destructive = {
            "deleteSheet", "deleteDimension", "deleteRange", "deleteEmbeddedObject",
            "deleteProtectedRange", "deleteTable", "deleteConditionalFormatRule",
        }
        warnings.extend(
            f"{operation} may remove spreadsheet data or structure."
            for request in payload["requests"]
            for operation in request
            if operation in destructive
        )
    after = {"summary": summary, "operation": {kind: payload}, "risk_warnings": warnings}
    operation_id = _approval_id(
        user_id,
        "sheets_update",
        spreadsheet_id,
        json.dumps({"before": before, "after": after}, sort_keys=True, ensure_ascii=False),
        str(metadata.get("modifiedTime") or ""),
    )
    if not _approved_operation(
        operation_id=operation_id,
        kind="sheets_update",
        title=metadata.get("name", "Google Sheet"),
        url=metadata.get("webViewLink"),
        before=_json_preview(before),
        after=_json_preview(after),
    ):
        return "The user rejected the proposed Sheets update. The spreadsheet was not changed."

    latest = _require_file(
        drive_service,
        spreadsheet_id,
        expected_mime="application/vnd.google-apps.spreadsheet",
        capability="canEdit",
    )
    if latest.get("modifiedTime") != metadata.get("modifiedTime"):
        _emit_task("edit-document", "Apply approved Sheets update", "failed")
        return "The spreadsheet changed after the proposal. Nothing was changed; inspect it and propose again."
    if affected_ranges:
        latest_values = sheets_service.spreadsheets().values().batchGet(
            spreadsheetId=spreadsheet_id,
            ranges=affected_ranges,
            valueRenderOption="FORMULA",
        ).execute().get("valueRanges", [])
        if latest_values != before["ranges"]:
            _emit_task("edit-document", "Apply approved Sheets update", "failed")
            return "The affected cells changed after the proposal. Nothing was changed; inspect them and propose again."

    _emit_task("edit-document", "Apply approved Sheets update", "in_progress")
    try:
        if kind == "values_update":
            result = sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "valueInputOption": payload["input_option"],
                    "data": payload["ranges"],
                },
            ).execute()
        elif kind == "values_append":
            result = sheets_service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=payload["range"],
                valueInputOption=payload["input_option"],
                insertDataOption="INSERT_ROWS",
                body={"values": payload["values"]},
            ).execute()
        elif kind == "values_clear":
            result = sheets_service.spreadsheets().values().batchClear(
                spreadsheetId=spreadsheet_id,
                body={"ranges": payload["ranges"]},
            ).execute()
        else:
            result = sheets_service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": payload["requests"]},
            ).execute()
    except Exception:
        log.exception("Failed to apply approved Sheets update %s", spreadsheet_id)
        _emit_task("edit-document", "Apply approved Sheets update", "failed")
        raise
    _emit_task("edit-document", "Apply approved Sheets update", "completed")
    return json.dumps(
        {
            "spreadsheet_id": spreadsheet_id,
            "title": metadata.get("name"),
            "drive_url": metadata.get("webViewLink"),
            "operation_kind": kind,
            "result": result,
        },
        ensure_ascii=False,
        default=str,
    )


def _column_number(column: str) -> int:
    number = 0
    for char in column:
        number = number * 26 + ord(char) - ord("A") + 1
    return number


def web_search(query: str) -> str:
    """Search the web using the self-hosted SearXNG instance."""
    settings = get_settings()
    searxng_url = getattr(settings, "searxng_url", "http://localhost:8080")

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                f"{searxng_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])[:5]

            if not results:
                return "No web search results found."

            formatted = []
            for r in results:
                title = r.get("title", "No Title")
                url = r.get("url", "")
                snippet = r.get("content", "")
                formatted.append(f"Title: {title}\nURL: {url}\nSnippet: {snippet}")
            return "\n\n".join(formatted)
    except Exception as e:
        return f"Web search failed: {str(e)}"

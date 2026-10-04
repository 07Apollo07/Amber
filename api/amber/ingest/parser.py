"""Document parsers for PDF, TXT, and Markdown files."""

import io
from typing import Any

from pypdf import PdfReader


def parse_document(file_bytes: bytes, mime_type: str, filename: str) -> list[dict[str, Any]]:
    """Parses file bytes into a list of section/page blocks with content and metadata."""
    file_type = _infer_file_type(mime_type, filename)

    if file_type == "pdf":
        return _parse_pdf(file_bytes)
    elif file_type in ("txt", "md"):
        text = file_bytes.decode("utf-8", errors="ignore")
        return [{"page": 1, "section_title": filename, "content": text}]
    else:
        text = file_bytes.decode("utf-8", errors="ignore")
        return [{"page": 1, "section_title": filename, "content": text}]


def _infer_file_type(mime_type: str, filename: str) -> str:
    lower_name = filename.lower()
    if "pdf" in mime_type or lower_name.endswith(".pdf"):
        return "pdf"
    if "markdown" in mime_type or lower_name.endswith(".md"):
        return "md"
    if "text" in mime_type or lower_name.endswith(".txt"):
        return "txt"
    return "other"


def _parse_pdf(file_bytes: bytes) -> list[dict[str, Any]]:
    reader = PdfReader(io.BytesIO(file_bytes))
    blocks = []
    for idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            blocks.append(
                {
                    "page": idx + 1,
                    "section_title": f"Page {idx + 1}",
                    "content": text,
                }
            )
    return blocks

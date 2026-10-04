"""Tests for document parsing, chunking, and ingestion API endpoints."""

from fastapi.testclient import TestClient

from amber.ingest.chunker import chunk_document_blocks
from amber.ingest.parser import parse_document


def test_parse_text_document():
    content = b"Hello world! This is a test markdown document.\n\n# Heading 1\nSome paragraph text here."
    blocks = parse_document(content, "text/markdown", "test.md")
    assert len(blocks) > 0
    assert any("Hello world" in b["content"] for b in blocks)


def test_chunk_document_blocks():
    blocks = [{"content": "Paragraph one. " * 50, "section_title": "Section 1", "metadata": {}}]
    chunks = chunk_document_blocks(blocks)
    assert len(chunks) > 0
    assert all("content" in c and "token_count" in c for c in chunks)


def test_documents_endpoints_unauthenticated(client: TestClient):
    response = client.get("/api/documents")
    assert response.status_code == 401

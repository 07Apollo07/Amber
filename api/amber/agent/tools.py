"""Agent tools: pgvector document search and SearXNG web search."""

import httpx
from amber.util.config import get_settings
from amber.util.db import connect
from amber.repository import hybrid_search_chunks
from amber.ingest.embedder import generate_embeddings


def vector_search(query: str, user_email: str = "system@amber.local") -> str:
    """Search internal documents using hybrid vector cosine distance and full-text search."""
    settings = get_settings()
    embeddings = generate_embeddings([query])
    if not embeddings:
        return "No internal embeddings generated."

    with connect(settings) as conn:
        results = hybrid_search_chunks(
            conn,
            user_email=user_email,
            user_domain=None,
            query_embedding=embeddings[0],
            query_text=query,
            limit=5,
        )

    if not results:
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

        source_header = f"[Source: {doc_title} (ID: {doc_id}, Type: {file_type}"
        if page is not None:
            source_header += f", Page: {page}"
        if drive_url:
            source_header += f", Drive Link: {drive_url}"
        source_header += "]"

        formatted.append(f"{source_header}\n{content}")
    return "\n\n".join(formatted)


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

"""Embedding generation using Google GenAI SDK (text-embedding-004, 1536 dimensions)."""

from google import genai
from google.genai import types
from posthog.ai.gemini import Client as PostHogGeminiClient

from amber.util.config import get_settings
from amber.util.posthog import get_posthog_client


def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """Generates 1536-dimensional embeddings for a list of text strings."""
    if not texts:
        return []

    settings = get_settings()
    api_key = settings.gemini_api_key.get_secret_value() or None
    posthog_client = get_posthog_client()
    client = (
        PostHogGeminiClient(posthog_client=posthog_client, **({"api_key": api_key} if api_key else {}))
        if posthog_client is not None
        else genai.Client(api_key=api_key) if api_key else genai.Client()
    )

    embeddings = []
    # Batch or individual generation
    for text in texts:
        response = client.models.embed_content(
            model="gemini-embedding-2",
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=1536),
        )
        embeddings.append(list(response.embeddings[0].values))
    return embeddings

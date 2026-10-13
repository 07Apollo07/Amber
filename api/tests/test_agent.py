"""Tests for the agent chat and conversation history endpoints."""

import pytest
from fastapi.testclient import TestClient


def test_agent_chat_unauthenticated(client: TestClient) -> None:
    resp = client.post("/api/agent/chat", json={"message": "Hello"})
    assert resp.status_code in (401, 403)


def test_get_conversation_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/agent/conversations/some-thread-id")
    assert resp.status_code in (401, 403)

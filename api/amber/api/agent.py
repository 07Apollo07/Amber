"""Agent chat API endpoint with LangGraph state persistence in PostgreSQL."""

import asyncio
import base64
import inspect
import json
import logging
import os
import time
import uuid
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from amber import repository
from amber.agent.graph import create_agent_graph, get_agent_model
from amber.util import db
from amber.util.config import Settings
from amber.util.security import CsrfProtected, CurrentUser, DbDep, SettingsDep, cookie_names, verified_session

router = APIRouter(prefix="/api/agent", tags=["agent"])
log = logging.getLogger(__name__)

_MODEL_LIST_CACHE_SECONDS = 60
_LITELLM_REQUEST_TIMEOUT_SECONDS = 10
_LIVE_ALLOWED_EVENTS = {
    "conversation.item.create",
    "input_audio_buffer.append",
    "input_audio_buffer.clear",
    "input_audio_buffer.commit",
    "response.cancel",
    "response.create",
    "session.update",
}
_LIVE_MAX_MESSAGE_BYTES = 256 * 1024


class ChatRequest(BaseModel):
    message: str = ""
    thread_id: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=255)
    collection_id: uuid.UUID | None = None
    decision: Literal["approve", "reject"] | None = None
    operation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ConversationName(BaseModel):
    name: str = Field(min_length=1, max_length=255)


def _default_serializer(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def _message_to_dict(message: Any) -> dict:
    if hasattr(message, "model_dump"):
        d = message.model_dump()
    elif hasattr(message, "__dict__"):
        d = dict(message.__dict__)
    else:
        d = {"content": str(message)}
    if hasattr(message, "type"):
        d["type"] = message.type
    return d


def _serialize_data(stream_type: str, data: Any) -> str:
    if stream_type == "messages":
        if isinstance(data, (list, tuple)) and len(data) == 2:
            message, metadata = data
            return json.dumps([_message_to_dict(message), metadata], default=_default_serializer)
    return json.dumps(data, default=_default_serializer)


def _litellm_models_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1/models"):
        return base
    if base.endswith("/v1"):
        return f"{base}/models"
    return f"{base}/v1/models"


def _litellm_realtime_url(base_url: str, model: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1/realtime"):
        pass
    elif path.endswith("/v1"):
        path = f"{path}/realtime"
    else:
        path = f"{path}/v1/realtime"
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}.get(parts.scheme)
    if scheme is None or not parts.netloc:
        raise ValueError("LiteLLM base URL must be an absolute HTTP(S) URL")
    return urlunsplit((scheme, parts.netloc, path, urlencode({"model": model}), ""))


@router.get("/live/config")
async def get_live_config(user: CurrentUser, settings: SettingsDep) -> dict[str, Any]:
    """Expose only the configured Live model ID; proxy credentials remain server-side."""
    enabled = bool(settings.litellm_base_url and settings.agent_live_model_name)
    return {
        "enabled": enabled,
        "model": settings.agent_live_model_name if enabled else None,
    }


@router.websocket("/live")
async def live_agent(websocket: WebSocket) -> None:
    """Authenticate and relay Gemini Live WebSocket events through the LiteLLM proxy."""
    settings: Settings = websocket.app.state.settings
    if websocket.headers.get("origin") != settings.public_origin:
        await websocket.close(code=4403, reason="Cross-origin connection blocked")
        return
    session_cookie_name, _, _ = cookie_names(settings)
    if not websocket.cookies.get(session_cookie_name):
        await websocket.close(code=4401, reason="Not signed in")
        return
    if not settings.litellm_base_url or not settings.agent_live_model_name:
        await websocket.close(code=1013, reason="Live voice is not configured")
        return

    try:
        with db.connect(settings) as conn:
            _, claims = verified_session(websocket, settings, conn)
            user = repository.get_user_by_firebase_uid(conn, claims["uid"])
            if user is None or user["status"] != "active":
                await websocket.close(code=4401, reason="Not signed in")
                return
    except HTTPException:
        await websocket.close(code=4401, reason="Not signed in")
        return

    try:
        upstream_url = _litellm_realtime_url(settings.litellm_base_url, settings.agent_live_model_name)
    except ValueError:
        log.exception("Invalid LiteLLM base URL for Live voice")
        await websocket.close(code=1011, reason="Live voice is unavailable")
        return

    await websocket.accept()
    api_key = settings.litellm_api_key.get_secret_value()
    headers = {"OpenAI-Beta": "realtime=v1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with websockets.connect(
            upstream_url,
            extra_headers=headers,
            max_size=_LIVE_MAX_MESSAGE_BYTES,
            ping_interval=20,
            ping_timeout=20,
        ) as upstream:

            async def browser_to_proxy() -> None:
                while True:
                    message = await websocket.receive_text()
                    if len(message.encode("utf-8")) > _LIVE_MAX_MESSAGE_BYTES:
                        raise ValueError("Live voice message exceeded the size limit")
                    try:
                        event = json.loads(message)
                    except ValueError as exc:
                        raise ValueError("Live voice messages must be JSON") from exc
                    if not isinstance(event, dict) or event.get("type") not in _LIVE_ALLOWED_EVENTS:
                        raise ValueError("Unsupported Live voice event")
                    await upstream.send(message)

            async def proxy_to_browser() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = {
                asyncio.create_task(browser_to_proxy()),
                asyncio.create_task(proxy_to_browser()),
            }
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                error = task.exception()
                if error is not None:
                    raise error
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        log.info("Live voice WebSocket disconnected")
    except Exception:
        log.exception("Live voice proxy failed")
        await websocket.close(code=1011, reason="Live voice connection failed")
    else:
        await websocket.close(code=1000)


async def _available_models(request: Request, settings: Settings) -> list[str]:
    """Return the proxy's currently available model IDs, cached briefly per API process."""
    if not settings.litellm_base_url:
        return []

    now = time.monotonic()
    cached = getattr(request.app.state, "litellm_models_cache", None)
    if cached and cached["expires_at"] > now:
        return cached["models"]

    headers = {}
    api_key = settings.litellm_api_key.get_secret_value()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_LITELLM_REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(_litellm_models_url(settings.litellm_base_url), headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Unable to load available models from LiteLLM: %s", exc)
        raise HTTPException(status_code=502, detail="Unable to load available models from LiteLLM") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        log.warning("LiteLLM returned an invalid model list response")
        raise HTTPException(status_code=502, detail="LiteLLM returned an invalid model list")

    models = list(
        dict.fromkeys(
            item["id"]
            for item in payload["data"]
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        )
    )
    request.app.state.litellm_models_cache = {
        "models": models,
        "expires_at": now + _MODEL_LIST_CACHE_SECONDS,
    }
    return models


@router.get("/models")
async def list_agent_models(
    request: Request,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """List model IDs available to Amber through the configured LiteLLM proxy."""
    if not settings.litellm_base_url:
        return {
            "enabled": False,
            "default_model": settings.agent_model_name,
            "models": [],
        }

    return {
        "enabled": True,
        "default_model": settings.agent_model_name,
        "models": await _available_models(request, settings),
    }


@router.post("/v2/stream", dependencies=[CsrfProtected])
async def stream_agent_v2(
    request: Request,
    body: ChatRequest,
    user: CurrentUser,
    conn: DbDep,
    settings: SettingsDep,
) -> StreamingResponse:
    """Stream chat responses following the official LangGraph v2 protocol with Postgres checkpointing."""
    graph = getattr(request.app.state, "agent_graph", None)
    if not graph:
        graph = create_agent_graph()

    if body.decision is not None and not body.thread_id:
        raise HTTPException(status_code=400, detail="A conversation ID is required to respond to an approval")
    thread_id = body.thread_id or str(uuid.uuid4())
    try:
        conversation_id = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID") from None
    conversation = (
        repository.get_conversation(conn, conversation_id, user["id"])
        if body.decision is not None
        else repository.ensure_agent_conversation(conn, conversation_id, user["id"])
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if body.decision is None and body.collection_id is not None:
        collection = repository.get_accessible_collection(
            conn,
            body.collection_id,
            user_email=user["email"],
            user_domain=user.get("domain"),
        )
        if collection is None:
            raise HTTPException(status_code=404, detail="Collection not found")

    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"user_email": user["email"]}
    }
    if body.model:
        available_models = await _available_models(request, settings)
        if body.model not in available_models:
            raise HTTPException(status_code=400, detail="The selected model is not available")
        config["configurable"]["model_name"] = body.model
    if body.decision is None and not body.message.strip():
        raise HTTPException(status_code=400, detail="A message is required")
    if body.decision is not None:
        if body.message.strip():
            raise HTTPException(status_code=400, detail="Approval requests cannot include a chat message")
        if not body.operation_id:
            raise HTTPException(status_code=400, detail="An approval operation ID is required")
        state = await graph.aget_state(config)
        if not state or not state.values or state.values.get("user_id") != str(user["id"]):
            raise HTTPException(status_code=404, detail="Pending approval not found")
        pending = [
            interrupt.value
            for task in state.tasks
            for interrupt in getattr(task, "interrupts", ())
            if isinstance(getattr(interrupt, "value", None), dict)
        ]
        if not any(
            item.get("type") == "workspace_approval"
            and item.get("operation_id") == body.operation_id
            for item in pending
        ):
            raise HTTPException(status_code=409, detail="This approval is no longer pending")
        graph_input: Any = Command(
            resume={"approved": body.decision == "approve", "operation_id": body.operation_id}
        )
    else:
        graph_input = {
            "messages": [("user", body.message)],
            "user_id": str(user["id"]),
            "user_email": user["email"].lower(),
            "user_domain": (user.get("domain") or "").lower() or None,
            "collection_id": str(body.collection_id) if body.collection_id else None,
            "tasks": [],
            "visuals": {},
        }
    conn.commit()

    async def sse_generator():
        print(f"[SSE_V2] Starting stream for thread_id={thread_id}, message={body.message!r}")
        yield f"event: metadata\ndata: {json.dumps({'thread_id': thread_id})}\n\n"
        try:
            async for chunk in graph.astream(
                graph_input,
                config=config,
                stream_mode=["values", "messages", "updates", "custom"],
                version="v2",
            ):
                stream_type = chunk.get("type", "unknown")
                ns = chunk.get("ns", ())
                data = chunk.get("data")

                if ns:
                    event_name = f"{stream_type}|{'|'.join(ns)}"
                else:
                    event_name = stream_type

                print(f"[SSE_V2] Chunk type={stream_type}, event_name={event_name}, data={data}")
                serialized_data = _serialize_data(stream_type, data)
                print(f"[SSE_V2] Yielding serialized_data={serialized_data[:200]}...")
                yield f"event: {event_name}\ndata: {serialized_data}\n\n"
            if getattr(graph, "checkpointer", None):
                final_state = await graph.aget_state(config)
                for task in getattr(final_state, "tasks", ()):
                    for pending_interrupt in getattr(task, "interrupts", ()):
                        value = getattr(pending_interrupt, "value", None)
                        if isinstance(value, dict) and value.get("type") == "workspace_approval":
                            yield f"event: approval\ndata: {json.dumps(value, default=_default_serializer)}\n\n"
            print("[SSE_V2] Stream completed successfully, yielding [DONE]")
            yield "event: end\ndata: [DONE]\n\n"
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[SSE_V2] Error during streaming: {e}\n{tb}")
            yield f"event: error\ndata: {json.dumps({'error': str(e), 'traceback': tb})}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        },
    )


@router.post("/chat", dependencies=[CsrfProtected])
def chat_agent(request: Request, body: ChatRequest, user: CurrentUser) -> StreamingResponse:
    """Stream chat responses from the LangGraph agent with conversation state stored in Postgres."""
    graph = getattr(request.app.state, "agent_legacy_graph", None)
    if not graph:
        graph = create_agent_graph()

    def generate():
        thread_id = body.thread_id or str(uuid.uuid4())
        yield f"data: {json.dumps({'thread_id': thread_id})}\n\n"

        config = {
            "configurable": {"thread_id": thread_id},
            "metadata": {"user_email": user["email"]}
        }
        try:
            tool_calls = []
            tool_results = []
            
            for event in graph.stream(
                {
                    "messages": [("user", body.message)],
                    "user_id": str(user["id"]),
                    "user_email": user["email"].lower(),
                    "user_domain": (user.get("domain") or "").lower() or None,
                },
                config=config,
            ):
                for node_name, node_output in event.items():
                    messages = node_output.get("messages", [])
                    for msg in messages:
                        if not hasattr(msg, "content") or not msg.content:
                            continue
                        
                        msg_type = getattr(msg, "type", "unknown")
                        
                        if msg_type == "tool":
                            # This is a tool result - capture it for trace panel, don't send to chat
                            tool_name = getattr(msg, "name", "unknown_tool")
                            tool_call_id = getattr(msg, "tool_call_id", None)
                            
                            tool_results.append({
                                "tool_call_id": tool_call_id,
                                "name": tool_name,
                                "result": msg.content,
                                "status": "success"
                            })
                            
                            # Update corresponding tool call with result
                            for tc in tool_calls:
                                if tc["id"] == tool_call_id:
                                    tc["result"] = msg.content
                                    tc["status"] = "success"
                                    break
                            
                            # Send tool result as structured event for trace panel
                            yield f"data: {json.dumps({'type': 'tool_result', 'tool_call_id': tool_call_id, 'name': tool_name, 'result': msg.content})}\n\n"
                            
                        elif msg_type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                            # This is an AI message with tool calls - capture for trace panel
                            for tc in msg.tool_calls:
                                tool_call_data = {
                                    "id": tc.get("id"),
                                    "name": tc.get("name"),
                                    "args": json.dumps(tc.get("args", {})),
                                    "status": "running",
                                    "latencyMs": None
                                }
                                tool_calls.append(tool_call_data)
                                yield f"data: {json.dumps({'type': 'tool_call', **tool_call_data})}\n\n"
                            
                            # Also send the AI message content if it has any
                            if msg.content:
                                yield f"data: {json.dumps({'node': node_name, 'content': msg.content})}\n\n"
                                
                        elif msg_type in ("human", "ai"):
                            # Regular chat messages - stream to chat
                            yield f"data: {json.dumps({'node': node_name, 'content': msg.content})}\n\n"
            
            # Send final tool calls summary
            if tool_calls:
                yield f"data: {json.dumps({'type': 'tool_calls_complete', 'tool_calls': tool_calls})}\n\n"
            if tool_results:
                yield f"data: {json.dumps({'type': 'tool_results_complete', 'tool_results': tool_results})}\n\n"
                
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/conversations")
def list_conversations(
    user: CurrentUser,
    conn: DbDep,
) -> list[dict[str, Any]]:
    """List the current user's agent conversations."""
    conversations = repository.list_conversations_for_user(conn, user["id"])
    return [
        {
            "id": str(conversation["id"]),
            "title": conversation["title"],
            "updatedAt": conversation["updated_at"].isoformat(),
        }
        for conversation in conversations
    ]


@router.get("/conversations/{thread_id}")
def get_conversation(
    request: Request,
    thread_id: uuid.UUID,
    user: CurrentUser,
    conn: DbDep,
) -> dict[str, Any]:
    """Retrieve conversation history for a given thread_id from Postgres."""
    conversation = repository.get_conversation(conn, thread_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    graph = getattr(request.app.state, "agent_graph", None)
    if not graph:
        graph = create_agent_graph()

    config = {"configurable": {"thread_id": str(thread_id)}}
    try:
        state = graph.get_state(config)
        messages = []
        tasks = []
        visuals = {}
        pending_approval = None
        if state and state.values:
            raw_messages = state.values.get("messages", [])
            for msg in raw_messages:
                msg_dict = _message_to_dict(msg)
                messages.append(msg_dict)
            raw_tasks = state.values.get("tasks", [])
            if isinstance(raw_tasks, list):
                tasks = raw_tasks
            raw_visuals = state.values.get("visuals", {})
            if isinstance(raw_visuals, dict):
                visuals = raw_visuals
            for task in getattr(state, "tasks", ()):
                for pending_interrupt in getattr(task, "interrupts", ()):
                    value = getattr(pending_interrupt, "value", None)
                    if isinstance(value, dict) and value.get("type") == "workspace_approval":
                        pending_approval = value
                        break
        return {
            "thread_id": str(thread_id),
            "title": conversation["title"],
            "messages": messages,
            "tasks": tasks,
            "visuals": visuals,
            "pending_approval": pending_approval,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load conversation: {e}") from e


@router.put("/conversations/{thread_id}", dependencies=[CsrfProtected])
def rename_conversation(
    thread_id: uuid.UUID,
    req: ConversationName,
    user: CurrentUser,
    conn: DbDep,
) -> dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Conversation name can't be empty")
    try:
        conversation = repository.update_conversation_title(conn, thread_id, user["id"], name)
    except LookupError:
        raise HTTPException(status_code=404, detail="Conversation not found") from None
    conn.commit()
    return {"id": str(conversation["id"]), "title": conversation["title"]}


@router.delete("/conversations/{thread_id}", dependencies=[CsrfProtected])
async def remove_conversation(
    request: Request,
    thread_id: uuid.UUID,
    user: CurrentUser,
    conn: DbDep,
) -> dict[str, bool]:
    conversation = repository.get_conversation(conn, thread_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    graph = getattr(request.app.state, "agent_graph", None)
    if graph and graph.checkpointer:
        delete_async = getattr(graph.checkpointer, "adelete_thread", None)
        if callable(delete_async):
            deleted = delete_async(str(thread_id))
        else:
            deleted = graph.checkpointer.delete_thread(str(thread_id))
        if inspect.isawaitable(deleted):
            await deleted
    repository.delete_conversation(conn, thread_id, user["id"])
    conn.commit()
    return {"success": True}


@router.post("/conversations/{thread_id}/generate-title", dependencies=[CsrfProtected])
def generate_conversation_title(
    request: Request,
    thread_id: uuid.UUID,
    user: CurrentUser,
    conn: DbDep,
    settings: SettingsDep,
) -> dict[str, str]:
    conversation = repository.get_conversation(conn, thread_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    graph = getattr(request.app.state, "agent_graph", None)
    if not graph:
        graph = create_agent_graph(settings=settings)
    if not graph.checkpointer:
        raise HTTPException(status_code=503, detail="Conversation history is unavailable")

    state = graph.get_state({"configurable": {"thread_id": str(thread_id)}})
    messages = state.values.get("messages", []) if state and state.values else []
    first_user_message = next(
        (message.content for message in messages if getattr(message, "type", "") == "human"),
        None,
    )
    if not first_user_message:
        raise HTTPException(status_code=400, detail="Conversation has no user message to title")

    result = get_agent_model(settings).invoke(
        [
            SystemMessage(
                content="Create a concise, descriptive title for this conversation. "
                "Return only the title, with no quotation marks or explanation. "
                "Use at most 8 words."
            ),
            HumanMessage(content=str(first_user_message)[:2000]),
        ]
    )
    title_content = result.content
    if isinstance(title_content, list):
        title_content = " ".join(
            part["text"]
            for part in title_content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    title = str(title_content).strip().strip("\"'")[:255].strip()
    if not title:
        raise HTTPException(status_code=502, detail="The model returned an empty conversation title")

    updated = repository.update_conversation_title(conn, thread_id, user["id"], title)
    conn.commit()
    return {"id": str(updated["id"]), "title": updated["title"]}

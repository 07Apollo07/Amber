"""Agent chat API endpoint with LangGraph state persistence in PostgreSQL."""

import json
import inspect
import uuid
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from amber import repository
from amber.agent.graph import create_agent_graph, get_agent_model
from amber.util.security import CsrfProtected, CurrentUser, DbDep, SettingsDep

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


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


@router.post("/v2/stream")
async def stream_agent_v2(
    request: Request,
    body: ChatRequest,
    user: CurrentUser,
    conn: DbDep,
) -> StreamingResponse:
    """Stream chat responses following the official LangGraph v2 protocol with Postgres checkpointing."""
    graph = getattr(request.app.state, "agent_graph", None)
    if not graph:
        graph = create_agent_graph()

    thread_id = body.thread_id or str(uuid.uuid4())
    try:
        conversation_id = uuid.UUID(thread_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid conversation ID") from None
    conversation = repository.ensure_agent_conversation(conn, conversation_id, user["id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conn.commit()

    config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {"user_email": user["email"]}
    }

    async def sse_generator():
        print(f"[SSE_V2] Starting stream for thread_id={thread_id}, message={body.message!r}")
        yield f"event: metadata\ndata: {json.dumps({'thread_id': thread_id})}\n\n"
        try:
            async for chunk in graph.astream(
                {"messages": [("user", body.message)]},
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


@router.post("/chat")
def chat_agent(request: Request, body: ChatRequest, user: CurrentUser) -> StreamingResponse:
    """Stream chat responses from the LangGraph agent with conversation state stored in Postgres."""
    graph = getattr(request.app.state, "agent_graph", None)
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
            current_tool_call = None
            
            for event in graph.stream({"messages": [("user", body.message)]}, config=config):
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
        if state and state.values:
            raw_messages = state.values.get("messages", [])
            for msg in raw_messages:
                msg_dict = _message_to_dict(msg)
                messages.append(msg_dict)
        return {
            "thread_id": str(thread_id),
            "title": conversation["title"],
            "messages": messages,
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

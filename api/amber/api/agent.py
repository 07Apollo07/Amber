"""Agent chat API endpoint with LangGraph state persistence in PostgreSQL."""

import json
import uuid
from typing import Any
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from amber.agent.graph import create_agent_graph
from amber.util.security import CurrentUser

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None


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
def list_conversations(request: Request, user: CurrentUser) -> list[dict[str, Any]]:
    """List recent conversations for the current user from Postgres checkpoints."""
    graph = getattr(request.app.state, "agent_graph", None)
    if not graph or not graph.checkpointer:
        return []

    conversations = {}
    try:
        for c in graph.checkpointer.list(None):
            thread_id = c.config["configurable"].get("thread_id")
            if not thread_id:
                continue

            title = "New Conversation"
            if c.checkpoint and "channel_values" in c.checkpoint:
                messages = c.checkpoint["channel_values"].get("messages", [])
                for msg in messages:
                    content = getattr(msg, "content", None)
                    if content:
                        title = content[:40] + ("..." if len(content) > 40 else "")
                        break

            conversations[thread_id] = {
                "id": thread_id,
                "title": title,
                "updatedAt": "Recent"
            }
    except Exception:
        pass

    return list(conversations.values())


@router.get("/conversations/{thread_id}")
def get_conversation(request: Request, thread_id: str, user: CurrentUser) -> dict[str, Any]:
    """Retrieve conversation history for a given thread_id from Postgres."""
    graph = getattr(request.app.state, "agent_graph", None)
    if not graph:
        graph = create_agent_graph()

    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = graph.get_state(config)
        messages = []
        if state and state.values:
            raw_messages = state.values.get("messages", [])
            for msg in raw_messages:
                role = getattr(msg, "type", "unknown")
                content = getattr(msg, "content", str(msg))
                messages.append({"role": role, "content": content})
        return {"thread_id": thread_id, "messages": messages}
    except Exception as e:
        return {"thread_id": thread_id, "messages": [], "error": str(e)}

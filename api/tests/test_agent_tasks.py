"""Tests for the agent's persistent task pad."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from amber.agent.tools import _normalize_agent_tasks, update_task_list


class TaskState(MessagesState):
    tasks: list[dict]


def test_normalize_agent_tasks_trims_titles_and_preserves_status() -> None:
    assert _normalize_agent_tasks(
        [{"id": "read-source", "title": "  Read the source  ", "status": "in_progress"}]
    ) == [{"id": "read-source", "title": "Read the source", "status": "in_progress"}]


@pytest.mark.parametrize(
    "tasks",
    [
        [{"id": "duplicate", "title": "First", "status": "pending"},
         {"id": "duplicate", "title": "Second", "status": "pending"}],
        [{"id": "invalid id", "title": "Read source", "status": "pending"}],
        [{"id": "read-source", "title": "Read source", "status": "unknown"}],
        [{"id": "read-source", "title": " " * 2, "status": "pending"}],
    ],
)
def test_normalize_agent_tasks_rejects_invalid_tasks(tasks: list[dict]) -> None:
    with pytest.raises(ValueError):
        _normalize_agent_tasks(tasks)


def test_update_task_list_tool_updates_graph_state() -> None:
    plan = [{"id": "read-source", "title": "Read the source", "status": "in_progress"}]
    builder = StateGraph(TaskState)
    builder.add_node(
        "request_plan",
        lambda _: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "update_task_list",
                            "args": {"tasks": plan, "update_summary": "Starting the research"},
                            "id": "task-plan-call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
    )
    builder.add_node("tools", ToolNode([update_task_list]))
    builder.add_edge(START, "request_plan")
    builder.add_edge("request_plan", "tools")
    builder.add_edge("tools", END)

    result = builder.compile().invoke({"messages": [], "tasks": []})

    assert result["tasks"] == plan
    assert result["messages"][-1].tool_call_id == "task-plan-call"

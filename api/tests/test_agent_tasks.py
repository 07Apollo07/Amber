"""Tests for the agent's persistent task pad."""

import operator
from typing import Annotated

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from amber.agent.tools import (
    _normalize_agent_tasks,
    _validate_visual_rows,
    render_chart,
    render_timeline,
    update_task_list,
)


class TaskState(MessagesState):
    tasks: list[dict]


class VisualState(MessagesState):
    visuals: Annotated[dict[str, dict], operator.or_]


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


def test_visual_row_validation_rejects_nested_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="must be strings, numbers"):
        _validate_visual_rows([{"month": "Jan", "amount": {"unexpected": "object"}}])
    with pytest.raises(ValueError, match="must be finite"):
        _validate_visual_rows([{"month": "Jan", "amount": float("nan")}])


@pytest.mark.parametrize(
    ("chart_type", "series"),
    [
        ("bar", ["revenue"]),
        ("line", ["revenue"]),
        ("area", ["revenue"]),
        ("donut", ["share"]),
    ],
)
def test_render_chart_accepts_supported_chart_types(chart_type: str, series: list[str]) -> None:
    chart = {
        "title": "Product share",
        "chart_type": chart_type,
        "category_key": "product",
        "series": series,
        "rows": [{"product": "Product A", series[0]: 45}],
        "description": "",
    }
    builder = StateGraph(VisualState)
    builder.add_node(
        "request_chart",
        lambda _: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "render_chart",
                            "args": chart,
                            "id": f"{chart_type}-call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
    )
    builder.add_node("tools", ToolNode([render_chart]))
    builder.add_edge(START, "request_chart")
    builder.add_edge("request_chart", "tools")
    builder.add_edge("tools", END)

    result = builder.compile().invoke({"messages": [], "visuals": {}})

    assert result["visuals"][f"{chart_type}-call"]["chart_type"] == chart_type


def test_render_chart_rejects_donut_with_multiple_series() -> None:
    with pytest.raises(ValueError, match="exactly one numeric series"):
        render_chart.func(
            title="Product share",
            chart_type="donut",
            category_key="product",
            series=["share", "returns"],
            rows=[{"product": "Product A", "share": 45, "returns": 2}],
            description="",
            tool_call_id="donut-call",
        )


def test_render_chart_tool_updates_visual_state() -> None:
    chart = {
        "title": "Revenue by month",
        "chart_type": "line",
        "category_key": "month",
        "series": ["revenue"],
        "rows": [{"month": "Jan", "revenue": 120}],
        "description": "Source: reviewed workbook.",
    }
    builder = StateGraph(VisualState)
    builder.add_node(
        "request_chart",
        lambda _: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "render_chart",
                            "args": chart,
                            "id": "chart-call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
    )
    builder.add_node("tools", ToolNode([render_chart]))
    builder.add_edge(START, "request_chart")
    builder.add_edge("request_chart", "tools")
    builder.add_edge("tools", END)

    result = builder.compile().invoke({"messages": [], "visuals": {}})

    assert result["visuals"]["chart-call"]["kind"] == "chart"
    assert result["visuals"]["chart-call"]["rows"] == chart["rows"]


def test_render_timeline_accepts_display_date_formats_and_longer_titles() -> None:
    events = [
        {
            "date": "2024-01-15",
            "event": "A detailed milestone title " + ("with useful context " * 10),
        },
        {
            "date_label": "Q2 2024",
            "title": "Quarterly milestone",
            "summary": "A source-backed summary.",
        },
        {
            "timestamp": 2025,
            "label": "Annual milestone",
            "details": "",
        },
    ]
    builder = StateGraph(VisualState)
    builder.add_node(
        "request_timeline",
        lambda _: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "render_timeline",
                            "args": {
                                "title": "Founding milestones",
                                "events": events,
                                "description": "",
                            },
                            "id": "timeline-call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        },
    )
    builder.add_node("tools", ToolNode([render_timeline]))
    builder.add_edge(START, "request_timeline")
    builder.add_edge("request_timeline", "tools")
    builder.add_edge("tools", END)

    result = builder.compile().invoke({"messages": [], "visuals": {}})

    assert result["visuals"]["timeline-call"]["events"] == [
        {"date": "2024-01-15", "event": events[0]["event"].strip(), "details": ""},
        {"date": "Q2 2024", "event": "Quarterly milestone", "details": "A source-backed summary."},
        {"date": "2025", "event": "Annual milestone", "details": ""},
    ]


@pytest.mark.parametrize(
    "event",
    [
        {"date": "2024"},
        {"event": "Milestone"},
        {"date": "2024", "event": "  "},
        {"date": "2024", "event": "Milestone", "details": {"not": "text"}},
    ],
)
def test_render_timeline_rejects_events_missing_usable_content(event: dict) -> None:
    with pytest.raises(ValueError):
        render_timeline.func(
            title="Milestones",
            events=[event],
            description="",
            tool_call_id="invalid-timeline",
        )

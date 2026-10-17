"""Tests for the Google Workspace agent tool validation and previews."""

from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from amber.agent.graph import _handle_agent_tool_error
from amber.agent.tools import (
    _SHEETS_READ_FIELDS,
    _doc_text,
    _docs_change_preview,
    _normalize_sheet_operation,
    _parse_bounded_sheet_range,
    _skip_first_section_break,
    _validate_docs_requests,
    _validate_sheet_batch_requests,
    drive_get_file,
    drive_upload_file,
)


def test_sheet_read_field_mask_places_named_ranges_at_spreadsheet_level() -> None:
    assert ",namedRanges," in _SHEETS_READ_FIELDS
    assert "sheets(" in _SHEETS_READ_FIELDS
    sheet_fields = _SHEETS_READ_FIELDS.split("sheets(", 1)[1]
    assert "namedRanges" not in sheet_fields
    assert "pivotTables" not in sheet_fields
    assert "pivotTable" in sheet_fields


def test_doc_text_reads_body_tables_and_tab_content() -> None:
    document = {
        "body": {
            "content": [
                {"paragraph": {"elements": [{"textRun": {"content": "Body text\n"}}]}},
                {
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {
                                        "content": [
                                            {
                                                "paragraph": {
                                                    "elements": [
                                                        {"textRun": {"content": "Table cell\n"}}
                                                    ]
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                },
            ]
        }
    }
    assert _doc_text(document) == "Body text\nTable cell\n"

    tabbed_document = {
        "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "duplicate"}}]}}]},
        "tabs": [
            {
                "documentTab": {
                    "body": {
                        "content": [
                            {"paragraph": {"elements": [{"textRun": {"content": "First tab"}}]}}
                        ]
                    },
                    "headers": {
                        "header-1": {
                            "content": [
                                {"paragraph": {"elements": [{"textRun": {"content": "Header"}}]}}
                            ]
                        }
                    },
                }
            }
        ],
    }
    assert _doc_text(tabbed_document) == "First tabHeader"


def test_docs_batch_validation_allows_supported_requests_and_rejects_others() -> None:
    _validate_docs_requests(
        [
            {
                "replaceAllText": {
                    "containsText": {"text": "old text", "matchCase": True},
                    "replaceText": "new text",
                }
            }
        ]
    )
    with pytest.raises(ValueError, match="not allowed"):
        _validate_docs_requests([{"createNamedStyle": {}}])
    with pytest.raises(ValueError, match="HTTPS"):
        _validate_docs_requests([{"insertInlineImage": {"uri": "http://example.com/image.png"}}])


def test_docs_preview_describes_text_changes() -> None:
    preview = _docs_change_preview(
        "Update a heading",
        [
            {
                "replaceAllText": {
                    "containsText": {"text": "Old heading"},
                    "replaceText": "New heading",
                }
            }
        ],
    )
    assert preview["summary"] == "Update a heading"
    assert preview["proposed_effects"] == ["Replace text matching 'Old heading' with 'New heading'."]


def test_paragraph_style_range_skips_first_section_break() -> None:
    document = {
        "body": {
            "content": [
                {"startIndex": 0, "endIndex": 1, "sectionBreak": {"sectionStyle": {}}},
                {"startIndex": 1, "endIndex": 20, "paragraph": {"elements": []}},
            ]
        }
    }
    requests = [
        {
            "updateParagraphStyle": {
                "range": {"startIndex": 0, "endIndex": 20},
                "paragraphStyle": {"namedStyleType": "HEADING_1"},
                "fields": "namedStyleType",
            }
        }
    ]
    adjusted = _skip_first_section_break(document, requests)
    assert adjusted[0]["updateParagraphStyle"]["range"] == {"startIndex": 1, "endIndex": 20}
    assert requests[0]["updateParagraphStyle"]["range"]["startIndex"] == 0


def test_paragraph_style_range_rejects_targeting_only_first_section_break() -> None:
    document = {
        "body": {
            "content": [
                {"startIndex": 0, "endIndex": 1, "sectionBreak": {"sectionStyle": {}}},
                {"startIndex": 1, "endIndex": 20, "paragraph": {"elements": []}},
            ]
        }
    }
    with pytest.raises(ValueError, match="first section break"):
        _skip_first_section_break(
            document,
            [{"updateParagraphStyle": {"range": {"startIndex": 0, "endIndex": 1}}}],
        )


def test_sheet_ranges_are_bounded_and_cell_limited() -> None:
    assert _parse_bounded_sheet_range("'Budget 2025'!A1:D20") == (1, 1, 20, 4)
    with pytest.raises(ValueError, match="bounded A1 range"):
        _parse_bounded_sheet_range("Budget!A:A")
    with pytest.raises(ValueError, match="limited"):
        _parse_bounded_sheet_range("Budget!A1:AB72")


def test_sheets_batch_validation_allowlists_api_operations() -> None:
    _validate_sheet_batch_requests(
        [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": 1,
                        "startRowIndex": 0,
                        "endRowIndex": 2,
                        "startColumnIndex": 0,
                        "endColumnIndex": 2,
                    },
                    "cell": {},
                    "fields": "userEnteredFormat",
                }
            }
        ]
    )
    with pytest.raises(ValueError, match="not allowed"):
        _validate_sheet_batch_requests([{"executeArbitraryCode": {}}])
    with pytest.raises(ValueError, match="fully bounded"):
        _validate_sheet_batch_requests(
            [{"repeatCell": {"range": {"sheetId": 1}, "cell": {}, "fields": "userEnteredFormat"}}]
        )
    with pytest.raises(ValueError, match="2000 cells"):
        _validate_sheet_batch_requests(
            [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": 1,
                            "startRowIndex": 0,
                            "endRowIndex": 51,
                            "startColumnIndex": 0,
                            "endColumnIndex": 51,
                        },
                        "cell": {},
                        "fields": "userEnteredFormat",
                    }
                }
            ]
        )


def test_sheet_update_accepts_range_a1_values_shape() -> None:
    kind, payload = _normalize_sheet_operation(
        {
            "values_update": {
                "rangeA1": "Sales!A1:B2",
                "values": [["Item", "Qty"], ["Mango", 5]],
            }
        }
    )
    assert kind == "values_update"
    assert payload == {
        "ranges": [
            {
                "range": "Sales!A1:B2",
                "values": [["Item", "Qty"], ["Mango", 5]],
            }
        ]
    }


def test_sheet_update_accepts_flat_action_shape() -> None:
    kind, payload = _normalize_sheet_operation(
        {
            "action": "values_update",
            "rangeA1": "Sales!A1:B1",
            "values": [["Item", "Qty"]],
        }
    )
    assert kind == "values_update"
    assert payload["ranges"] == [
        {"range": "Sales!A1:B1", "values": [["Item", "Qty"]]}
    ]


def test_tool_node_returns_validation_error_to_model_as_tool_message() -> None:
    @tool
    def failing_tool() -> str:
        """Raise a validation error."""
        raise ValueError("Use bounded A1 ranges.")

    node = ToolNode([failing_tool], handle_tool_errors=_handle_agent_tool_error)
    workflow = StateGraph(MessagesState)
    workflow.add_node("tools", node)
    workflow.add_edge(START, "tools")
    result = workflow.compile().invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "failing_tool",
                            "args": {},
                            "id": "test-call",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    )
    tool_message = result["messages"][-1]
    assert "Tool input or validation error" in tool_message.content
    assert "Use bounded A1 ranges." in tool_message.content


def test_google_api_error_handler_preserves_field_violation_details() -> None:
    body = (
        b'{"error":{"code":400,"message":"Request contains an invalid argument.",'
        b'"details":[{"@type":"type.googleapis.com/google.rpc.BadRequest",'
        b'"fieldViolations":[{"field":"requests[0].repeatCell.range",'
        b'"description":"The range must specify a sheet ID and valid indices."}]}]}}'
    )
    error = HttpError(
        SimpleNamespace(status=400, reason="Bad Request"),
        body,
    )
    message = _handle_agent_tool_error(error)
    assert "HTTP 400" in message
    assert "The range must specify a sheet ID and valid indices." in message
    assert "requests[0].repeatCell.range" in message


def test_injected_user_id_is_not_exposed_as_a_model_argument() -> None:
    assert "user_id" not in drive_get_file.tool_call_schema.model_fields
    assert "user_id" not in drive_upload_file.tool_call_schema.model_fields

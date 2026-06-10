from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.states.base import PhaseContext
from src.agent.states.empty_response import EmptyResponseState

pytestmark = pytest.mark.unit


def _make_ctx(content="", intent=None, retry=0, tool_calls=None, messages=None):
    response = AIMessage(content=content)
    if tool_calls is not None:
        response.tool_calls = tool_calls
    return PhaseContext(
        agent_state={
            "messages": messages or [HumanMessage(content="test")],
            "retry_count": retry,
        },
        response=response,
        intent=intent,
    )


# ── No nudge cases ─────────────────────────────────────────────────────────────

def test_no_nudge_when_tool_call_present():
    ctx = _make_ctx(tool_calls=[{"name": "get_bitwig_state", "args": {}, "id": "x", "type": "tool_call"}])
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is None


def test_no_nudge_after_three_retries():
    ctx = _make_ctx(content="Hier ist ein Plan.", intent="song_creation", retry=3)
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is None


def test_no_nudge_for_knowledge_text_response():
    """Pure text answers are valid for knowledge intent."""
    ctx = _make_ctx(content="Techno hat typisch 130-145 BPM.", intent="knowledge")
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is None


# ── Nudge cases ────────────────────────────────────────────────────────────────

def test_nudge_on_empty_response():
    """Empty LLM response (think-only) always gets nudged."""
    ctx = _make_ctx(content="", intent=None)
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None
    assert result.early_return["retry_count"] == 1
    assert "Tool" in result.early_return["messages"][1].content


def test_nudge_on_song_creation_text_only():
    ctx = _make_ctx(content="Hier ist mein Track-Plan.", intent="song_creation")
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None
    assert result.early_return["retry_count"] == 1


def test_nudge_on_status_text_only():
    ctx = _make_ctx(content="Ich prüfe die Verbindung.", intent="status")
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None


def test_nudge_on_launchpad_text_only():
    ctx = _make_ctx(content="Ich lege einen Beat auf.", intent="launchpad")
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None


def test_nudge_on_control_text_only():
    ctx = _make_ctx(content="Ich starte die Wiedergabe.", intent="control")
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None


def test_nudge_increments_retry_count():
    ctx = _make_ctx(content="", intent="song_creation", retry=1)
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None
    assert result.early_return["retry_count"] == 2


def test_nudge_still_fires_at_retry_two():
    """retry_count=2 → noch ein Nudge erlaubt (Grenze liegt bei 3)."""
    ctx = _make_ctx(content="Noch ein Plan.", intent="launchpad", retry=2)
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is not None
    assert result.early_return["retry_count"] == 3


def test_nudge_stops_at_retry_three():
    """retry_count=3 → kein weiterer Nudge."""
    ctx = _make_ctx(content="Noch ein Plan.", intent="launchpad", retry=3)
    result = EmptyResponseState().execute(ctx)
    assert result.early_return is None

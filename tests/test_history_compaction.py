from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.states.invoke import _trim_messages
from src.agent.states.preparation import PreparationState

pytestmark = pytest.mark.unit


def test_prepare_messages_summarizes_older_history():
    messages = [HumanMessage(content=f"Nachricht {i}") for i in range(10)]

    prepared = PreparationState._prepare_messages(messages)

    assert isinstance(prepared[0], SystemMessage)
    assert "Kompakter Verlauf" in prepared[0].content
    assert "Nachricht 0" in prepared[0].content
    assert len(prepared) == 5
    assert [m.content for m in prepared[1:]] == [f"Nachricht {i}" for i in range(6, 10)]


def test_prepare_messages_trims_recent_tool_results():
    messages = [ToolMessage(content="x" * 500, tool_call_id="call-1")]

    prepared = PreparationState._prepare_messages(messages)

    assert prepared[0].content.endswith(" …[gekürzt]")
    assert len(prepared[0].content) < 320


def test_phase_transition_summary_drops_obsolete_history():
    messages = [
        HumanMessage(content="Welche VST habe ich installiert?"),
        AIMessage(content="Das ist alter Smalltalk und nicht mehr relevant."),
        HumanMessage(content="Erstelle Tear Drops Bass auf Track 1"),
        AIMessage(content="Plan: Bass-Track mit VB-ROYAL vorbereiten."),
        HumanMessage(content="ja"),
        AIMessage(content=""),
        HumanMessage(content="Deine Antwort war leer. Nutze jetzt das passende Tool."),
        AIMessage(content="", tool_calls=[
            {"name": "execute_setup", "args": {"result": {}}, "id": "c1", "type": "tool_call"}
        ]),
    ]

    prepared = PreparationState._prepare_messages(messages, "planning", "setup")

    assert isinstance(prepared[0], SystemMessage)
    assert "Workflow-Phasenwechsel planning → setup" in prepared[0].content
    assert "Erstelle Tear Drops Bass auf Track 1" in prepared[0].content
    assert "Welche VST" not in prepared[0].content
    assert "alter Smalltalk" not in prepared[0].content


def test_invoke_trim_preserves_compact_context_plus_recent_window():
    messages = [SystemMessage(content="Kompakter Verlauf")] + [
        HumanMessage(content=f"Nachricht {i}") for i in range(8)
    ]

    trimmed = _trim_messages(messages, max_messages=3)

    assert isinstance(trimmed[0], SystemMessage)
    assert [m.content for m in trimmed[1:]] == ["Nachricht 5", "Nachricht 6", "Nachricht 7"]

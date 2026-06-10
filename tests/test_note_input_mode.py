"""Tests für die Noten-Eingabe-Abfrage (Launchpad vs. Agent)."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.router import classify_note_input_answer
from src.agent.states.base import PhaseContext
from src.agent.states.preparation import PreparationState, _NOTE_INPUT_QUESTION, _NOTE_INPUT_HINTS

pytestmark = pytest.mark.unit


# ── classify_note_input_answer ─────────────────────────────────────────────────

def test_launchpad_keyword_detected():
    assert classify_note_input_answer("Launchpad bitte") == "launchpad"

def test_selbst_detected_as_launchpad():
    assert classify_note_input_answer("ich möchte selbst spielen") == "launchpad"

def test_selber_detected_as_launchpad():
    assert classify_note_input_answer("selber einspielen") == "launchpad"

def test_agent_is_default():
    assert classify_note_input_answer("generiere bitte") == "agent"

def test_automatisch_returns_agent():
    assert classify_note_input_answer("automatisch") == "agent"

def test_empty_defaults_to_agent():
    assert classify_note_input_answer("") == "agent"


# ── PreparationState Abfrage-Logik ────────────────────────────────────────────

def _make_ctx(note_input_mode, user_text="erstelle einen Piano Track", intent="song_creation"):
    """Hilfsfunktion: erstellt einen PhaseContext mit gesetztem note_input_mode."""
    return PhaseContext(
        agent_state={
            "messages": [HumanMessage(content=user_text)],
            "generation_phase": "idle",
            "retry_count": 0,
            "note_input_mode": note_input_mode,
        },
        response=None,
        intent=intent,
    )


def test_first_song_creation_triggers_question(monkeypatch):
    """note_input_mode=None + song_creation → Frage wird gestellt, kein LLM-Call."""
    monkeypatch.setattr(
        "src.agent.states.preparation.classify_intent_llm",
        lambda text: "song_creation",
    )
    ctx = _make_ctx(note_input_mode=None)
    result = PreparationState().execute(ctx)

    assert result.early_return is not None
    msgs = result.early_return["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], AIMessage)
    assert "Launchpad" in msgs[0].content
    assert result.early_return["note_input_mode"] == "pending"


def test_question_not_repeated_when_pending(monkeypatch):
    """note_input_mode=pending → Antwort klassifizieren, keine weitere Frage."""
    monkeypatch.setattr(
        "src.agent.states.preparation.classify_intent_llm",
        lambda text: "song_creation",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation.classify_note_input_answer",
        lambda text: "agent",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._get_prompt_for_mode",
        lambda mode: "SYSTEM",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._route_request",
        lambda text: "song",
    )
    ctx = _make_ctx(note_input_mode="pending", user_text="Agent bitte")
    result = PreparationState().execute(ctx)

    assert result.early_return is None
    assert result.updates.get("note_input_mode") == "agent"


def test_launchpad_hint_injected_into_messages(monkeypatch):
    """note_input_mode=launchpad → Hint als erste SystemMessage im Kontext."""
    monkeypatch.setattr(
        "src.agent.states.preparation.classify_intent_llm",
        lambda text: "song_creation",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._get_prompt_for_mode",
        lambda mode: "SYSTEM",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._route_request",
        lambda text: "song",
    )
    ctx = _make_ctx(note_input_mode="launchpad")
    result = PreparationState().execute(ctx)

    assert result.early_return is None
    from langchain_core.messages import SystemMessage
    assert any(
        isinstance(m, SystemMessage) and "SELBST" in m.content
        for m in result.messages
    )


def test_no_question_for_non_song_intent(monkeypatch):
    """Für knowledge/control keine Abfrage, auch wenn note_input_mode=None."""
    monkeypatch.setattr(
        "src.agent.states.preparation.classify_intent_llm",
        lambda text: "knowledge",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._get_prompt_for_mode",
        lambda mode: "SYSTEM",
    )
    monkeypatch.setattr(
        "src.agent.states.preparation._route_request",
        lambda text: "song",
    )
    ctx = _make_ctx(note_input_mode=None, intent="knowledge",
                    user_text="Was ist ein Arpeggio?")
    result = PreparationState().execute(ctx)

    assert result.early_return is None


# ── _prepare_messages mit note_input_mode ─────────────────────────────────────

def test_prepare_messages_injects_agent_hint():
    from langchain_core.messages import SystemMessage
    messages = [HumanMessage(content="test")]
    prepared = PreparationState._prepare_messages(messages, note_input_mode="agent")
    hints = [m for m in prepared if isinstance(m, SystemMessage) and "AGENT" in m.content]
    assert hints, "Agent-Hint fehlt in den Nachrichten"


def test_prepare_messages_no_hint_when_none():
    from langchain_core.messages import SystemMessage
    messages = [HumanMessage(content="test")]
    prepared = PreparationState._prepare_messages(messages, note_input_mode=None)
    hints = [m for m in prepared if isinstance(m, SystemMessage)
             and ("SELBST" in m.content or "AGENT" in m.content)]
    assert not hints

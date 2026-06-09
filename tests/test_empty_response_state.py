from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.states.base import PhaseContext
from src.agent.states.empty_response import (
    EmptyResponseState,
    _needs_known_songs_nudge,
    _needs_launchpad_tool_nudge,
    _needs_setup_tool_nudge,
    _needs_status_tool_nudge,
)

pytestmark = pytest.mark.unit


def test_song_creation_text_response_needs_setup_nudge():
    response = AIMessage(content="Hier ist ein Track-Plan.")
    state = {
        "messages": [HumanMessage(content="kannst du mir einen Track vom Song Levels in Bitwig erstellen")],
        "generation_phase": "idle",
    }

    assert _needs_setup_tool_nudge(response, state, {}, intent="song_creation") is True


def test_empty_response_state_turns_song_plan_into_setup_retry():
    response = AIMessage(content="Hier ist ein Track-Plan.")
    state = {
        "messages": [HumanMessage(content="kannst du mir einen Track vom Song Levels in Bitwig erstellen")],
        "generation_phase": "idle",
        "retry_count": 0,
    }
    ctx = PhaseContext(agent_state=state, response=response, intent="song_creation")

    result = EmptyResponseState().execute(ctx)

    assert result.early_return is not None
    assert result.early_return["generation_phase"] == "setup"
    assert result.early_return["retry_count"] == 1
    assert result.early_return["messages"][1].content.startswith("Deine Antwort war nur ein Plan.")


def test_non_song_text_response_does_not_need_setup_nudge():
    response = AIMessage(content="Das ist eine Erklärung.")
    state = {
        "messages": [HumanMessage(content="was ist sidechain compression?")],
        "generation_phase": "idle",
    }

    assert _needs_setup_tool_nudge(response, state, {}) is False


def test_known_songs_text_response_needs_tool_nudge():
    response = AIMessage(content="Ich kenne einige Songs.")
    state = {
        "messages": [HumanMessage(content="welche Songs kennst du ?")],
        "generation_phase": "planning",
    }

    assert _needs_known_songs_nudge(response, state, intent="knowledge") is True


def test_empty_response_state_nudges_known_songs_tool():
    response = AIMessage(content="Ich kenne Songs aus der Datenbank.")
    state = {
        "messages": [HumanMessage(content="welche Songs kennst du ?")],
        "generation_phase": "planning",
        "retry_count": 0,
    }
    ctx = PhaseContext(agent_state=state, response=response, intent="knowledge")

    result = EmptyResponseState().execute(ctx)

    assert result.early_return is not None
    assert result.early_return["retry_count"] == 1
    assert "list_known_songs" in result.early_return["messages"][1].content


def test_known_songs_nudge_does_not_repeat_after_tool_call():
    response = AIMessage(content="Hier ist die Songliste.")
    state = {
        "messages": [
            HumanMessage(content="welche Songs kennst du ?"),
            AIMessage(content="", tool_calls=[{
                "name": "list_known_songs",
                "args": {"limit": 20},
                "id": "songs-1",
                "type": "tool_call",
            }]),
            ToolMessage(content="Bekannte Songs: ...", tool_call_id="songs-1"),
        ],
        "generation_phase": "planning",
    }

    assert _needs_known_songs_nudge(response, state, intent="knowledge") is False


def test_status_text_response_needs_tool_nudge():
    response = AIMessage(content="Ich prüfe Verbindung und Track-Zustand.")
    state = {
        "messages": [HumanMessage(content="Wie viele Tracks sind in Bitwig vorhanden?")],
        "generation_phase": "planning",
    }

    assert _needs_status_tool_nudge(response, state, intent="status") is True


def test_status_nudge_does_not_repeat_after_track_state_tool():
    response = AIMessage(content="Es sind 5 Tracks vorhanden.")
    state = {
        "messages": [
            HumanMessage(content="Wie viele Tracks sind in Bitwig vorhanden?"),
            AIMessage(content="", tool_calls=[{
                "name": "get_bitwig_track_state",
                "args": {},
                "id": "state-1",
                "type": "tool_call",
            }]),
            ToolMessage(content="5 tracks", tool_call_id="state-1"),
        ],
        "generation_phase": "planning",
    }

    assert _needs_status_tool_nudge(response, state, intent="status") is False


def test_launchpad_text_response_needs_tool_nudge():
    response = AIMessage(content="Lass mich zuerst Verbindung und Launchpad-Modus prüfen.")
    state = {
        "messages": [HumanMessage(content="spiele einen Beat mit dem Launchpad")],
        "generation_phase": "verifying",
    }

    assert _needs_launchpad_tool_nudge(response, state, intent="launchpad") is True


def test_launchpad_mode_nudge_does_not_repeat_after_tool_call():
    response = AIMessage(content="Ich prüfe den Launchpad-Modus.")
    state = {
        "messages": [
            HumanMessage(content="prüfe den Launchpad Modus"),
            AIMessage(content="", tool_calls=[{
                "name": "get_launchpad_mode",
                "args": {},
                "id": "launchpad-1",
                "type": "tool_call",
            }]),
            ToolMessage(content="mode=drum", tool_call_id="launchpad-1"),
        ],
        "generation_phase": "verifying",
    }

    assert _needs_launchpad_tool_nudge(response, state, intent="launchpad") is False


def test_launchpad_play_request_still_needs_play_notes_after_mode_check():
    response = AIMessage(content="Bitwig ist verbunden, ich lege einen Beat auf.")
    state = {
        "messages": [
            HumanMessage(content="spiele einen Beat auf dem Launchpad"),
            AIMessage(content="", tool_calls=[{
                "name": "get_launchpad_mode",
                "args": {},
                "id": "launchpad-1",
                "type": "tool_call",
            }]),
            ToolMessage(content="Timeout", tool_call_id="launchpad-1"),
        ],
        "generation_phase": "planning",
    }

    assert _needs_launchpad_tool_nudge(response, state, intent="launchpad") is True


def test_launchpad_play_request_does_not_repeat_after_play_notes():
    response = AIMessage(content="Der Beat läuft.")
    state = {
        "messages": [
            HumanMessage(content="spiele einen Beat auf dem Launchpad"),
            AIMessage(content="", tool_calls=[{
                "name": "play_notes",
                "args": {"notes": []},
                "id": "launchpad-1",
                "type": "tool_call",
            }]),
            ToolMessage(content="ok", tool_call_id="launchpad-1"),
        ],
        "generation_phase": "planning",
    }

    assert _needs_launchpad_tool_nudge(response, state, intent="launchpad") is False


from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from src.agent.router import (
    _CONTROL_TOOL_NAMES,
    _TOOLS_GENERATING,
    _TOOLS_KNOWLEDGE,
    _TOOLS_PLANNING,
    _TOOLS_SETUP,
    _TOOLS_STATUS,
    _TOOLS_VERIFYING,
    _effective_generation_phase,
    _filter_tools_for_mode,
    _latest_user_text,
    _phase_after_recent_tools,
)

pytestmark = pytest.mark.unit


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _tools(names: set[str] | list[str]) -> list[_FakeTool]:
    return [_FakeTool(name) for name in sorted(names)]


def _names(tools: list[_FakeTool]) -> set[str]:
    return {tool.name for tool in tools}


def test_song_without_keyword_uses_limited_planning_tools():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING | {"export_mlx_training_data"}
    selected = _filter_tools_for_mode("song", _tools(all_names))

    assert _names(selected) == set(_TOOLS_PLANNING)
    assert len(selected) < len(all_names)


def test_song_workflow_starts_in_planning_phase():
    assert _effective_generation_phase([], "idle", "song") == "planning"


def test_song_creation_question_stays_planning_not_knowledge():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING | _TOOLS_KNOWLEDGE
    phase = _effective_generation_phase([], "idle", "kannst du mir einen Track vom Song Levels in Bitwig erstellen")
    selected = _filter_tools_for_mode(
        "song",
        _tools(all_names),
        intent="song_creation",
        phase=phase,
    )

    assert phase == "planning"
    assert _names(selected) == set(_TOOLS_PLANNING)


def test_song_creation_uses_workflow_phase_not_all_production_tools():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING
    selected = _filter_tools_for_mode("song", _tools(all_names), intent="song_creation", phase="setup")

    assert _names(selected) == set(_TOOLS_SETUP)
    assert _names(selected) != set(all_names)


def test_generating_phase_uses_note_tools():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING | _TOOLS_VERIFYING
    selected = _filter_tools_for_mode("song", _tools(all_names), phase="generating")

    assert _names(selected) == set(_TOOLS_GENERATING)


def test_verifying_phase_uses_validation_tools():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING | _TOOLS_VERIFYING
    selected = _filter_tools_for_mode("song", _tools(all_names), phase="verifying")

    assert _names(selected) == set(_TOOLS_VERIFYING)


def test_knowledge_task_can_use_broader_knowledge_tools():
    all_names = _TOOLS_KNOWLEDGE | _TOOLS_SETUP | _TOOLS_GENERATING
    selected = _filter_tools_for_mode("song", _tools(all_names), intent="knowledge")

    assert _names(selected) == set(_TOOLS_KNOWLEDGE)


def test_artist_song_search_is_knowledge_not_song_default():
    all_names = _TOOLS_KNOWLEDGE | _TOOLS_PLANNING | _TOOLS_SETUP
    selected = _filter_tools_for_mode("song", _tools(all_names), intent="knowledge")

    assert _names(selected) == set(_TOOLS_KNOWLEDGE)
    assert "web_search" in _names(selected)
    assert "search_artist_song" in _names(selected)


def test_known_songs_query_includes_song_list_tool():
    selected = _filter_tools_for_mode("song", _tools(_TOOLS_KNOWLEDGE), intent="knowledge")

    assert "list_known_songs" in _names(selected)


def test_track_count_query_uses_status_tools_not_setup():
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_STATUS
    selected = _filter_tools_for_mode("song", _tools(all_names), intent="status")

    assert _names(selected) == set(_TOOLS_STATUS)
    assert "execute_setup" not in _names(selected)


def test_launchpad_play_request_gets_launchpad_tools():
    all_names = _TOOLS_PLANNING | {
        "check_bitwig_connection", "suggest_notes", "get_launchpad_mode",
        "listen_played_notes", "play_notes", "arm_track",
    }
    selected = _filter_tools_for_mode("song", _tools(all_names), intent="launchpad")

    assert "get_launchpad_mode" in _names(selected)
    assert "play_notes" in _names(selected)
    assert "query_bitwig_docs" not in _names(selected)


def test_latest_user_text_ignores_launchpad_tool_nudge():
    messages = [
        HumanMessage(content="spiele einen Beat auf dem Launchpad"),
        HumanMessage(content=(
            "Der Nutzer will einen Beat hören. "
            "Rufe jetzt direkt `play_notes` mit einem einfachen Drum-Beat auf. "
            "Kein Freitext, keine Absichtserklärung, nur Tool-Call."
        )),
    ]

    assert _latest_user_text(messages) == "spiele einen Beat auf dem Launchpad"


def test_confirmation_keeps_incomplete_workflow_in_planning():
    assert _effective_generation_phase([], "planning", "ja") == "planning"
    assert _effective_generation_phase([], "idle", "ja") == "planning"


def test_control_mode_stays_limited_to_control_tools():
    all_names = _CONTROL_TOOL_NAMES | _TOOLS_PLANNING | _TOOLS_SETUP
    selected = _filter_tools_for_mode("control", _tools(all_names))

    assert _names(selected) == set(_CONTROL_TOOL_NAMES)


def test_recent_setup_tool_advances_to_verifying_phase():
    class FakeAIMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    messages = [FakeAIMessage()]

    assert _phase_after_recent_tools(messages, "setup") == "verifying"


def test_neutral_tool_after_setup_keeps_verifying_phase():
    class SetupMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    class NeutralMessage:
        tool_calls = [{"name": "get_bitwig_track_state", "args": {}, "id": "2"}]

    assert _phase_after_recent_tools([SetupMessage(), NeutralMessage()], "idle") == "verifying"


def test_effective_phase_drives_next_tool_selection_after_setup_to_verifying():
    class FakeAIMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    phase = _phase_after_recent_tools([FakeAIMessage()], "setup")
    all_names = _TOOLS_PLANNING | _TOOLS_SETUP | _TOOLS_GENERATING | _TOOLS_VERIFYING
    selected = _filter_tools_for_mode("song", _tools(all_names), phase=phase)

    assert phase == "verifying"
    assert _names(selected) == set(_TOOLS_VERIFYING)

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from src.agent.router import (
    _effective_generation_phase,
    _latest_user_text,
    _phase_after_recent_tools,
    _select_tools_for_context,
)

pytestmark = pytest.mark.unit


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def _tools(names: set[str] | list[str]) -> list[_FakeTool]:
    return [_FakeTool(name) for name in sorted(names)]


def _names(tools: list[_FakeTool]) -> set[str]:
    return {tool.name for tool in tools}


def test_all_tools_always_returned():
    """Phase 3: kein Filtering — alle Tools immer sichtbar."""
    all_names = {"control_bitwig", "get_bitwig_state", "execute_setup",
                 "write_pattern_raw", "launchpad", "query_knowledge",
                 "web_search", "store_result_in_kb", "scan_and_learn_project",
                 "reconstruct_project", "create_track_from_recipe", "learn_song_from_youtube"}
    all_tool_list = _tools(all_names)
    result = _select_tools_for_context(
        [], lambda: all_tool_list, "idle", intent="knowledge"
    )
    assert _names(result) == all_names


def test_select_tools_returns_all_regardless_of_intent():
    all_names = {"control_bitwig", "execute_setup", "query_knowledge", "web_search"}
    tools = _tools(all_names)
    for intent in ("control", "knowledge", "launchpad", "song_creation", "song_default"):
        result = _select_tools_for_context([], lambda: tools, "idle", intent=intent)
        assert _names(result) == all_names, f"intent={intent} should return all tools"


def test_song_workflow_starts_in_planning_phase():
    assert _effective_generation_phase([], "idle", "song") == "planning"


def test_confirmation_keeps_incomplete_workflow_in_planning():
    assert _effective_generation_phase([], "planning", "ja") == "planning"
    assert _effective_generation_phase([], "idle", "ja") == "planning"


def test_latest_user_text_ignores_empty_response_nudge():
    messages = [
        HumanMessage(content="spiele einen Beat auf dem Launchpad"),
        HumanMessage(content=(
            "Deine Antwort enthielt keinen Tool-Call. "
            "Ruf jetzt direkt das passende Tool auf. "
            "Kein Text, nur Tool-Call."
        )),
    ]

    assert _latest_user_text(messages) == "spiele einen Beat auf dem Launchpad"


def test_recent_setup_tool_advances_to_verifying_phase():
    class FakeAIMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    messages = [FakeAIMessage()]

    assert _phase_after_recent_tools(messages, "setup") == "verifying"


def test_neutral_tool_after_setup_keeps_verifying_phase():
    class SetupMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    class NeutralMessage:
        tool_calls = [{"name": "get_bitwig_state", "args": {}, "id": "2"}]

    assert _phase_after_recent_tools([SetupMessage(), NeutralMessage()], "idle") == "verifying"


def test_write_pattern_raw_advances_to_verifying():
    class PatternMessage:
        tool_calls = [{"name": "write_pattern_raw", "args": {}, "id": "1"}]

    assert _phase_after_recent_tools([PatternMessage()], "generating") == "verifying"


def test_effective_phase_drives_next_tool_selection_after_setup_to_verifying():
    class FakeAIMessage:
        tool_calls = [{"name": "execute_setup", "args": {}, "id": "1"}]

    phase = _phase_after_recent_tools([FakeAIMessage()], "setup")
    assert phase == "verifying"

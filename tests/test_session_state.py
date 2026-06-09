import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.core import _default_state, _merge_session_state, _state_for_user_turn


pytestmark = pytest.mark.unit


def test_state_for_user_turn_preserves_phase_and_resets_retry():
    session_state = _default_state()
    session_state["messages"] = [HumanMessage(content="erstelle einen Track")]
    session_state["generation_phase"] = "generating"
    session_state["retry_count"] = 3

    state = _state_for_user_turn(session_state, "weiter")

    assert state["generation_phase"] == "generating"
    assert state["retry_count"] == 0
    assert [m.content for m in state["messages"]] == ["erstelle einen Track", "weiter"]


def test_merge_session_state_persists_graph_updates():
    previous = _default_state()
    previous["messages"] = [HumanMessage(content="erstelle einen Track")]
    result = {
        "messages": [HumanMessage(content="erstelle einen Track"), AIMessage(content="ok")],
        "generation_phase": "setup",
        "track_count": 5,
    }

    merged = _merge_session_state(previous, result)

    assert merged["generation_phase"] == "setup"
    assert merged["track_count"] == 5
    assert merged["messages"][-1].content == "ok"

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.policy import enforce_policy_on_response, is_concrete_track_task


@pytest.mark.unit
def test_detects_concrete_track_task():
    text = "Erstelle einen 20-sekündigen Rock-Riff mit Phase-4, Distortion und Amp bei 120 BPM"
    assert is_concrete_track_task(text) is True


@pytest.mark.unit
def test_non_task_question_not_concrete():
    text = "Was macht ein Kompressor?"
    assert is_concrete_track_task(text) is False


@pytest.mark.unit
def test_allows_execute_result_unchanged():
    """execute_result ist kein totes Tool — Policy lässt es durch."""
    state = {"messages": [HumanMessage(content="Erstelle einen Rock-Bass mit FM-4, 120 BPM")]}
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "execute_result", "args": {"result": {}}, "id": "c2", "type": "tool_call"},
        ],
    )
    out, meta = enforce_policy_on_response(state, response)
    assert meta["action"] == "allow"
    assert [tc["name"] for tc in out.tool_calls] == ["check_bitwig_connection", "execute_result"]


@pytest.mark.unit
def test_removes_hallucinated_legacy_tools():
    """setup_instrument_track und write_notes_to_clip werden herausgefiltert."""
    state = {"messages": [HumanMessage(content="Rock-Riff Track mit Phase-4")]}
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "setup_instrument_track", "args": {"track_index": 1}, "id": "c2", "type": "tool_call"},
            {"name": "write_notes_to_clip", "args": {}, "id": "c3", "type": "tool_call"},
        ],
    )
    out, meta = enforce_policy_on_response(state, response)
    assert meta["action"] == "rewrite"
    assert "setup_instrument_track" in meta["violations"]
    names = [tc["name"] for tc in out.tool_calls]
    assert "setup_instrument_track" not in names
    assert "write_notes_to_clip" not in names
    assert "check_bitwig_connection" in names


@pytest.mark.unit
def test_removes_build_song_dead_tool():
    """build_song existiert nicht mehr — wird aus tool_calls entfernt."""
    state = {"messages": [HumanMessage(content="Erstelle einen Bass-Track")]}
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "build_song", "args": {"project_json": "{}"}, "id": "c2", "type": "tool_call"},
        ],
    )
    out, meta = enforce_policy_on_response(state, response)
    assert meta["action"] == "rewrite"
    assert "build_song" in meta["violations"]
    assert all(tc["name"] != "build_song" for tc in out.tool_calls)


@pytest.mark.unit
def test_no_tool_calls_returns_none_action():
    """Antwort ohne tool_calls → keine Policy-Aktion."""
    state = {"messages": [HumanMessage(content="Hallo")]}
    response = AIMessage(content="Hallo zurück")
    _, meta = enforce_policy_on_response(state, response)
    assert meta["action"] == "none"

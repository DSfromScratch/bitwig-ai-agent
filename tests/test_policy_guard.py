import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.policy import enforce_policy_on_response, is_concrete_track_task
from src.agent.states.base import PhaseContext
from src.agent.states.policy_guard import PolicyGuardState


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
    state = {
        "messages": [HumanMessage(content="Erstelle einen Rock-Bass mit FM-4, 120 BPM")],
        "generation_phase": "setup",
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "execute_setup", "args": {"result": {}}, "id": "c2", "type": "tool_call"},
        ],
    )
    out, meta = enforce_policy_on_response(state, response)
    assert meta["action"] == "allow"
    assert [tc["name"] for tc in out.tool_calls] == ["check_bitwig_connection", "execute_setup"]


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


@pytest.mark.unit
def test_blocks_setup_tool_during_planning_phase():
    state = {
        "messages": [HumanMessage(content="Erstelle Levels in Bitwig")],
        "generation_phase": "planning",
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "query_bitwig_docs", "args": {"query": "Levels"}, "id": "c1", "type": "tool_call"},
            {"name": "execute_setup", "args": {"result": {}}, "id": "c2", "type": "tool_call"},
        ],
    )

    out, meta = enforce_policy_on_response(state, response)

    assert meta["action"] == "rewrite"
    assert "phase:planning:execute_setup" in meta["violations"]
    assert [tc["name"] for tc in out.tool_calls] == ["query_bitwig_docs"]


@pytest.mark.unit
def test_allows_launchpad_tools_during_planning_phase():
    state = {
        "messages": [HumanMessage(content="spiele einen Beat auf dem Launchpad")],
        "generation_phase": "planning",
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "check_bitwig_connection", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "get_launchpad_mode", "args": {}, "id": "c2", "type": "tool_call"},
        ],
    )

    out, meta = enforce_policy_on_response(state, response)

    assert meta["action"] == "allow"
    assert [tc["name"] for tc in out.tool_calls] == ["check_bitwig_connection", "get_launchpad_mode"]


@pytest.mark.unit
def test_blocks_project_tool_during_generating_phase():
    state = {
        "messages": [HumanMessage(content="ja")],
        "generation_phase": "generating",
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "scan_and_learn_project", "args": {}, "id": "c1", "type": "tool_call"},
            {"name": "play_notes", "args": {"notes": [{"note": 36}]}, "id": "c2", "type": "tool_call"},
        ],
    )

    out, meta = enforce_policy_on_response(state, response)

    assert meta["action"] == "rewrite"
    assert "phase:generating:scan_and_learn_project" in meta["violations"]
    assert [tc["name"] for tc in out.tool_calls] == ["play_notes"]


@pytest.mark.unit
def test_policy_guard_uses_pending_phase_updates(monkeypatch):
    entries = []
    monkeypatch.setattr(
        "src.agent.states.policy_guard._append_policy_feedback",
        lambda entry: entries.append(entry),
    )
    state = {
        "messages": [HumanMessage(content="ja")],
        "generation_phase": "idle",
    }
    response = AIMessage(
        content="",
        tool_calls=[
            {"name": "execute_setup", "args": {"result": {}}, "id": "c1", "type": "tool_call"},
        ],
    )
    ctx = PhaseContext(
        agent_state=state,
        response=response,
        updates={"generation_phase": "setup"},
    )

    out = PolicyGuardState().execute(ctx)

    assert [tc["name"] for tc in out.response.tool_calls] == ["execute_setup"]
    assert entries[-1]["action"] == "allow"
    assert entries[-1]["phase"] == "setup"

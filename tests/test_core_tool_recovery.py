import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.recovery import _recover_tool_calls, _has_invalid_tool_output, _classify_invalid_output


@pytest.mark.unit
def test_recover_tool_calls_does_not_synthesize_on_truncated_build_song():
    state = {
        "messages": [
            HumanMessage(content="Erstelle einen Rock-Riff Track mit Phase-4, Distortion, Amp, 120 BPM, 40 Beats"),
        ]
    }
    response = AIMessage(
        content='<tool_call>\n{"name": "build_song", "arguments": "{\"bpm\": 120, \"tracks\": [{\"index\": 1',
        tool_calls=[],
    )

    out = _recover_tool_calls(response, state)
    assert not out.tool_calls
    assert _has_invalid_tool_output(out) is True


# ── Diagnostic classification ─────────────────────────────────────────────────

@pytest.mark.unit
def test_classify_xml_fragment():
    """Offenes <tool_call> ohne </tool_call> → xml_fragment."""
    response = AIMessage(
        content='<tool_call>{"name": "build_song", "arguments": {"bpm": 120',
        tool_calls=[],
    )
    assert _classify_invalid_output(response) == "xml_fragment"


@pytest.mark.unit
def test_classify_truncated_json():
    """<tool_call>…</tool_call> mit kaputtem JSON → truncated_json."""
    response = AIMessage(
        content='<tool_call>{"name": "build_song", "args": {"bpm": 120</tool_call>',
        tool_calls=[],
    )
    assert _classify_invalid_output(response) == "truncated_json"


@pytest.mark.unit
def test_classify_malformed_args():
    """<tool_call>…</tool_call> mit validem JSON aber falschem Schema → malformed_args."""
    response = AIMessage(
        content='<tool_call>{"name": "build_song", "args": {"bpm": 120}}</tool_call>',
        tool_calls=[],
    )
    assert _classify_invalid_output(response) == "malformed_args"


@pytest.mark.unit
def test_classify_empty_args():
    """tool_call-Objekt ohne args → empty_args."""
    response = AIMessage(
        content="",
        tool_calls=[{"name": "build_song", "args": {}, "id": "c0", "type": "tool_call"}],
    )
    assert _classify_invalid_output(response) == "empty_args"


@pytest.mark.unit
def test_classify_unknown_tool_schema():
    """Unbekannter Tool-Name → unknown_tool_schema."""
    response = AIMessage(
        content="",
        tool_calls=[{"name": "nonexistent_tool", "args": {"x": 1}, "id": "c0", "type": "tool_call"}],
    )
    assert _classify_invalid_output(response) == "unknown_tool_schema"

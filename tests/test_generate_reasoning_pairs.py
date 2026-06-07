"""Tests für scripts/generate_reasoning_pairs.py (B.1 Retrieve-Then-Reason-Pairs)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_reasoning_pairs.py"
_spec = importlib.util.spec_from_file_location("generate_reasoning_pairs", _SCRIPT)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def pairs():
    return gen.build_pairs()


def test_builds_expected_count(pairs):
    assert len(pairs) == len(gen.RHYTHM_SPECS) + len(gen.INSTRUMENT_SPECS)
    assert len(pairs) >= 20


def test_message_roles(pairs):
    for p in pairs:
        roles = [m["role"] for m in p["messages"]]
        assert roles == ["system", "user", "assistant"]


def test_think_always_closed(pairs):
    """Qwen3 </think>-Problem: Trainingsdaten dürfen es NICHT verstärken."""
    for p in pairs:
        a = p["messages"][-1]["content"]
        assert a.count("<think>") == 1
        assert a.count("</think>") == 1
        assert a.index("<think>") < a.index("</think>")


def test_tool_call_is_valid_json(pairs):
    for p in pairs:
        a = p["messages"][-1]["content"]
        tool_json = a.split("</think>", 1)[1].strip()
        obj = json.loads(tool_json)
        assert obj["tool"] in {"write_pattern", "load_instrument"}
        assert isinstance(obj["args"], dict)


def test_drum_patterns_are_finite(pairs):
    """Kein Runaway: alle Steps im Takt, Pattern gecappt, jede Note endet."""
    drum_pairs = [p for p in pairs
                  if '"tool": "write_pattern"' in p["messages"][-1]["content"]]
    assert drum_pairs
    for p in drum_pairs:
        a = p["messages"][-1]["content"]
        obj = json.loads(a.split("</think>", 1)[1].strip())
        notes = json.loads(obj["args"]["notes"])
        assert 0 < len(notes) <= 24
        for n in notes:
            assert 0 <= n["step"] <= 15
            assert n["duration"] >= 1
            assert 0.0 < n["velocity"] <= 1.0


def test_rhythm_user_context_injects_kb_tool(pairs):
    rhythm = [p for p in pairs
              if "get_rhythm_pattern(" in p["messages"][1]["content"]]
    assert len(rhythm) == len(gen.RHYTHM_SPECS)


def test_instrument_pairs_pick_top_ranked_device(pairs):
    instr = [p for p in pairs
             if '"tool": "load_instrument"' in p["messages"][-1]["content"]]
    assert len(instr) == len(gen.INSTRUMENT_SPECS)
    for p, spec in zip(instr, gen.INSTRUMENT_SPECS):
        top_device = spec[4][0][0]
        obj = json.loads(p["messages"][-1]["content"].split("</think>", 1)[1].strip())
        assert obj["args"]["device_name"] == top_device


def test_validate_pair_rejects_unclosed_think():
    bad = {"messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": '<think>\nkein Close\n{"tool": "write_pattern", "args": {}}'},
    ]}
    with pytest.raises(AssertionError):
        gen._validate_pair(bad)

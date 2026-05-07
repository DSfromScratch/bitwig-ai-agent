"""Tests für LangGraph Routing- und Steuerungsentscheidungen.

Testet drei Ebenen:
  1. Unit: Routing-Funktionen direkt aufrufen (fan_out, route_after_assemble, route_after_verify)
  2. Struktur: Graph-Topologie — Nodes und Edges korrekt verdrahtet
  3. E2E: Welcher Pfad wird tatsächlich genommen (execute_build aufgerufen / nicht aufgerufen)
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Send


# ── Hilfsdaten ────────────────────────────────────────────────────────────────

_INSTRUMENT_JSON = json.dumps({"instrument": "Phase-4", "fx": [], "preset": "", "fx_preset": ""})
_NOTES_JSON = json.dumps({
    "bpm": 120, "length_beats": 8,
    "notes": [
        {"step": 0.0, "pitch": 52, "vel": 0.8, "dur": 0.5},
        {"step": 2.0, "pitch": 55, "vel": 0.7, "dur": 0.5},
    ],
})

_BASE_CFG = {
    "genre": "Rock", "bpm": 120, "track_count": 1,
    "key": "E minor", "length_beats": 16,
    "technique": "Standard", "rhythm_pattern": "Straight Eighths",
    "string_register": "Mid (D3-G3)", "dynamics_shape": "Accent 1&3",
    "fx_preset": "Distortion+Amp",
}

_VALID_ASSEMBLED = json.dumps({
    "bpm": 120,
    "tracks": [{"index": 1, "instrument": "Phase-4", "fx": [],
                "clip": {"slot": 0, "length_beats": 16.0,
                         "notes": [{"step": 0.0, "pitch": 52, "vel": 0.8, "dur": 0.5}]}}],
})


def _fake_llm(content: str) -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = AIMessage(content=content)
    return m


def _fake_verify() -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = {"ok": True, "track_count": 1, "warnings": [], "report_text": "OK"}
    return m


def _base_state(**overrides) -> dict:
    from src.agent.core import _default_state
    s = _default_state()
    s["messages"] = [HumanMessage(content="Erstelle einen Song")]
    s["ui_song_config"] = dict(_BASE_CFG)
    s.update(overrides)
    return s


def _run_e2e(ui_cfg: dict, extra_patches: list | None = None) -> tuple[dict, dict]:
    """Vollständiger Graphen-Lauf mit Spies auf execute_build_node und reply_node."""
    from src.agent.master_graph import execute_build_node, reply_node, build_master_graph
    from src.agent.core import _default_state

    spy_build = MagicMock(wraps=execute_build_node)
    spy_reply = MagicMock(wraps=reply_node)

    patches = [
        patch("src.agent.slaves.instrument_slave._get_llm",
              return_value=_fake_llm(_INSTRUMENT_JSON)),
        patch("src.agent.slaves.note_slave._get_llm",
              return_value=_fake_llm(_NOTES_JSON)),
        patch("src.agent.master_graph.execute_build_node", spy_build),
        patch("src.agent.master_graph.reply_node",         spy_reply),
        patch("src.agent.tools.song_tools._check_bridge", return_value=True),
        patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
        patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
        patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
        patch("time.sleep"),
        patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
    ] + (extra_patches or [])

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        state = _default_state()
        state["messages"] = [HumanMessage(content="Erstelle einen Song")]
        state["ui_song_config"] = dict(ui_cfg)
        result = build_master_graph().invoke(state)

    return result, {"build": spy_build, "reply": spy_reply}


# ══════════════════════════════════════════════════════════════════════════════
# 1. fan_out_to_slaves — Unit
# ══════════════════════════════════════════════════════════════════════════════

class TestFanOutRouting:
    """fan_out_to_slaves gibt Send-Objekte für den LangGraph Fan-out zurück."""

    @pytest.fixture(autouse=True)
    def sends(self):
        from src.agent.master_graph import fan_out_to_slaves
        self._sends = fan_out_to_slaves(_base_state())

    @pytest.mark.unit
    def test_returns_exactly_two_sends(self):
        assert len(self._sends) == 2

    @pytest.mark.unit
    def test_all_items_are_send_objects(self):
        assert all(isinstance(s, Send) for s in self._sends)

    @pytest.mark.unit
    def test_targets_instrument_slave(self):
        nodes = {s.node for s in self._sends}
        assert "instrument_slave" in nodes

    @pytest.mark.unit
    def test_targets_harmony_slave(self):
        nodes = {s.node for s in self._sends}
        assert "harmony_slave" in nodes

    @pytest.mark.unit
    def test_no_other_targets(self):
        nodes = {s.node for s in self._sends}
        assert nodes == {"instrument_slave", "harmony_slave"}

    @pytest.mark.unit
    def test_sends_full_state(self):
        """Jedes Send-Objekt muss den vollständigen State als arg enthalten."""
        state = _base_state()
        from src.agent.master_graph import fan_out_to_slaves
        sends = fan_out_to_slaves(state)
        for s in sends:
            assert "slave_plan" in s.arg or "messages" in s.arg


# ══════════════════════════════════════════════════════════════════════════════
# 2. route_after_assemble — Unit
# ══════════════════════════════════════════════════════════════════════════════

class TestRouteAfterAssemble:
    """route_after_assemble wählt den nächsten Node nach assemble_node."""

    @pytest.fixture(autouse=True)
    def fn(self):
        from src.agent.master_graph import route_after_assemble
        self._route = route_after_assemble

    @pytest.mark.unit
    def test_assembled_json_routes_to_execute_build(self):
        state = _base_state(assembled_json=_VALID_ASSEMBLED)
        assert self._route(state) == "execute_build"

    @pytest.mark.unit
    def test_no_assembled_json_routes_to_reply(self):
        state = _base_state(assembled_json=None)
        assert self._route(state) == "reply"

    @pytest.mark.unit
    def test_empty_assembled_json_routes_to_reply(self):
        state = _base_state(assembled_json="")
        assert self._route(state) == "reply"

    @pytest.mark.unit
    def test_max_retries_reached_routes_to_reply(self):
        """3 Fehler-Retries → immer reply, kein execute_build."""
        state = _base_state(
            assembled_json=None,
            slave_retry_counts={"instrument": 3},
        )
        assert self._route(state) == "reply"

    @pytest.mark.unit
    def test_partial_retries_still_routes_to_reply_without_json(self):
        """1 Retry aber kein JSON → reply (Slaves werden nochmal laufen)."""
        state = _base_state(
            assembled_json=None,
            slave_retry_counts={"instrument": 1},
        )
        assert self._route(state) == "reply"

    @pytest.mark.unit
    def test_valid_json_wins_over_retry_count(self):
        """assembled_json hat Vorrang — auch bei vorhandenen Retries."""
        state = _base_state(
            assembled_json=_VALID_ASSEMBLED,
            slave_retry_counts={"instrument": 2},
        )
        assert self._route(state) == "execute_build"


# ══════════════════════════════════════════════════════════════════════════════
# 3. route_after_verify — Unit
# ══════════════════════════════════════════════════════════════════════════════

class TestRouteAfterVerify:
    """route_after_verify wählt den nächsten Node nach verify_node."""

    @pytest.fixture(autouse=True)
    def fn(self):
        from src.agent.master_graph import route_after_verify
        self._route = route_after_verify

    @pytest.mark.unit
    def test_phase_done_routes_to_reply(self):
        assert self._route(_base_state(generation_phase="done")) == "reply"

    @pytest.mark.unit
    def test_phase_error_routes_to_reply(self):
        assert self._route(_base_state(generation_phase="error")) == "reply"

    @pytest.mark.unit
    def test_phase_verifying_routes_to_reply(self):
        """Auch bei offenen Warnings → reply (vereinfacht, kein Korrektur-Loop)."""
        assert self._route(_base_state(generation_phase="verifying")) == "reply"

    @pytest.mark.unit
    def test_phase_idle_routes_to_reply(self):
        assert self._route(_base_state(generation_phase="idle")) == "reply"

    @pytest.mark.unit
    def test_any_phase_always_reply(self):
        """route_after_verify ohne retry_signal gibt immer 'reply' zurück."""
        for phase in ("done", "error", "verifying", "generating", "planning", "idle"):
            result = self._route(_base_state(generation_phase=phase))
            assert result == "reply", f"phase={phase!r} sollte 'reply' ergeben, bekam {result!r}"

    # ── Neue Tests: retry_signal → "plan" ──────────────────────────────────

    @pytest.mark.unit
    def test_instrument_retry_signal_routes_to_plan(self):
        state = _base_state(generation_phase="verifying", retry_signal="instrument_retry")
        assert self._route(state) == "plan"

    @pytest.mark.unit
    def test_harmony_retry_signal_routes_to_plan(self):
        state = _base_state(generation_phase="verifying", retry_signal="harmony_retry")
        assert self._route(state) == "plan"

    @pytest.mark.unit
    def test_note_retry_signal_routes_to_plan(self):
        state = _base_state(generation_phase="verifying", retry_signal="note_retry")
        assert self._route(state) == "plan"

    @pytest.mark.unit
    def test_error_phase_with_signal_routes_to_reply(self):
        """generation_phase='error' hat Vorrang — selbst wenn retry_signal gesetzt."""
        state = _base_state(generation_phase="error", retry_signal="instrument_retry")
        assert self._route(state) == "reply"

    @pytest.mark.unit
    def test_done_phase_no_signal_routes_to_reply(self):
        state = _base_state(generation_phase="done", retry_signal=None)
        assert self._route(state) == "reply"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Graph-Topologie — Nodes und Edges korrekt verdrahtet
# ══════════════════════════════════════════════════════════════════════════════

class TestGraphTopology:
    """Strukturprüfung des kompilierten Graphen."""

    @pytest.fixture(scope="class", autouse=True)
    def graph_info(self, request):
        from src.agent.master_graph import build_master_graph
        g = build_master_graph()
        gg = g.get_graph()
        request.cls._nodes = set(gg.nodes.keys())
        request.cls._edges = {(e.source, e.target) for e in gg.edges}

    @pytest.mark.unit
    def test_all_expected_nodes_present(self):
        expected = {"plan", "instrument_slave", "harmony_slave",
                    "note_slave", "assemble", "execute_build", "verify", "reply"}
        assert expected.issubset(self._nodes)

    @pytest.mark.unit
    def test_entry_point_is_plan(self):
        assert ("__start__", "plan") in self._edges

    @pytest.mark.unit
    def test_fan_out_plan_to_instrument_slave(self):
        assert ("plan", "instrument_slave") in self._edges

    @pytest.mark.unit
    def test_fan_out_plan_to_harmony_slave(self):
        assert ("plan", "harmony_slave") in self._edges

    @pytest.mark.unit
    def test_fan_in_instrument_to_note_slave(self):
        assert ("instrument_slave", "note_slave") in self._edges

    @pytest.mark.unit
    def test_fan_in_harmony_to_note_slave(self):
        assert ("harmony_slave", "note_slave") in self._edges

    @pytest.mark.unit
    def test_note_slave_to_assemble(self):
        assert ("note_slave", "assemble") in self._edges

    @pytest.mark.unit
    def test_assemble_to_execute_build(self):
        assert ("assemble", "execute_build") in self._edges

    @pytest.mark.unit
    def test_assemble_to_reply_fallback(self):
        """assemble → reply muss als Fehler-Kante existieren."""
        assert ("assemble", "reply") in self._edges

    @pytest.mark.unit
    def test_execute_build_to_verify(self):
        assert ("execute_build", "verify") in self._edges

    @pytest.mark.unit
    def test_verify_to_reply(self):
        assert ("verify", "reply") in self._edges

    @pytest.mark.unit
    def test_reply_to_end(self):
        assert ("reply", "__end__") in self._edges

    @pytest.mark.unit
    def test_no_direct_plan_to_note_slave(self):
        """plan darf note_slave nicht direkt ansteuern — nur via Fan-out."""
        assert ("plan", "note_slave") not in self._edges

    @pytest.mark.unit
    def test_no_direct_plan_to_assemble(self):
        assert ("plan", "assemble") not in self._edges

    @pytest.mark.unit
    def test_verify_to_plan_retry_edge(self):
        """verify → plan muss als Retry-Kante existieren (Observer-Loop)."""
        assert ("verify", "plan") in self._edges


# ══════════════════════════════════════════════════════════════════════════════
# 5. Konditionelles Routing E2E — welcher Pfad wird tatsächlich genommen?
# ══════════════════════════════════════════════════════════════════════════════

class TestConditionalRoutingE2E:
    """Prüft welche Nodes bei bestimmten Bedingungen wirklich aufgerufen werden."""

    @pytest.mark.e2e
    def test_success_path_calls_execute_build(self):
        """Alle Slaves OK → assembled_json gesetzt → execute_build_node aufgerufen."""
        _, spies = _run_e2e(_BASE_CFG)
        assert spies["build"].call_count == 1

    @pytest.mark.e2e
    def test_success_path_calls_reply(self):
        """Erfolgreiche Pipeline endet immer in reply_node."""
        _, spies = _run_e2e(_BASE_CFG)
        assert spies["reply"].call_count == 1

    @pytest.mark.e2e
    def test_instrument_error_skips_execute_build(self):
        """Fehlerhafte instrument_slave-Antwort → kein assembled_json → execute_build NICHT aufgerufen."""
        _, spies = _run_e2e(
            _BASE_CFG,
            extra_patches=[
                patch("src.agent.slaves.instrument_slave._get_llm",
                      return_value=_fake_llm("kein json")),
            ],
        )
        assert spies["build"].call_count == 0

    @pytest.mark.e2e
    def test_instrument_error_still_calls_reply(self):
        """Auch bei Fehler-Pfad muss reply_node aufgerufen werden."""
        _, spies = _run_e2e(
            _BASE_CFG,
            extra_patches=[
                patch("src.agent.slaves.instrument_slave._get_llm",
                      return_value=_fake_llm("kein json")),
            ],
        )
        assert spies["reply"].call_count == 1

    @pytest.mark.e2e
    def test_success_path_generation_phase_done(self):
        """Erfolgreicher Durchlauf endet in generation_phase='done'."""
        result, _ = _run_e2e(_BASE_CFG)
        assert result.get("generation_phase") == "done"

    @pytest.mark.e2e
    def test_error_path_assembled_json_is_none(self):
        """Fehler-Pfad: assembled_json bleibt None."""
        result, _ = _run_e2e(
            _BASE_CFG,
            extra_patches=[
                patch("src.agent.slaves.instrument_slave._get_llm",
                      return_value=_fake_llm("kein json")),
            ],
        )
        assert result.get("assembled_json") is None

    @pytest.mark.e2e
    def test_execute_build_receives_assembled_json(self):
        """execute_build_node bekommt im State ein valides assembled_json."""
        _, spies = _run_e2e(_BASE_CFG)
        assert spies["build"].call_count == 1
        state_arg = spies["build"].call_args[0][0]
        raw = state_arg.get("assembled_json")
        assert raw is not None
        data = json.loads(raw)
        assert "tracks" in data and "bpm" in data

    @pytest.mark.e2e
    def test_reply_node_receives_build_result(self):
        """reply_node sieht das build_result aus execute_build_node."""
        _, spies = _run_e2e(_BASE_CFG)
        assert spies["reply"].call_count == 1
        state_arg = spies["reply"].call_args[0][0]
        build_result = state_arg.get("build_result", "")
        assert "build_song OK" in build_result


# ══════════════════════════════════════════════════════════════════════════════
# 6. _slave_results_reducer — Unit
# ══════════════════════════════════════════════════════════════════════════════

class TestSlaveResultsReducer:
    """Unit-Tests für den custom Reducer mit __reset__-Sentinel."""

    @pytest.fixture(autouse=True)
    def reducer(self):
        from src.agent.state import _slave_results_reducer
        self._r = _slave_results_reducer

    @pytest.mark.unit
    def test_normal_append_accumulates(self):
        assert self._r([{"a": 1}], [{"b": 2}]) == [{"a": 1}, {"b": 2}]

    @pytest.mark.unit
    def test_reset_sentinel_clears_existing(self):
        result = self._r([{"a": 1}, {"b": 2}], [{"__reset__": True}])
        assert result == []

    @pytest.mark.unit
    def test_reset_sentinel_consumed_rest_kept(self):
        result = self._r([{"old": 1}], [{"__reset__": True}, {"new": 2}])
        assert result == [{"new": 2}]

    @pytest.mark.unit
    def test_empty_existing_normal_append(self):
        assert self._r([], [{"x": 1}]) == [{"x": 1}]

    @pytest.mark.unit
    def test_multiple_appends_accumulate(self):
        r1 = self._r([], [{"a": 1}])
        r2 = self._r(r1, [{"b": 2}])
        assert r2 == [{"a": 1}, {"b": 2}]

    @pytest.mark.unit
    def test_empty_new_does_not_change_existing(self):
        assert self._r([{"a": 1}], []) == [{"a": 1}]

    @pytest.mark.unit
    def test_reset_on_empty_existing_stays_empty(self):
        result = self._r([], [{"__reset__": True}])
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# 7. _compute_quality — Unit
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeQuality:
    """Unit-Tests für den Observer-Kern: Score-Berechnung und Retry-Signal."""

    @pytest.fixture(autouse=True)
    def fn(self):
        from src.agent.master_graph import _compute_quality
        self._q = _compute_quality

    @pytest.mark.unit
    def test_track_count_zero_returns_instrument_retry(self):
        score, signal = self._q({"track_count": 0, "warnings": []}, None)
        assert score == 0.0
        assert signal == "instrument_retry"

    @pytest.mark.unit
    def test_bridge_unreachable_no_track_count_returns_instrument_retry(self):
        score, signal = self._q({"ok": False}, None)
        assert score == 0.0
        assert signal == "instrument_retry"

    @pytest.mark.unit
    def test_clean_report_high_score_no_signal(self):
        score, signal = self._q({"ok": True, "track_count": 1, "warnings": []}, None)
        assert score >= 0.75
        assert signal is None

    @pytest.mark.unit
    def test_single_warning_still_above_threshold(self):
        score, signal = self._q({"track_count": 1, "warnings": ["minor issue"]}, None)
        assert score == pytest.approx(0.85)
        assert signal is None

    @pytest.mark.unit
    def test_two_warnings_below_threshold_triggers_retry(self):
        score, signal = self._q({"track_count": 1, "warnings": ["w1", "w2"]}, None)
        assert score == pytest.approx(0.70)
        assert score < 0.75
        assert signal is not None

    @pytest.mark.unit
    def test_instrument_warning_text_triggers_instrument_retry(self):
        score, signal = self._q(
            {"track_count": 1, "warnings": ["instrument missing", "track empty"]}, None
        )
        assert signal == "instrument_retry"

    @pytest.mark.unit
    def test_generic_warning_triggers_note_retry(self):
        score, signal = self._q(
            {"track_count": 1, "warnings": ["no notes generated", "velocity too low"]}, None
        )
        assert signal == "note_retry"

    @pytest.mark.unit
    def test_low_notes_density_two_tracks_triggers_note_retry(self):
        """2 Tracks mit je 1 Note in 16 Beats → score = 0.60 < 0.75 → note_retry."""
        sparse_json = json.dumps({
            "tracks": [
                {"clip": {"notes": [{"step": 0}], "length_beats": 16}},
                {"clip": {"notes": [{"step": 0}], "length_beats": 16}},
            ]
        })
        score, signal = self._q({"track_count": 2, "warnings": []}, sparse_json)
        assert score < 0.75
        assert signal == "note_retry"

    @pytest.mark.unit
    def test_good_notes_density_no_retry(self):
        """8 Noten in 16 Beats → density = 0.5 → kein Retry."""
        dense_json = json.dumps({
            "tracks": [{"clip": {
                "notes": [{"step": float(i)} for i in range(8)],
                "length_beats": 16,
            }}]
        })
        score, signal = self._q({"track_count": 1, "warnings": []}, dense_json)
        assert signal is None

    @pytest.mark.unit
    def test_score_clamped_to_zero_not_negative(self):
        score, _ = self._q({"track_count": 1, "warnings": ["w"] * 10}, None)
        assert score == 0.0

    @pytest.mark.unit
    def test_score_never_exceeds_one(self):
        score, _ = self._q({"ok": True, "track_count": 5, "warnings": []}, None)
        assert score <= 1.0

    @pytest.mark.unit
    def test_no_signal_when_score_above_threshold(self):
        score, signal = self._q({"track_count": 1, "warnings": []}, None)
        assert score >= 0.75
        assert signal is None

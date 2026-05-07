"""Tests für LangGraph Slave-Koordination.

Prüft:
  - Alle drei Slaves (instrument, harmony, note) werden aufgerufen
  - Fan-out: instrument_slave + harmony_slave parallel aus plan_node
  - Fan-in Stufe 1: beide Ergebnisse erreichen note_slave (harmony-Kontext)
  - Fan-in Stufe 2: note_slave-Ergebnis erreicht assemble_node
  - slave_results enthält alle drei Typen ohne Fehler
  - Retry-Verhalten: fehlgeschlagener Slave blockiert assemble_node
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import MagicMock, patch, call

import pytest
from langchain_core.messages import AIMessage, HumanMessage


# ── Fake-Daten (minimal valide) ───────────────────────────────────────────────

_INSTRUMENT_JSON = json.dumps({"instrument": "Phase-4", "fx": [], "preset": "", "fx_preset": ""})
_NOTES_JSON = json.dumps({
    "bpm": 120, "length_beats": 8,
    "notes": [
        {"step": 0.0, "pitch": 52, "vel": 0.8, "dur": 0.5},  # E3
        {"step": 1.0, "pitch": 55, "vel": 0.7, "dur": 0.5},  # G3
        {"step": 2.0, "pitch": 57, "vel": 0.8, "dur": 0.5},  # A3
        {"step": 3.0, "pitch": 59, "vel": 0.7, "dur": 0.5},  # B3
    ],
})

_BASE_CFG = {
    "genre": "Rock", "bpm": 120, "track_count": 2,
    "key": "E minor", "length_beats": 16,
    "technique": "Standard", "rhythm_pattern": "Straight Eighths",
    "string_register": "Mid (D3-G3)", "dynamics_shape": "Accent 1&3",
    "fx_preset": "Distortion+Amp",
}


def _fake_llm(content: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content=content)
    return llm


def _fake_verify() -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = {"ok": True, "track_count": 1, "warnings": [], "report_text": "OK"}
    return m


def _run_graph_with_spies(ui_cfg: dict, extra_patches: list | None = None) -> tuple[dict, dict]:
    """Führt den Graphen aus und gibt (final_state, spy_dict) zurück.

    spy_dict enthält MagicMock-Spies für jeden Slave-Node,
    die die echte Funktion via `wraps=` aufrufen.
    """
    from src.agent.slaves.instrument_slave import run_instrument_slave
    from src.agent.slaves.harmony_slave import run_harmony_slave
    from src.agent.slaves.note_slave import run_note_slave
    from src.agent.master_graph import build_master_graph
    from src.agent.core import _default_state

    osc = MagicMock()
    spy_instrument = MagicMock(wraps=run_instrument_slave)
    spy_harmony    = MagicMock(wraps=run_harmony_slave)
    spy_note       = MagicMock(wraps=run_note_slave)

    patches = [
        patch("src.agent.slaves.instrument_slave._get_llm",
              return_value=_fake_llm(_INSTRUMENT_JSON)),
        patch("src.agent.slaves.note_slave._get_llm",
              return_value=_fake_llm(_NOTES_JSON)),
        patch("src.agent.master_graph.run_instrument_slave", spy_instrument),
        patch("src.agent.master_graph.run_harmony_slave",    spy_harmony),
        patch("src.agent.master_graph.run_note_slave",       spy_note),
        patch("src.agent.tools.song_tools._check_bridge", return_value=True),
        patch("src.agent.tools.song_tools._osc_client", return_value=osc),
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

    spies = {
        "instrument": spy_instrument,
        "harmony":    spy_harmony,
        "note":       spy_note,
    }
    return result, spies


# ══════════════════════════════════════════════════════════════════════════════
# 1. Slave-Aufruf-Koordination: Wer wurde aufgerufen?
# ══════════════════════════════════════════════════════════════════════════════

class TestSlaveCallCoordination:
    """Prüft ob alle Slaves im LangGraph-Durchlauf aufgerufen wurden."""

    @pytest.fixture(scope="class", autouse=True)
    def run_once(self, request):
        result, spies = _run_graph_with_spies(_BASE_CFG)
        request.cls._result = result
        request.cls._spies  = spies
        # slave_results aus finalem State für Typ-Prüfungen
        request.cls._slave_results = result.get("slave_results", [])

    @pytest.mark.e2e
    def test_instrument_slave_called_once(self):
        """instrument_slave muss genau einmal aufgerufen worden sein."""
        assert self._spies["instrument"].call_count == 1

    @pytest.mark.e2e
    def test_harmony_slave_called_once(self):
        """harmony_slave muss genau einmal aufgerufen worden sein."""
        assert self._spies["harmony"].call_count == 1

    @pytest.mark.e2e
    def test_note_slave_called_once(self):
        """note_slave muss genau einmal aufgerufen worden sein."""
        assert self._spies["note"].call_count == 1

    @pytest.mark.e2e
    def test_slave_results_contain_instrument(self):
        """slave_results muss einen Eintrag mit type='instrument' enthalten."""
        types = [r.get("type") for r in self._slave_results]
        assert "instrument" in types

    @pytest.mark.e2e
    def test_slave_results_contain_harmony(self):
        """slave_results muss einen Eintrag mit type='harmony' enthalten."""
        types = [r.get("type") for r in self._slave_results]
        assert "harmony" in types

    @pytest.mark.e2e
    def test_slave_results_contain_notes(self):
        """slave_results muss einen Eintrag mit type='notes' enthalten."""
        types = [r.get("type") for r in self._slave_results]
        assert "notes" in types

    @pytest.mark.e2e
    def test_no_slave_error_in_results(self):
        """Kein Slave darf einen Fehler-Eintrag hinterlassen haben."""
        errors = [r for r in self._slave_results if "error" in r]
        assert errors == [], f"Slave-Fehler gefunden: {errors}"

    @pytest.mark.e2e
    def test_all_three_types_present(self):
        """Genau die Typen {instrument, harmony, notes} müssen vorhanden sein."""
        types = {r.get("type") for r in self._slave_results}
        assert {"instrument", "harmony", "notes"}.issubset(types)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Denkerg ebnisse: Inhalt der Slave-Outputs prüfen
# ══════════════════════════════════════════════════════════════════════════════

class TestSlaveThinkingResults:
    """Prüft den Inhalt (Denkergebnisse) jedes Slaves im slave_results-State."""

    @pytest.fixture(scope="class", autouse=True)
    def run_once(self, request):
        result, spies = _run_graph_with_spies(_BASE_CFG)
        request.cls._slave_results = result.get("slave_results", [])

    def _get(self, type_: str) -> dict:
        return next((r for r in self._slave_results if r.get("type") == type_), {})

    @pytest.mark.e2e
    def test_instrument_result_has_instrument_field(self):
        r = self._get("instrument")
        assert "instrument" in r
        assert r["instrument"] == "Phase-4"

    @pytest.mark.e2e
    def test_instrument_result_has_fx_list(self):
        r = self._get("instrument")
        assert isinstance(r.get("fx"), list)

    @pytest.mark.e2e
    def test_harmony_result_has_key(self):
        r = self._get("harmony")
        assert "key" in r          # z.B. "E minor"

    @pytest.mark.e2e
    def test_harmony_result_has_scale_name(self):
        r = self._get("harmony")
        assert "scale_name" in r

    @pytest.mark.e2e
    def test_harmony_result_has_allowed_pitch_classes(self):
        r = self._get("harmony")
        pcs = r.get("allowed_pitch_classes", [])
        assert isinstance(pcs, list) and len(pcs) > 0

    @pytest.mark.e2e
    def test_harmony_result_has_register_range(self):
        r = self._get("harmony")
        assert "register_low" in r and "register_high" in r
        assert r["register_low"] < r["register_high"]

    @pytest.mark.e2e
    def test_note_result_has_bpm(self):
        r = self._get("notes")
        assert "bpm" in r

    @pytest.mark.e2e
    def test_note_result_has_notes_list(self):
        r = self._get("notes")
        assert isinstance(r.get("notes"), list)
        assert len(r["notes"]) > 0

    @pytest.mark.e2e
    def test_note_result_notes_have_required_fields(self):
        r = self._get("notes")
        for n in r.get("notes", []):
            assert "step"  in n
            assert "pitch" in n
            assert "vel"   in n
            assert "dur"   in n

    @pytest.mark.e2e
    def test_note_result_pitches_in_valid_midi_range(self):
        r = self._get("notes")
        for n in r.get("notes", []):
            assert 0 <= n["pitch"] <= 127, f"Pitch {n['pitch']} außerhalb MIDI-Range"

    @pytest.mark.e2e
    def test_note_result_velocities_in_valid_range(self):
        r = self._get("notes")
        for n in r.get("notes", []):
            assert 0.0 < n["vel"] <= 1.0, f"Velocity {n['vel']} außerhalb 0–1"

    @pytest.mark.e2e
    def test_note_result_has_length_beats(self):
        r = self._get("notes")
        assert "length_beats" in r
        assert float(r["length_beats"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. Fan-in: note_slave erhält Harmony-Kontext aus harmony_slave
# ══════════════════════════════════════════════════════════════════════════════

class TestFanInHarmonyContext:
    """note_slave muss den harmony-Kontext im State vorfinden wenn es läuft."""

    @pytest.mark.e2e
    def test_note_slave_state_contains_harmony_result(self):
        """Der State der note_slave-Eingabe muss den harmony-Output enthalten."""
        from src.agent.slaves.note_slave import run_note_slave

        captured_states: list[dict] = []

        def capturing_note_slave(state: dict) -> dict:
            captured_states.append(dict(state))
            return run_note_slave(state)

        patches = [
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.master_graph.run_note_slave", capturing_note_slave),
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm(_INSTRUMENT_JSON)),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from src.agent.master_graph import build_master_graph
            from src.agent.core import _default_state
            state = _default_state()
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_BASE_CFG)
            build_master_graph().invoke(state)

        assert len(captured_states) > 0, "note_slave wurde nicht aufgerufen"
        note_state = captured_states[0]
        results_in_state = note_state.get("slave_results", [])
        harmony_present = any(r.get("type") == "harmony" for r in results_in_state)
        assert harmony_present, (
            f"Harmony-Ergebnis fehlt im note_slave-State. "
            f"Vorhandene Typen: {[r.get('type') for r in results_in_state]}"
        )

    @pytest.mark.e2e
    def test_note_slave_state_contains_instrument_result(self):
        """Der State der note_slave-Eingabe muss auch den instrument-Output enthalten."""
        from src.agent.slaves.note_slave import run_note_slave

        captured_states: list[dict] = []

        def capturing_note_slave(state: dict) -> dict:
            captured_states.append(dict(state))
            return run_note_slave(state)

        patches = [
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.master_graph.run_note_slave", capturing_note_slave),
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm(_INSTRUMENT_JSON)),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]

        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from src.agent.master_graph import build_master_graph
            from src.agent.core import _default_state
            state = _default_state()
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_BASE_CFG)
            build_master_graph().invoke(state)

        assert len(captured_states) > 0
        results_in_state = captured_states[0].get("slave_results", [])
        assert any(r.get("type") == "instrument" for r in results_in_state)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Retry-Verhalten: fehlerhafte Slaves blockieren assemble_node
# ══════════════════════════════════════════════════════════════════════════════

class TestSlaveRetryBehavior:

    @pytest.mark.e2e
    def test_instrument_parse_error_produces_error_result(self):
        """Ungültige LLM-Antwort → instrument_slave liefert type=instrument + error."""
        patches = [
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm("das ist kein JSON")),
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from src.agent.master_graph import build_master_graph
            from src.agent.core import _default_state
            state = _default_state()
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_BASE_CFG)
            result = build_master_graph().invoke(state)

        slave_results = result.get("slave_results", [])
        instrument_errors = [
            r for r in slave_results
            if r.get("type") == "instrument" and "error" in r
        ]
        assert len(instrument_errors) > 0, "Fehler-Eintrag für instrument_slave erwartet"

    @pytest.mark.e2e
    def test_instrument_parse_error_prevents_assembled_json(self):
        """Fehlerhafte instrument_slave-Antwort → assembled_json bleibt None."""
        patches = [
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm("kein json")),
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            from src.agent.master_graph import build_master_graph
            from src.agent.core import _default_state
            state = _default_state()
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_BASE_CFG)
            result = build_master_graph().invoke(state)

        assert result.get("assembled_json") is None

    @pytest.mark.e2e
    def test_all_slaves_ok_produces_assembled_json(self):
        """Alle Slaves erfolgreich → assembled_json muss gesetzt sein."""
        result, _ = _run_graph_with_spies(_BASE_CFG)
        assert result.get("assembled_json") is not None
        json.loads(result["assembled_json"])  # muss valides JSON sein

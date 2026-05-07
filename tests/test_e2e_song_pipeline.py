"""End-to-End Tests für die vollständige Song-Pipeline.

Ablauf:
    UI-Config → plan_node → harmony_slave + instrument_slave → note_slave
              → assemble_node → execute_build_node → verify_node → reply_node

LLM-Calls und OSC werden gemockt — kein Bitwig, kein vLLM erforderlich.
"""
from __future__ import annotations

import json
import os
from contextlib import ExitStack
from unittest.mock import MagicMock, patch, patch as _patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage


# ── Fake-LLM-Antworten ────────────────────────────────────────────────────────

_INSTRUMENT_JSON = json.dumps({
    "instrument": "Phase-4",
    "fx": [],
    "preset": "",
    "fx_preset": "",
})

# E-minor-Noten im Low-Register (E2–D3 = MIDI 40–50), alle in E-minor-Skala
_NOTES_JSON = json.dumps({
    "bpm": 100,
    "length_beats": 8,
    "notes": [
        {"step": 0.0, "pitch": 40, "vel": 0.8, "dur": 0.5},  # E2
        {"step": 1.0, "pitch": 43, "vel": 0.7, "dur": 0.5},  # G2
        {"step": 2.0, "pitch": 45, "vel": 0.8, "dur": 0.5},  # A2
        {"step": 3.0, "pitch": 47, "vel": 0.7, "dur": 0.5},  # B2
        {"step": 4.0, "pitch": 40, "vel": 0.8, "dur": 0.5},  # E2
        {"step": 5.0, "pitch": 43, "vel": 0.7, "dur": 0.5},  # G2
        {"step": 6.0, "pitch": 45, "vel": 0.6, "dur": 0.5},  # A2
        {"step": 7.0, "pitch": 47, "vel": 0.8, "dur": 0.5},  # B2
    ],
})


def _fake_llm(response_content: str) -> MagicMock:
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content=response_content)
    return llm


def _fake_verify() -> MagicMock:
    m = MagicMock()
    m.invoke.return_value = {
        "ok": True, "track_count": 1, "warnings": [],
        "report_text": "OK", "tracks_info": "",
    }
    return m


# ── Screenshot-Config (wie im Bitwig Controller UI eingestellt) ───────────────

_SCREENSHOT_CFG = {
    "genre": "Pop", "bpm": 100, "track_count": 1,
    "key": "E minor", "length_beats": 64,
    "technique": "Standard", "rhythm_pattern": "Gallop",
    "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
    "fx_preset": "Distortion+Amp",
}


# ── Patch-Liste (wiederverwendbar) ────────────────────────────────────────────

def _all_patches(osc_client: MagicMock) -> list:
    return [
        patch("src.agent.slaves.instrument_slave._get_llm",
              return_value=_fake_llm(_INSTRUMENT_JSON)),
        patch("src.agent.slaves.note_slave._get_llm",
              return_value=_fake_llm(_NOTES_JSON)),
        patch("src.agent.tools.song_tools._check_bridge", return_value=True),
        patch("src.agent.tools.song_tools._osc_client", return_value=osc_client),
        patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
        patch("src.agent.tools.song_tools.verify_song", _fake_verify()),
        patch("time.sleep"),
        patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
    ]


def _run_graph(ui_cfg: dict) -> tuple[dict, MagicMock]:
    """Baut den LangGraph und führt ihn mit der gegebenen UI-Config aus.
    Gibt (final_state, osc_mock) zurück.
    """
    from src.agent.master_graph import build_master_graph
    from src.agent.core import _default_state

    osc = MagicMock()
    with ExitStack() as stack:
        for p in _all_patches(osc):
            stack.enter_context(p)
        state = _default_state()
        state["messages"] = [HumanMessage(content="Erstelle einen Song")]
        state["ui_song_config"] = dict(ui_cfg)
        result = build_master_graph().invoke(state)
    return result, osc


# ══════════════════════════════════════════════════════════════════════════════
# 1. Screenshot-Variante vollständig durchlaufen
# ══════════════════════════════════════════════════════════════════════════════

class TestE2EScreenshotConfig:
    """End-to-End: Screenshot-Config (Pop · 100 BPM · 1 Track · E minor · 64 beats · Gallop).

    Die Pipeline läuft einmal für die gesamte Klasse — alle Tests prüfen
    dasselbe Ergebnis-Dict.
    """

    @pytest.fixture(scope="class", autouse=True)
    def pipeline_result(self, request):
        result, osc = _run_graph(_SCREENSHOT_CFG)
        request.cls._result = result
        request.cls._osc = osc

    @pytest.mark.e2e
    def test_pipeline_has_assembled_json(self):
        assert self._result.get("assembled_json") is not None

    @pytest.mark.e2e
    def test_assembled_json_valid(self):
        data = json.loads(self._result["assembled_json"])
        assert isinstance(data, dict)
        assert "tracks" in data

    @pytest.mark.e2e
    def test_assembled_bpm_100(self):
        """BPM 100 aus Screenshot-Config muss im assembled_json stehen."""
        data = json.loads(self._result["assembled_json"])
        assert data["bpm"] == 100

    @pytest.mark.e2e
    def test_assembled_track_count_1(self):
        """track_count=1 → genau 1 Track im assembled_json."""
        data = json.loads(self._result["assembled_json"])
        assert len(data["tracks"]) == 1

    @pytest.mark.e2e
    def test_assembled_instrument_phase4(self):
        """Fake-LLM liefert Phase-4 — muss im Track landen."""
        data = json.loads(self._result["assembled_json"])
        assert data["tracks"][0]["instrument"] == "Phase-4"

    @pytest.mark.e2e
    def test_assembled_clip_length_64(self):
        """length_beats=64 aus Config → Clip-Länge 64 Beats."""
        data = json.loads(self._result["assembled_json"])
        assert data["tracks"][0]["clip"]["length_beats"] == 64.0

    @pytest.mark.e2e
    def test_assembled_clip_has_notes(self):
        """Clip muss Noten enthalten."""
        data = json.loads(self._result["assembled_json"])
        assert len(data["tracks"][0]["clip"]["notes"]) > 0

    @pytest.mark.e2e
    def test_build_result_ok(self):
        """execute_build_node muss 'build_song OK' zurückgeben."""
        assert "build_song OK" in self._result.get("build_result", "")

    @pytest.mark.e2e
    def test_build_result_bpm_100(self):
        assert "BPM=100" in self._result.get("build_result", "")

    @pytest.mark.e2e
    def test_osc_tempo_set_to_100(self):
        """OSC muss /transport/tempo 100.0 empfangen haben."""
        self._osc.send_message.assert_any_call("/transport/tempo", 100.0)

    @pytest.mark.e2e
    def test_osc_track_added(self):
        """OSC muss /track/add/instrument gesendet haben."""
        self._osc.send_message.assert_any_call("/track/add/instrument", 1)

    @pytest.mark.e2e
    def test_generation_phase_done(self):
        assert self._result.get("generation_phase") == "done"

    @pytest.mark.e2e
    def test_reply_message_present(self):
        msgs = self._result.get("messages", [])
        assert any(isinstance(m, AIMessage) for m in msgs)

    @pytest.mark.e2e
    def test_reply_contains_bpm(self):
        msgs = self._result.get("messages", [])
        last_ai = next((m for m in reversed(msgs) if isinstance(m, AIMessage)), None)
        assert last_ai is not None
        assert "100" in last_ai.content


# ══════════════════════════════════════════════════════════════════════════════
# 2. track_count-Varianten: assemble_node baut richtige Anzahl Tracks
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
@pytest.mark.parametrize("track_count,expected_tracks", [
    (1, 1),
    (2, 2),
    (4, 4),
    (6, 6),
], ids=["1track", "2tracks", "4tracks", "6tracks"])
def test_e2e_track_count_variants(track_count, expected_tracks):
    """assembled_json muss für jeden track_count-Wert die richtige Anzahl Tracks haben."""
    cfg = dict(_SCREENSHOT_CFG, track_count=track_count)
    result, _ = _run_graph(cfg)
    assert result.get("assembled_json") is not None
    data = json.loads(result["assembled_json"])
    assert len(data["tracks"]) == expected_tracks


# ══════════════════════════════════════════════════════════════════════════════
# 3. length_beats-Varianten: Clip-Länge im assembled_json korrekt
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
@pytest.mark.parametrize("length_beats", [8, 16, 32, 64],
                          ids=["8beats", "16beats", "32beats", "64beats"])
def test_e2e_length_variants(length_beats):
    """Clip-Länge im assembled_json muss length_beats aus der UI-Config entsprechen."""
    cfg = dict(_SCREENSHOT_CFG, length_beats=length_beats)
    result, _ = _run_graph(cfg)
    assert result.get("assembled_json") is not None
    data = json.loads(result["assembled_json"])
    assert data["tracks"][0]["clip"]["length_beats"] == float(length_beats)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Observer + State Pattern — Retry-Loop
# ══════════════════════════════════════════════════════════════════════════════

def _run_graph_with_verify(ui_cfg: dict, verify_mock: MagicMock) -> tuple[dict, MagicMock]:
    """Graph-Lauf mit eigenem verify_song-Mock (für Side-Effect-Tests)."""
    from src.agent.master_graph import build_master_graph
    from src.agent.core import _default_state

    osc = MagicMock()
    patches = [
        patch("src.agent.slaves.instrument_slave._get_llm",
              return_value=_fake_llm(_INSTRUMENT_JSON)),
        patch("src.agent.slaves.note_slave._get_llm",
              return_value=_fake_llm(_NOTES_JSON)),
        patch("src.agent.tools.song_tools._check_bridge", return_value=True),
        patch("src.agent.tools.song_tools._osc_client", return_value=osc),
        patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
        patch("src.agent.tools.song_tools.verify_song", verify_mock),
        patch("time.sleep"),
        patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        state = _default_state()
        state["messages"] = [HumanMessage(content="Erstelle einen Song")]
        state["ui_song_config"] = dict(ui_cfg)
        result = build_master_graph().invoke(state)
    return result, osc


class TestObserverRetryLoop:
    """Observer+State Pattern: verify liefert erst schlechte Qualität, dann OK.

    Prüft den vollständigen Retry-Zyklus: Budget-Dekrement, Slave-Neustart,
    slave_results-Reset und korrekten End-State.
    """

    @pytest.mark.e2e
    def test_retry_decrements_budget(self):
        """Erster verify schlechte Qualität (2 Warnings) → notes-Budget dekrementiert."""
        verify_mock = MagicMock()
        verify_mock.invoke.side_effect = [
            {"ok": True, "track_count": 1, "warnings": ["w1", "w2"]},
            {"ok": True, "track_count": 1, "warnings": []},
        ]
        result, _ = _run_graph_with_verify(_SCREENSHOT_CFG, verify_mock)
        assert result["retry_budget"]["note"] == 1   # war 2, einmal dekrementiert
        assert result["generation_phase"] == "done"

    @pytest.mark.e2e
    def test_retry_pipeline_ends_done(self):
        """Nach erfolgreichem Retry endet die Pipeline in 'done'."""
        verify_mock = MagicMock()
        verify_mock.invoke.side_effect = [
            {"ok": True, "track_count": 1, "warnings": ["x1", "x2"]},
            {"ok": True, "track_count": 1, "warnings": []},
        ]
        result, _ = _run_graph_with_verify(_SCREENSHOT_CFG, verify_mock)
        assert result["generation_phase"] == "done"

    @pytest.mark.e2e
    def test_retry_verify_called_twice(self):
        """Bei einem Retry muss verify_song genau zweimal aufgerufen werden."""
        verify_mock = MagicMock()
        verify_mock.invoke.side_effect = [
            {"ok": True, "track_count": 1, "warnings": ["bad1", "bad2"]},
            {"ok": True, "track_count": 1, "warnings": []},
        ]
        _run_graph_with_verify(_SCREENSHOT_CFG, verify_mock)
        assert verify_mock.invoke.call_count == 2

    @pytest.mark.e2e
    def test_retry_slaves_called_twice(self):
        """Bei Retry werden alle Slaves nochmal ausgeführt (Fan-out zurück zu plan)."""
        from src.agent.slaves.instrument_slave import run_instrument_slave

        spy_instrument = MagicMock(wraps=run_instrument_slave)
        verify_mock = MagicMock()
        verify_mock.invoke.side_effect = [
            {"ok": True, "track_count": 1, "warnings": ["w1", "w2"]},
            {"ok": True, "track_count": 1, "warnings": []},
        ]
        patches = [
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm(_INSTRUMENT_JSON)),
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.master_graph.run_instrument_slave", spy_instrument),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", verify_mock),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]
        from src.agent.master_graph import build_master_graph
        from src.agent.core import _default_state
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            state = _default_state()
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_SCREENSHOT_CFG)
            build_master_graph().invoke(state)

        assert spy_instrument.call_count == 2

    @pytest.mark.e2e
    def test_retry_resets_slave_results(self):
        """Nach Retry enthält slave_results nur die Ergebnisse des zweiten Durchlaufs."""
        verify_mock = MagicMock()
        verify_mock.invoke.side_effect = [
            {"ok": True, "track_count": 1, "warnings": ["w1", "w2"]},
            {"ok": True, "track_count": 1, "warnings": []},
        ]
        result, _ = _run_graph_with_verify(_SCREENSHOT_CFG, verify_mock)
        types = [r.get("type") for r in result.get("slave_results", [])]
        assert types.count("instrument") == 1, f"Doppelter instrument-Eintrag: {types}"
        assert types.count("harmony") == 1,    f"Doppelter harmony-Eintrag: {types}"
        assert types.count("notes") == 1,      f"Doppelter notes-Eintrag: {types}"

    @pytest.mark.e2e
    def test_no_retry_when_budget_exhausted(self):
        """Budget=0 → kein Retry, Pipeline endet ohne weiteren Slave-Durchlauf."""
        verify_mock = MagicMock()
        verify_mock.invoke.return_value = {
            "ok": True, "track_count": 1, "warnings": ["w1", "w2"],
        }
        from src.agent.master_graph import build_master_graph
        from src.agent.core import _default_state

        patches = [
            patch("src.agent.slaves.instrument_slave._get_llm",
                  return_value=_fake_llm(_INSTRUMENT_JSON)),
            patch("src.agent.slaves.note_slave._get_llm",
                  return_value=_fake_llm(_NOTES_JSON)),
            patch("src.agent.tools.song_tools._check_bridge", return_value=True),
            patch("src.agent.tools.song_tools._osc_client", return_value=MagicMock()),
            patch("src.agent.tools.song_tools._get_current_track_count", return_value=0),
            patch("src.agent.tools.song_tools.verify_song", verify_mock),
            patch("time.sleep"),
            patch.dict(os.environ, {"NOTE_SLAVE_CANDIDATES": "1"}),
        ]
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            state = _default_state()
            state["retry_budget"] = {"instrument": 0, "harmony": 0, "notes": 0}
            state["messages"] = [HumanMessage(content="Erstelle einen Song")]
            state["ui_song_config"] = dict(_SCREENSHOT_CFG)
            result = build_master_graph().invoke(state)

        # Auch ohne Budget darf kein Infinite Loop entstehen
        assert result.get("generation_phase") in ("done", "verifying", "error")
        # verify nur einmal aufgerufen (kein Budget → kein Retry-Loop)
        assert verify_mock.invoke.call_count == 1

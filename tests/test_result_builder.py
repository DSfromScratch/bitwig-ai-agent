"""
LLM-Evaluations-Test: Kann das LLM ein korrektes BitwigResult bauen?

Das predefined Result dient als Goldstandard-Validator.
Der Test prüft ob das LLM bei einem gegebenen Prompt das richtige
Result-Objekt konstruiert — Instrument, Parameter-Ranges, FX.

Strategie: Event-Bus subscribe auf result_step_done / result_done —
der Executor emittiert diese Events während der Ausführung. Kein
Message-History-Graben, kein Patch auf interne LangChain-Objekte.
OSC wird stumm geschaltet; kein echtes Bitwig nötig.

Erfordert laufendes vLLM-Backend (wird übersprungen wenn nicht erreichbar).
Neo4j optional — Test läuft auch ohne DB (LLM nutzt dann nur Systemprompt-Wissen).
"""
import pytest
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Goldstandard-Spezifikationen ──────────────────────────────────────────────

WARM_PAD_SPEC = {
    "context_type": "track",
    "target_track": 1,
    "instrument": "phase-4",            # case-insensitiv
    "param_ranges": {
        # Remote-Control-Index → (min, max) — erwarteter Wertebereich
        3: (0.25, 0.45),                # Cutoff: warm = 0.3–0.4
        5: (0.4, 0.85),                 # Attack: langsam anschwellend
    },
    "required_effects": ["reverb"],     # mindestens ein Reverb
    "forbidden_duplicates": ["load_instrument"],  # kein doppeltes Instrument-Laden
}

ROCK_SONG_SPEC = {
    "context_type": "song",
    "required_tracks": ["kick", "bass", "guitar"],   # mindestens diese Rollen
    "bpm_range": (100, 160),
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _vllm_reachable() -> bool:
    """Prüft ob das vLLM-Backend erreichbar ist."""
    import os, urllib.request
    url = os.getenv("VLLM_BASE_URL", "http://localhost:8100") + "/health"
    try:
        urllib.request.urlopen(url, timeout=2.0)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def vllm_available():
    return _vllm_reachable()


# ── Graph-Runner: lauscht auf Event-Bus ──────────────────────────────────────

def _run_and_capture(prompt: str) -> dict | None:
    """
    Führt den Agent-Graph aus und gibt ein rekonstruiertes BitwigResult zurück.

    Lauscht auf result_step_done / result_done Events die execute_result emittiert.
    OSC wird stumm geschaltet; kein echtes Bitwig nötig.
    """
    from langchain_core.messages import HumanMessage
    from src.agent.core import get_graph, _default_state
    from src.agent.events import get_event_bus, reset_event_bus

    reset_event_bus()
    bus = get_event_bus()

    steps_done: list[dict] = []
    meta_done:  list[dict] = []

    def _on_step(event: dict) -> None:
        steps_done.append(event["payload"])

    def _on_done(event: dict) -> None:
        meta_done.append(event["payload"])

    bus.subscribe("result_step_done", _on_step)
    bus.subscribe("result_done", _on_done)

    try:
        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):

            graph = get_graph()
            state = _default_state()
            state["messages"] = [HumanMessage(content=prompt)]
            graph.invoke(state)
    finally:
        bus.unsubscribe("result_step_done", _on_step)
        bus.unsubscribe("result_done", _on_done)

    if not meta_done:
        return None

    meta  = meta_done[0]
    steps = [
        {"type": s["type"], "args": s["args"], "status": "done", "note": ""}
        for s in sorted(steps_done, key=lambda x: x.get("index", 0))
    ]
    return {
        "context_type": meta.get("context_type"),
        "target":       meta.get("target", {}),
        "summary":      meta.get("summary", ""),
        "steps":        steps,
    }


# ── Validierungs-Helfer ───────────────────────────────────────────────────────

def _steps_of_type(result: dict, step_type: str) -> list[dict]:
    return [s for s in result.get("steps", []) if s.get("type") == step_type]


def validate_warm_pad(result: dict) -> list[str]:
    """Validiert ein Result gegen WARM_PAD_SPEC. Gibt Fehler-Liste zurück."""
    errors: list[str] = []
    spec = WARM_PAD_SPEC

    # context_type
    if result.get("context_type") != spec["context_type"]:
        errors.append(f"context_type: erwartet '{spec['context_type']}', got '{result.get('context_type')}'")

    # target enthält track_index 1
    target = result.get("target", {})
    if target.get("track_index") != spec["target_track"]:
        errors.append(f"target.track_index: erwartet {spec['target_track']}, got {target.get('track_index')}")

    # Instrument geladen
    load_steps = _steps_of_type(result, "load_instrument")
    if not load_steps:
        errors.append("Kein load_instrument-Step vorhanden")
    else:
        name = load_steps[0].get("args", {}).get("name", "").lower()
        if spec["instrument"] not in name:
            errors.append(f"load_instrument: erwartet '{spec['instrument']}', got '{name}'")

    # Keine doppelten load_instrument
    if len(load_steps) > 1:
        errors.append(f"Doppelter load_instrument: {len(load_steps)}x vorhanden")

    # Parameter-Ranges
    param_steps = _steps_of_type(result, "set_param")
    param_map: dict[int, float] = {}
    for s in param_steps:
        idx = s.get("args", {}).get("index")
        val = s.get("args", {}).get("value")
        if idx is not None and val is not None:
            param_map[int(idx)] = float(val)

    for idx, (lo, hi) in spec["param_ranges"].items():
        if idx in param_map:
            val = param_map[idx]
            if not (lo <= val <= hi):
                errors.append(f"Param[{idx}]={val:.2f} außerhalb [{lo}, {hi}]")
        # Nicht gefunden = kein Fehler (LLM darf Parameter weglassen)

    # Mindestens ein Reverb-Effect
    effect_steps = _steps_of_type(result, "append_effect")
    effect_names = [s.get("args", {}).get("name", "").lower() for s in effect_steps]
    for fx in spec["required_effects"]:
        if not any(fx in n for n in effect_names):
            errors.append(f"Pflicht-Effect fehlt: '{fx}' (gefunden: {effect_names})")

    # status-Feld wird vom Executor verwaltet, nicht vom LLM — kein Check hier

    return errors


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestResultBuilder:
    """Prüft ob LLM + (optional) Neo4j ein korrektes BitwigResult konstruiert."""

    @pytest.mark.integration
    def test_warm_pad_result_structure(self, vllm_available):
        """LLM baut für 'warmer Pad Track 1' ein valides BitwigResult."""
        if not vllm_available:
            pytest.skip("vLLM nicht erreichbar")

        result = _run_and_capture(
            "Richte auf Track 1 einen warmen Pad-Sound ein mit Phase-4, "
            "Cutoff ca. 35%, langsamem Attack, und Reverb."
        )

        assert result is not None, "LLM hat execute_result nicht aufgerufen"

        errors = validate_warm_pad(result)
        assert not errors, (
            "BitwigResult entspricht nicht dem Goldstandard:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    @pytest.mark.integration
    def test_result_has_steps(self, vllm_available):
        """Result enthält mindestens 2 Steps (Instrument + mind. 1 Param/FX)."""
        if not vllm_available:
            pytest.skip("vLLM nicht erreichbar")

        result = _run_and_capture(
            "Richte Track 2 ein: Phase-4 laden, Cutoff auf 0.4 setzen, Chorus als Effekt hinzufügen."
        )

        assert result is not None, "execute_result nicht aufgerufen"
        steps = result.get("steps", [])
        assert len(steps) >= 2, f"Zu wenige Steps: {steps}"

    @pytest.mark.integration
    def test_no_direct_load_instrument(self, vllm_available):
        """LLM setzt load_instrument in Steps[], ruft es nicht als separates Tool auf."""
        if not vllm_available:
            pytest.skip("vLLM nicht erreichbar")

        from langchain_core.messages import AIMessage

        with patch("src.agent.tools.song_tools._check_bridge", return_value=True), \
             patch("pythonosc.udp_client.SimpleUDPClient"):

            from src.agent.core import get_graph, _default_state
            from langchain_core.messages import HumanMessage

            graph = get_graph()
            state = _default_state()
            state["messages"] = [HumanMessage(
                content="Richte Track 1 mit Phase-4 ein, Cutoff 0.35, Reverb drauf."
            )]
            final = graph.invoke(state)

        # Zähle direkte bitwig_load_instrument Calls (sollten 0 sein)
        direct_load_calls = [
            tc for msg in final.get("messages", [])
            if isinstance(msg, AIMessage)
            for tc in (msg.tool_calls or [])
            if tc.get("name") == "bitwig_load_instrument"
        ]
        assert len(direct_load_calls) == 0, (
            f"LLM rief bitwig_load_instrument direkt auf ({len(direct_load_calls)}x) "
            "statt es in execute_result Steps zu verpacken"
        )


# ── Unit-Test: Validator-Logik selbst ────────────────────────────────────────

class TestResultValidator:
    """Unit-Tests für validate_warm_pad — kein LLM nötig."""

    @pytest.mark.unit
    def test_valid_result_passes(self):
        result = {
            "context_type": "track",
            "target": {"track_index": 1},
            "neo4j_context": [],
            "summary": "Phase-4 Pad",
            "steps": [
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
                {"type": "set_param", "args": {"track_index": 1, "index": 3, "value": 0.35}, "status": "pending", "note": ""},
                {"type": "set_param", "args": {"track_index": 1, "index": 5, "value": 0.6}, "status": "pending", "note": ""},
                {"type": "append_effect", "args": {"track_index": 1, "name": "Reverb"}, "status": "pending", "note": ""},
            ]
        }
        errors = validate_warm_pad(result)
        assert errors == [], f"Fehler in validem Result: {errors}"

    @pytest.mark.unit
    def test_wrong_instrument_fails(self):
        result = {
            "context_type": "track",
            "target": {"track_index": 1},
            "steps": [
                {"type": "load_instrument", "args": {"track_index": 1, "name": "FM-4"}, "status": "pending", "note": ""},
                {"type": "append_effect", "args": {"track_index": 1, "name": "Reverb"}, "status": "pending", "note": ""},
            ]
        }
        errors = validate_warm_pad(result)
        assert any("load_instrument" in e for e in errors)

    @pytest.mark.unit
    def test_cutoff_out_of_range_fails(self):
        result = {
            "context_type": "track",
            "target": {"track_index": 1},
            "steps": [
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
                {"type": "set_param", "args": {"track_index": 1, "index": 3, "value": 0.9}, "status": "pending", "note": ""},
                {"type": "append_effect", "args": {"track_index": 1, "name": "Reverb"}, "status": "pending", "note": ""},
            ]
        }
        errors = validate_warm_pad(result)
        assert any("Param[3]" in e for e in errors)

    @pytest.mark.unit
    def test_missing_reverb_fails(self):
        result = {
            "context_type": "track",
            "target": {"track_index": 1},
            "steps": [
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
            ]
        }
        errors = validate_warm_pad(result)
        assert any("reverb" in e.lower() for e in errors)

    @pytest.mark.unit
    def test_duplicate_load_instrument_fails(self):
        result = {
            "context_type": "track",
            "target": {"track_index": 1},
            "steps": [
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
                {"type": "load_instrument", "args": {"track_index": 1, "name": "Phase-4"}, "status": "pending", "note": ""},
                {"type": "append_effect", "args": {"track_index": 1, "name": "Reverb"}, "status": "pending", "note": ""},
            ]
        }
        errors = validate_warm_pad(result)
        assert any("Doppelter" in e for e in errors)


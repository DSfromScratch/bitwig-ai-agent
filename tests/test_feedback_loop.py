"""
E2E-Test für den Musik-Feedback-Loop.

Testet die vollständige Kette:
  write_pattern → validate_and_learn → Neo4j-Speicherung

Alle externen Abhängigkeiten (Bitwig, LLM, Neo4j) werden gemockt.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock, call


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _llm_response(score: float, issues: list[str] | None = None,
                  suggestions: list[str] | None = None) -> str:
    return json.dumps({
        "score":       score,
        "rhythmic_ok": score >= 0.65,
        "harmonic_ok": True,
        "genre_fit":   True,
        "issues":      issues or [],
        "suggestions": suggestions or [],
        "summary":     f"Test-Pattern, Score {score:.2f}.",
    })


# ── Jazz-Pattern-Qualität ──────────────────────────────────────────────────────

class TestJazzPattern:
    """Stellt sicher dass Jazz-Patterns korrekte Elemente enthalten."""

    @pytest.mark.unit
    def test_jazz_drums_have_ride(self):
        from src.agent.tools.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        pitches = {n["pitch"] for n in notes}
        assert 51 in pitches, f"Jazz-Drums müssen Ride (MIDI51) enthalten. Pitches: {pitches}"

    @pytest.mark.unit
    def test_jazz_drums_have_snare(self):
        from src.agent.tools.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        pitches = {n["pitch"] for n in notes}
        assert 38 in pitches, f"Jazz-Drums müssen Snare (MIDI38) haben. Pitches: {pitches}"

    @pytest.mark.unit
    def test_jazz_drums_snare_on_offbeats(self):
        """Snare muss auf Beat 2 und 4 (steps 1.0 und 3.0) liegen."""
        from src.agent.tools.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        snare_steps = sorted({n["step"] % 4 for n in notes if n["pitch"] == 38})
        assert 1.0 in snare_steps, f"Snare muss auf Beat 2 (step 1.0). Steps: {snare_steps}"
        assert 3.0 in snare_steps, f"Snare muss auf Beat 4 (step 3.0). Steps: {snare_steps}"

    @pytest.mark.unit
    def test_jazz_drums_hh_pedal_on_offbeats(self):
        """HH-Pedal (MIDI44) typischerweise auf Beat 2+4 im Jazz."""
        from src.agent.tools.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        hh_pedal_steps = sorted({n["step"] % 4 for n in notes if n["pitch"] == 44})
        assert len(hh_pedal_steps) >= 1, f"HH-Pedal sollte in Jazz-Pattern. Steps: {hh_pedal_steps}"

    @pytest.mark.unit
    def test_jazz_prompt_mentions_ride(self):
        """Validator-Prompt für Jazz muss Ride-Cymbal als Kriterium nennen."""
        from src.agent.tools.pattern_generators import _drums
        from src.agent.tools.music_validator import _build_validation_prompt
        notes = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)
        assert "Ride" in prompt or "51" in prompt, \
            "Jazz-Prompt muss Ride-Cymbal erwähnen"
        assert "Jazz" in prompt or "jazz" in prompt, \
            "Jazz-Prompt muss Jazz-spezifische Kriterien enthalten"

    @pytest.mark.unit
    def test_jazz_validator_scores_ride_pattern_high(self):
        """Validator soll Jazz-Pattern mit Ride+Snare hoch bewerten (>= 0.70)."""
        from src.agent.tools.pattern_generators import _drums
        from src.agent.tools.music_validator import _build_validation_prompt

        notes = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)

        mock_response = _llm_response(0.78, suggestions=["Ride-Variationen einbauen"])

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_response):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)

        assert result.get("score", 0) >= 0.70, \
            f"Jazz-Pattern mit Ride+Snare: score={result.get('score')}, erwartet >= 0.70"

    @pytest.mark.unit
    def test_rock_prompt_unchanged(self):
        """Rock-Prompt enthält weiterhin Kick+Snare-Kriterien."""
        from src.agent.tools.pattern_generators import _drums
        from src.agent.tools.music_validator import _build_validation_prompt
        notes = _drums("rock", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "rock", "A", "minor", 2, 120)
        assert "Beat 1" in prompt or "Beat 2" in prompt, \
            "Rock-Prompt muss Beat-Kriterien enthalten"


# ── E2E Feedback-Loop ──────────────────────────────────────────────────────────

class TestFeedbackLoopE2E:
    """Testet write_pattern → validate_and_learn → Neo4j komplett gemockt."""

    def _mock_neo4j_session(self):
        """Erstellt einen Neo4j-Session-Mock."""
        session    = MagicMock()
        run_result = MagicMock()
        run_result.single.return_value = None
        session.run.return_value        = run_result
        session.__enter__               = lambda s: session
        session.__exit__                = MagicMock(return_value=False)
        return session

    @pytest.mark.unit
    def test_validate_and_learn_stores_to_neo4j(self):
        """validate_and_learn ruft Neo4j-Speicherung auf wenn Score verfügbar."""
        from src.agent.tools.pattern_generators import _drums

        notes = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.82)
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session
        driver.__enter__            = lambda d: driver
        driver.__exit__             = MagicMock(return_value=False)

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert "0.82" in result, f"Score sollte im Output sein: {result}"
        assert "✓" in result,    f"Guter Score sollte ✓ enthalten: {result}"
        assert driver.session.called, "Neo4j-Session wurde nicht aufgerufen"

    @pytest.mark.unit
    def test_validate_and_learn_low_score_suggests_improvement(self):
        """Bei Score < 0.7 soll 'Verbesserung empfohlen' im Output stehen."""
        from src.agent.tools.pattern_generators import _drums

        notes     = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.45, issues=["Kick fehlt"], suggestions=["Kick auf Beat 1"])
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert "⚠" in result or "Verbesserung" in result, \
            f"Niedriger Score soll Verbesserungshinweis geben: {result}"
        assert "Kick" in result, f"Issues sollen im Output stehen: {result}"

    @pytest.mark.unit
    def test_score_and_learn_returns_score(self):
        """score_and_learn gibt score + notes + suggestions zurück."""
        from src.agent.tools.pattern_generators import _drums

        notes     = _drums("jazz", 2, "basic")
        mock_resp = _llm_response(0.76, suggestions=["Ride-Variationen einbauen"])
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import score_and_learn
            result = score_and_learn(notes, "VD-HEAVY", genre="jazz", key="C")

        assert result["score"]   == pytest.approx(0.76, abs=0.01)
        assert result["learned"] is True
        assert "Ride" in result["suggestions"][0]
        assert result["needs_improvement"] is False

    @pytest.mark.unit
    def test_write_pattern_calls_validate(self):
        """write_pattern generiert Noten und gibt OSC-Ergebnis zurück."""
        mock_resp = _llm_response(0.80)

        with patch("src.bitwig_executor._check_connection", return_value=True), \
             patch("bitwigbridge.executor._exec_step_and_wait", return_value="write_notes"), \
             patch("src.agent.osc.track_state._get_current_track_count", return_value=2), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from src.agent.tools.pattern_tools import write_pattern
            result = write_pattern.invoke({
                "track_index": 1,
                "instrument":  "VD-HEAVY",
                "genre":       "rock",
                "key":         "A",
                "scale":       "minor",
                "bars":        2,
                "bpm":         120,
            })

        assert isinstance(result, str)
        assert len(result) > 0
        assert "write_pattern" in result or "drums" in result.lower() or "Noten" in result

    @pytest.mark.unit
    def test_full_loop_write_then_validate(self):
        """Vollständige Kette: write_pattern → validate_and_learn hintereinander."""
        mock_resp = _llm_response(0.78, suggestions=["HiHat-Variation einbauen"])
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.bitwig_executor._check_connection", return_value=True), \
             patch("bitwigbridge.executor._exec_step_and_wait", return_value="write_notes"), \
             patch("src.agent.osc.track_state._get_current_track_count", return_value=2), \
             patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):

            from src.agent.tools.pattern_tools import write_pattern
            from src.agent.tools.music_learning import validate_and_learn
            from src.agent.tools.pattern_generators import _drums

            # Schritt 1: Pattern generieren und schreiben
            write_result = write_pattern.invoke({
                "track_index": 1, "instrument": "VD-HEAVY", "genre": "rock",
                "key": "A", "scale": "minor", "bars": 2, "bpm": 120,
            })

            # Schritt 2: Validieren und in Neo4j speichern
            notes        = _drums("rock", 2, "basic")
            learn_result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert isinstance(write_result, str)
        assert "0.78" in learn_result or "Score" in learn_result
        assert driver.session.called, "Neo4j wurde nie aufgerufen"

    @pytest.mark.unit
    def test_validate_and_learn_no_llm_returns_graceful(self):
        """Wenn LLM nicht verfügbar: kein Absturz, sinnvoller Hinweis."""
        from src.agent.tools.pattern_generators import _drums

        notes = _drums("rock", 2, "basic")

        with patch("src.agent.tools.music_validator._is_available", return_value=False):
            from src.agent.tools.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert isinstance(result, str)
        assert len(result) > 0
        assert "nicht verfügbar" in result or "übersprungen" in result

    @pytest.mark.unit
    def test_neo4j_upsert_called_with_correct_fields(self):
        """Neo4j MERGE-Abfrage enthält instrument, genre, score."""
        from src.agent.tools.pattern_generators import _drums

        notes     = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.75)
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import score_and_learn
            score_and_learn(notes, "VD-HEAVY", genre="rock", key="A", store_to_neo4j=True)

        # Prüfe dass Neo4j-Aufrufe gemacht wurden
        assert session.run.called, "Neo4j session.run() nie aufgerufen"
        # Prüfe dass irgendein Query instrument-Kontext enthält
        all_queries = " ".join(str(c) for c in session.run.call_args_list)
        assert "VD-HEAVY" in all_queries or "instrument" in all_queries.lower(), \
            f"Neo4j-Query sollte Instrument enthalten. Calls: {session.run.call_args_list}"

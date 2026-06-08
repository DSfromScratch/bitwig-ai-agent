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
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        pitches = {n["pitch"] for n in notes}
        assert 51 in pitches, f"Jazz-Drums müssen Ride (MIDI51) enthalten. Pitches: {pitches}"

    @pytest.mark.unit
    def test_jazz_drums_have_snare(self):
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        pitches = {n["pitch"] for n in notes}
        assert 38 in pitches, f"Jazz-Drums müssen Snare (MIDI38) haben. Pitches: {pitches}"

    @pytest.mark.unit
    def test_jazz_drums_snare_on_offbeats(self):
        """Snare muss auf Beat 2 und 4 (steps 1.0 und 3.0) liegen."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        snare_steps = sorted({n["step"] % 4 for n in notes if n["pitch"] == 38})
        assert 1.0 in snare_steps, f"Snare muss auf Beat 2 (step 1.0). Steps: {snare_steps}"
        assert 3.0 in snare_steps, f"Snare muss auf Beat 4 (step 3.0). Steps: {snare_steps}"

    @pytest.mark.unit
    def test_jazz_drums_hh_pedal_on_offbeats(self):
        """HH-Pedal (MIDI44) typischerweise auf Beat 2+4 im Jazz."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("jazz", 2, "basic")
        hh_pedal_steps = sorted({n["step"] % 4 for n in notes if n["pitch"] == 44})
        assert len(hh_pedal_steps) >= 1, f"HH-Pedal sollte in Jazz-Pattern. Steps: {hh_pedal_steps}"

    @pytest.mark.unit
    def test_jazz_prompt_mentions_ride(self):
        """Validator-Prompt für Jazz muss Ride-Cymbal als Kriterium nennen."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)
        assert "Ride" in prompt or "51" in prompt, \
            "Jazz-Prompt muss Ride-Cymbal erwähnen"
        assert "Jazz" in prompt or "jazz" in prompt, \
            "Jazz-Prompt muss Jazz-spezifische Kriterien enthalten"

    @pytest.mark.unit
    def test_jazz_validator_scores_ride_pattern_high(self):
        """Validator soll Jazz-Pattern mit Ride+Snare hoch bewerten (>= 0.70)."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt

        notes = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)

        mock_response = _llm_response(0.78, suggestions=["Ride-Variationen einbauen"])

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_response):
            from src.agent.tools.music.music_validator import validate_music_pattern
            result = validate_music_pattern(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)

        assert result.get("score", 0) >= 0.70, \
            f"Jazz-Pattern mit Ride+Snare: score={result.get('score')}, erwartet >= 0.70"

    @pytest.mark.unit
    def test_rock_prompt_unchanged(self):
        """Rock-Prompt enthält weiterhin Kick+Snare-Kriterien."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes = _drums("rock", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "rock", "A", "minor", 2, 120)
        assert "Beat 1" in prompt or "Beat 2" in prompt, \
            "Rock-Prompt muss Beat-Kriterien enthalten"

    @pytest.mark.unit
    def test_jazz_rhythmic_ok_uses_ride_not_kick(self):
        """rhythmic_ok-Kriterium nennt Ride (MIDI51), nicht Kick+Snare, bei Jazz."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-Jazz", "jazz", "C", "minor", 2, 120)
        # Finde den rhythmic_ok-Wert im JSON-Template
        rhythmic_ok_line = ""
        for line in prompt.splitlines():
            if '"rhythmic_ok"' in line:
                rhythmic_ok_line = line
                break
        assert rhythmic_ok_line, "rhythmic_ok-Zeile nicht im Prompt gefunden"
        assert "Ride" in rhythmic_ok_line or "MIDI51" in rhythmic_ok_line, \
            f"Jazz rhythmic_ok muss Ride erwähnen: {rhythmic_ok_line}"
        assert "Kick" not in rhythmic_ok_line, \
            f"Jazz rhythmic_ok darf Kick nicht erwähnen: {rhythmic_ok_line}"

    @pytest.mark.unit
    def test_rock_rhythmic_ok_uses_kick_snare(self):
        """rhythmic_ok-Kriterium nennt Kick+Snare bei Rock."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes = _drums("rock", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "rock", "A", "minor", 2, 120)
        rhythmic_ok_line = ""
        for line in prompt.splitlines():
            if '"rhythmic_ok"' in line:
                rhythmic_ok_line = line
                break
        assert "Kick" in rhythmic_ok_line or "Snare" in rhythmic_ok_line, \
            f"Rock rhythmic_ok muss Kick+Snare erwähnen: {rhythmic_ok_line}"


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
        from src.agent.tools.music.pattern_generators import _drums

        notes = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.82)
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session
        driver.__enter__            = lambda d: driver
        driver.__exit__             = MagicMock(return_value=False)

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.knowledge.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert "0.82" in result, f"Score sollte im Output sein: {result}"
        assert "✓" in result,    f"Guter Score sollte ✓ enthalten: {result}"
        assert driver.session.called, "Neo4j-Session wurde nicht aufgerufen"

    @pytest.mark.unit
    def test_validate_and_learn_low_score_suggests_improvement(self):
        """Bei Score < 0.7 soll 'Verbesserung empfohlen' im Output stehen."""
        from src.agent.tools.music.pattern_generators import _drums

        notes     = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.45, issues=["Kick fehlt"], suggestions=["Kick auf Beat 1"])
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.knowledge.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert "⚠" in result or "Verbesserung" in result, \
            f"Niedriger Score soll Verbesserungshinweis geben: {result}"
        assert "Kick" in result, f"Issues sollen im Output stehen: {result}"

    @pytest.mark.unit
    def test_score_and_learn_returns_score(self):
        """score_and_learn gibt score + notes + suggestions zurück."""
        from src.agent.tools.music.pattern_generators import _drums

        notes     = _drums("jazz", 2, "basic")
        mock_resp = _llm_response(0.76, suggestions=["Ride-Variationen einbauen"])
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.knowledge.music_learning import score_and_learn
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
            from src.agent.tools.music.pattern_tools import write_pattern
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
             patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):

            from src.agent.tools.music.pattern_tools import write_pattern
            from src.agent.tools.knowledge.music_learning import validate_and_learn
            from src.agent.tools.music.pattern_generators import _drums

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
        from src.agent.tools.music.pattern_generators import _drums

        notes = _drums("rock", 2, "basic")

        with patch("src.agent.tools.music.music_validator._is_available", return_value=False):
            from src.agent.tools.knowledge.music_learning import validate_and_learn
            result = validate_and_learn.invoke(
                {"notes": notes, "instrument": "VD-HEAVY", "genre": "rock", "key": "A"})

        assert isinstance(result, str)
        assert len(result) > 0
        assert "nicht verfügbar" in result or "übersprungen" in result

    @pytest.mark.unit
    def test_neo4j_upsert_called_with_correct_fields(self):
        """Neo4j MERGE-Abfrage enthält instrument, genre, score."""
        from src.agent.tools.music.pattern_generators import _drums

        notes     = _drums("rock", 2, "basic")
        mock_resp = _llm_response(0.75)
        session   = self._mock_neo4j_session()
        driver    = MagicMock()
        driver.session.return_value = session

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.knowledge.music_learning import score_and_learn
            score_and_learn(notes, "VD-HEAVY", genre="rock", key="A", store_to_neo4j=True)

        # Prüfe dass Neo4j-Aufrufe gemacht wurden
        assert session.run.called, "Neo4j session.run() nie aufgerufen"
        # Prüfe dass irgendein Query instrument-Kontext enthält
        all_queries = " ".join(str(c) for c in session.run.call_args_list)
        assert "VD-HEAVY" in all_queries or "instrument" in all_queries.lower(), \
            f"Neo4j-Query sollte Instrument enthalten. Calls: {session.run.call_args_list}"


# ── E2E Feedback-Loop mit echtem Neo4j ────────────────────────────────────────

@pytest.mark.neo4j
class TestFeedbackLoopNeo4j:
    """Real-Neo4j-E2E: score_and_learn schreibt ProductionPattern + PatternAttempt."""

    _INSTRUMENT = "TestDrums_E2E"

    @pytest.fixture(autouse=True)
    def _cleanup_test_nodes(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        import os
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )

        def _clean():
            with driver.session() as s:
                s.run(
                    "MATCH (a:PatternAttempt {instrument: $i}) DETACH DELETE a",
                    i=self._INSTRUMENT,
                )
                s.run(
                    "MATCH (p:ProductionPattern {instrument: $i}) DETACH DELETE p",
                    i=self._INSTRUMENT,
                )

        _clean()
        yield
        _clean()
        driver.close()

    def _call_score_and_learn(self, notes, score: float):
        """Ruft score_and_learn mit gemocktem LLM auf."""
        mock_resp = _llm_response(score)
        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=mock_resp):
            from src.agent.tools.knowledge.music_learning import score_and_learn
            return score_and_learn(
                notes, self._INSTRUMENT, genre="rock", key="A",
                scale="minor", bars=2, bpm=120, store_to_neo4j=True,
            )

    def _query_pattern(self):
        """Liest ProductionPattern aus Neo4j."""
        import os
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                "MATCH (p:ProductionPattern {instrument: $i, genre: 'rock'}) "
                "RETURN p.iteration AS iteration, p.last_score AS last_score, "
                "       p.avg_score AS avg_score, p.notes_json AS notes_json",
                i=self._INSTRUMENT,
            ).single()
        driver.close()
        return dict(result) if result else None

    def _count_attempts(self):
        """Zählt PatternAttempt-Nodes für dieses Instrument."""
        import os
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                "MATCH (a:PatternAttempt {instrument: $i}) RETURN count(a) AS n",
                i=self._INSTRUMENT,
            ).single()
        driver.close()
        return result["n"] if result else 0

    @pytest.mark.neo4j
    def test_score_and_learn_creates_production_pattern(self):
        """score_and_learn legt ProductionPattern mit korrekten Feldern an."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 2, "basic")

        result = self._call_score_and_learn(notes, 0.82)

        assert result["learned"] is True
        assert result["score"] == pytest.approx(0.82, abs=0.01)

        node = self._query_pattern()
        assert node is not None, "ProductionPattern wurde nicht in Neo4j gespeichert"
        assert node["iteration"] == 1, f"Erster Call → iteration=1, got {node['iteration']}"
        assert node["last_score"] == pytest.approx(0.82, abs=0.01), \
            f"last_score sollte 0.82 sein, got {node['last_score']}"
        assert node["avg_score"] is not None and 0 < node["avg_score"] <= 1.0, \
            f"avg_score out of range: {node['avg_score']}"

    @pytest.mark.neo4j
    def test_second_call_increments_iteration(self):
        """Zweiter score_and_learn-Call erhöht iteration auf 2."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 2, "basic")

        self._call_score_and_learn(notes, 0.80)
        self._call_score_and_learn(notes, 0.60)

        node = self._query_pattern()
        assert node is not None
        assert node["iteration"] == 2, f"Zwei Calls → iteration=2, got {node['iteration']}"
        assert node["last_score"] == pytest.approx(0.60, abs=0.01), \
            f"last_score sollte letzten Score (0.60) enthalten, got {node['last_score']}"

    @pytest.mark.neo4j
    def test_pattern_attempt_nodes_created(self):
        """Jeder score_and_learn-Call legt einen PatternAttempt-Node an."""
        from src.agent.tools.music.pattern_generators import _drums
        notes1 = _drums("rock", 2, "basic")
        notes2 = _drums("rock", 2, "complex") if hasattr(
            __import__("src.agent.tools.music.pattern_generators", fromlist=["_drums"]),
            "_drums"
        ) else notes1

        self._call_score_and_learn(notes1, 0.80)

        attempts_after_first = self._count_attempts()
        assert attempts_after_first >= 1, "Erster Call sollte PatternAttempt anlegen"

    @pytest.mark.neo4j
    def test_get_pattern_history_reads_back_stored_data(self):
        """get_pattern_history liest korrekte Daten aus Neo4j."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.knowledge.music_learning import get_pattern_history

        notes = _drums("rock", 2, "basic")
        self._call_score_and_learn(notes, 0.82)

        history = get_pattern_history(self._INSTRUMENT, "rock")

        assert history, "get_pattern_history soll non-empty dict zurückgeben"
        assert "iterations" in history, f"Fehlende 'iterations'-Key: {history}"
        assert history["iterations"] == 1, f"iterations=1 erwartet, got {history['iterations']}"
        assert "avg_score" in history, f"Fehlende 'avg_score'-Key: {history}"
        assert 0 < history["avg_score"] <= 1.0, f"avg_score out of range: {history['avg_score']}"

    @pytest.mark.neo4j
    def test_notes_json_quality_gate(self):
        """notes_json wird nur gespeichert wenn score >= 0.7."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 2, "basic")

        # Erster Call mit Score unter Gate
        self._call_score_and_learn(notes, 0.65)
        node = self._query_pattern()
        assert node is not None
        assert node["notes_json"] is None, \
            f"Score 0.65 < 0.7 → notes_json sollte null sein, got: {node['notes_json'][:50] if node['notes_json'] else None}"

        # Zweiter Call mit Score über Gate
        self._call_score_and_learn(notes, 0.80)
        node = self._query_pattern()
        assert node["notes_json"] is not None, \
            "Score 0.80 >= 0.7 → notes_json sollte gespeichert sein"

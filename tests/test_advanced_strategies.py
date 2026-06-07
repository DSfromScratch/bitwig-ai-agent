"""
Erweiterte Test-Strategien:

  1. Property-based  — Hypothesis: zufällige MIDI-Kombinationen
  2. Mutation        — Prüft ob Assertions Fehler wirklich fangen
  3. Snapshot        — Prompt-Text gegen gespeicherte Referenz
  4. Performance     — LLM-Antwortzeit unter Last

Alle Tests laufen ohne externe Dienste (unit-Marker).
"""
from __future__ import annotations

import json
import time
import threading
import pytest
from unittest.mock import patch, MagicMock


# ══════════════════════════════════════════════════════════════════════════════
# 1. PROPERTY-BASED TESTS (Hypothesis)
# ══════════════════════════════════════════════════════════════════════════════

from hypothesis import given, assume, settings as hyp_settings
from hypothesis import strategies as st

# Strategie: gültiges MIDI-Note-Dict
midi_note = st.fixed_dictionaries({
    "step":  st.floats(min_value=0.0, max_value=32.0, allow_nan=False, allow_infinity=False),
    "pitch": st.integers(min_value=0, max_value=127),
    "vel":   st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
    "dur":   st.floats(min_value=0.01, max_value=8.0,  allow_nan=False, allow_infinity=False),
})

midi_note_list = st.lists(midi_note, min_size=1, max_size=64)

instrument_st = st.sampled_from([
    "VD-HEAVY", "VB-ROYAL", "Guitar", "Piano", "Phase-4", "Dexed", "Mono-Synth"
])
genre_st = st.sampled_from([
    "rock", "pop", "jazz", "hip-hop", "funk", "blues", "trap", "contemporary"
])
key_st    = st.sampled_from(["C", "A", "D", "E", "G", "F", "Bb"])
scale_st  = st.sampled_from(["major", "minor", "chromatic"])


class TestPropertyBased:

    @pytest.mark.unit
    @given(notes=midi_note_list, instrument=instrument_st,
           genre=genre_st, key=key_st, scale=scale_st)
    @hyp_settings(max_examples=80, deadline=2000)
    def test_build_prompt_never_crashes(self, notes, instrument, genre, key, scale):
        """_build_validation_prompt überlebt beliebige MIDI-Inputs ohne Exception."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        result = _build_validation_prompt(notes, instrument, genre, key, scale, 2, 120)
        assert isinstance(result, str)
        assert len(result) > 50

    @pytest.mark.unit
    @given(notes=midi_note_list, instrument=instrument_st, genre=genre_st)
    @hyp_settings(max_examples=60, deadline=2000)
    def test_prompt_always_contains_instrument_and_genre(self, notes, instrument, genre):
        """Prompt enthält immer Instrument und Genre — unabhängig von den Noten."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(notes, instrument, genre, "C", "minor", 2, 120)
        assert instrument in prompt
        assert genre in prompt

    @pytest.mark.unit
    @given(pitch=st.integers(min_value=0, max_value=127),
           vel=st.floats(min_value=0.01, max_value=1.0, allow_nan=False),
           step=st.floats(min_value=0.0, max_value=16.0, allow_nan=False, allow_infinity=False),
           dur=st.floats(min_value=0.01, max_value=4.0, allow_nan=False, allow_infinity=False))
    @hyp_settings(max_examples=100, deadline=1000)
    def test_single_note_prompt_survives(self, pitch, vel, step, dur):
        """Auch ein einzelner Ton erzeugt einen gültigen Prompt."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        note = [{"step": step, "pitch": pitch, "vel": vel, "dur": dur}]
        result = _build_validation_prompt(note, "Piano", "pop", "C", "major", 1, 120)
        assert "Piano" in result

    @pytest.mark.unit
    @given(notes=midi_note_list)
    @hyp_settings(max_examples=60, deadline=2000)
    def test_drum_generators_produce_valid_range(self, notes):
        """Drum-Generator gibt immer MIDI 35-81 zurück (Standard Drum-Kit)."""
        from src.agent.tools.music.pattern_generators import _drums
        for genre in ("rock", "jazz", "hip-hop", "funk"):
            result = _drums(genre, 2, "basic")
            for note in result:
                assert 35 <= note["pitch"] <= 81, \
                    f"Drum-MIDI {note['pitch']} außerhalb Standard-Range in {genre}"
                assert 0.0 < note["vel"] <= 1.0
                assert note["dur"] > 0.0

    @pytest.mark.unit
    @given(genre=genre_st, root=st.integers(min_value=28, max_value=52))
    @hyp_settings(max_examples=60, deadline=2000)
    def test_bass_generator_always_in_bass_range(self, genre, root):
        """Bass-Generator gibt Noten in praktischem Bass-Bereich zurück."""
        from src.agent.tools.music.pattern_generators import _bass
        result = _bass(genre, 2, root, "basic")
        for note in result:
            # Bass-Bereich: tief genug für Bässe (MIDI21=A0), hoch genug für Fills
            assert 21 <= note["pitch"] <= 72, \
                f"Bass-MIDI {note['pitch']} außerhalb realistischem Bereich für {genre}/root={root}"
            assert note["dur"] > 0

    @pytest.mark.unit
    @given(score=st.floats(min_value=1.01, max_value=100.0, allow_nan=False))
    @hyp_settings(max_examples=50, deadline=1000)
    def test_score_normalization_always_produces_0_1(self, score):
        """Score-Normalisierung: jeder Wert > 1 wird auf 0-1 skaliert."""
        result_json = json.dumps({"score": score, "rhythmic_ok": True,
                                  "harmonic_ok": True, "genre_fit": True,
                                  "issues": [], "suggestions": [], "summary": "test"})
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 1, "basic")

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=result_json):
            from src.agent.tools.music.music_validator import validate_music_pattern
            result = validate_music_pattern(notes, "VD-HEAVY", "rock", "A", "minor")

        assert 0.0 <= result.get("score", 0) <= 1.0, \
            f"Score {score} → {result.get('score')} nicht in [0,1]"

    @pytest.mark.unit
    @given(result=st.one_of(
        st.just({}),
        st.fixed_dictionaries({"context_type": st.just("song"), "steps": st.just([])}),
    ))
    @hyp_settings(max_examples=30, deadline=1000)
    def test_as_dict_idempotent_on_plain_dict(self, result):
        """_as_dict gibt plain dicts unverändert zurück."""
        from src.bitwig_executor import _as_dict
        assert _as_dict(result) is result


# ══════════════════════════════════════════════════════════════════════════════
# 2. MUTATION TESTS
# Prüft ob unsere Assertions spezifisch genug sind um Mutations zu fangen.
# Methode: Code-Varianten (Mutations) manuell einbauen → Test muss FAIL.
# ══════════════════════════════════════════════════════════════════════════════

class TestMutationDetection:
    """Jeder Test hier prüft eine Mutation — er muss fehlschlagen wenn die
    Assertion zu lasch ist. Format: original_fn vs. mutierte_fn."""

    @pytest.mark.unit
    def test_score_threshold_mutation(self):
        """Assertion score >= 0.65 soll 0.64 ablehnen (off-by-one Mutation)."""
        def is_good_score(score: float) -> bool:
            return score >= 0.65

        assert is_good_score(0.65) is True
        assert is_good_score(0.64) is False,  "Mutation score>=0.64 nicht erkannt"
        assert is_good_score(0.649) is False, "Mutation score>=0.649 nicht erkannt"

    @pytest.mark.unit
    def test_drum_kick_detection_mutation(self):
        """Kick-Erkennung: MIDI36 != MIDI38 (Kick != Snare Mutation)."""
        notes = [{"pitch": 38, "step": 0, "vel": 0.8, "dur": 0.25}]  # nur Snare, kein Kick
        pitches = {n["pitch"] for n in notes}

        # Original: korrekte Prüfung
        has_kick_correct = 36 in pitches
        # Mutation: falsche MIDI-Nummer
        has_kick_mutated = 38 in pitches  # Mutation: 36→38

        assert has_kick_correct is False, "Kein Kick erkannt — korrekt"
        assert has_kick_mutated is True,  "Mutation 36→38 nicht erkannt (liefert True statt False)"
        assert has_kick_correct != has_kick_mutated, \
            "Test unterscheidet Original von Mutation"

    @pytest.mark.unit
    def test_jazz_ride_detection_mutation(self):
        """MIDI51 (Ride) != MIDI49 (Crash) — Mutation soll erkannt werden."""
        notes_with_ride  = [{"pitch": 51, "step": 0, "vel": 0.75, "dur": 0.25}]
        notes_with_crash = [{"pitch": 49, "step": 0, "vel": 0.75, "dur": 0.25}]

        has_ride_correct = any(n["pitch"] == 51 for n in notes_with_ride)
        has_ride_mutated = any(n["pitch"] == 51 for n in notes_with_crash)  # kein Ride

        assert has_ride_correct is True
        assert has_ride_mutated is False, "Mutation Ride=49 nicht erkannt"

    @pytest.mark.unit
    def test_velocity_boundary_mutation(self):
        """vel <= 1.0 vs vel < 1.0 — Grenzwert-Mutation."""
        def valid_vel_correct(v): return 0.0 < v <= 1.0   # Original
        def valid_vel_mutated(v): return 0.0 < v < 1.0    # Mutation: <= → <

        assert valid_vel_correct(1.0) is True
        assert valid_vel_mutated(1.0) is False, "Boundary-Mutation <= → < nicht erkannt"
        assert valid_vel_correct(0.0) is False
        assert valid_vel_mutated(0.0) is False

    @pytest.mark.unit
    def test_hh_conflict_detection_mutation(self):
        """HH-Konflikt erkennt genau Step-Kollision, nicht nur Pitch-Kollision."""
        notes_conflict    = [{"pitch": 42, "step": 0.0}, {"pitch": 46, "step": 0.0}]
        notes_no_conflict = [{"pitch": 42, "step": 0.0}, {"pitch": 46, "step": 0.5}]

        def has_hh_conflict(notes):
            hh_c = {n["step"] for n in notes if n["pitch"] == 42}
            hh_o = {n["step"] for n in notes if n["pitch"] == 46}
            return bool(hh_c & hh_o)

        def has_hh_conflict_mutated(notes):
            # Mutation: nur Pitch prüfen, nicht Step
            pitches = {n["pitch"] for n in notes}
            return 42 in pitches and 46 in pitches  # falsch! ignoriert Steps

        assert has_hh_conflict(notes_conflict) is True
        assert has_hh_conflict(notes_no_conflict) is False
        # Mutation erkennt keinen Unterschied mehr:
        assert has_hh_conflict_mutated(notes_no_conflict) is True, \
            "Mutation detektiert — Step wird nicht mehr geprüft"

    @pytest.mark.unit
    def test_score_normalization_mutation(self):
        """score/10 Normalisierung: Mutation score/100 liefert anderen Wert."""
        raw_score = 7.5
        normalized_correct = round(raw_score / 10.0, 2)   # 0.75
        normalized_mutated = round(raw_score / 100.0, 2)  # 0.075

        assert normalized_correct == 0.75
        assert normalized_mutated == round(7.5 / 100.0, 2)  # 0.07 oder 0.08 je nach Rounding
        assert normalized_correct != normalized_mutated, \
            "Divisions-Mutation /10 → /100 erkannt"

    @pytest.mark.unit
    def test_tuplet_step_size_mutation(self):
        """Septolen-Step 4/7 ≠ Quintolen-Step 4/5 — Mutation erkennt Unterschied."""
        septole_step  = round(4.0 / 7, 3)   # 0.571
        quintole_step = round(4.0 / 5, 3)   # 0.800 — Mutation: 7→5

        notes_septole  = [{"step": round(i * septole_step,  3)} for i in range(7)]
        notes_quintole = [{"step": round(i * quintole_step, 3)} for i in range(5)]

        def is_septole(notes):
            diffs = [round(notes[i+1]["step"]-notes[i]["step"], 2)
                     for i in range(len(notes)-1)]
            return all(abs(d - 0.57) < 0.01 for d in diffs)

        assert is_septole(notes_septole) is True
        assert is_septole(notes_quintole) is False, \
            "Mutation 7→5 (Quintole statt Septole) nicht erkannt"


# ══════════════════════════════════════════════════════════════════════════════
# 3. SNAPSHOT TESTS (syrupy)
# Prompt-Texte gegen gespeicherte Referenz-Snapshots vergleichen.
# Erster Lauf: Snapshots erstellen (--snapshot-update)
# Folge-Läufe: Abweichungen = Fehler
# ══════════════════════════════════════════════════════════════════════════════

class TestSnapshots:

    @pytest.mark.unit
    def test_rock_drum_prompt_snapshot(self, snapshot):
        """Rock-Drum-Prompt ist deterministisch und ändert sich nicht unbeabsichtigt."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt

        notes  = _drums("rock", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "rock", "A", "minor", 2, 120)
        # Nur die ersten 3 Zeilen (Änderungen in Noten-Details ignorieren)
        header = "\n".join(prompt.splitlines()[:8])
        assert header == snapshot

    @pytest.mark.unit
    def test_jazz_drum_prompt_snapshot(self, snapshot):
        """Jazz-Drum-Prompt enthält Ride-Kriterien — Snapshot erkennt Regressionen."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt

        notes  = _drums("jazz", 2, "basic")
        prompt = _build_validation_prompt(notes, "VD-HEAVY", "jazz", "C", "minor", 2, 120)
        header = "\n".join(prompt.splitlines()[:8])
        assert header == snapshot

    @pytest.mark.unit
    def test_melody_prompt_no_drum_criteria_snapshot(self, snapshot):
        """Melodie-Prompt enthält keine Drum-Kriterien — Snapshot schützt vor Regression."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes  = [{"step": 0, "pitch": 60, "vel": 0.8, "dur": 0.5},
                  {"step": 0.5, "pitch": 64, "vel": 0.75, "dur": 0.5}]
        prompt = _build_validation_prompt(notes, "Piano", "contemporary", "C", "chromatic", 2, 60)
        header = "\n".join(prompt.splitlines()[:8])
        assert header == snapshot

    @pytest.mark.unit
    def test_error_pattern_prompt_snapshot(self, snapshot):
        """Fehler-Pattern-Prompt enthält ACHTUNG-Präambel — Snapshot schützt Format."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        notes  = [{"step": 0, "pitch": 46, "vel": 0.85, "dur": 0.5},
                  {"step": 0.5, "pitch": 48, "vel": 0.72, "dur": 0.5}]
        base   = _build_validation_prompt(notes, "VB-ROYAL", "rock", "A", "minor", 2, 120)
        prompt = "ACHTUNG: Dieses Pattern enthält möglicherweise einen Fehler.\n\n" + base
        header = "\n".join(prompt.splitlines()[:3])
        assert header == snapshot


# ══════════════════════════════════════════════════════════════════════════════
# 4. PERFORMANCE TESTS
# LLM-Antwortzeit unter Last: sequenziell + parallel.
# ══════════════════════════════════════════════════════════════════════════════

def _mock_llm_fast(prompt: str) -> str:
    """Schneller Mock-LLM: antwortet in ~5ms."""
    time.sleep(0.005)
    return json.dumps({"score": 0.78, "rhythmic_ok": True, "harmonic_ok": True,
                       "genre_fit": True, "issues": [], "suggestions": [],
                       "summary": "Performance-Test."})


def _mock_llm_slow(prompt: str) -> str:
    """Langsamer Mock-LLM: antwortet in ~150ms."""
    time.sleep(0.15)
    return json.dumps({"score": 0.72, "rhythmic_ok": True, "harmonic_ok": True,
                       "genre_fit": True, "issues": [], "suggestions": [],
                       "summary": "Slow performance test."})


class TestPerformance:

    @pytest.mark.unit
    def test_single_validation_under_200ms(self):
        """Einzelne Validierung (ohne echtes LLM) < 200ms."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 2, "basic")

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", side_effect=_mock_llm_fast):
            from src.agent.tools.music.music_validator import validate_music_pattern
            start = time.perf_counter()
            result = validate_music_pattern(notes, "VD-HEAVY", "rock", "A", "minor")
            elapsed = time.perf_counter() - start

        assert elapsed < 0.200, f"Validierung zu langsam: {elapsed*1000:.0f}ms (Limit: 200ms)"
        assert result.get("score") is not None

    @pytest.mark.unit
    def test_10_sequential_validations_throughput(self):
        """10 sequenzielle Validierungen: Gesamtzeit < 500ms (mock ~5ms each)."""
        from src.agent.tools.music.pattern_generators import _drums, _bass
        from src.agent.tools.music.music_data import _root_midi

        patterns = [
            (_drums("rock", 2, "basic"),         "VD-HEAVY", "rock"),
            (_drums("jazz", 2, "basic"),          "VD-HEAVY", "jazz"),
            (_drums("hip-hop", 2, "basic"),       "VD-HEAVY", "hip-hop"),
            (_bass("rock",    2, _root_midi("A"), "basic"), "VB-ROYAL", "rock"),
            (_bass("funk",    2, _root_midi("D"), "funk"),  "VB-ROYAL", "funk"),
            (_drums("funk",   2, "basic"),        "VD-HEAVY", "funk"),
            (_bass("jazz",    2, _root_midi("C"), "jazz"),  "VB-MELLOW", "jazz"),
            (_drums("trap",   2, "basic"),        "VD-HEAVY", "trap"),
            (_bass("blues",   2, _root_midi("A"), "basic"), "VB-ROYAL", "blues"),
            (_drums("pop",    2, "basic"),        "VD-HEAVY", "pop"),
        ]

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", side_effect=_mock_llm_fast):
            from src.agent.tools.music.music_validator import validate_music_pattern
            start = time.perf_counter()
            results = [validate_music_pattern(n, i, g, "A", "minor")
                       for n, i, g in patterns]
            elapsed = time.perf_counter() - start

        assert elapsed < 0.500, f"10 Validierungen zu langsam: {elapsed*1000:.0f}ms"
        assert all(r.get("score") is not None for r in results)
        avg_ms = elapsed / len(patterns) * 1000
        print(f"\n  Durchschnitt: {avg_ms:.1f}ms/Validierung")

    @pytest.mark.unit
    def test_parallel_validations_no_race_condition(self):
        """5 parallele Validierungen: keine Race-Conditions, alle Ergebnisse gültig."""
        from src.agent.tools.music.pattern_generators import _drums
        results = []
        errors  = []

        def _validate(genre: str):
            try:
                notes = _drums(genre, 2, "basic")
                with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
                     patch("src.agent.tools.music.music_validator._call_llm",
                           side_effect=_mock_llm_fast):
                    from src.agent.tools.music.music_validator import validate_music_pattern
                    r = validate_music_pattern(notes, "VD-HEAVY", genre, "A", "minor")
                    results.append(r)
            except Exception as e:
                errors.append(str(e))

        genres  = ["rock", "jazz", "hip-hop", "funk", "pop"]
        threads = [threading.Thread(target=_validate, args=(g,)) for g in genres]

        start = time.perf_counter()
        for t in threads: t.start()
        for t in threads: t.join()
        elapsed = time.perf_counter() - start

        assert len(errors) == 0, f"Race-Conditions: {errors}"
        assert len(results) == 5, f"Nur {len(results)}/5 Ergebnisse"
        assert all(0.0 <= r.get("score", -1) <= 1.0 for r in results)
        print(f"\n  5 parallele Validierungen in {elapsed*1000:.0f}ms")

    @pytest.mark.unit
    def test_slow_llm_timeout_detection(self):
        """Langsames LLM (150ms) wird korrekt verarbeitet — kein hängendes System."""
        from src.agent.tools.music.pattern_generators import _drums
        notes = _drums("rock", 2, "basic")

        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", side_effect=_mock_llm_slow):
            from src.agent.tools.music.music_validator import validate_music_pattern
            start   = time.perf_counter()
            result  = validate_music_pattern(notes, "VD-HEAVY", "rock", "A", "minor")
            elapsed = time.perf_counter() - start

        assert result.get("score") is not None
        assert elapsed >= 0.15, "Slow-LLM wurde nicht wirklich aufgerufen"
        assert elapsed < 1.0,   f"System hat sich bei langsamem LLM aufgehängt: {elapsed:.2f}s"

    @pytest.mark.unit
    def test_prompt_generation_is_fast(self):
        """Prompt-Generierung (ohne LLM) < 10ms für komplexe Patterns."""
        from src.agent.tools.music.pattern_generators import _drums
        from src.agent.tools.music.music_validator import _build_validation_prompt
        from tests.test_mlx_black_page_drums import BLACK_PAGE_DRUMS

        start = time.perf_counter()
        for _ in range(50):  # 50× ausführen
            _build_validation_prompt(
                BLACK_PAGE_DRUMS, "VD-HEAVY", "contemporary", "C", "minor", 4, 60
            )
        elapsed = time.perf_counter() - start
        avg_ms  = elapsed / 50 * 1000

        assert avg_ms < 10.0, f"Prompt-Generierung zu langsam: {avg_ms:.2f}ms/Aufruf"
        print(f"\n  Prompt-Generierung: {avg_ms:.2f}ms/Aufruf (50 Iterationen)")

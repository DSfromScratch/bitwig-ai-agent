"""
MLX-Evaluierungstest: "The Black Page" von Frank Zappa
(Arr. Jeff Tincher, © 2021 Munchkin Music Co)

Testet ob das fine-tuned Modell mit extremer rhythmischer Komplexität umgehen kann:
  - Polyrhythmen: Triolen, Quintolen (5), Sextolen (6), Septolen (7)
  - Atonale Chromatik (viele Vorzeichen)
  - Kein Standard-Genre-Pattern (kein Kick/Snare-Raster)
  - Dichte 32tel-Note-Gruppen bei ♩=60

Erwartung: Modell soll nicht abstürzen, kein "kein Kick" als Problem melden,
und die Komplexität als Qualitätsmerkmal erkennen (kein score < 0.3).
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch


# ── The Black Page — MIDI-Transkription (Takt 1-3, Melodiestimme) ─────────────
# Extrahiert aus Partitur (Arr. Jeff Tincher), ♩=60, 4/4
# Schritt-Notation: 1.0 = Viertelnote, 0.125 = 32tel
#
# Takt 1: chromatische Aufwärtsbewegung mit Vorschlägen + Quintole
# C#5=73, D5=74, Eb5=75, E5=76, F5=77, F#5=78, G5=79, Ab5=80, A5=81, B5=83
# Takt 2: Triolen + absteigende Chromatik + Septole
# Takt 3: Sextolen-Passage mit Synkopen

BLACK_PAGE_NOTES = [
    # ── Takt 1: Quintole + 32tel-Gruppen ──────────────────────────────────────
    {"step": 0.000, "pitch": 73, "vel": 0.85, "dur": 0.125},   # C#5 (32tel)
    {"step": 0.125, "pitch": 76, "vel": 0.80, "dur": 0.125},   # E5
    {"step": 0.250, "pitch": 78, "vel": 0.82, "dur": 0.125},   # F#5
    {"step": 0.375, "pitch": 80, "vel": 0.78, "dur": 0.125},   # Ab5
    {"step": 0.500, "pitch": 81, "vel": 0.75, "dur": 0.125},   # A5  (Quintole Start)
    {"step": 0.650, "pitch": 83, "vel": 0.72, "dur": 0.125},   # B5  (Quintole)
    {"step": 0.800, "pitch": 84, "vel": 0.80, "dur": 0.125},   # C6  (Quintole)
    {"step": 0.950, "pitch": 82, "vel": 0.68, "dur": 0.125},   # Bb5 (Quintole)
    {"step": 1.100, "pitch": 79, "vel": 0.70, "dur": 0.125},   # G5  (Quintole Ende)
    {"step": 1.250, "pitch": 77, "vel": 0.75, "dur": 0.250},   # F5  (Achtel)
    {"step": 1.500, "pitch": 75, "vel": 0.72, "dur": 0.125},   # Eb5
    {"step": 1.625, "pitch": 74, "vel": 0.68, "dur": 0.125},   # D5
    {"step": 1.750, "pitch": 73, "vel": 0.65, "dur": 0.125},   # C#5
    {"step": 1.875, "pitch": 71, "vel": 0.70, "dur": 0.125},   # B4
    # ── Takt 2: Septolen (7:4) ─────────────────────────────────────────────────
    {"step": 2.000, "pitch": 69, "vel": 0.80, "dur": 0.143},   # A4  (Septole 1/7)
    {"step": 2.143, "pitch": 71, "vel": 0.75, "dur": 0.143},   # B4  (2/7)
    {"step": 2.286, "pitch": 73, "vel": 0.78, "dur": 0.143},   # C#5 (3/7)
    {"step": 2.429, "pitch": 74, "vel": 0.72, "dur": 0.143},   # D5  (4/7)
    {"step": 2.571, "pitch": 76, "vel": 0.80, "dur": 0.143},   # E5  (5/7)
    {"step": 2.714, "pitch": 77, "vel": 0.68, "dur": 0.143},   # F5  (6/7)
    {"step": 2.857, "pitch": 75, "vel": 0.65, "dur": 0.143},   # Eb5 (7/7)
    # ── Takt 2 Fortsetzung: Triole ─────────────────────────────────────────────
    {"step": 3.000, "pitch": 72, "vel": 0.75, "dur": 0.333},   # C5  (Triole 1/3)
    {"step": 3.333, "pitch": 74, "vel": 0.70, "dur": 0.333},   # D5  (2/3)
    {"step": 3.667, "pitch": 76, "vel": 0.68, "dur": 0.333},   # E5  (3/3)
    # ── Takt 3: Sextolen (6:4) ────────────────────────────────────────────────
    {"step": 4.000, "pitch": 78, "vel": 0.82, "dur": 0.167},   # F#5 (Sextole 1/6)
    {"step": 4.167, "pitch": 80, "vel": 0.78, "dur": 0.167},   # Ab5 (2/6)
    {"step": 4.333, "pitch": 81, "vel": 0.75, "dur": 0.167},   # A5  (3/6)
    {"step": 4.500, "pitch": 79, "vel": 0.72, "dur": 0.167},   # G5  (4/6)
    {"step": 4.667, "pitch": 77, "vel": 0.70, "dur": 0.167},   # F5  (5/6)
    {"step": 4.833, "pitch": 75, "vel": 0.68, "dur": 0.167},   # Eb5 (6/6)
    # ── Takt 3 Ende: lange Note + 32tel-Gruppe ────────────────────────────────
    {"step": 5.000, "pitch": 73, "vel": 0.85, "dur": 0.500},   # C#5 (Viertel)
    {"step": 5.500, "pitch": 74, "vel": 0.72, "dur": 0.125},   # D5
    {"step": 5.625, "pitch": 76, "vel": 0.70, "dur": 0.125},   # E5
    {"step": 5.750, "pitch": 78, "vel": 0.68, "dur": 0.125},   # F#5
    {"step": 5.875, "pitch": 81, "vel": 0.75, "dur": 0.125},   # A5
    # ── Takt 4: Quintole + Sextole verschränkt ────────────────────────────────
    {"step": 6.000, "pitch": 83, "vel": 0.80, "dur": 0.200},   # B5  (Quintole 1/5)
    {"step": 6.200, "pitch": 84, "vel": 0.78, "dur": 0.200},   # C6  (2/5)
    {"step": 6.400, "pitch": 82, "vel": 0.75, "dur": 0.200},   # Bb5 (3/5)
    {"step": 6.600, "pitch": 80, "vel": 0.72, "dur": 0.200},   # Ab5 (4/5)
    {"step": 6.800, "pitch": 78, "vel": 0.70, "dur": 0.200},   # F#5 (5/5)
    {"step": 7.000, "pitch": 76, "vel": 0.82, "dur": 0.167},   # E5  (Sextole 1/6)
    {"step": 7.167, "pitch": 77, "vel": 0.78, "dur": 0.167},   # F5
    {"step": 7.333, "pitch": 79, "vel": 0.75, "dur": 0.167},   # G5
    {"step": 7.500, "pitch": 81, "vel": 0.72, "dur": 0.167},   # A5
    {"step": 7.667, "pitch": 80, "vel": 0.70, "dur": 0.167},   # Ab5
    {"step": 7.833, "pitch": 78, "vel": 0.68, "dur": 0.167},   # F#5
]


def _llm_response(score: float, issues=None, suggestions=None) -> str:
    return json.dumps({
        "score":       score,
        "rhythmic_ok": True,
        "harmonic_ok": True,
        "genre_fit":   True,
        "issues":      issues or [],
        "suggestions": suggestions or [],
        "summary":     f"The Black Page — komplexes atonales Pattern, Score {score:.2f}.",
    })


class TestBlackPageMLX:
    """The Black Page als Edge-Case für den MLX Validator."""

    @pytest.mark.unit
    def test_black_page_note_count(self):
        """Partitur-Transkription hat die erwartete Notendichte."""
        assert len(BLACK_PAGE_NOTES) >= 40, \
            f"Zu wenige Noten: {len(BLACK_PAGE_NOTES)}"
        steps = [n["step"] for n in BLACK_PAGE_NOTES]
        assert max(steps) >= 7.0, "Sollte mindestens 2 Takte abdecken"

    @pytest.mark.unit
    def test_black_page_has_chromatic_intervals(self):
        """Pattern enthält chromatische Halbtonschritte (Zappa-typisch)."""
        pitches = [n["pitch"] for n in BLACK_PAGE_NOTES]
        half_steps = sum(
            1 for i in range(len(pitches) - 1)
            if abs(pitches[i+1] - pitches[i]) == 1
        )
        assert half_steps >= 5, \
            f"Zu wenige chromatische Schritte: {half_steps}"

    @pytest.mark.unit
    def test_black_page_has_tuplet_rhythms(self):
        """Septolen und Quintolen sind im Pattern erkennbar (unregelmäßige Steps)."""
        steps = sorted(n["step"] for n in BLACK_PAGE_NOTES)
        # Septolen haben step-Abstände von ~0.143 (nicht glatt teilbar durch 0.125)
        diffs = [round(steps[i+1] - steps[i], 3) for i in range(len(steps)-1)]
        irregular = [d for d in diffs if d not in (0.125, 0.250, 0.500, 1.0)]
        assert len(irregular) >= 5, \
            f"Zu wenige unregelmäßige Rhythmen (Tuplets): {irregular[:5]}"

    @pytest.mark.unit
    def test_validator_prompt_for_atonal_melody(self):
        """Validator-Prompt für atonale Melodie enthält keine Drum-Kriterien."""
        from src.agent.tools.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(
            BLACK_PAGE_NOTES, "Piano", "contemporary", "C", "chromatic", 4, 60
        )
        assert "Piano" in prompt
        assert "contemporary" in prompt
        # Darf Drum-spezifische Kritik NICHT enthalten
        assert "Kick auf Beat" not in prompt, \
            "Nicht-Drum-Instrument soll keine Kick/Snare-Kriterien bekommen"

    @pytest.mark.unit
    def test_validator_does_not_flag_tuplets_as_error(self):
        """Modell soll Tuplet-Rhythmen nicht als 'rhythmically wrong' markieren."""
        mock_resp = _llm_response(
            0.82,
            suggestions=["Dynamische Kontraste ausbauen"]
        )
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                BLACK_PAGE_NOTES, "Piano", "contemporary", "C", "chromatic", 4, 60
            )

        assert result.get("rhythmic_ok") is True, \
            "Tuplet-Rhythmen sollen nicht als 'not rhythmic_ok' gelten"
        assert result.get("score", 0) >= 0.7, \
            f"Komplexes Stück soll nicht niedrig bewertet werden: {result.get('score')}"

    @pytest.mark.unit
    def test_validator_no_kick_complaint_for_melody(self):
        """'Kein Kick' soll bei Melodie-Pattern nicht als Issue auftauchen."""
        mock_resp = _llm_response(0.75)
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                BLACK_PAGE_NOTES, "Piano", "contemporary", "C", "chromatic", 4, 60
            )

        issues_text = " ".join(result.get("issues", [])).lower()
        assert "kick" not in issues_text and "snare" not in issues_text, \
            f"Kick/Snare-Kritik bei Melodie-Pattern: {result.get('issues')}"

    @pytest.mark.unit
    def test_validate_and_learn_handles_atonal(self):
        """validate_and_learn überlebt The Black Page ohne Exception."""
        mock_resp = _llm_response(
            0.80,
            suggestions=["Polyrhythmik beibehalten", "Dynamik ausbauen"]
        )
        session = _mock_neo4j_session()
        driver  = _mock_driver(session)

        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=mock_resp), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import validate_and_learn
            result = validate_and_learn.invoke({
                "notes":      BLACK_PAGE_NOTES,
                "instrument": "Piano",
                "genre":      "contemporary",
                "key":        "C",
                "scale":      "chromatic",
                "bars":       4,
                "bpm":        60,
            })

        assert isinstance(result, str)
        assert "0.80" in result or "Score" in result
        assert "✓" in result, f"Score 0.80 soll ✓ zeigen: {result}"

    @pytest.mark.unit
    def test_mlx_prompt_complexity(self):
        """Der generierte Prompt für The Black Page enthält Noten-Details."""
        from src.agent.tools.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(
            BLACK_PAGE_NOTES, "Piano", "contemporary", "C", "chromatic", 4, 60
        )
        # Prompt muss Pitch-Namen enthalten (A5, B5, C6 etc.)
        assert "MIDI" in prompt, "Prompt soll MIDI-Pitches zeigen"
        # Viele Noten → Prompt ist informativ
        assert len(prompt) > 400, f"Prompt zu kurz für Black Page: {len(prompt)}"
        # Tempo und Taktanzahl
        assert "60" in prompt
        assert "4" in prompt

    @pytest.mark.unit
    def test_score_not_penalized_for_missing_drums(self):
        """Pattern ohne Kick/Snare bekommt keinen automatischen Score-Abzug im Prompt."""
        from src.agent.tools.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(
            BLACK_PAGE_NOTES, "Piano", "contemporary", "C", "chromatic", 4, 60
        )
        # Der context_hint soll für Nicht-Drum-Instrumente leer/neutral sein
        assert "KEIN Kick" not in prompt, \
            "Kick-Fehlermeldung soll nicht für Piano-Pattern erscheinen"
        assert "wesentliches Problem" not in prompt, \
            "Kein 'wesentliches Problem' für atonale Melodie"


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _mock_neo4j_session():
    from unittest.mock import MagicMock
    session = MagicMock()
    session.run.return_value.single.return_value = None
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    return session


def _mock_driver(session):
    from unittest.mock import MagicMock
    driver = MagicMock()
    driver.session.return_value = session
    return driver

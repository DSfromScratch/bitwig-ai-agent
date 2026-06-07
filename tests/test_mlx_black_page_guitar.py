"""
MLX-Test: "Black Page" — Gitarren-TAB Version
(Arr. ContemporaryArtLaboratory, © 2021 MUNCHKIN MUSIC CO)

TAB-Konversion nach MIDI (Standard-Stimmung):
  String 1 (E4=64): Fret n → MIDI 64+n
  String 2 (B3=59): Fret n → MIDI 59+n
  String 3 (G3=55): Fret n → MIDI 55+n
  String 4 (D3=50): Fret n → MIDI 50+n
  String 5 (A2=45): Fret n → MIDI 45+n
  String 6 (E2=40): Fret n → MIDI 40+n

Gitarren-spezifische Herausforderungen:
  - Rasgueado: Rapid-Fire Sextolen auf einzelner Saite (Takt 6-7)
  - Chromatische Läufe über mehrere Saiten (Takt 1-3)
  - Septolen (7:4) in Takt 4-5
  - Kein Kick/Snare — darf nicht als Drum-Pattern behandelt werden
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock


# ── TAB → MIDI Hilfsfunktion ──────────────────────────────────────────────────

_OPEN = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}  # Standard-Stimmung

def tab(string: int, fret: int) -> int:
    """Konvertiert Gitarren-TAB (String 1-6, Fret 0-22) zu MIDI-Pitch."""
    return _OPEN[string] + fret


# ── Takt 1: Chromatischer Melodielauf (aus TAB gelesen) ──────────────────────
# String 1+2 oben, String 3+5 unten — dichte 32tel bei ♩=60

MEASURE_1 = [
    # String 1 (E4), Frets: 2,2,4
    {"step": 0.000, "pitch": tab(1,2),  "vel": 0.88, "dur": 0.125},  # F#4=66
    {"step": 0.125, "pitch": tab(1,2),  "vel": 0.82, "dur": 0.125},  # F#4=66
    {"step": 0.250, "pitch": tab(1,4),  "vel": 0.85, "dur": 0.125},  # Ab4=68
    # String 2 (B3), Fret: 4 → Eb4=63
    {"step": 0.375, "pitch": tab(2,4),  "vel": 0.80, "dur": 0.125},  # Eb4=63
    # String 3 (G3), Frets: 5,5,8 → C4=60, C4=60, Eb4=63
    {"step": 0.500, "pitch": tab(3,5),  "vel": 0.78, "dur": 0.125},  # C4=60
    {"step": 0.625, "pitch": tab(3,5),  "vel": 0.75, "dur": 0.125},  # C4=60
    {"step": 0.750, "pitch": tab(3,8),  "vel": 0.82, "dur": 0.125},  # Eb4=63
    # Triole: String 3, Frets 8,5 + String 2 Fret 8 → Eb4,C4,D4
    {"step": 0.875, "pitch": tab(3,5),  "vel": 0.72, "dur": 0.167},  # C4=60  (Triole 1/3)
    {"step": 1.042, "pitch": tab(2,8),  "vel": 0.78, "dur": 0.167},  # G4=67  (Triole 2/3)
    {"step": 1.208, "pitch": tab(3,7),  "vel": 0.70, "dur": 0.167},  # D4=62  (Triole 3/3)
    # String 3, Frets: 8,6,10 → Eb4=63, C#4=61, F4=65
    {"step": 1.375, "pitch": tab(3,8),  "vel": 0.80, "dur": 0.125},  # Eb4=63
    {"step": 1.500, "pitch": tab(3,6),  "vel": 0.75, "dur": 0.125},  # C#4=61
    {"step": 1.625, "pitch": tab(3,10), "vel": 0.82, "dur": 0.125},  # F4=65
    # Quintole: String 2+3, 9,7 / 8,8,5 → Fis4=66,D4=62,Eb4=63,Eb4=63,C4=60
    {"step": 1.750, "pitch": tab(2,7),  "vel": 0.72, "dur": 0.200},  # F#4=66 (Quintole 1/5)
    {"step": 1.950, "pitch": tab(3,7),  "vel": 0.70, "dur": 0.200},  # D4=62  (2/5)
    {"step": 2.150, "pitch": tab(2,8),  "vel": 0.78, "dur": 0.200},  # G4=67  (3/5)
    {"step": 2.350, "pitch": tab(3,8),  "vel": 0.75, "dur": 0.200},  # Eb4=63 (4/5)
    {"step": 2.550, "pitch": tab(3,5),  "vel": 0.68, "dur": 0.200},  # C4=60  (5/5)
    # String 5 (A2), Frets: 3,3 → C3=48 (Bass-Linie)
    {"step": 0.000, "pitch": tab(5,3),  "vel": 0.65, "dur": 0.500},  # C3=48
    {"step": 0.500, "pitch": tab(5,3),  "vel": 0.60, "dur": 0.500},  # C3=48
]

# ── Takt 4-5: Septolen (7:4) ─────────────────────────────────────────────────
# String 3+5, aus TAB: 5,8 / 5,5,6,5 / 5,5,7,7 / 7,5,6 / 8-7
# Septolen-Step = 4.0 / 7 ≈ 0.571 pro Gruppe

MEASURE_4_5 = [
    # Septole 1 (Takt 4, Beat 1-2): String 3, Frets 5,5,6,5,5,6,5
    {"step": 4.000, "pitch": tab(3,5),  "vel": 0.80, "dur": 0.143},  # C4=60  (1/7)
    {"step": 4.143, "pitch": tab(3,5),  "vel": 0.78, "dur": 0.143},  # C4=60  (2/7)
    {"step": 4.286, "pitch": tab(3,6),  "vel": 0.82, "dur": 0.143},  # C#4=61 (3/7)
    {"step": 4.429, "pitch": tab(3,5),  "vel": 0.75, "dur": 0.143},  # C4=60  (4/7)
    {"step": 4.571, "pitch": tab(3,5),  "vel": 0.78, "dur": 0.143},  # C4=60  (5/7)
    {"step": 4.714, "pitch": tab(3,6),  "vel": 0.72, "dur": 0.143},  # C#4=61 (6/7)
    {"step": 4.857, "pitch": tab(3,5),  "vel": 0.70, "dur": 0.143},  # C4=60  (7/7)
    # Septole 2 (Takt 5, Beat 1-2): String 5, Frets 5,7,5,7,5,6,5
    {"step": 5.000, "pitch": tab(5,5),  "vel": 0.82, "dur": 0.143},  # D3=50  (1/7)
    {"step": 5.143, "pitch": tab(5,7),  "vel": 0.80, "dur": 0.143},  # E3=52  (2/7)
    {"step": 5.286, "pitch": tab(5,5),  "vel": 0.78, "dur": 0.143},  # D3=50  (3/7)
    {"step": 5.429, "pitch": tab(5,7),  "vel": 0.75, "dur": 0.143},  # E3=52  (4/7)
    {"step": 5.571, "pitch": tab(5,5),  "vel": 0.72, "dur": 0.143},  # D3=50  (5/7)
    {"step": 5.714, "pitch": tab(5,6),  "vel": 0.70, "dur": 0.143},  # Eb3=51 (6/7)
    {"step": 5.857, "pitch": tab(5,5),  "vel": 0.68, "dur": 0.143},  # D3=50  (7/7)
    # String 6 (E2), Fret 6 → Bb2=46 (Bordun-Bass)
    {"step": 4.000, "pitch": tab(6,6),  "vel": 0.60, "dur": 1.000},  # Bb2=46
    {"step": 5.000, "pitch": tab(6,6),  "vel": 0.58, "dur": 1.000},  # Bb2=46
]

# ── Takt 6-7: Rasgueado — Sextolen-Tremolo ───────────────────────────────────
# String 5 Fret 7 = E3=52 (16×), dann String 4 Fret 10 = C4=60 (16×)
# Sextolen-Step = 4.0 / 6 ≈ 0.167 pro Note, Takt 6 = steps 20-24

def _rasgueado(string: int, fret: int, start: float, count: int,
               step_size: float = 0.167) -> list[dict]:
    """Generiert Rasgueado-Pattern (rapid repeated notes)."""
    return [
        {"step": round(start + i * step_size, 3),
         "pitch": tab(string, fret),
         "vel":   0.85 - (i % 6) * 0.03,   # leichte Velocity-Variation
         "dur":   step_size * 0.9}
        for i in range(count)
    ]

MEASURE_6_7 = (
    # Takt 6: String 5 Fret 7 = E3=52, 2×6 = 12 Noten (Sextolen)
    _rasgueado(5, 7, start=20.0, count=12, step_size=0.167) +
    # Takt 6 Mitte: String 4 Fret 10 = C4=60, 12 Noten
    _rasgueado(4, 10, start=22.0, count=12, step_size=0.167) +
    # Takt 7: String 5 Fret 7 = E3, dann Fret 6=Eb3=51, dann 5=D3=50
    _rasgueado(5, 7, start=24.0, count=6,  step_size=0.167) +
    _rasgueado(4, 6, start=25.0, count=6,  step_size=0.167) +
    _rasgueado(4, 5, start=26.0, count=6,  step_size=0.167) +
    # Bass-Bordun String 6 Fret 3 = G2=43
    [{"step": 20.0, "pitch": tab(6,3), "vel": 0.55, "dur": 4.0},
     {"step": 24.0, "pitch": tab(6,3), "vel": 0.55, "dur": 4.0}]
)

# Vollständiges Pattern
BLACK_PAGE_GUITAR = MEASURE_1 + MEASURE_4_5 + MEASURE_6_7


def _llm_ok(score: float = 0.82) -> str:
    return json.dumps({
        "score": score, "rhythmic_ok": True, "harmonic_ok": True,
        "genre_fit": True, "issues": [], "suggestions": ["Vibrato ausbauen"],
        "summary": f"Komplexes Gitarren-Pattern, Score {score:.2f}.",
    })


def _mock_neo4j():
    session = MagicMock()
    session.run.return_value.single.return_value = None
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    driver = MagicMock()
    driver.session.return_value = session
    return driver, session


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBlackPageGuitar:

    @pytest.mark.unit
    def test_tab_to_midi_conversion(self):
        """TAB-Konverter gibt korrekte MIDI-Pitches zurück."""
        assert tab(1, 0)  == 64   # E4 open
        assert tab(1, 2)  == 66   # F#4
        assert tab(3, 5)  == 60   # C4 (3rd string, 5th fret)
        assert tab(3, 10) == 65   # F4
        assert tab(5, 7)  == 52   # E3
        assert tab(4, 10) == 60   # C4
        assert tab(6, 3)  == 43   # G2

    @pytest.mark.unit
    def test_rasgueado_has_dense_notes(self):
        """Rasgueado-Pattern hat gleichmäßige dichte 32tel-ähnliche Abstände."""
        ras = _rasgueado(5, 7, start=0.0, count=12, step_size=0.167)
        assert len(ras) == 12
        steps = [n["step"] for n in ras]
        diffs = [round(steps[i+1] - steps[i], 2) for i in range(len(steps)-1)]
        assert all(abs(d - 0.17) < 0.01 for d in diffs), \
            f"Rasgueado-Steps ungleichmäßig: {diffs}"

    @pytest.mark.unit
    def test_rasgueado_velocity_variation(self):
        """Rasgueado hat leichte Velocity-Variation (realistisch)."""
        ras = _rasgueado(5, 7, start=0.0, count=6)
        vels = [n["vel"] for n in ras]
        assert max(vels) > min(vels), "Rasgueado braucht Velocity-Variation"
        assert max(vels) <= 0.90

    @pytest.mark.unit
    def test_septole_irregular_steps(self):
        """Septolen haben nicht-ganzzahlige Steps (~0.143)."""
        sept_steps = sorted(n["step"] for n in MEASURE_4_5
                            if 4.0 <= n["step"] < 5.0 and n["pitch"] != tab(6,6))
        diffs = [round(sept_steps[i+1]-sept_steps[i], 3)
                 for i in range(len(sept_steps)-1)]
        assert any(abs(d - 0.143) < 0.005 for d in diffs), \
            f"Keine Septolen-Steps gefunden: {diffs}"

    @pytest.mark.unit
    def test_full_guitar_note_range(self):
        """Pattern nutzt typischen Gitarren-MIDI-Bereich (40-80)."""
        pitches = [n["pitch"] for n in BLACK_PAGE_GUITAR]
        assert min(pitches) >= 40, f"Zu tief für Gitarre: {min(pitches)}"
        assert max(pitches) <= 80, f"Zu hoch für Gitarre: {max(pitches)}"
        span = max(pitches) - min(pitches)
        assert span >= 20, f"Zu kleiner Tonumfang: {span} Halbtonschritte"

    @pytest.mark.unit
    def test_guitar_prompt_no_drum_criteria(self):
        """Validator-Prompt für Gitarren-Pattern enthält keine Drum-Kriterien."""
        from src.agent.tools.music.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(
            BLACK_PAGE_GUITAR[:20], "Guitar", "contemporary", "C", "chromatic", 2, 60
        )
        assert "Kick auf Beat" not in prompt
        assert "KEIN Kick" not in prompt
        assert "Guitar" in prompt

    @pytest.mark.unit
    def test_rasgueado_not_flagged_as_error(self):
        """Rasgueado (rapid repeated notes) soll nicht als 'Issue' markiert werden."""
        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=_llm_ok(0.80)):
            from src.agent.tools.music.music_validator import validate_music_pattern
            result = validate_music_pattern(
                MEASURE_6_7, "Guitar", "contemporary", "C", "chromatic", 2, 60
            )
        assert result.get("score", 0) >= 0.70
        issues = " ".join(result.get("issues", [])).lower()
        assert "repeated" not in issues and "gleich" not in issues

    @pytest.mark.unit
    def test_full_black_page_guitar_validate_and_learn(self):
        """Vollständiges Gitarren-Pattern durchläuft validate_and_learn ohne Absturz."""
        driver, session = _mock_neo4j()
        with patch("src.agent.tools.music.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music.music_validator._call_llm", return_value=_llm_ok(0.85)), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.knowledge.music_learning import validate_and_learn
            result = validate_and_learn.invoke({
                "notes":      BLACK_PAGE_GUITAR,
                "instrument": "Guitar",
                "genre":      "contemporary",
                "key":        "C",
                "scale":      "chromatic",
                "bars":       8,
                "bpm":        60,
            })
        assert "✓" in result
        assert "0.85" in result
        assert session.run.called

    @pytest.mark.unit
    def test_guitar_vs_piano_different_range(self):
        """Gitarren-Version (tiefer) vs Piano-Version (höher) haben unterschiedliche Bereiche."""
        from tests.test_mlx_black_page import BLACK_PAGE_NOTES as PIANO_NOTES
        guitar_pitches = [n["pitch"] for n in BLACK_PAGE_GUITAR]
        piano_pitches  = [n["pitch"] for n in PIANO_NOTES]
        assert min(guitar_pitches) < min(piano_pitches), \
            "Gitarren-Version soll tiefere Noten haben (Bass-Strings)"
        assert max(piano_pitches) > max(guitar_pitches), \
            "Piano-Version soll höhere Noten haben (obere Oktaven)"

    @pytest.mark.unit
    def test_measure_6_rasgueado_single_pitch_repeated(self):
        """Takt 6 Rasgueado: dieselbe Note viele Male kurz hintereinander."""
        ras_e3 = [n for n in MEASURE_6_7
                  if n["pitch"] == tab(5,7) and 20.0 <= n["step"] < 22.0]
        assert len(ras_e3) >= 10, \
            f"Takt 6 Rasgueado E3: nur {len(ras_e3)} Noten (erwartet ≥ 10)"
        assert all(n["dur"] < 0.20 for n in ras_e3), \
            "Rasgueado-Noten müssen kurz sein (< 0.20 beats)"

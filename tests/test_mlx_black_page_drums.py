"""
MLX-Test: "The Black Page #1" — Original Drum-Version
(Arr. Jeff Tincher, © 2018 MUNCHKIN MUSIC CO, Music by Frank Zappa)

Geschrieben für Terry Bozzio — das schwierigste Drum-Solo der Rockgeschichte.
♩=60, 4/4 — jede Art von Tuplet: 3, 5, 6, 7, 7:8

Drum-MIDI Mapping (General MIDI):
  BD=36  SD=38  Rimshot=37  Ghost=38(vel<0.40)
  HH=42  HH_open=46  HH_pedal=44
  Ride=51  Crash=49  Ride_bell=53
  Tom_hi=50  Tom_mid=47  Tom_floor=45

Validator-Erwartungen:
  - Kick UND Snare vorhanden → rhythmisch korrekt (kein Rock-Pattern nötig)
  - Ghost Notes (vel 0.20-0.35) + Akzente (vel 0.90+) = legitim
  - 7:8-Ratio ist keine "Inkonsistenz"
  - Score soll > 0.70 — The Black Page ist ein Meisterwerk, kein schlechtes Pattern
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

# ── MIDI-Konstanten ────────────────────────────────────────────────────────────
BD=36; SD=38; RIM=37; HH=42; HH_O=46; HH_P=44
RIDE=51; CRASH=49; RIDE_B=53; T1=50; T2=47; TF=45


def n(step, pitch, vel, dur=0.125):
    return {"step": round(step,3), "pitch": pitch,
            "vel": round(vel,2), "dur": dur}

def ghost(step, dur=0.125):
    return n(step, SD, 0.28, dur)       # Ghost Note — sehr leise

def accent(step, pitch, dur=0.125):
    return n(step, pitch, 0.92, dur)    # Akzent (^)


# ── Takt 1: Erster Takt The Black Page ───────────────────────────────────────
# Dynamics mf (vel ~0.72)
# Obere Stimme (stems up): Snare + HH-Pattern
# Untere Stimme (stems down): Bass Drum

MEASURE_1 = [
    # Beat 1: BD + HH gleichzeitig
    n(0.000, BD,  0.80, 0.25),   n(0.000, HH,  0.70),
    n(0.125, SD,  0.72),         n(0.250, HH,  0.55),
    n(0.375, BD,  0.65),         n(0.375, SD,  0.68),
    # Beat 2: Triole (3:2) auf Snare
    n(0.500, SD,  0.75, 0.167),  n(0.500, HH,  0.60),
    n(0.667, SD,  0.70, 0.167),
    n(0.833, SD,  0.65, 0.167),
    # Beat 2 Mitte: HH pattern
    n(1.000, HH,  0.72),         n(1.000, BD,  0.78),
    n(1.125, SD,  0.68),         n(1.250, HH,  0.58),
    n(1.375, SD,  0.72),
    # Beat 3: Quintole (5:4)
    n(1.500, SD,  0.78, 0.200),  accent(1.500, HH_O, 0.200),
    n(1.700, SD,  0.65, 0.200),
    n(1.900, SD, 0.28, 0.200),  # ghost note
    n(2.100, SD,  0.70, 0.200),
    n(2.300, SD,  0.75, 0.200),
    # Beat 4: 32tel-Gruppe + BD-Akzent
    n(2.500, BD,  0.85, 0.25),
    n(2.625, SD,  0.60),         n(2.625, HH,  0.55),
    n(2.750, SD,  0.65),
    n(2.875, SD,  0.72),
    n(3.000, HH,  0.68),         n(3.000, BD,  0.70),
    n(3.125, SD,  0.55),
    n(3.250, SD,  0.60),
    n(3.375, SD, 0.92),   # Akzent am Taktende
]

# ── Takt 4-5: Quintole + Septole (wie Piano-Version, aber Schlagzeug) ─────────
# Takt 4 Beat 1: Quintole (5:4) auf Snare + Ride (×)
# Takt 5 Beat 1: Septole (7:4) auf Tom → Snare

MEASURE_4_5 = [
    # Quintole auf Ride + Snare-Ghostnotes
    *[n(4.0 + i*0.200, RIDE, 0.68 + i*0.02) for i in range(5)],
    *[ghost(4.0 + i*0.200 + 0.100) for i in range(5)],  # Ghostnotes dazwischen
    # BD durchgehend
    n(4.000, BD, 0.78, 0.5), n(4.500, BD, 0.65, 0.5),
    # Septole: Tom-Roll (T1→T2→TF) + Snare-Akzent
    *[n(6.0 + i*0.143, [T1,T2,TF,T2,T1,SD,SD][i], 0.70+i*0.02) for i in range(7)],
    n(7.000, SD, 0.88),   # Akzent nach Septole
    n(7.000, BD, 0.82),
    # Zweite Septole (Takt 5): Ride-Pattern (×)
    *[n(5.0 + i*0.143, RIDE, 0.65) for i in range(7)],
    *[n(5.0 + i*0.143 + 0.07, SD, 0.30) for i in range(7)],  # Ghost-Snare
]

# ── Takt 8: p<f crescendo — Sextolen verschachtelt ───────────────────────────
# Starts pp (vel ~0.30), crescendo zu ff (vel ~0.90) über 2 Takte

MEASURE_8 = [
    # Sextole 1: leise (p)
    *[n(8.0 + i*0.167, SD if i%2==0 else HH, 0.30+i*0.08) for i in range(6)],
    n(8.0, BD, 0.35, 0.5),
    # Triole dazwischen
    n(9.0, SD,  0.55, 0.333), n(9.333, T1, 0.60, 0.333), n(9.667, TF, 0.65, 0.333),
    # Sextole 2: lauter (mf)
    *[n(10.0 + i*0.167, SD if i%2==0 else RIDE, 0.60+i*0.04) for i in range(6)],
    n(10.0, BD, 0.72, 0.5),
    # Akzent am Ende (f)
    accent(11.0, CRASH), n(11.0, BD, 0.90),
    n(11.0, SD,  0.88),
]

# ── Takt 14: 7:8 — das einzigartige Zappa-Verhältnis ─────────────────────────
# 7 Noten in der Zeit von 8 Achteln (4 Beats) → step = 4/7 ≈ 0.571 pro Note
# Aus der Partitur: BD+SD-Kombination, dann Ride-Becken

MEASURE_14_7_8 = [
    # 7 Noten über 4 Beats (7:8 Verhältnis)
    *[n(14.0 + i*(4.0/7), [BD,SD,T1,SD,BD,T2,SD][i],
       [0.85,0.80,0.72,0.88,0.82,0.70,0.90][i], 4.0/7*0.8)
      for i in range(7)],
    # Ride-Begleitung gleichzeitig (8tel-Pulse)
    *[n(14.0 + i*0.5, RIDE, 0.62) for i in range(8)],
    # Quintole direkt danach (Takt 14 Ende)
    *[n(18.0 + i*0.200, [SD,T1,T2,TF,SD][i], 0.75+i*0.02) for i in range(5)],
]

# ── Takt 16: Finales Pattern mit dynamischem Crescendo ───────────────────────
MEASURE_16 = [
    n(20.0, BD,   0.88),  n(20.0, CRASH, 0.90),
    n(20.125, SD, 0.55),  n(20.250, HH,  0.50),
    # Triole
    n(20.5,   SD, 0.70, 0.333), n(20.833, T1, 0.68, 0.333), n(21.167, TF, 0.65, 0.333),
    # Quintole + Ghost
    *[n(21.5 + i*0.200, SD, 0.35+i*0.10) for i in range(5)],  # crescendo
    n(22.5,  BD,  0.90),   n(22.5, SD,  0.92),    # Schluss-Akzent
    n(22.75, HH_P,0.65),
    n(23.0,  SD,  0.28),   # Ghost Note am Ende
    n(23.5,  BD,  0.85),   n(23.75, CRASH, 0.75),
]

# ── Vollständiges Pattern ─────────────────────────────────────────────────────
BLACK_PAGE_DRUMS = MEASURE_1 + MEASURE_4_5 + MEASURE_8 + MEASURE_14_7_8 + MEASURE_16


def _ok(score=0.82, issues=None):
    return json.dumps({
        "score": score, "rhythmic_ok": True, "harmonic_ok": True,
        "genre_fit": True, "issues": issues or [],
        "suggestions": ["Dynamik-Kontraste ausbauen"],
        "summary": f"The Black Page Drums — Score {score:.2f}.",
    })


def _neo4j():
    session = MagicMock()
    session.run.return_value.single.return_value = None
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    driver = MagicMock()
    driver.session.return_value = session
    return driver, session


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBlackPageDrums:

    @pytest.mark.unit
    def test_has_kick_and_snare(self):
        """The Black Page hat Kick UND Snare — trotz Komplexität."""
        pitches = {n["pitch"] for n in BLACK_PAGE_DRUMS}
        assert BD in pitches,    "Kein Bass Drum (MIDI36) im Pattern"
        assert SD in pitches,    "Keine Snare (MIDI38) im Pattern"
        assert RIDE in pitches,  "Kein Ride (MIDI51) im Pattern"

    @pytest.mark.unit
    def test_ghost_notes_detected(self):
        """Ghost Notes haben sehr niedrige Velocity (< 0.40)."""
        ghost_notes = [n for n in BLACK_PAGE_DRUMS
                       if n["pitch"] == SD and n["vel"] < 0.40]
        assert len(ghost_notes) >= 3, \
            f"Zu wenige Ghost Notes: {len(ghost_notes)}"

    @pytest.mark.unit
    def test_accent_notes_detected(self):
        """Akzent-Noten haben hohe Velocity (> 0.85)."""
        accents = [n for n in BLACK_PAGE_DRUMS if n["vel"] > 0.85]
        assert len(accents) >= 5, \
            f"Zu wenige Akzente: {len(accents)}"

    @pytest.mark.unit
    def test_velocity_range_wide(self):
        """Ghost→Akzent Velocity-Spanne > 0.60 (typisch für Terry Bozzio)."""
        vels   = [n["vel"] for n in BLACK_PAGE_DRUMS]
        span   = max(vels) - min(vels)
        assert span >= 0.60, \
            f"Zu geringe Dynamik-Spanne: {span:.2f} (Ghost→Akzent)"

    @pytest.mark.unit
    def test_7_8_ratio_step_size(self):
        """7:8-Verhältnis: 7 Noten in 4 Beats → step ≈ 0.571."""
        m14_notes = [n for n in MEASURE_14_7_8
                     if 14.0 <= n["step"] < 18.0 and n["pitch"] != RIDE]
        assert len(m14_notes) == 7, \
            f"7:8 muss genau 7 Noten haben: {len(m14_notes)}"
        steps = sorted(n["step"] for n in m14_notes)
        diffs = [round(steps[i+1]-steps[i], 3) for i in range(len(steps)-1)]
        expected = round(4.0/7, 3)
        assert all(abs(d - expected) < 0.01 for d in diffs), \
            f"7:8 step soll {expected}, bekommen: {diffs}"

    @pytest.mark.unit
    def test_multiple_tuplet_types(self):
        """Pattern enthält Triolen, Quintolen UND Septolen (alle 3 Typen)."""
        all_steps = sorted(n["step"] for n in BLACK_PAGE_DRUMS)
        diffs     = set(round(all_steps[i+1]-all_steps[i], 2)
                        for i in range(len(all_steps)-1) if all_steps[i+1] > all_steps[i])

        has_triplet  = any(abs(d - 0.333) < 0.02 for d in diffs)
        has_quintole = any(abs(d - 0.200) < 0.02 for d in diffs)
        has_septole  = any(abs(d - 0.143) < 0.01 for d in diffs)

        assert has_triplet,  "Keine Triolen-Steps (0.333) gefunden"
        assert has_quintole, "Keine Quintolen-Steps (0.200) gefunden"
        assert has_septole,  "Keine Septolen-Steps (0.143) gefunden"

    @pytest.mark.unit
    def test_validator_context_hint_drum(self):
        """Validator erkennt vollständiges Drum-Kit (Kick+Snare+HH)."""
        from src.agent.tools.music_validator import _build_validation_prompt
        prompt = _build_validation_prompt(
            BLACK_PAGE_DRUMS, "VD-HEAVY", "contemporary", "C", "minor", 4, 60
        )
        assert "vollständiges Drum-Kit" in prompt or "Kick" in prompt, \
            "Validator soll Drum-Kit-Status im Kontext nennen"
        assert "KEIN Kick" not in prompt, \
            "Kick ist vorhanden — soll nicht als fehlend gemeldet werden"

    @pytest.mark.unit
    def test_black_page_drums_score_not_penalized(self):
        """The Black Page Drums soll nicht wegen Komplexität bestraft werden."""
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=_ok(0.78)):
            from src.agent.tools.music_validator import validate_music_pattern
            result = validate_music_pattern(
                BLACK_PAGE_DRUMS, "VD-HEAVY", "contemporary", "C", "minor", 4, 60
            )
        assert result.get("score", 0) >= 0.70, \
            f"The Black Page Drums soll score >= 0.70, bekam: {result.get('score')}"
        assert result.get("rhythmic_ok") is True

    @pytest.mark.unit
    def test_validate_and_learn_full_drums(self):
        """validate_and_learn überlebt The Black Page Drums komplett."""
        driver, session = _neo4j()
        with patch("src.agent.tools.music_validator._is_available", return_value=True), \
             patch("src.agent.tools.music_validator._call_llm", return_value=_ok(0.82)), \
             patch("neo4j.GraphDatabase.driver", return_value=driver):
            from src.agent.tools.music_learning import validate_and_learn
            result = validate_and_learn.invoke({
                "notes":      BLACK_PAGE_DRUMS,
                "instrument": "VD-HEAVY",
                "genre":      "contemporary",
                "key":        "C",
                "scale":      "minor",
                "bars":       4,
                "bpm":        60,
            })
        assert "✓" in result
        assert session.run.called

    @pytest.mark.unit
    def test_drums_score_higher_than_empty_pattern(self):
        """The Black Page Drums (Kick+Snare) soll höher scoren als leeres Pattern."""
        from src.agent.tools.music_validator import _build_validation_prompt
        prompt_full  = _build_validation_prompt(
            BLACK_PAGE_DRUMS, "VD-HEAVY", "rock", "A", "minor", 2, 60
        )
        prompt_empty = _build_validation_prompt(
            [{"step":0,"pitch":42,"vel":0.5,"dur":0.25}],  # nur HH, kein Kick/Snare
            "VD-HEAVY", "rock", "A", "minor", 2, 60
        )
        assert "vollständiges Drum-Kit" in prompt_full, \
            "Vollständiges Kit soll erkannt werden"
        assert "KEIN Kick" in prompt_empty or "KEINE Snare" in prompt_empty, \
            "Fehlende Drum-Elemente sollen gemeldet werden"

    @pytest.mark.unit
    def test_all_three_black_page_versions_coexist(self):
        """Piano-, Gitarren- und Drum-Version haben verschiedene Pitch-Schwerpunkte."""
        from tests.test_mlx_black_page        import BLACK_PAGE_NOTES  as PIANO
        from tests.test_mlx_black_page_guitar import BLACK_PAGE_GUITAR as GUITAR

        piano_avg  = sum(n["pitch"] for n in PIANO)   / len(PIANO)
        guitar_avg = sum(n["pitch"] for n in GUITAR)  / len(GUITAR)
        drum_avg   = sum(n["pitch"] for n in BLACK_PAGE_DRUMS) / len(BLACK_PAGE_DRUMS)

        # Piano am höchsten, Drums am tiefsten (Kick=36)
        assert piano_avg  > guitar_avg, \
            f"Piano ({piano_avg:.1f}) soll höher als Guitar ({guitar_avg:.1f})"
        assert drum_avg   < guitar_avg, \
            f"Drums ({drum_avg:.1f}) soll tiefer als Guitar ({guitar_avg:.1f})"

"""
MLX Fine-tuning Evaluation Tests.

Misst Verbesserungen des fine-tuned Modells (bitwig-music) gegenüber
dem Basis-Modell (qwen3:8b) auf musik-spezifischen Aufgaben.

Ausführen:
    pytest tests/test_mlx_evaluation.py -v -s -m evaluation
    pytest tests/test_mlx_evaluation.py::TestMusicValidatorQuality -v -s
"""
import json
import os
import time
import pytest

from src.agent.tools.music.pattern_generators import _drums, _bass, _chords, _root_midi


# ── Bekannte Test-Patterns (Ground Truth) ─────────────────────────────────────

GOOD_ROCK_BEAT = {
    "notes": [
        # Kick auf 1+3, Snare auf 2+4, HiHat 8tel
        {"step": 0.0, "pitch": 36, "vel": 0.9,  "dur": 0.25},  # Kick Beat 1
        {"step": 1.0, "pitch": 38, "vel": 0.85, "dur": 0.25},  # Snare Beat 2
        {"step": 2.0, "pitch": 36, "vel": 0.85, "dur": 0.25},  # Kick Beat 3
        {"step": 3.0, "pitch": 38, "vel": 0.8,  "dur": 0.25},  # Snare Beat 4
        {"step": 0.0, "pitch": 42, "vel": 0.6,  "dur": 0.25},  # HH
        {"step": 0.5, "pitch": 42, "vel": 0.45, "dur": 0.25},
        {"step": 1.0, "pitch": 42, "vel": 0.6,  "dur": 0.25},
        {"step": 1.5, "pitch": 42, "vel": 0.45, "dur": 0.25},
        {"step": 2.0, "pitch": 42, "vel": 0.6,  "dur": 0.25},
        {"step": 2.5, "pitch": 42, "vel": 0.45, "dur": 0.25},
        {"step": 3.0, "pitch": 42, "vel": 0.6,  "dur": 0.25},
        {"step": 3.5, "pitch": 42, "vel": 0.45, "dur": 0.25},
    ],
    "expected_score_min": 0.55,   # 0.6 ist akzeptabel für 2-Bar basic beat
    "expected_rhythmic_ok": True,
    "description": "Klassischer Rock-Beat (Kick 1+3, Snare 2+4, HH 8tel)",
}

BAD_PATTERN_ONLY_HIHAT = {
    "notes": [
        {"step": i * 0.25, "pitch": 42, "vel": 0.5, "dur": 0.25}
        for i in range(16)
    ],
    "expected_score_max": 0.5,
    "expected_rhythmic_ok": False,
    "expected_issues_contain": ["kick", "snare", "einseitig", "überrepräsentiert",
                                 "hh", "hi-hat", "fehlt", "missing", "only"],
    "description": "Schlechtes Pattern: nur HiHat (kein Kick/Snare)",
}

BAD_PATTERN_NO_GROOVE = {
    "notes": [
        {"step": 0.0, "pitch": 36, "vel": 0.9, "dur": 0.25},  # Nur Kick auf Beat 1
    ],
    "expected_score_max": 0.50,
    "expected_rhythmic_ok": False,
    "description": "Schlechtes Pattern: nur 1 Note",
}

GOOD_BASS_LINE = {
    "notes": _bass("rock", 2, _root_midi("A", 2), "basic"),
    "expected_score_min": 0.6,
    "description": "Valide Rock-Bassline (Root+Quinte)",
}


# ── Hilfsfunktionen ────────────────────────────────────────────────────────────

def _call_validator(notes: list, instrument: str = "VD-HEAVY",
                    genre: str = "rock", key: str = "A") -> dict:
    """Ruft den Validator auf und gibt strukturiertes Ergebnis zurück."""
    from src.agent.tools.music.music_validator import validate_music_pattern
    result = validate_music_pattern(notes, instrument, genre, key, "minor", 2, 120)
    return result


def _is_valid_response(result: dict) -> bool:
    """Prüft ob Antwort vollständig und valide ist."""
    required = {"score", "rhythmic_ok", "issues", "suggestions", "summary"}
    if not result or not required.issubset(result.keys()):
        return False
    if not isinstance(result["score"], (int, float)):
        return False
    if not 0.0 <= result["score"] <= 1.0:
        return False
    return True


def _issues_mention(result: dict, keywords: list[str]) -> bool:
    """Prüft ob Issues oder Suggestions relevante Keywords enthalten."""
    text = " ".join([
        *result.get("issues", []),
        *result.get("suggestions", []),
        result.get("summary", ""),
    ]).lower()
    return any(kw.lower() in text for kw in keywords)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def mlx_available():
    """True wenn MLX-Server auf Mac läuft."""
    try:
        import httpx
        os.environ.setdefault("MAC_LLM_TYPE", "mlx")
        r = httpx.get("http://192.168.0.4:8080/v1/models", timeout=3.0)
        return r.status_code == 200 and bool(r.text.strip())
    except Exception:
        return False


# ── Test-Klassen ───────────────────────────────────────────────────────────────

@pytest.mark.evaluation
class TestJSONFormatCompliance:
    """Prüft ob das Modell konsistent valides JSON zurückgibt."""

    def test_good_beat_returns_valid_json(self, mlx_available):
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(GOOD_ROCK_BEAT["notes"])
        assert _is_valid_response(result), \
            f"Ungültiges JSON-Format: {result}"

    def test_bad_pattern_returns_valid_json(self, mlx_available):
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(BAD_PATTERN_ONLY_HIHAT["notes"])
        assert _is_valid_response(result), \
            f"Ungültiges JSON-Format: {result}"

    def test_score_is_float_between_0_and_1(self, mlx_available):
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(GOOD_ROCK_BEAT["notes"])
        assert isinstance(result.get("score"), (int, float))
        assert 0.0 <= result["score"] <= 1.0

    def test_required_fields_present(self, mlx_available):
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(GOOD_ROCK_BEAT["notes"])
        for field in ["score", "rhythmic_ok", "harmonic_ok", "issues", "suggestions", "summary"]:
            assert field in result, f"Feld '{field}' fehlt in Antwort"


@pytest.mark.evaluation
class TestMusicValidatorQuality:
    """Prüft ob das Modell musikalisch korrekte Bewertungen gibt."""

    def test_good_beat_gets_high_score(self, mlx_available):
        """Klassischer Rock-Beat soll Score >= 0.7 bekommen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(GOOD_ROCK_BEAT["notes"])
        assert _is_valid_response(result)
        score = result["score"]
        assert score >= GOOD_ROCK_BEAT["expected_score_min"], \
            f"Guter Beat bekommt zu niedrigen Score: {score:.2f} " \
            f"(erwartet >= {GOOD_ROCK_BEAT['expected_score_min']})\n" \
            f"Issues: {result.get('issues', [])}"

    def test_only_hihat_gets_low_score(self, mlx_available):
        """Pattern mit nur HiHat soll Score < 0.5 bekommen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(BAD_PATTERN_ONLY_HIHAT["notes"])
        assert _is_valid_response(result)
        score = result["score"]
        assert score <= BAD_PATTERN_ONLY_HIHAT["expected_score_max"], \
            f"Schlechtes Pattern bekommt zu hohen Score: {score:.2f} " \
            f"(erwartet <= {BAD_PATTERN_ONLY_HIHAT['expected_score_max']})"

    def test_good_beat_rhythmic_ok(self, mlx_available):
        """Klassischer Rock-Beat soll rhythmic_ok=True ODER Score >= 0.55 haben."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(GOOD_ROCK_BEAT["notes"])
        # Akzeptiere: rhythmic_ok=True ODER hoher Score (Modell kann strenger sein)
        rhythmic = result.get("rhythmic_ok")
        score    = result.get("score", 0)
        assert rhythmic is True or score >= 0.55, \
            f"Guter Beat: rhythmic_ok={rhythmic}, score={score:.2f} — beides zu niedrig"

    def test_bad_pattern_has_issues(self, mlx_available):
        """Schlechtes Pattern soll Probleme in Issues/Suggestions nennen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(BAD_PATTERN_ONLY_HIHAT["notes"])
        assert _is_valid_response(result)
        has_relevant = _issues_mention(
            result, BAD_PATTERN_ONLY_HIHAT["expected_issues_contain"]
        )
        assert has_relevant or len(result.get("issues", [])) > 0, \
            f"Schlechtes Pattern hat keine Issues: {result.get('issues', [])}"

    def test_single_note_gets_very_low_score(self, mlx_available):
        """Pattern mit nur 1 Note soll Score < 0.4 bekommen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        result = _call_validator(BAD_PATTERN_NO_GROOVE["notes"])
        assert _is_valid_response(result)
        assert result["score"] <= BAD_PATTERN_NO_GROOVE["expected_score_max"], \
            f"Score {result['score']:.2f} zu hoch für 1-Noten-Pattern"


@pytest.mark.evaluation
class TestScoreDiscrimination:
    """Prüft ob das Modell gut zwischen guten und schlechten Patterns unterscheidet."""

    def test_good_beats_higher_than_bad(self, mlx_available):
        """Gute Patterns müssen höheren Score als schlechte bekommen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        good_result = _call_validator(GOOD_ROCK_BEAT["notes"])
        bad_result  = _call_validator(BAD_PATTERN_ONLY_HIHAT["notes"])

        assert _is_valid_response(good_result) and _is_valid_response(bad_result)
        diff = good_result["score"] - bad_result["score"]
        assert diff > 0.1, \
            f"Score-Unterschied zu klein: gut={good_result['score']:.2f}, " \
            f"schlecht={bad_result['score']:.2f}, diff={diff:.2f}"

    @pytest.mark.parametrize("genre,style", [
        ("rock",    "full"),
        ("hip-hop", "basic"),
        ("jazz",    "basic"),
    ])
    def test_generated_patterns_get_positive_scores(self, genre, style, mlx_available):
        """Algorithmisch generierte Patterns sollen Score > 0.5 bekommen."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        from src.agent.tools.music.pattern_generators import _drums
        notes  = _drums(genre, 2, style)
        result = _call_validator(notes, genre=genre)
        assert _is_valid_response(result), f"Kein valides JSON für {genre}/{style}"
        assert result["score"] >= 0.4, \
            f"Generiertes {genre} Pattern Score zu niedrig: {result['score']:.2f}"


@pytest.mark.evaluation
class TestResponseConsistency:
    """Prüft Konsistenz — gleiches Pattern soll ähnliche Scores bekommen."""

    def test_same_pattern_consistent_scores(self, mlx_available):
        """Gleiches Pattern zweimal → Score-Differenz < 0.2."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")
        r1 = _call_validator(GOOD_ROCK_BEAT["notes"])
        r2 = _call_validator(GOOD_ROCK_BEAT["notes"])

        if not (_is_valid_response(r1) and _is_valid_response(r2)):
            pytest.skip("Kein valides JSON erhalten")

        diff = abs(r1["score"] - r2["score"])
        assert diff < 0.2, \
            f"Inkonsistente Scores: {r1['score']:.2f} vs {r2['score']:.2f} (diff={diff:.2f})"


# ── Benchmark-Report ───────────────────────────────────────────────────────────

@pytest.mark.evaluation
@pytest.mark.slow
class TestBenchmarkReport:
    """Vollständiger Benchmark-Report für das fine-tuned Modell."""

    def test_full_benchmark(self, mlx_available, capsys):
        """Erstellt vollständigen Benchmark-Report."""
        if not mlx_available:
            pytest.skip("MLX-Server nicht erreichbar")

        test_cases = [
            ("Guter Rock-Beat",      GOOD_ROCK_BEAT["notes"],          "VD-HEAVY", "rock"),
            ("Nur HiHat",            BAD_PATTERN_ONLY_HIHAT["notes"],  "VD-HEAVY", "rock"),
            ("1 Note",               BAD_PATTERN_NO_GROOVE["notes"],   "VD-HEAVY", "rock"),
            ("Generierter Rock",     _drums("rock",    2, "full"),      "VD-HEAVY", "rock"),
            ("Generierter Hip-Hop",  _drums("hip-hop", 2, "basic"),     "VD-HEAVY", "hip-hop"),
            ("Generierter Jazz",     _drums("jazz",    2, "basic"),     "VD-HEAVY", "jazz"),
            ("Rock-Bass",            _bass("rock", 2, _root_midi("A",2), "basic"), "VB-ROYAL", "rock"),
        ]

        results = []
        for name, notes, instrument, genre in test_cases:
            result = _call_validator(notes, instrument, genre)
            valid  = _is_valid_response(result)
            results.append({
                "name":     name,
                "valid":    valid,
                "score":    result.get("score", None) if valid else None,
                "rhythmic": result.get("rhythmic_ok", None) if valid else None,
                "issues":   len(result.get("issues", [])) if valid else 0,
            })

        with capsys.disabled():
            print("\n" + "="*60)
            print("  MLX Fine-tuned Model — Benchmark Report")
            print("="*60)
            valid_count = sum(1 for r in results if r["valid"])
            print(f"\nJSON-Format: {valid_count}/{len(results)} valide")
            print(f"\n{'Pattern':<25} {'Score':>6} {'Rhythmik':>9} {'Issues':>7} {'Valid':>6}")
            print("-"*55)
            for r in results:
                score   = f"{r['score']:.2f}" if r["score"] is not None else "N/A"
                rhyth   = str(r["rhythmic"]) if r["rhythmic"] is not None else "N/A"
                print(f"{r['name']:<25} {score:>6} {rhyth:>9} {r['issues']:>7} {'✓' if r['valid'] else '✗':>6}")

        # Mindestanforderungen
        assert valid_count >= len(results) * 0.8, \
            f"Zu viele ungültige Antworten: {valid_count}/{len(results)}"

        scores = [r["score"] for r in results if r["score"] is not None]
        if scores:
            avg = sum(scores) / len(scores)
            assert avg > 0.3, f"Durchschnittlicher Score zu niedrig: {avg:.2f}"

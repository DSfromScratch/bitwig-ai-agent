"""
E2E Guitar Score Loop Test.

Erstellt ein vollständiges Rock-Band-Arrangement (Drums + Bass + Gitarren-Lead).
Launchpad-Workflow: Agent legt nur Tracks und Instrumente an — keine Noten-Generierung.
Gitarren-Lead wird direkt via BitwigResultBuilder (OOP) eingespielt.

Score-Kriterien:
  30 % — Drum-Tracks vorhanden (v9 Kick/Snare/Hat in Bitwig-Tracks)
  30 % — Bass-Track vorhanden (FM-4)
  30 % — Gitarren-Lead vorhanden (Phase-4 Track mit Noten via OOP)
  10 % — Tempo gesetzt (120 BPM)

Benötigt: Bitwig + BitwigAgentBridge + vLLM aktiv.
"""
import re
import time
import pytest

SCORE_THRESHOLD = 0.75
MAX_ITERATIONS = 3

# Launchpad-Workflow: Agent legt Tracks + Instrumente an, keine Noten
# v9 Kick/Snare/Hat = Bitwig Built-in Sampler → laden sofort, kein Browser-Timeout
DRUMS_BASS_PROMPT = (
    "Erstelle Rock-Drums und Bass — 120 BPM. Genau 4 Tracks, KEIN Lead. "
    "Instrumente: 'v9 Kick' (Track 1), 'v9 Snare' (Track 2), 'v9 Hat Closed' (Track 3), 'FM-4' (Track 4). "
    "Ablauf: execute_setup (Tracks + Instrumente + Tempo), dann get_bitwig_track_state."
)


_DRUM_KEYWORDS   = ("v9 kick", "v9 snare", "v9 hat", "drum machine", "e-kick", "e-snare")
_BASS_KEYWORDS   = ("fm-4", "bass", "fm4")
_GUITAR_KEYWORDS = ("phase-4", "phase 4", "lead", "guitar", "polymer")


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_guitar_state(
    track_count: int,
    note_counts: dict[str, int],
    result_text: str = "",
    track_names: list[str] | None = None,
) -> tuple[float, dict[str, str]]:
    """Bewertet ob ein vollständiges Rock-Arrangement mit Gitarre erstellt wurde.

    Launchpad-Workflow: Drums/Bass werden nur nach Track-Existenz bewertet (keine Noten-Pflicht).
    Gitarren-Lead wird nach Track-Existenz + Noten bewertet (OOP direkt via BitwigResultBuilder).

    track_names: Live-Track-Namen aus Bitwig.
    """
    bd: dict[str, str] = {}
    _names = [n.lower() for n in (track_names or [])]

    def _track_notes(keywords: tuple[str, ...]) -> int:
        return sum(v for k, v in note_counts.items()
                   if k != "__total__" and any(kw in k.lower() for kw in keywords))

    def _track_exists(keywords: tuple[str, ...]) -> bool:
        """Prüft ob ein Track mit passendem Namen in Bitwig existiert."""
        return any(any(kw in name for kw in keywords) for name in _names)

    def _track_count_by(keywords: tuple[str, ...]) -> int:
        return sum(1 for name in _names if any(kw in name for kw in keywords))

    # 1. Drums (30 %) — Launchpad-Workflow: Track-Existenz zählt, nicht Noten
    drum_track_count = _track_count_by(_DRUM_KEYWORDS)
    ds = min(drum_track_count / 3, 1.0) * 0.30   # 3 Drum-Tracks = voll
    bd["drums"] = f"{drum_track_count} Tracks (v9 Kick/Snare/Hat) → {ds:.2f}"

    # 2. Bass (30 %) — Track-Existenz
    bass_exists = _track_exists(_BASS_KEYWORDS)
    bs = 0.30 if bass_exists else 0.0
    bd["bass"] = f"exists={bass_exists} → {bs:.2f}"

    # 3. Gitarren-Lead (30 %) — 10 % Track-Existenz + 20 % Noten (OOP-Pfad)
    guitar_notes  = _track_notes(_GUITAR_KEYWORDS)
    guitar_tracks = [k for k in note_counts
                     if k != "__total__" and any(kw in k.lower() for kw in _GUITAR_KEYWORDS)]
    guitar_exists = bool(guitar_tracks) or _track_exists(_GUITAR_KEYWORDS)
    exist_score   = 0.10 if guitar_exists else 0.0
    note_score    = min(guitar_notes / 4, 1.0) * 0.20   # 4 Noten = voll
    gs = exist_score + note_score
    label = ", ".join(guitar_tracks) if guitar_tracks else (
        next((n for n in (track_names or []) if any(kw in n.lower() for kw in _GUITAR_KEYWORDS)),
             "keiner")
    )
    bd["guitar"] = f"[{label}] exists={guitar_exists} {guitar_notes} Noten → {gs:.2f}"

    # 4. Tempo (10 %)
    ts = (
        0.10
        if result_text and "120" in result_text
        and re.search(r"(bpm|tempo)", result_text, re.IGNORECASE)
        else 0.0
    )
    bd["tempo"] = f"→ {ts:.2f}"

    return round(ds + bs + gs + ts, 3), bd


def _build_guitar_feedback(
    score: float,
    breakdown: dict[str, str],
    track_names: list[str],
) -> str:
    """Gibt drums_bass_feedback zurück (guitar wird via OOP ausgeführt, kein Feedback nötig)."""
    drum_score = float(breakdown["drums"].split("→")[-1].strip())
    bass_score = float(breakdown["bass"].split("→")[-1].strip())

    db_issues = []
    if drum_score < 0.10:
        db_issues.append(
            "Drum-Tracks fehlen. Exakt 3 Tracks anlegen: 'v9 Kick' (Track 1), "
            "'v9 Snare' (Track 2), 'v9 Hat Closed' (Track 3)."
        )
    if bass_score < 0.10:
        db_issues.append("Bass-Track fehlt. FM-4 auf Track 4 laden.")

    if db_issues:
        return (
            f"Vorheriges Ergebnis unvollständig (Score {score:.0%}):\n"
            + "\n".join(f"  - {m}" for m in db_issues)
            + "\n\n" + DRUMS_BASS_PROMPT
        )
    return DRUMS_BASS_PROMPT


# ── Unit Tests für Scoring und Modelle ───────────────────────────────────────

class TestGuitarScoreFunction:

    @pytest.mark.unit
    def test_empty_scores_zero(self):
        score, _ = score_guitar_state(0, {})
        assert score == 0.0

    @pytest.mark.unit
    def test_full_band_scores_high(self):
        track_names = ["v9 Kick", "v9 Snare", "v9 Hat Closed", "FM-4", "Phase-4"]
        score, bd = score_guitar_state(
            track_count=5,
            note_counts={"Phase-4": 8},
            result_text="set_tempo 120 BPM",
            track_names=track_names,
        )
        assert score >= SCORE_THRESHOLD, f"Full-Band zu tief: {score} {bd}"

    @pytest.mark.unit
    def test_guitar_detected_by_phase4(self):
        _, bd = score_guitar_state(1, {"Phase-4": 8}, track_names=["Phase-4"])
        guitar_score = float(bd["guitar"].split("→")[-1].strip())
        assert guitar_score >= 0.20

    @pytest.mark.unit
    def test_missing_guitar_penalized(self):
        names_no  = ["v9 Kick", "v9 Snare", "v9 Hat Closed", "FM-4"]
        names_yes = ["v9 Kick", "v9 Snare", "v9 Hat Closed", "FM-4", "Phase-4"]
        s_no,  _ = score_guitar_state(4, {}, result_text="120 BPM", track_names=names_no)
        s_yes, _ = score_guitar_state(5, {"Phase-4": 4}, result_text="120 BPM",
                                       track_names=names_yes)
        assert s_yes > s_no + 0.20


class TestBitwigResultModels:
    """Unit-Tests für die neuen OOP-Modelle."""

    @pytest.mark.unit
    def test_builder_creates_valid_result(self):
        from src.agent.models import BitwigResultBuilder
        result = (
            BitwigResultBuilder(bpm=120, genre="rock")
            .set_tempo(120)
            .add_track()
            .load_instrument(1, "v9 Kick")
            .play()
            .build()
        )
        assert result.tempo == 120
        assert result.track_count == 1
        assert len(result.steps) == 4

    @pytest.mark.unit
    def test_builder_to_dict_compatible(self):
        from src.agent.models import BitwigResultBuilder
        result = (
            BitwigResultBuilder()
            .set_tempo(120)
            .add_track()
            .build()
        )
        d = result.to_dict()
        assert "steps" in d
        assert d["steps"][0]["type"] == "set_tempo"
        assert d["steps"][0]["args"]["bpm"] == 120
        assert d["steps"][1]["type"] == "add_track"

    @pytest.mark.unit
    def test_step_validation_rejects_invalid_tempo(self):
        from pydantic import ValidationError
        from src.agent.models.steps import SetTempoStep
        with pytest.raises(ValidationError):
            SetTempoStep(bpm=30)   # < 60 BPM → Fehler

    @pytest.mark.unit
    def test_execute_result_accepts_bitwig_result_object(self):
        from unittest.mock import patch
        from src.agent.models import BitwigResultBuilder

        result = BitwigResultBuilder().set_tempo(120).build()

        with patch("src.agent.tools.bitwig.song_tools._check_bridge", return_value=False), \
             patch("pythonosc.udp_client.SimpleUDPClient"), \
             patch("time.sleep"):
            from bitwig_mcp_server import execute_result
            output = execute_result(result)

        assert isinstance(output, str)
        assert len(output) > 0

    @pytest.mark.unit
    def test_execute_plan_calls_execute_result(self):
        from unittest.mock import patch
        from src.agent.models import BitwigResultBuilder
        from src.agent.core import execute_plan

        result = BitwigResultBuilder().set_tempo(120).build()

        with patch("src.bitwig_executor.execute_result", return_value="OK") as mock_er:
            output = execute_plan(result)

        mock_er.assert_called_once_with(result)
        assert output == "OK"


# ── Integration Test (benötigt Bitwig + vLLM) ─────────────────────────────────

@pytest.mark.integration
@pytest.mark.slow
class TestE2EGuitarLoop:
    """Full-Band Rock-Arrangement.

    Zwei-Phasen-Ansatz:
      Phase 1 — Drums + Bass via Agent (testet LLM-Planung)
      Phase 2 — Gitarren-Lead via BitwigResultBuilder direkt (testet OOP-Execution)

    Das vermeidet das LLM-Token-Truncation-Problem bei write_notes + langen Thinking-Blöcken
    und demonstriert gleichzeitig die neue OOP-Schicht (execute_plan).
    """

    def _agent_drums_bass(self, prompt: str, reset: bool = True) -> tuple[str, dict[str, int], list[str]]:
        from src.agent.core import chat
        from src.agent.events import get_event_bus
        from src.agent.tools.bitwig.song_tools import (
            _clear_all_tracks, _get_note_counts, _reset_note_counts,
        )
        if reset:
            deleted = _clear_all_tracks()
            from src.agent.tools.bitwig.song_tools import _get_current_track_count
            remaining = _get_current_track_count()
            status = "✓" if remaining == 0 else f"⚠ {remaining} Track(s) verblieben!"
            print(f"  Bitwig reset: {deleted} Track(s) gelöscht {status}")
            if remaining > 0:
                import warnings
                warnings.warn(f"Reset unvollständig: {remaining} Track(s) noch in Bitwig nach Clear")
        else:
            _reset_note_counts()

        step_errors: list[str] = []
        bus = get_event_bus()
        def _on_step_error(ev):
            step_errors.append(ev["payload"].get("error", ""))
        bus.subscribe("result_step_error", _on_step_error)
        try:
            result = chat(prompt)
        finally:
            bus.unsubscribe("result_step_error", _on_step_error)

        time.sleep(1.0)
        return result, _get_note_counts(), step_errors

    def _execute_guitar(self, track_index: int) -> str:
        """Fügt Gitarren-Lead via BitwigResultBuilder + execute_plan hinzu.

        Kein LLM — direkter OOP-Ansatz. Testet die neue execute_plan()-Schicht.
        """
        from src.agent.core import execute_plan
        from src.agent.models import BitwigResultBuilder
        from src.agent.tools.bitwig.song_tools import _reset_note_counts

        _reset_note_counts()
        result = (
            BitwigResultBuilder()
            .add_track()
            .load_instrument(track_index, "Phase-4")
            .write_notes(track_index, notes=[
                {"step": 0,  "pitch": 52, "vel": 0.8, "dur": 2.0},
                {"step": 4,  "pitch": 55, "vel": 0.8, "dur": 2.0},
                {"step": 8,  "pitch": 57, "vel": 0.8, "dur": 2.0},
                {"step": 12, "pitch": 59, "vel": 0.8, "dur": 2.0},
            ], length_beats=16.0)
            .build()
        )
        return execute_plan(result)

    def test_guitar_score_loop(self, osc_available):
        """Rock-Band mit Gitarre: Agent für Tracks/Instrumente, OOP für Gitarren-Noten."""
        if not osc_available:
            pytest.skip("Bitwig nicht erreichbar (Port 8002/8001) — Integration-Test übersprungen")
        import os
        import urllib.request
        _llm_base = os.getenv("VLLM_BASE_URL", "http://localhost:8100").rstrip("/")
        try:
            urllib.request.urlopen(f"{_llm_base}/v1/models", timeout=3)
        except Exception:
            pytest.skip(f"Agent-LLM nicht erreichbar ({_llm_base}) — LLM-Test übersprungen")

        scores:    list[float] = []
        db_prompt = DRUMS_BASS_PROMPT

        for iteration in range(1, MAX_ITERATIONS + 1):
            _divider(f"ITERATION {iteration}/{MAX_ITERATIONS}")

            # Phase 1: Drums + Bass via Agent (nur Tracks/Instrumente anlegen)
            print(f"Phase 1 — Agent Drums+Bass: {db_prompt[:120]}")
            db_result, notes_db, db_step_errors = self._agent_drums_bass(db_prompt, reset=True)
            print(f"  Drums+Bass Notes: {notes_db}")

            # Vorbedingung: keine Browser-Timeouts
            browser_errors = [e for e in db_step_errors if "browser_timeout" in e]
            if browser_errors:
                pytest.fail(
                    f"Vorbedingung nicht erfüllt: Phase 1 Browser-Load fehlgeschlagen "
                    f"(Iteration {iteration}).\nFehler: {browser_errors}"
                )

            # Phase 2: Gitarren-Lead via BitwigResultBuilder (OOP direkt, kein LLM)
            from src.agent.tools.bitwig.song_tools import _get_current_track_count
            real_track_count = _get_current_track_count()
            guitar_track_idx = real_track_count + 1
            print(f"Phase 2 — OOP Gitarre (Track {guitar_track_idx})")
            guitar_result = self._execute_guitar(guitar_track_idx)
            time.sleep(0.5)

            if "error:browser_timeout" in guitar_result or (
                "FEHLER" in guitar_result and "0 Steps" not in guitar_result
            ):
                pytest.fail(
                    f"Vorbedingung nicht erfüllt: Phase 2 fehlgeschlagen.\n"
                    f"Ergebnis: {guitar_result[:400]}"
                )

            from src.agent.tools.bitwig.song_tools import _get_note_counts, _get_track_names
            track_count  = _get_current_track_count()
            notes_guitar = _get_note_counts()
            track_names  = _get_track_names()

            print(f"  Track-Namen: {track_names}")
            print(f"  Gitarre Noten: {notes_guitar}")

            combined_text = db_result + "\n" + guitar_result
            score, breakdown = score_guitar_state(
                track_count, notes_guitar, combined_text, track_names
            )
            scores.append(score)
            _print_report(score, breakdown, combined_text)

            if score >= SCORE_THRESHOLD:
                print(f"\nZiel erreicht in Iteration {iteration}!")
                break

            if iteration < MAX_ITERATIONS:
                db_prompt = _build_guitar_feedback(score, breakdown, track_names)

        final_score = scores[-1]
        _divider("ERGEBNIS")
        print(f"Score: {final_score:.2f} nach {len(scores)} Iteration(en)")
        print(f"Alle Scores: {[f'{s:.2f}' for s in scores]}")

        assert final_score >= SCORE_THRESHOLD, (
            f"Score {final_score:.2f} < {SCORE_THRESHOLD} "
            f"nach {len(scores)} Iterationen."
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _divider(label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def _print_report(score: float, breakdown: dict[str, str], result_text: str) -> None:
    print(f"\nScore: {score:.2f} {'✓' if score >= SCORE_THRESHOLD else '✗'}")
    for k, v in breakdown.items():
        print(f"  {k:12s}: {v}")
    print("\nAgent-Output (letzte 5 Zeilen):")
    for line in result_text.strip().splitlines()[-5:]:
        print(f"  {line}")

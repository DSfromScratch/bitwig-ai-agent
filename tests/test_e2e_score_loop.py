"""
E2E Score Loop Test.

Führt einen vollständigen Agenten-Zyklus aus:
  1. Agent erstellt Rock Intro via execute_result
  2. Bitwig-Zustand wird via OSC abgefragt (echte Daten, kein Text-Parsing)
     - Track-Anzahl: /agent/track/count
     - Note-Counts:  /clip/note/count/all  (noteCountMap in Java-Extension)
  3. Score (0..1) aus echten Bitwig-Daten berechnet
  4. Bei Score < SCORE_THRESHOLD: Feedback-Prompt → nächste Iteration
  5. Maximal MAX_ITERATIONS Versuche

Benötigt: Bitwig + BitwigAgentBridge + vLLM aktiv.

Markers:
  @pytest.mark.integration  – benötigt Bitwig + vLLM
  @pytest.mark.slow         – mehrere LLM-Aufrufe, > 30 s
"""
import re
import time
import pytest

SCORE_THRESHOLD = 0.80
MAX_ITERATIONS = 3

INITIAL_PROMPT = (
    "Erstelle ein Rock Intro mit Drums und Bass — 4 Takte, 120 BPM. Spiele es ab."
)

_DRUM_KEYWORDS = ("v9 kick", "v9 snare", "v9 hat", "drum machine", "e-kick", "e-snare")


# ── Scoring (basiert auf echten Bitwig-OSC-Daten) ────────────────────────────

def score_bitwig_state(
    track_count: int,
    note_counts: dict[str, int],
    result_text: str = "",
) -> tuple[float, dict[str, str]]:
    """Bewertet Bitwig-Zustand anhand echter OSC-Abfragen.

    Args:
        track_count:  Anzahl Tracks aus /agent/track/count
        note_counts:  Pro-Track Note-Counts aus /clip/note/count/all
                      z.B. {"v9 Kick": 8, "v9 Snare": 8, "v9 Hat Closed": 8}
        result_text:  Agent-Output (nur für Tempo-Check genutzt)

    Kriterien:
      30 % — Track-Anzahl (mindestens 3)
      40 % — Noten in Bitwig (Summe aus noteCountMap, min 24)
      20 % — Drum-Instrumente (Keyword-Treffer in Track-Namen)
      10 % — Tempo gesetzt (120 BPM, aus Agent-Text)
    """
    bd: dict[str, str] = {}

    # 1. Track-Anzahl (30 %)
    tc_score = min(track_count / 3, 1.0) * 0.30
    bd["tracks"] = f"{track_count}/3 → {tc_score:.2f}"

    # 2. Noten in Bitwig (40 %) — echte Daten aus noteCountMap
    total_notes = sum(note_counts.values()) if note_counts else 0
    nc_score = min(total_notes / 24, 1.0) * 0.40
    detail = ", ".join(f"{k}={v}" for k, v in note_counts.items()) or "keine"
    bd["notes"] = f"{total_notes} Noten [{detail}] → {nc_score:.2f}"

    # 3. Drum-Instrumente (20 %) — Track-Namen aus noteCountMap
    known_drums = sum(
        1 for name in note_counts
        if any(kw in name.lower() for kw in _DRUM_KEYWORDS)
    )
    dc_score = min(known_drums / 2, 1.0) * 0.20
    bd["drums"] = f"{known_drums} Drum-Tracks → {dc_score:.2f}"

    # 4. Tempo (10 %) — aus Agent-Text (OSC hat keine Tempo-Abfrage)
    tempo_score = (
        0.10
        if result_text and "120" in result_text
        and re.search(r"(bpm|tempo)", result_text, re.IGNORECASE)
        else 0.0
    )
    bd["tempo"] = f"→ {tempo_score:.2f}"

    total = round(tc_score + nc_score + dc_score + tempo_score, 3)
    return total, bd


def _build_feedback_prompt(
    score: float,
    breakdown: dict[str, str],
    note_counts: dict[str, int],
) -> str:
    """Erstellt einen Feedback-Prompt der den Agent auf Lücken hinweist."""
    max_per_key = {"tracks": 0.30, "notes": 0.40, "drums": 0.20, "tempo": 0.10}
    issue_messages = {
        "tracks": (
            "Es wurden zu wenige Tracks erstellt. "
            "Mindestens 3 Drum-Tracks (Kick, Snare, Hihat) werden benötigt."
        ),
        "notes": (
            f"Zu wenige Noten in Bitwig geschrieben (aktuell: {sum(note_counts.values())} Noten). "
            "Jeder Drum-Track benötigt mindestens 8 Noten für 4 Takte."
        ),
        "drums": (
            "Drum-Instrumente (v9 Kick, v9 Snare, v9 Hat Closed) wurden nicht erkannt. "
            "Verwende query_bitwig_docs für die korrekten Instrument-Namen."
        ),
        "tempo": "Das Tempo wurde nicht auf 120 BPM gesetzt.",
    }

    issues = []
    for key, val in breakdown.items():
        actual = float(val.split("→")[-1].strip())
        if actual < max_per_key.get(key, 0) * 0.7:
            issues.append(issue_messages[key])

    lines = [f"Vorheriges Ergebnis unvollständig (Score {score:.0%}). Bitte korrigiere:"]
    lines += [f"  - {msg}" for msg in issues]
    lines += ["", INITIAL_PROMPT]
    return "\n".join(lines)


# ── Unit Tests (kein Bitwig nötig) ────────────────────────────────────────────

class TestScoreFunction:
    """Stellt sicher dass der Scorer korrekt funktioniert."""

    @pytest.mark.unit
    def test_empty_result_scores_zero(self):
        score, _ = score_bitwig_state(track_count=0, note_counts={})
        assert score == 0.0

    @pytest.mark.unit
    def test_perfect_osc_data_scores_high(self):
        score, bd = score_bitwig_state(
            track_count=3,
            note_counts={"v9 Kick": 8, "v9 Snare": 8, "v9 Hat Closed": 8},
            result_text="set_tempo 120 BPM",
        )
        assert score >= 0.80, f"Perfektes OSC-Ergebnis zu tief: {score} {bd}"

    @pytest.mark.unit
    def test_notes_from_osc_not_text(self):
        """Noten kommen aus note_counts dict, nicht aus result_text."""
        score_with_osc, _ = score_bitwig_state(
            track_count=3,
            note_counts={"v9 Kick": 10, "v9 Snare": 10},
            result_text="",  # kein Text
        )
        score_text_only, _ = score_bitwig_state(
            track_count=3,
            note_counts={},  # keine OSC-Daten
            result_text="write_drum_pattern kick 10 Noten → Track 1\nwrite_drum_pattern snare 10 Noten → Track 2",
        )
        assert score_with_osc > score_text_only, (
            "OSC-Noten müssen höher scoren als Text-Only. "
            f"OSC: {score_with_osc}, Text: {score_text_only}"
        )

    @pytest.mark.unit
    def test_feedback_includes_note_count(self):
        bd = {
            "tracks": "3/3 → 0.30",
            "notes": "4 Noten [...] → 0.07",
            "drums": "0 Drum-Tracks → 0.00",
            "tempo": "→ 0.10",
        }
        fb = _build_feedback_prompt(0.47, bd, note_counts={"Instrument 1": 4})
        assert INITIAL_PROMPT in fb
        assert "4 Noten" in fb


# ── Integration Test (benötigt Bitwig + vLLM) ─────────────────────────────────

@pytest.mark.integration
@pytest.mark.slow
class TestE2EScoreLoop:
    """Führt den vollständigen Score-Loop mit realem Agenten und OSC-Analyse aus."""

    def _agent_run(self, prompt: str) -> tuple[str, int, dict[str, int]]:
        """Bereinigt Bitwig, startet Agenten, gibt (result_text, track_count, note_counts) zurück.

        Vor jedem Run werden ALLE Tracks gelöscht und der Note-Counter zurückgesetzt,
        damit jede Iteration unabhängig auf einem sauberen Zustand startet.
        """
        from src.agent.core import chat
        from src.agent.tools.song_tools import (
            _clear_all_tracks,
            _get_current_track_count,
            _get_note_counts,
        )

        deleted = _clear_all_tracks()
        print(f"  Bitwig reset: {deleted} Track(s) gelöscht")
        time.sleep(0.5)  # Bitwig State nach Löschung stabilisieren

        result = chat(prompt)
        time.sleep(1.0)  # Bitwig State nach Ausführung stabilisieren

        count = _get_current_track_count()
        notes = _get_note_counts()
        return result, count, notes

    def test_rock_intro_score_loop(self, osc_available):
        """Rock Intro: iteriere bis Score >= SCORE_THRESHOLD."""
        if not osc_available:
            pytest.fail("Vorbedingung nicht erfüllt: Bitwig / OSC Bridge nicht erreichbar (Port 8001)")

        prompt = INITIAL_PROMPT
        scores: list[float] = []
        all_breakdowns: list[dict] = []
        all_note_counts: list[dict] = []

        for iteration in range(1, MAX_ITERATIONS + 1):
            _print_divider(f"ITERATION {iteration}/{MAX_ITERATIONS}")
            print(f"Prompt: {prompt[:160]}")

            result_text, track_count, note_counts = self._agent_run(prompt)
            all_note_counts.append(note_counts)

            score, breakdown = score_bitwig_state(track_count, note_counts, result_text)
            scores.append(score)
            all_breakdowns.append(breakdown)

            _print_score_report(score, breakdown, result_text)

            if score >= SCORE_THRESHOLD:
                print(f"\nZiel erreicht in Iteration {iteration}!")
                break

            if iteration < MAX_ITERATIONS:
                prompt = _build_feedback_prompt(score, breakdown, note_counts)

        final_score = scores[-1]
        print(f"\n{'='*60}")
        print(f"ERGEBNIS: {final_score:.2f} nach {len(scores)} Iteration(en)")
        print(f"Scores: {[f'{s:.2f}' for s in scores]}")
        print(f"Noten je Iteration: {all_note_counts}")

        assert final_score >= SCORE_THRESHOLD, (
            f"Score {final_score:.2f} < Schwellwert {SCORE_THRESHOLD} "
            f"nach {len(scores)} Iterationen.\n"
            f"Scores: {scores}\n"
            f"Note-Counts: {all_note_counts[-1]}\n"
            f"Breakdown: {all_breakdowns[-1]}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_divider(label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")


def _print_score_report(
    score: float,
    breakdown: dict[str, str],
    result_text: str,
) -> None:
    print(f"\nScore: {score:.2f} {'✓' if score >= SCORE_THRESHOLD else '✗'}")
    for k, v in breakdown.items():
        print(f"  {k:8s}: {v}")
    last_lines = result_text.strip().splitlines()[-5:]
    print("\nAgent-Output (letzte 5 Zeilen):")
    for line in last_lines:
        print(f"  {line}")

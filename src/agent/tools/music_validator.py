"""
Musik-Validator: sendet Noten/Kontext an Mac-LLM (Ollama/Qwen3-4B),
erhält harmonische/rhythmische Bewertung + Verbesserungsvorschläge.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

log = logging.getLogger("bitwig-agent")

MAC_LLM_URL   = os.getenv("MAC_LLM_URL",   "http://192.168.0.4:11434")
MAC_LLM_MODEL = os.getenv("MAC_LLM_MODEL", "qwen3:4b")


def _is_available() -> bool:
    try:
        import httpx
        r = httpx.get(f"{MAC_LLM_URL}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _build_validation_prompt(
    notes: list[dict],
    instrument: str,
    genre: str,
    key: str,
    scale: str,
    bars: int,
    bpm: int,
) -> str:
    note_summary = []
    from collections import Counter
    pitches = Counter(n.get("pitch", 0) for n in notes)
    _NAMES = {36:"Kick",37:"Rim",38:"Snare",39:"Clap",42:"HH",44:"PedHH",46:"OpenHH",
              49:"Crash",51:"Ride",36:"Kick"}
    for p, c in sorted(pitches.items()):
        name = _NAMES.get(p, f"MIDI{p}")
        vels = [round(n["vel"],2) for n in notes if n.get("pitch")==p]
        note_summary.append(f"  {name}(MIDI{p}): {c}× vel={vels[:3]}")

    steps = sorted(set(n.get("step",0) for n in notes))
    return f"""Du bist ein erfahrener Musik-Theoretiker und Produzent.
Bewerte dieses MIDI-Pattern für Bitwig Studio:

Instrument: {instrument}
Genre: {genre} | Key: {key} {scale} | {bars} Takte | {bpm} BPM
Anzahl Noten: {len(notes)}

Noten-Zusammenfassung:
{chr(10).join(note_summary)}

Erste Steps: {steps[:12]}

Antworte NUR als JSON (kein Text davor/danach):
{{
  "score": <0.0-1.0>,
  "rhythmic_ok": <true/false>,
  "harmonic_ok": <true/false>,
  "genre_fit": <true/false>,
  "issues": ["<Problem 1>", "<Problem 2>"],
  "suggestions": ["<Verbesserung 1>", "<Verbesserung 2>"],
  "summary": "<1 Satz Gesamtbewertung>"
}}"""


def _build_rag_context(instrument: str, genre: str, key: str) -> str:
    """Lädt erfolgreiche Patterns als Few-Shot-Kontext (Ansatz 2: RAG)."""
    try:
        from src.agent.tools.music_learning import get_rag_examples
        examples = get_rag_examples(instrument, genre, key, min_score=0.75, limit=2)
        if not examples:
            return ""
        lines = ["\nErfolgreiche frühere Patterns (Lernbeispiele):"]
        for ex in examples:
            lines.append(
                f"  • {ex['instrument']}/{ex['genre']} "
                f"score={ex.get('score',0):.2f} "
                f"({ex.get('iterations',1)} Iterationen) "
                f"→ {', '.join((ex.get('suggestions') or [])[:2])}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


def validate_music_pattern(
    notes: list[dict],
    instrument: str,
    genre: str = "rock",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
) -> dict[str, Any]:
    """Bewertet ein MIDI-Pattern via Mac-LLM.

    Returns: {score, rhythmic_ok, harmonic_ok, genre_fit, issues, suggestions, summary}
    Gibt leeres Dict zurück wenn Mac-LLM nicht erreichbar.
    """
    if not _is_available():
        log.debug("Mac-LLM nicht erreichbar (%s) — Validierung übersprungen", MAC_LLM_URL)
        return {}

    rag_ctx = _build_rag_context(instrument, genre, key)
    prompt  = _build_validation_prompt(notes, instrument, genre, key, scale, bars, bpm) + rag_ctx

    try:
        import httpx
        response = httpx.post(
            f"{MAC_LLM_URL}/api/chat",
            json={
                "model": MAC_LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 512},
            },
            timeout=30.0,
        )
        data     = response.json()
        msg      = data.get("message", {})
        # Qwen3 thinking mode: content kann leer sein, Antwort in thinking
        content  = msg.get("content") or msg.get("thinking", "{}")
        result = json.loads(content)
        log.info("[MusicValidator] score=%.2f  %s", result.get("score", 0), result.get("summary", ""))
        return result
    except Exception as exc:
        log.warning("Mac-LLM Validierung fehlgeschlagen: %s", exc)
        return {}


@tool
def validate_music(
    notes: list,
    instrument: str,
    genre: str = "rock",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
) -> str:
    """Bewertet generierte MIDI-Noten auf harmonische/rhythmische Korrektheit via Mac-LLM.

    Gibt Score (0-1), Probleme und Verbesserungsvorschläge zurück.
    Nur verfügbar wenn Mac-LLM (Ollama) auf 192.168.0.4:11434 läuft.

    Args:
        notes: Liste von Note-Dicts {pitch, step, vel, dur}
        instrument: Instrument-Name (z.B. "VD-HEAVY", "VB-ROYAL")
        genre: Genre (rock, jazz, hip-hop, ...)
        key: Tonart (C, A, D, ...)
        scale: Tonleiter (minor, major, ...)
        bars: Anzahl Takte
        bpm: Tempo
    """
    result = validate_music_pattern(notes, instrument, genre, key, scale, bars, bpm)
    if not result:
        return "[validate_music] Mac-LLM nicht erreichbar — Validierung übersprungen."

    score = result.get("score", 0)
    issues = result.get("issues", [])
    suggestions = result.get("suggestions", [])
    summary = result.get("summary", "")

    lines = [f"[validate_music] Score: {score:.2f} — {summary}"]
    if issues:
        lines.append("Probleme: " + "; ".join(issues))
    if suggestions:
        lines.append("Vorschläge: " + "; ".join(suggestions))

    return "\n".join(lines)

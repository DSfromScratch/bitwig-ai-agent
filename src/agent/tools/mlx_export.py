"""
MLX Training Data Export: exportiert validierte Patterns aus Neo4j als JSONL
für MLX LoRA Fine-Tuning auf Apple Silicon (Mac).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

log = logging.getLogger("bitwig-agent")

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _midi_to_name(midi: int) -> str:
    return f"{_NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


def _build_prompt(pattern: dict) -> str:
    inst  = pattern.get("instrument", "synth")
    genre = pattern.get("genre", "electronic")
    key   = pattern.get("key", "C")
    scale = pattern.get("scale", "major")
    bars  = pattern.get("bars") or 2
    bpm   = pattern.get("bpm") or 120
    return (
        f"Erstelle ein {bars}-taktiges Pattern für {inst} im Genre {genre}, "
        f"Tonart {key}-{scale}, {bpm} BPM."
    )


def _build_completion(pattern: dict) -> str:
    score       = pattern.get("avg_score", 0.0)
    suggestions = pattern.get("last_suggestions") or []
    notes_json  = pattern.get("notes_json")

    parts = [f"Score: {score:.2f}"]

    if suggestions:
        if isinstance(suggestions, str):
            suggestions = [suggestions]
        parts.append("Verbesserungen: " + "; ".join(suggestions))

    if notes_json:
        try:
            notes = json.loads(notes_json) if isinstance(notes_json, str) else notes_json
            note_names = [_midi_to_name(n["note"]) for n in notes[:8] if "note" in n]
            if note_names:
                parts.append("Noten: " + ", ".join(note_names))
            parts.append("Pattern:\n" + json.dumps(notes, ensure_ascii=False))
        except Exception:
            pass

    return "\n".join(parts)


def _fetch_patterns(min_score: float, limit: int) -> list[dict]:
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                """
                MATCH (p:ProductionPattern)
                WHERE p.avg_score >= $min_score AND p.iteration >= 2
                RETURN p.instrument AS instrument, p.genre AS genre,
                       p.key AS key, p.scale AS scale,
                       p.avg_score AS avg_score, p.iteration AS iteration,
                       p.last_suggestions AS last_suggestions,
                       p.last_issues AS last_issues,
                       p.last_score AS last_score,
                       p.notes_json AS notes_json,
                       p.bpm AS bpm, p.bars AS bars
                ORDER BY p.avg_score DESC
                LIMIT $limit
                """,
                min_score=min_score, limit=limit,
            ).data()
        driver.close()
        return result
    except Exception as exc:
        log.warning("Neo4j-Export fehlgeschlagen: %s", exc)
        return []


def _theory_examples() -> list[dict]:
    """Statische Music-Theory Trainingsbeispiele für MLX."""
    scales = {
        "C-Dur":   [48, 50, 52, 53, 55, 57, 59, 60],
        "A-Moll":  [57, 59, 60, 62, 64, 65, 67, 69],
        "G-Dur":   [43, 45, 47, 48, 50, 52, 54, 55],
        "D-Moll":  [50, 52, 53, 55, 57, 58, 60, 62],
        "E-Moll":  [52, 54, 55, 57, 59, 60, 62, 64],
        "F-Dur":   [41, 43, 45, 46, 48, 50, 52, 53],
        "B-Moll":  [47, 49, 50, 52, 54, 55, 57, 59],
    }
    chords = {
        "Am": [57, 60, 64], "C":   [60, 64, 67], "F":   [53, 57, 60],
        "G":  [55, 59, 62], "Dm":  [50, 53, 57], "Em":  [52, 55, 59],
        "E":  [52, 56, 59], "Am7": [57, 60, 64, 67], "Cmaj7": [60, 64, 67, 71],
    }
    genre_bpm = {
        "Techno": "130–145 BPM, 4-on-the-floor Kick, minimale Melodien, kurze repetitive Patterns",
        "House":  "120–128 BPM, Off-Beat HiHats, Chord-Stabs auf 2+4, Bass-Groove",
        "DnB":    "160–180 BPM, Amen-Break Variation, Reese Bass, Synth Stabs",
        "Ambient": "60–90 BPM, lange Pads, Reverb-heavy, keine Percussion",
        "Rock":   "100–140 BPM, Gitarren-Riffs, Snare auf 2+4, E-Bass Grundton",
    }

    examples = []

    for name, notes in scales.items():
        names_str = ", ".join(_midi_to_name(n) for n in notes)
        midi_str  = ", ".join(str(n) for n in notes)
        examples.append({"messages": [
            {"role": "user",      "content": f"{name} Skala — MIDI-Noten"},
            {"role": "assistant", "content": f"{name}: [{midi_str}]\nNoten: {names_str}"},
        ]})

    for chord_name, notes in chords.items():
        names_str = ", ".join(_midi_to_name(n) for n in notes)
        examples.append({"messages": [
            {"role": "user",      "content": f"Akkord {chord_name} — MIDI-Noten"},
            {"role": "assistant", "content": f"{chord_name}: {notes} ({names_str})"},
        ]})

    for genre, desc in genre_bpm.items():
        examples.append({"messages": [
            {"role": "user",      "content": f"Genre {genre} — typische Eigenschaften"},
            {"role": "assistant", "content": f"{genre}: {desc}"},
        ]})

    return examples


def export_training_data(
    output_path: str = "./training_data",
    min_score: float = 0.70,
    limit: int = 500,
    include_theory: bool = True,
) -> dict[str, Any]:
    """Exportiert validierte Patterns aus Neo4j als MLX JSONL Training-Daten.

    Erstellt train.jsonl, valid.jsonl und export_stats.json im output_path.
    Format: Chat-Format kompatibel mit mlx-lm LoRA Fine-Tuning.
    """
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    patterns = _fetch_patterns(min_score, limit)
    log.info("[MLX Export] %d Patterns aus Neo4j (min_score=%.2f)", len(patterns), min_score)

    examples: list[dict] = []

    for p in patterns:
        examples.append({"messages": [
            {"role": "user",      "content": _build_prompt(p)},
            {"role": "assistant", "content": _build_completion(p)},
        ]})

        # Fehler-Feedback-Beispiel wenn score < 0.7
        issues = p.get("last_issues") or []
        if issues and (p.get("last_score") or 1.0) < 0.7:
            if isinstance(issues, str):
                issues = [issues]
            examples.append({"messages": [
                {"role": "user",      "content": f"Probleme im Pattern: {'; '.join(issues)}"},
                {"role": "assistant", "content": _build_completion(p)},
            ]})

    if include_theory:
        theory = _theory_examples()
        examples.extend(theory)
        log.info("[MLX Export] +%d Theory-Beispiele", len(theory))

    if not examples:
        return {
            "exported":    False,
            "error":       "Keine Patterns gefunden — Neo4j leer oder min_score zu hoch",
            "train_count": 0,
            "valid_count": 0,
        }

    split_idx = max(1, int(len(examples) * 0.9))
    train_ex  = examples[:split_idx]
    valid_ex  = examples[split_idx:]

    (out_dir / "train.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in train_ex) + "\n",
        encoding="utf-8",
    )
    (out_dir / "valid.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in valid_ex) + "\n",
        encoding="utf-8",
    )

    stats = {
        "exported_at":      datetime.utcnow().isoformat(),
        "neo4j_patterns":   len(patterns),
        "theory_examples":  len(examples) - len(patterns),
        "total_examples":   len(examples),
        "train_count":      len(train_ex),
        "valid_count":      len(valid_ex),
        "min_score":        min_score,
        "output_path":      str(out_dir.resolve()),
    }
    (out_dir / "export_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info("[MLX Export] %d Train + %d Valid → %s", len(train_ex), len(valid_ex), out_dir)
    return {"exported": True, "error": None, **stats}


def get_export_stats(output_path: str = "./training_data") -> dict[str, Any]:
    """Liest Export-Statistiken des letzten Exports."""
    stats_path = Path(output_path) / "export_stats.json"
    if not stats_path.exists():
        return {"error": "Noch kein Export — export_mlx_training_data zuerst aufrufen"}
    try:
        return json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


@tool
def export_mlx_training_data(
    output_path: str = "./training_data",
    min_score: float = 0.70,
    limit: int = 500,
) -> str:
    """Exportiert validierte Patterns aus Neo4j als JSONL für MLX LoRA Fine-Tuning auf Mac.

    Erstellt train.jsonl + valid.jsonl (Chat-Format) + export_stats.json.
    Enthält: Pattern-Generierungs-Beispiele aus Neo4j + Music-Theory-Beispiele.
    Empfehlung: Mindestens 20–30 validate_and_learn-Iterationen vor dem Export.
    """
    result = export_training_data(output_path, min_score, limit)

    if not result.get("exported"):
        return f"[MLX Export] Fehlgeschlagen: {result.get('error')}"

    lines = [
        f"[MLX Export] ✓ {result['train_count']} Train + {result['valid_count']} Valid Beispiele",
        f"Neo4j Patterns: {result['neo4j_patterns']} | Theory: {result['theory_examples']}",
        f"Ausgabe: {result['output_path']}/",
        "",
        "Nächste Schritte (auf Mac Terminal):",
        "  make mlx-setup        # MLX + mlx-lm installieren",
        "  make mlx-sync-data    # Daten auf Mac übertragen",
        "  make mlx-train        # LoRA Fine-Tuning starten",
    ]
    return "\n".join(lines)

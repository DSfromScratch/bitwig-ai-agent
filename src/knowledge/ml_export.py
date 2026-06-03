"""
ML Training-Daten Export für MLX Fine-tuning auf Apple Silicon Mac.

Exportiert ProductionPattern-Knoten aus Neo4j als JSONL-Datei
im MLX-LM LoRA Format: {"prompt": "...", "completion": "..."}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("bitwig-agent")

EXPORT_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))) / "training_data"


def export_patterns_to_jsonl(
    min_score: float = 0.7,
    output_file: str | None = None,
) -> str:
    """Exportiert bewertete Patterns aus Neo4j als JSONL für MLX Fine-tuning.

    Format: {"prompt": "<Kontext>", "completion": "<Empfehlung>"}

    Args:
        min_score: Mindest-Score (Standard: 0.7)
        output_file: Ausgabepfad (Standard: training_data/patterns.jsonl)

    Returns: Pfad zur exportierten Datei
    """
    output_path = Path(output_file or EXPORT_DIR / "patterns.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            patterns = s.run(
                """
                MATCH (p:ProductionPattern)
                WHERE p.avg_score >= $min_score AND p.iteration >= 2
                RETURN p.instrument AS instrument, p.genre AS genre,
                       p.key AS key, p.scale AS scale,
                       p.avg_score AS score, p.iteration AS iterations,
                       p.last_issues AS issues,
                       p.last_suggestions AS suggestions
                ORDER BY p.avg_score DESC
                """,
                min_score=min_score,
            ).data()
        driver.close()
    except Exception as exc:
        return f"Fehler beim Neo4j-Export: {exc}"

    if not patterns:
        return f"Keine Patterns mit Score >= {min_score} gefunden. Erst mehr Patterns validieren."

    examples = []
    for p in patterns:
        instrument  = p.get("instrument", "?")
        genre       = p.get("genre", "?")
        key         = p.get("key", "C")
        scale       = p.get("scale", "minor")
        score       = p.get("score", 0)
        issues      = p.get("issues") or []
        suggestions = p.get("suggestions") or []

        # Prompt: Kontext-Beschreibung
        prompt = (
            f"Du bist ein Musik-Produzent. Bewerte und verbessere ein MIDI-Pattern:\n"
            f"Instrument: {instrument} | Genre: {genre} | Key: {key} {scale}\n"
            f"Was sind die wichtigsten Verbesserungen für dieses Pattern?"
        )

        # Completion: Gelernte Verbesserungen
        completion_parts = []
        if score >= 0.8:
            completion_parts.append(f"Das Pattern ist gut (Score {score:.2f}).")
        else:
            completion_parts.append(f"Score: {score:.2f} — Verbesserungen nötig.")

        if issues:
            completion_parts.append(f"Probleme: {'; '.join(issues)}.")
        if suggestions:
            completion_parts.append(f"Empfehlungen: {'; '.join(suggestions)}.")

        examples.append({
            "prompt":     prompt,
            "completion": " ".join(completion_parts),
        })

    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    log.info("ML-Export: %d Patterns → %s", len(examples), output_path)
    return f"✓ {len(examples)} Patterns exportiert → {output_path}"


def export_validator_conversations(
    min_score: float = 0.6,
    output_file: str | None = None,
) -> str:
    """Exportiert Validator-Konversationen im Chat-Format für instruction fine-tuning.

    Format: {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
    """
    output_path = Path(output_file or EXPORT_DIR / "conversations.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            patterns = s.run(
                """
                MATCH (p:ProductionPattern)
                WHERE p.iteration >= 1
                RETURN p.instrument AS instrument, p.genre AS genre,
                       p.key AS key, p.scale AS scale,
                       p.avg_score AS score,
                       p.last_issues AS issues,
                       p.last_suggestions AS suggestions
                ORDER BY p.avg_score DESC
                LIMIT 500
                """,
            ).data()
        driver.close()
    except Exception as exc:
        return f"Fehler: {exc}"

    if not patterns:
        return "Keine Daten für Konversations-Export."

    examples = []
    for p in patterns:
        instrument  = p.get("instrument", "?")
        genre       = p.get("genre", "?")
        key         = p.get("key", "C")
        scale       = p.get("scale", "minor")
        score       = p.get("score", 0) or 0
        issues      = p.get("issues") or []
        suggestions = p.get("suggestions") or []

        user_msg = (
            f"Bewerte dieses MIDI-Pattern für {instrument} im Genre {genre}, "
            f"Tonart {key} {scale}. Gib Score (0-1), Probleme und Vorschläge."
        )

        quality = "gut" if score >= 0.75 else "verbesserungswürdig"
        asst_parts = [
            f'{{"score": {score:.2f}, "quality": "{quality}"',
            f'"issues": {json.dumps(issues, ensure_ascii=False)}',
            f'"suggestions": {json.dumps(suggestions, ensure_ascii=False)}}}',
        ]

        examples.append({
            "messages": [
                {"role": "user",      "content": user_msg},
                {"role": "assistant", "content": ", ".join(asst_parts)},
            ]
        })

    with open(output_path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    return f"✓ {len(examples)} Konversationen → {output_path}"


def get_export_stats() -> dict:
    """Zeigt Statistiken über vorhandene Trainingsdaten."""
    stats = {}
    for name in ("patterns.jsonl", "conversations.jsonl"):
        path = EXPORT_DIR / name
        if path.exists():
            with open(path) as f:
                lines = sum(1 for _ in f)
            stats[name] = lines
        else:
            stats[name] = 0
    return stats

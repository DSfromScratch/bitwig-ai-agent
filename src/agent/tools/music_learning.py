"""
Musik-Lernschleife: vergleicht generierte Patterns mit Mac-LLM-Bewertung,
speichert Feedback in Neo4j für kontinuierliche Verbesserung.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

log = logging.getLogger("bitwig-agent")


def score_and_learn(
    notes: list[dict],
    instrument: str,
    genre: str = "rock",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
    store_to_neo4j: bool = True,
) -> dict[str, Any]:
    """Validiert Pattern, speichert Feedback in Neo4j, gibt Verbesserungsvorschläge zurück.

    Workflow:
    1. Validiert via Mac-LLM (music_validator)
    2. Speichert score + issues + notes_json in Neo4j (ProductionPattern)
    3. Gibt {score, improved_notes, suggestions} zurück
    """
    from src.agent.tools.music_validator import validate_music_pattern

    validation = validate_music_pattern(notes, instrument, genre, key, scale, bars, bpm)

    if not validation:
        return {"score": None, "notes": notes, "suggestions": [], "learned": False}

    score       = validation.get("score", 0.5)
    issues      = validation.get("issues", [])
    suggestions = validation.get("suggestions", [])

    if store_to_neo4j:
        _store_learning_feedback(
            instrument, genre, key, scale, score, issues, suggestions,
            notes=notes, bpm=bpm, bars=bars,
        )

    log.info("[MusicLearning] %s/%s score=%.2f issues=%d",
             instrument, genre, score, len(issues))

    return {
        "score":       score,
        "notes":       notes,
        "issues":      issues,
        "suggestions": suggestions,
        "learned":     True,
        "needs_improvement": score < 0.7,
    }


def _context_signature(instrument: str, genre: str, key: str, scale: str,
                       bpm: int | None, bars: int | None) -> str:
    """Stabiler Fingerprint pro Validierungs-Kontext — Attempts mit gleicher
    Signature konkurrieren um denselben (prompt, chosen, rejected)-Slot."""
    return f"{instrument}|{genre}|{key}|{scale}|bpm={bpm or '?'}|bars={bars or '?'}"


def _store_learning_feedback(
    instrument: str,
    genre: str,
    key: str,
    scale: str,
    score: float,
    issues: list[str],
    suggestions: list[str],
    notes: list[dict] | None = None,
    bpm: int | None = None,
    bars: int | None = None,
) -> None:
    """Speichert Validierungs-Feedback in Neo4j.

    Schreibt:
    1. ProductionPattern (aggregiert: last_score, avg_score, beste notes_json)
    2. PatternAttempt (jeder Try einzeln — Quelle für DPO-Pair-Extraktion)
    """
    import json as _json
    from datetime import datetime, timezone
    import hashlib

    notes_json = _json.dumps(notes, ensure_ascii=False) if notes else None
    ctx_sig = _context_signature(instrument, genre, key, scale, bpm, bars)
    now_iso = datetime.now(timezone.utc).isoformat()
    # Attempt-ID = stabiler Hash über (Kontext + Noten) → idempotent bei Wiederholungen
    attempt_id = hashlib.sha256(
        f"{ctx_sig}|{notes_json or ''}".encode("utf-8")
    ).hexdigest()[:16]

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            s.run(
                """
                MERGE (p:ProductionPattern {instrument: $inst, genre: $genre, key: $key, scale: $scale})
                SET p.last_score       = $score,
                    p.last_issues      = $issues,
                    p.last_suggestions = $suggestions,
                    p.iteration        = coalesce(p.iteration, 0) + 1,
                    p.avg_score        = (coalesce(p.avg_score, 0) * coalesce(p.iteration, 1) + $score)
                                         / (coalesce(p.iteration, 1) + 1),
                    p.notes_json       = CASE WHEN $score >= 0.7 AND $notes_json IS NOT NULL
                                              THEN $notes_json ELSE p.notes_json END,
                    p.bpm              = CASE WHEN $bpm IS NOT NULL THEN $bpm ELSE p.bpm END,
                    p.bars             = CASE WHEN $bars IS NOT NULL THEN $bars ELSE p.bars END
                """,
                inst=instrument, genre=genre, key=key, scale=scale,
                score=score, issues=issues, suggestions=suggestions,
                notes_json=notes_json, bpm=bpm, bars=bars,
            )
            # Jeder Attempt einzeln — auch failed-Versionen bleiben für DPO erhalten
            if notes_json is not None:
                s.run(
                    """
                    MATCH (p:ProductionPattern {instrument: $inst, genre: $genre, key: $key, scale: $scale})
                    MERGE (a:PatternAttempt {attempt_id: $attempt_id})
                      ON CREATE SET a.created_at = $now,
                                    a.context_signature = $ctx_sig,
                                    a.instrument = $inst,
                                    a.genre = $genre,
                                    a.key = $key,
                                    a.scale = $scale,
                                    a.bpm = $bpm,
                                    a.bars = $bars,
                                    a.notes_json = $notes_json,
                                    a.score = $score,
                                    a.issues = $issues,
                                    a.suggestions = $suggestions,
                                    a.exported_to_dpo = false
                      ON MATCH SET  a.score = $score,
                                    a.issues = $issues,
                                    a.suggestions = $suggestions,
                                    a.last_seen_at = $now
                    MERGE (p)-[:HAS_ATTEMPT]->(a)
                    """,
                    inst=instrument, genre=genre, key=key, scale=scale,
                    bpm=bpm, bars=bars, notes_json=notes_json, score=score,
                    issues=issues, suggestions=suggestions,
                    attempt_id=attempt_id, ctx_sig=ctx_sig, now=now_iso,
                )
        driver.close()
    except Exception as exc:
        log.debug("Neo4j-Feedback-Speicherung fehlgeschlagen: %s", exc)



def get_rag_examples(
    instrument: str,
    genre: str,
    key: str = "C",
    min_score: float = 0.75,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Holt gut bewertete Patterns aus Neo4j als RAG-Beispiele (Ansatz 2).

    Returns: Liste von {instrument, genre, key, avg_score, last_suggestions}
    """
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
                WHERE p.avg_score IS NOT NULL AND p.avg_score >= $min_score
                  AND (p.genre = $genre OR p.instrument = $instrument)
                RETURN p.instrument AS instrument, p.genre AS genre,
                       p.key AS key, p.avg_score AS score,
                       p.last_suggestions AS suggestions,
                       p.iteration AS iterations
                ORDER BY p.avg_score DESC
                LIMIT $limit
                """,
                instrument=instrument, genre=genre,
                min_score=min_score, limit=limit,
            ).data()
        driver.close()
        return result
    except Exception as exc:
        log.debug("RAG-Beispiele konnten nicht geladen werden: %s", exc)
        return []


def get_pattern_history(instrument: str, genre: str) -> dict[str, Any]:
    """Liest gespeichertes Pattern-Feedback aus Neo4j."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                "MATCH (p:ProductionPattern {instrument: $inst, genre: $genre}) "
                "RETURN p.avg_score AS avg_score, p.iteration AS iterations, "
                "       p.last_issues AS issues, p.last_suggestions AS suggestions",
                inst=instrument, genre=genre,
            ).single()
        driver.close()
        return dict(result) if result else {}
    except Exception:
        return {}


@tool
def validate_and_learn(
    notes: list,
    instrument: str,
    genre: str = "rock",
    key: str = "C",
    scale: str = "minor",
    bars: int = 2,
    bpm: int = 120,
) -> str:
    """Validiert generierte Noten via Mac-LLM und speichert Feedback zum Lernen in Neo4j.

    Gibt Score (0-1), erkannte Probleme und Verbesserungsvorschläge zurück.
    Bei Score < 0.7: Noten sollten angepasst werden.
    Bei Score >= 0.7: Pattern ist gut genug.

    Kombiniert music_validator + Neo4j-Lernschleife.
    """
    result = score_and_learn(notes, instrument, genre, key, scale, bars, bpm)

    if not result.get("learned"):
        return "[validate_and_learn] Mac-LLM nicht verfügbar — Validierung übersprungen."

    score    = result["score"]
    quality  = "✓ Gut" if score >= 0.7 else "⚠ Verbesserung empfohlen"
    issues   = result.get("issues", [])
    suggs    = result.get("suggestions", [])

    lines = [f"[validate_and_learn] Score: {score:.2f} {quality}"]
    if issues:
        lines.append("Probleme: " + "; ".join(issues))
    if suggs:
        lines.append("Vorschläge: " + "; ".join(suggs))

    history = get_pattern_history(instrument, genre)
    if history.get("iterations", 0) > 1:
        lines.append(
            f"Lernhistorie: {history['iterations']} Iterationen, "
            f"Ø Score: {history.get('avg_score', 0):.2f}"
        )

    return "\n".join(lines)

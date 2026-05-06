"""HarmonySlave — deterministische Harmonie-Ableitung aus Prompt + Neo4j-Genrewissen.

Ziel:
- keine freie LLM-Improvisation, sondern stabiler Harmonie-Kontext
- liefert erlaubte Pitch-Classes + Register für den Note-Slave
"""
from __future__ import annotations

import logging
import re
from typing import Any

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.harmony-slave")

_PITCH_CLASS = {
    "C": 0, "C#": 1, "DB": 1,
    "D": 2, "D#": 3, "EB": 3,
    "E": 4,
    "F": 5, "F#": 6, "GB": 6,
    "G": 7, "G#": 8, "AB": 8,
    "A": 9, "A#": 10, "BB": 10,
    "B": 11,
}

_SCALE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "blues": [0, 3, 5, 6, 7, 10],
}


def _detect_genre(user_text: str) -> str:
    lower = user_text.lower()
    for g in ("rock", "metal", "blues", "pop", "techno", "house", "ambient", "trap", "hip-hop", "dubstep"):
        if g in lower:
            return g
    return ""


def _neo4j_genre_context(user_text: str) -> dict[str, Any]:
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session, is_available
        if not is_available():
            return {}
    except Exception:
        return {}

    words = [w for w in re.findall(r"\b\w{3,}\b", user_text.lower())][:8]
    if not words:
        return {}

    try:
        with neo4j_session() as s:
            row = s.run(
                """
                MATCH (g:Genre)
                WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w
                       OR toLower(coalesce(g.description, '')) CONTAINS w)
                RETURN g.name AS name, g.key_mode AS key_mode
                LIMIT 1
                """,
                words=words,
            ).single()
            if row:
                return {
                    "genre": (row.get("name") or "").lower(),
                    "key_mode": (row.get("key_mode") or "").lower(),
                }
    except Exception as exc:
        log.debug("HarmonySlave Neo4j-Query fehlgeschlagen: %s", exc)
    return {}


def _extract_root_and_scale(user_text: str, scale_hint: str, genre: str, key_mode: str) -> tuple[str, str]:
    text = f"{user_text} {scale_hint}".lower()
    genre_l = (genre or "").lower()

    # Beispiele: E-Moll, a minor, C-dur, g# moll
    m = re.search(r"\b([a-g](?:#|b)?)\s*[- ]?\s*(moll|minor|dur|major)\b", text)
    if m:
        root = m.group(1).upper().replace("B", "b")
        mode = m.group(2)
        if mode in ("dur", "major"):
            return root, "major"
        # Stilabhängig in minor eher pentatonisch für Rock/Blues/Metal
        if any(k in genre_l for k in ("rock", "blues", "metal")):
            return root, "minor_pentatonic"
        return root, "minor"

    if "pentaton" in text:
        # Root falls separat erwähnt, sonst E für Gitarren-Riffs
        rm = re.search(r"\b([a-g](?:#|b)?)\b", text)
        root = rm.group(1).upper().replace("B", "b") if rm else "E"
        return root, "minor_pentatonic"

    if "blues" in text:
        rm = re.search(r"\b([a-g](?:#|b)?)\b", text)
        root = rm.group(1).upper().replace("B", "b") if rm else "E"
        return root, "blues"

    # Defaults je Genre/Mode
    if any(k in genre_l for k in ("rock", "blues", "metal")):
        return "E", "minor_pentatonic"
    if key_mode == "major" or "pop" in genre_l:
        return "C", "major"
    return "A", "minor"


def _register_for_context(genre: str, instrument_hint: str) -> tuple[int, int]:
    genre_l = (genre or "").lower()
    if "phase-4" in instrument_hint.lower() or any(k in genre_l for k in ("rock", "blues", "metal")):
        return 40, 52
    if "pop" in genre_l:
        return 48, 60
    return 45, 57


def _preferred_pitches(root_pc: int, allowed_pcs: list[int], low: int, high: int) -> list[int]:
    in_range = [p for p in range(low, high + 1) if (p % 12) in allowed_pcs]
    if not in_range:
        return [low, (low + high) // 2, high]

    root_candidates = [p for p in in_range if (p % 12) == root_pc]
    third_candidates = [p for p in in_range if (p % 12) in (((root_pc + 3) % 12), ((root_pc + 4) % 12))]
    fifth_candidates = [p for p in in_range if (p % 12) == ((root_pc + 7) % 12)]

    picks: list[int] = []
    if root_candidates:
        picks.append(root_candidates[0])
    if third_candidates:
        picks.append(third_candidates[min(1, len(third_candidates) - 1)])
    if fifth_candidates:
        picks.append(fifth_candidates[min(1, len(fifth_candidates) - 1)])

    return picks or in_range[:3]


def run_harmony_slave(state: AgentState) -> dict:
    plan = state.get("slave_plan") or {}
    retry = (state.get("slave_retry_counts") or {}).get("harmony", 0)
    user_text = plan.get("user_text", "")
    scale_hint = plan.get("scale", "")
    instrument_hint = plan.get("instrument_hint", "")

    detected_genre = _detect_genre(user_text)
    neo4j_ctx = _neo4j_genre_context(user_text)
    # Explizit im Text genanntes Genre hat Vorrang vor Neo4j-Fuzzy-Match
    genre = detected_genre or neo4j_ctx.get("genre") or ""
    key_mode = neo4j_ctx.get("key_mode") or ("major" if "dur" in user_text.lower() else "minor")

    root, scale_name = _extract_root_and_scale(user_text, scale_hint, genre, key_mode)
    root_pc = _PITCH_CLASS.get(root.upper(), 9)
    intervals = _SCALE_INTERVALS.get(scale_name, _SCALE_INTERVALS["minor"])
    allowed_pcs = sorted({(root_pc + i) % 12 for i in intervals})

    low, high = _register_for_context(genre, instrument_hint)
    preferred = _preferred_pitches(root_pc, allowed_pcs, low, high)

    context = {
        "type": "harmony",
        "genre": genre or "unknown",
        "key": f"{root} {'major' if scale_name == 'major' else 'minor'}",
        "scale_name": scale_name,
        "allowed_pitch_classes": allowed_pcs,
        "register_low": low,
        "register_high": high,
        "preferred_pitches": preferred,
        "target_notes": preferred,
    }

    log.info(
        "HarmonySlave — OK: genre=%s, key=%s, scale=%s, pcs=%s, range=%s-%s",
        context["genre"], context["key"], context["scale_name"],
        context["allowed_pitch_classes"], context["register_low"], context["register_high"],
    )

    return {
        "slave_results": [context],
        "slave_retry_counts": {"harmony": retry},
    }

"""
Reward-Funktion für Bitwig-Agent Tool-Aufrufe.
Bewertet eine Modell-Antwort automatisch mit 0.0–1.0.

Komponenten (je 0.25):
  1. JSON-Validität
  2. Korrekter Tool-Name
  3. Vollständige Parameter
  4. Neo4j-Match (Track / Scale / Projekt)
"""
from __future__ import annotations

import json
import re

def _project_match(query: str, candidates: list[str]) -> bool:
    """Fuzzy-Match: Projekt-Name ohne Satzzeichen, wortbasiert."""
    if not query:
        return True
    import re
    def _words(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())
    q_words = _words(query)
    for c in candidates:
        c_words = _words(c)
        if q_words == c_words or q_words.issubset(c_words) or c_words.issubset(q_words):
            return True
        # Mindestens 60% Wort-Überschneidung
        if c_words and len(q_words & c_words) / max(len(q_words), len(c_words)) >= 0.6:
            return True
    return False


_KEY_DE_TO_EN: dict[str, str] = {
    "cis": "c#", "des": "c#", "dis": "d#", "es": "eb", "eis": "e#",
    "fis": "f#", "ges": "gb", "gis": "g#", "as": "ab", "ais": "a#",
    "b": "bb", "h": "b",
    "dur": "major", "moll": "minor",
}

def _normalize_key(key: str) -> str:
    """Konvertiert deutsche Tonartbezeichnungen → englisch (lowercase)."""
    k = key.lower().replace("-", " ").replace("_", " ")
    parts = k.split()
    out = []
    for p in parts:
        out.append(_KEY_DE_TO_EN.get(p, p))
    return " ".join(out)


VALID_TOOLS = {
    "create_track_from_recipe",
    "reconstruct_project",
    "write_pattern",
    "scan_and_learn_project",
    "get_song_context",
}

REQUIRED_PARAMS: dict[str, list[str]] = {
    "create_track_from_recipe": ["track_name", "project_name"],
    "reconstruct_project":      ["project_name"],
    "write_pattern":            ["track_name", "notes", "length_beats"],
    "scan_and_learn_project":   [],
    "get_song_context":         ["project_name"],
}

_neo4j_cache: dict | None = None


def _neo4j_context() -> dict:
    global _neo4j_cache
    if _neo4j_cache is not None:
        return _neo4j_cache
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            _neo4j_cache = {}
            return {}
        with session() as s:
            track_rows   = s.run("MATCH (sr:SoundRecipe) RETURN sr.track_name AS t").data()
            project_rows = s.run("MATCH (p:BitwigProject) RETURN p.name AS n").data()
            scene_rows   = s.run("MATCH (sc:Scene) RETURN sc.name AS n").data()
            scale_rows   = s.run("MATCH (s:Scale) RETURN s.name_en AS n").data()
        _neo4j_cache = {
            "tracks":   [r["t"].lower() for r in track_rows if r["t"]],
            "projects": [r["n"] for r in project_rows if r["n"]],
            "scenes":   [r["n"].lower() for r in scene_rows if r["n"]],
            "scales":   [r["n"].lower() for r in scale_rows if r["n"]],
        }
    except Exception:
        _neo4j_cache = {}
    return _neo4j_cache


def _extract_json(text: str) -> dict | None:
    """Extrahiert JSON aus Model-Ausgabe (mit oder ohne Markdown-Fences)."""
    text = text.strip()
    # Markdown-Code-Block entfernen
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    # Erstes {} suchen
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None


def score_completion(prompt: str, completion: str) -> tuple[float, dict]:
    """Bewertet eine Modell-Antwort. Gibt (score 0-1, breakdown) zurück."""
    breakdown: dict = {}
    score = 0.0

    # ── 1. JSON-Validität (0.25) ─────────────────────────────────────────────
    parsed = _extract_json(completion)
    if parsed is None:
        breakdown["json"] = False
        return 0.0, breakdown
    breakdown["json"] = True
    score += 0.25

    # ── 2. Tool-Name (0.25) ──────────────────────────────────────────────────
    tool = parsed.get("tool") or parsed.get("action") or ""
    if tool not in VALID_TOOLS:
        # Fuzzy: Teilstring-Match
        tool = next((t for t in VALID_TOOLS if t in tool or tool in t), "")
    breakdown["tool"] = tool or None
    if tool:
        score += 0.25
    else:
        return score, breakdown

    # ── 3. Parameter vollständig (0.25) ──────────────────────────────────────
    args = parsed.get("args") or parsed.get("parameters") or {}
    if not isinstance(args, dict):
        args = {}
    required = REQUIRED_PARAMS.get(tool, [])
    if required:
        present = [p for p in required if p in args]
        param_ratio = len(present) / len(required)
        score += 0.25 * param_ratio
        breakdown["params"] = f"{len(present)}/{len(required)}"
    else:
        score += 0.25
        breakdown["params"] = "n/a"

    # ── 4. Neo4j-Validierung (0.25) ──────────────────────────────────────────
    ctx = _neo4j_context()
    neo4j_ok = False

    if tool == "create_track_from_recipe":
        track = (args.get("track_name") or "").lower()
        project = (args.get("project_name") or "").lower()
        track_ok   = any(track in t or t in track for t in ctx.get("tracks", []))
        project_ok = _project_match(project, ctx.get("projects", []))
        neo4j_ok   = track_ok and project_ok
        breakdown["track_ok"]   = track_ok
        breakdown["project_ok"] = project_ok

    elif tool == "reconstruct_project":
        project = (args.get("project_name") or "").lower()
        neo4j_ok = _project_match(project, ctx.get("projects", []))
        breakdown["project_ok"] = neo4j_ok

    elif tool == "write_pattern":
        notes = args.get("notes")
        # Notes müssen Liste von Dicts mit 'pitch' sein
        notes_ok = (
            isinstance(notes, list)
            and len(notes) > 0
            and isinstance(notes[0], dict)
            and "pitch" in notes[0]
        )
        # Tonart prüfen wenn vorhanden
        key = _normalize_key(args.get("key") or "")
        key_ok = (not key) or any(key in s or s in key for s in ctx.get("scales", []))
        neo4j_ok = notes_ok and key_ok
        breakdown["notes_ok"] = notes_ok
        breakdown["key_ok"]   = key_ok

    elif tool == "scan_and_learn_project":
        neo4j_ok = True   # Kein Argument nötig

    elif tool == "get_song_context":
        project = (args.get("project_name") or "").lower()
        neo4j_ok = not project or _project_match(project, ctx.get("projects", []))
        breakdown["project_ok"] = neo4j_ok

    if neo4j_ok:
        score += 0.25
    breakdown["neo4j"] = neo4j_ok

    return round(min(1.0, score), 3), breakdown


def invalidate_cache() -> None:
    """Cache leeren (nach Neo4j-Updates)."""
    global _neo4j_cache
    _neo4j_cache = None

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


# ── Musiktheorie-Hilfsfunktionen ────────────────────────────────────────────

_SCALE_NOTES_CACHE: dict[str, list[int]] | None = None


def _load_scale_notes() -> dict[str, list[int]]:
    """Lädt Scale.notes aus Neo4j (Pitch-Klassen 0–11)."""
    global _SCALE_NOTES_CACHE
    if _SCALE_NOTES_CACHE is not None:
        return _SCALE_NOTES_CACHE
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            _SCALE_NOTES_CACHE = {}
            return {}
        with session() as s:
            rows = s.run("MATCH (sc:Scale) RETURN sc.name_en AS name, sc.notes AS notes").data()
        _SCALE_NOTES_CACHE = {
            r["name"].lower(): [n % 12 for n in r["notes"]]
            for r in rows if r["name"] and r["notes"]
        }
    except Exception:
        _SCALE_NOTES_CACHE = {}
    return _SCALE_NOTES_CACHE


def key_conformance(notes: list[dict], key: str) -> float:
    """
    Anteil der Noten deren Pitch-Klasse in der Tonart liegt.
    0.0 = alle Noten außerhalb, 1.0 = alle diatonisch.
    """
    if not notes or not key:
        return 1.0  # kein Kontext → neutral

    scale_map = _load_scale_notes()
    key_norm = _normalize_key(key)

    # Versuche exakten Match, dann Teilstring-Match
    scale_pcs: list[int] | None = scale_map.get(key_norm)
    if scale_pcs is None:
        for k, v in scale_map.items():
            if key_norm in k or k in key_norm:
                scale_pcs = v
                break
    if scale_pcs is None:
        return 1.0  # Tonart nicht gefunden → neutral

    scale_set = set(scale_pcs)
    in_key = sum(1 for n in notes if n.get("pitch", 0) % 12 in scale_set)
    return in_key / len(notes)


def rhythm_density_match(notes: list[dict], energy: float, total_steps: int = 64) -> float:
    """
    Bewertet ob Noten-Dichte zur Szenen-Energie passt.
    energy 0.0–1.0: niedrig = spärlich, hoch = dicht.
    score = 1 - |actual_density - expected_density|
    """
    if not notes:
        return 0.5  # keine Noten → neutral

    unique_steps = len({n.get("step", 0) for n in notes})
    actual_density = unique_steps / max(total_steps, 1)

    # Erwartete Dichte: linear 0.1 (bei energy=0) bis 0.8 (bei energy=1)
    expected_density = 0.1 + energy * 0.7

    diff = abs(actual_density - expected_density)
    return max(0.0, 1.0 - diff * 2)  # *2 damit 0.5 Diff = 0 Score


def harmonic_complement(new_notes: list[dict], existing_notes: list[list[dict]]) -> float:
    """
    Bewertet ob neue Noten harmonisch zu bestehenden MIDI-Clips passen.
    Misst: Anteil Pitch-Klassen-Überschneidung (Komplementarität, nicht Identität).
    Ideal: neue Noten füllen Lücken in bestehenden Clips.
    """
    if not new_notes or not existing_notes:
        return 0.8  # kein Kontext → gut (keine Konflikte)

    existing_pcs: set[int] = set()
    for clip_notes in existing_notes:
        for n in clip_notes:
            if isinstance(n, dict):
                existing_pcs.add(n.get("pitch", 0) % 12)

    if not existing_pcs:
        return 0.8

    new_pcs = {n.get("pitch", 0) % 12 for n in new_notes}

    # Komplementarität: neue PCs die nicht in existing sind
    new_only = new_pcs - existing_pcs
    complement_ratio = len(new_only) / max(len(new_pcs), 1)

    # Vollständige Überschneidung ist okay (Verdopplung) aber weniger wertvoll
    # Vollständig neu = 1.0, Hälfte neu = 0.75, komplett identisch = 0.5
    return 0.5 + complement_ratio * 0.5


def musical_reward(
    notes: list[dict],
    key: str = "",
    energy: float = 0.5,
    existing_clips: list[list[dict]] | None = None,
    total_steps: int = 64,
) -> tuple[float, dict]:
    """
    Kombinierter musikalischer Reward (0.0–1.0).

    key_conformance:      40% — Noten diatonisch zur Tonart?
    rhythm_density_match: 30% — Dichte passt zu Szenen-Energie?
    harmonic_complement:  30% — Komplementär zu bestehenden Clips?
    """
    kc = key_conformance(notes, key)
    rd = rhythm_density_match(notes, energy, total_steps)
    hc = harmonic_complement(notes, existing_clips or [])

    score = kc * 0.4 + rd * 0.3 + hc * 0.3
    return round(score, 3), {
        "key_conformance": round(kc, 3),
        "rhythm_density":  round(rd, 3),
        "harmonic_compl":  round(hc, 3),
    }


# ── Key-Normalisierung ───────────────────────────────────────────────────────

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
    "write_pattern_raw",
    "scan_and_learn_project",
    "get_song_context",
}

REQUIRED_PARAMS: dict[str, list[str]] = {
    "create_track_from_recipe": ["track_name", "project_name"],
    "reconstruct_project":      ["project_name"],
    "write_pattern":            ["track_name", "notes", "length_beats"],
    "write_pattern_raw":        ["track_index", "notes", "length_beats"],
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

    elif tool in ("write_pattern", "write_pattern_raw"):
        # notes kann str (JSON) oder Liste sein
        raw_notes = args.get("notes")
        if isinstance(raw_notes, str):
            try:
                raw_notes = json.loads(raw_notes)
            except (json.JSONDecodeError, TypeError):
                raw_notes = None

        notes_ok = (
            isinstance(raw_notes, list)
            and len(raw_notes) > 0
            and isinstance(raw_notes[0], dict)
            and "pitch" in raw_notes[0]
        )
        breakdown["notes_ok"] = notes_ok

        if notes_ok:
            # Musikalischer Reward
            key_raw  = args.get("key") or args.get("description") or ""
            energy   = float(args.get("scene_energy") or 0.5)
            mus_score, mus_breakdown = musical_reward(
                raw_notes, key=key_raw, energy=energy
            )
            breakdown.update(mus_breakdown)
            # neo4j_ok = notes strukturell korrekt + musikalisch > 0.5
            neo4j_ok = mus_score >= 0.5
            # Anteiligen Score addieren (ersetzt fixe 0.25)
            score += 0.35 * mus_score
            breakdown["musical_score"] = mus_score
            # früh rückgeben — Score schon inkl. musikalischem Anteil
            return round(min(1.0, score), 3), breakdown
        else:
            neo4j_ok = False

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

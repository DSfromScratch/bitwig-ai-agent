"""NoteSlave — Drums aus Neo4j-Pattern-Library, Melodie per LLM.

Output: {bpm, length_beats, roles: {role_name: [{step,pitch,vel,dur}, ...]}}
"""
from __future__ import annotations

import json
import logging
import os
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.note-slave")

_DRUM_ROLES = {"kick", "snare", "hihat", "clap", "tom", "openhat", "crash"}

_SYSTEM_PROMPT = """\
Du bist ein MIDI-Kompositions-Spezialist für Bitwig Studio.
Erstelle MIDI-Noten NUR für die angegebenen melodischen Rollen.

Antworte NUR mit einem validen JSON-Objekt — kein Text, kein Markdown, kein <think>.

Format:
{
  "bpm": 174,
  "length_beats": 16,
  "roles": {
    "bass":  [{"step":0.0,"pitch":33,"vel":0.9,"dur":0.5}, ...],
    "pad":   [{"step":0.0,"pitch":45,"vel":0.42,"dur":3.75}, ...]
  }
}

Felder:
  step         — Beat-Position ab 0.0
  pitch        — MIDI-Pitch 0–127
  vel          — Velocity 0.01–1.0 (Akzente: 0.85–1.0, Hintergrund: 0.3–0.5)
  dur          — Dauer in Beats (0.5=Achtel, 1.0=Viertel, 2.0=Halbe)

Regeln:
- Erzeuge NUR die Rollen die im Prompt gelistet sind
- Halte dich strikt an Tonart, Skala und Register (allowed_pitch_classes, register_low–register_high)
- BPM und Genre bestimmen Rhythmik und Energie

Bass-Regeln:
  - 2–4 verschiedene Pitches im angegebenen Register (register_low bis register_low+12)
  - Rhythmisch aktiv: mindestens 8 Noten in 16 Beats
  - Für Reese/Sub-Bass (DnB, Dubstep): tief (register_low), druckvoll, stark synkopiert
  - Für Funk/House: walking bassline mit Oktavsprüngen

Melodische Rollen (lead, melody, chords, pad):
  - Nur Pitches aus allowed_pitch_classes im angegebenen Register
  - lead/melody: 8–16 Noten, melodische Phrase mit Bewegung und Wiederholung
  - chords: Akkord-Voicings (2–4 gleichzeitige Noten mit gleichem step), gehaltene Dauer (1.0–2.0)
  - pad: sparse, lange Noten (dur 2.0–4.0), Atmosphäre, 2–4 Noten gesamt
"""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


# ── Pattern-Library ────────────────────────────────────────────────────────────

def _expand_pattern(notes: list[dict], target: float, period: float) -> list[dict]:
    """Füllt ein kurzes Pattern auf target_beats auf durch Wiederholung."""
    if not notes or period <= 0 or target <= period:
        return notes
    expanded: list[dict] = []
    offset = 0.0
    while offset < target:
        for n in notes:
            new_step = round(n["step"] + offset, 4)
            if new_step >= target:
                break
            expanded.append({**n, "step": new_step})
        offset += period
    return expanded


def _query_drum_patterns(genre: str, roles: list[str], beat_count: float) -> dict[str, list]:
    """Holt Drum-Patterns aus Neo4j und expandiert sie auf beat_count."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session, is_available
        if not is_available():
            return {}
    except Exception:
        return {}

    # Genre-Aliase für Neo4j-Suche
    genre_search = genre.replace("drum and bass", "drum").lower()  # "drum and bass" → "drum"

    found: dict[str, list] = {}
    try:
        with neo4j_session() as s:
            for role in roles:
                row = s.run(
                    """
                    MATCH (p:Pattern)
                    WHERE p.role = $role
                      AND toLower(p.genre) CONTAINS $genre
                    RETURN p.notes_json AS notes_json,
                           p.length_beats AS length_beats,
                           p.id AS id
                    ORDER BY rand() LIMIT 1
                    """,
                    role=role,
                    genre=genre_search,
                ).single()
                if not row:
                    continue
                raw_notes: list = json.loads(row["notes_json"])
                period = float(row["length_beats"])
                expanded = _expand_pattern(raw_notes, beat_count, period)
                found[role] = expanded
                log.info(
                    "NoteSlave: %s → Pattern '%s' (%d→%d Noten, period=%.1f)",
                    role, row["id"], len(raw_notes), len(expanded), period,
                )
    except Exception as exc:
        log.debug("Pattern-Query fehlgeschlagen: %s", exc)

    return found


# ── LLM ───────────────────────────────────────────────────────────────────────

def _get_llm() -> ChatOpenAI:
    base = os.getenv("VLLM_BASE_URL", "http://192.168.0.4:8000") + "/v1"
    model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
    return ChatOpenAI(
        base_url=base,
        api_key="vllm",
        model=model,
        temperature=0.6,
        max_tokens=2400,
        timeout=120,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def _validate_notes(notes: list) -> list:
    valid = []
    for n in notes:
        try:
            # Accept common LLM field-name aliases
            pitch = int(n.get("pitch") if n.get("pitch") is not None else n["note"])
            vel_raw = n.get("vel") if n.get("vel") is not None else n.get("velocity", 0.8)
            vel   = float(vel_raw) / (127.0 if float(vel_raw) > 1.0 else 1.0)
            dur   = float(n.get("dur") if n.get("dur") is not None else n.get("duration", 0.5))
            step  = float(n.get("step") if n.get("step") is not None else n.get("time", n.get("beat", 0.0)))
            if 0 <= pitch <= 127 and 0.0 < vel <= 1.0 and dur > 0 and step >= 0:
                valid.append({"step": step, "pitch": pitch, "vel": vel, "dur": dur})
        except (KeyError, TypeError, ValueError):
            continue
    return valid


def _parse_multitrack_json(text: str, expected_roles: list[str]) -> dict | None:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                pass

    if not data or "roles" not in data:
        return None

    roles_raw = data.get("roles", {})
    if not isinstance(roles_raw, dict):
        return None

    validated: dict[str, list] = {}
    for role in expected_roles:
        raw_notes = roles_raw.get(role, [])
        notes = _validate_notes(raw_notes if isinstance(raw_notes, list) else [])
        if notes:
            validated[role] = notes

    if not validated:
        return None

    return {
        "bpm":          float(data.get("bpm", 120)),
        "length_beats": float(data.get("length_beats", 16)),
        "roles":        validated,
    }


def _find_harmony_context(state: AgentState) -> dict:
    for r in reversed(state.get("slave_results") or []):
        if r.get("type") == "harmony" and "error" not in r:
            return r
    return {}


# ── Haupt-Node ────────────────────────────────────────────────────────────────

def run_note_slave(state: AgentState) -> dict:
    plan       = state.get("slave_plan") or {}
    retry      = (state.get("slave_retry_counts") or {}).get("notes", 0)
    results    = state.get("slave_results") or []

    user_text  = plan.get("user_text", "")
    bpm        = plan.get("bpm", 120)
    beat_count = float(plan.get("beat_count", 16))
    genre      = (plan.get("genre") or "").lower()

    instrument_result = next(
        (r for r in results if r.get("type") == "instrument" and "error" not in r), None
    )
    all_roles = [t["role"] for t in (instrument_result.get("tracks", []) if instrument_result else [])]
    if not all_roles:
        all_roles = ["bass", "lead"]

    drum_roles    = [r for r in all_roles if r in _DRUM_ROLES]
    melodic_roles = [r for r in all_roles if r not in _DRUM_ROLES]

    # ── Stufe 1: Drums aus Pattern-Library ────────────────────────────────────
    drum_notes: dict[str, list] = {}
    if drum_roles and genre:
        drum_notes = _query_drum_patterns(genre, drum_roles, beat_count)

    # Drums ohne Pattern-Treffer → LLM als Fallback
    drums_via_llm = [r for r in drum_roles if r not in drum_notes]
    llm_roles = drums_via_llm + melodic_roles

    final_roles: dict[str, list] = dict(drum_notes)

    # ── Stufe 2: LLM für Melodie (+ fehlende Drums) ───────────────────────────
    if llm_roles:
        harmony = _find_harmony_context(state)

        hint = [
            f"Prompt: {user_text}",
            f"BPM: {bpm}",
            f"Clip-Länge: {beat_count} Beats",
            f"Benötigte Rollen: {', '.join(llm_roles)}",
        ]
        if harmony:
            hint.append(
                f"Tonart: {harmony.get('key', '')}, "
                f"Skala: {harmony.get('scale_name', '')}, "
                f"Erlaubte Pitch-Classes: {harmony.get('allowed_pitch_classes', [])}, "
                f"Register: {harmony.get('register_low', 36)}–{harmony.get('register_high', 84)}"
            )

        user_msg = "\n".join(hint)
        log.info(
            "NoteSlave — LLM-Call (retry=%d, bpm=%s, beats=%s, llm_rollen=%s, pattern_rollen=%s)",
            retry, bpm, beat_count, llm_roles, list(drum_notes.keys()),
        )

        llm = _get_llm()
        response: AIMessage = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])

        raw = response.content or ""
        parsed = _parse_multitrack_json(raw, llm_roles)

        if parsed:
            final_roles.update(parsed["roles"])
        else:
            log.warning("NoteSlave — LLM Parse-Fehler (retry=%d): %s", retry, raw[:150])
            if not final_roles:
                return {
                    "slave_results": [{"type": "notes", "error": "parse_failed",
                                       "raw": raw[:200], "retry": True}],
                    "slave_retry_counts": {"notes": retry + 1},
                }

    if not final_roles:
        log.warning("NoteSlave — keine Noten erzeugt (retry=%d)", retry)
        return {
            "slave_results": [{"type": "notes", "error": "no_notes", "retry": True}],
            "slave_retry_counts": {"notes": retry + 1},
        }

    role_counts = {r: len(final_roles.get(r, [])) for r in all_roles}
    pattern_src = list(drum_notes.keys())
    log.info(
        "NoteSlave — OK: bpm=%s, pattern=%s, llm=%s, noten=%s",
        bpm, pattern_src, llm_roles, role_counts,
    )
    return {
        "slave_results": [{"type": "notes", "bpm": float(bpm),
                           "length_beats": beat_count, "roles": final_roles}],
        "slave_retry_counts": {"notes": retry},
    }

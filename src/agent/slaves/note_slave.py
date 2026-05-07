"""NoteSlave — fokussierter LLM-Call nur für MIDI-Noten-Sequenz.

Produziert max. 20 Noten (~300 Token Output) — weit unter max_tokens-Grenze.
Das Master-Graph behandelt Wiederholungen für längere Clips.
Output wird in slave_results Liste gesammelt (Fan-in via operator.add Reducer).
"""
from __future__ import annotations

import json
import logging
import os
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState
from src.audio.style_rules import (
    apply_dynamics,
    apply_register_hint,
    apply_rhythm_pattern,
    apply_technique,
)

log = logging.getLogger("bitwig-agent.note-slave")

_SYSTEM_PROMPT = """\
Du bist ein MIDI-Kompositions-Spezialist für Bitwig Studio.
Deine einzige Aufgabe: Komponiere eine kurze MIDI-Notensequenz (max. 16 Noten) für die gegebene Anfrage.

Antworte NUR mit einem validen JSON-Objekt — kein Text, keine Erklärung, kein Markdown.

Format:
{
  "bpm": 120,
  "length_beats": 8,
  "notes": [
    {"step": 0.0, "pitch": 64, "vel": 0.9, "dur": 0.5},
    {"step": 0.5, "pitch": 62, "vel": 0.7, "dur": 0.5}
  ]
}

Felder:
- bpm: Tempo (float)
- length_beats: Clip-Länge in Beats (z.B. 8 für 2 Takte, 16 für 4 Takte)
- notes[].step: Beat-Position ab 0.0
- notes[].pitch: MIDI-Pitch 0–127
- notes[].vel: Velocity 0.0–1.0, für Akzente 0.9–1.0, für schwache Schläge 0.5–0.7
- notes[].dur: Dauer in Beats (0.25=Sechzehntel, 0.5=Achtel, 1.0=Viertel)

Regeln:
- Für Rock-, Metal- oder Blues-Riffs bevorzuge den tiefen Gitarrenbereich: E2=40, G2=43, A2=45, B2=47, D3=50, E3=52
- Erzeuge ein wiedererkennbares Hauptmotiv über 2 bis 4 Beats und variiere es danach rhythmisch oder melodisch leicht
- Nutze Power-Riff-Charakter: viele kurze Noten, Akzente auf Downbeats, mindestens 1-2 Offbeat- oder Synkopen-Stellen
- Verwende mindestens 4 verschiedene Pitches wenn die Anfrage ein Riff, Guitar, Rock, Metal oder Blues erwähnt
- Rhythmus variieren: Mix aus 0.25, 0.5 und 1.0 dur Werten; vermeide stumpfe Gleichverteilung nur auf Vierteln
- Velocity dynamisch: starke Schläge (beat 0, 2, 4...) lauter als Zwischennoten; einzelne Ghost-Noten leiser
- Wenn Technik "Palm Mute" erwähnt wird: mehr kurze Noten (dur 0.1-0.25) im tiefen Register, eher harte Downbeat-Akzente
- Wenn Technik "Legato" erwähnt wird: mehr verbundene Phrasen (dur 0.5-1.0), kleine melodische Schritte statt Sprünge
- Wenn Technik "Bend Heavy" oder "Vibrato" erwähnt wird: halte Zielnoten länger (dur 0.75-1.5) und setze Peaks auf Phrasenenden
- Wenn Rhythmus "Gallop" erwähnt wird: baue wiederholt 0.25/0.25/0.5 Gruppen ein
- Wenn Rhythmus "Triplet Feel" erwähnt wird: nutze 0.33/0.66-artige Verteilungen statt strikt gerade Raster
- Wenn Saitenbereich "Low" erwähnt wird: Schwerpunkt E2-D3 (40-50), bei "Mid": D3-G3 (50-55), bei "Lead": G3-E4 (55-64)
- Wenn Dynamik "Accent 1&3" oder "Accent 2&4" erwähnt wird: diese Beats hörbar lauter als die Zwischenzeiten
- Vermeide zu einfache Tonleitern aufwärts/abwärts ohne Motivik
- max. 16 Noten — das Pattern wird extern wiederholt
Kein <think>-Block, keine Erklärung. Nur JSON.
"""

_JSON_RE = re.compile(r'\{.*\}', re.DOTALL)


def _resolve_candidate_count(user_text: str) -> int:
    """Anzahl der zu sammelnden LLM-Kandidaten (mit sicheren Grenzen)."""
    env_val = os.getenv("NOTE_SLAVE_CANDIDATES", "").strip()
    if env_val:
        try:
            return max(1, min(12, int(env_val)))
        except ValueError:
            pass

    txt = user_text.lower()
    if any(k in txt for k in ("riff", "rock", "metal", "blues", "guitar")):
        return 8
    return 4


def _get_llm() -> ChatOpenAI:
    base = os.getenv("VLLM_BASE_URL", "http://192.168.0.4:8000") + "/v1"
    model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
    return ChatOpenAI(
        base_url=base,
        api_key="vllm",
        model=model,
        temperature=0.5,
        max_tokens=600,   # 16 Noten × ~30 Token = ~480, mit Overhead sicher 600
        timeout=90,
    )


def _parse_notes_json(text: str) -> dict | None:
    """Extrahiert {bpm, length_beats, notes} aus dem LLM-Output."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
        if "notes" in data and "bpm" in data:
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(text)
    if match:
        try:
            data = json.loads(match.group())
            if "notes" in data and "bpm" in data:
                return data
        except json.JSONDecodeError:
            pass
    return None


def _validate_notes(notes: list) -> list:
    """Filtert ungültige Noten (pitch out of range, fehlende Felder)."""
    valid = []
    for n in notes:
        try:
            pitch = int(n["pitch"])
            vel = float(n.get("vel", 0.8))
            dur = float(n.get("dur", 0.5))
            step = float(n.get("step", 0.0))
            if 0 <= pitch <= 127 and 0.0 < vel <= 1.0 and dur > 0:
                valid.append({"step": step, "pitch": pitch, "vel": vel, "dur": dur})
        except (KeyError, TypeError, ValueError):
            continue
    return valid


def _find_harmony_context(state: AgentState) -> dict:
    for r in reversed(state.get("slave_results") or []):
        if r.get("type") == "harmony" and "error" not in r:
            return r
    return {}


def _enforce_harmony(notes: list[dict], harmony: dict) -> list[dict]:
    """Projiziert LLM-Noten in den harmonischen Zielraum (Pitch-Class + Register)."""
    if not notes:
        return notes

    allowed_pcs = set(harmony.get("allowed_pitch_classes") or [])
    low = int(harmony.get("register_low", 0))
    high = int(harmony.get("register_high", 127))
    preferred = harmony.get("preferred_pitches") or []

    if not allowed_pcs:
        return notes

    snapped: list[dict] = []
    for n in notes:
        pitch = int(n["pitch"])
        pitch = max(low, min(high, pitch))

        if (pitch % 12) not in allowed_pcs:
            # Suche nächstgelegenen Pitch im erlaubten Tonvorrat innerhalb des Registers
            candidates = [p for p in range(low, high + 1) if (p % 12) in allowed_pcs]
            if candidates:
                pitch = min(candidates, key=lambda p: abs(p - pitch))

        # Leichte Präferenz auf Zieltöne (Root/3rd/5th), ohne harte Quantisierung jeder Note
        if preferred and (n["step"] % 2.0 == 0):
            pitch = min(preferred, key=lambda p: abs(p - pitch))

        snapped.append({**n, "pitch": pitch})

    return snapped


def _break_repetitive_loop(notes: list[dict], harmony: dict) -> list[dict]:
    """Entschärft starre 3/4-Noten-Loops (z. B. 40-43-47-40-...)."""
    if len(notes) < 12:
        return notes

    pitches = [int(n["pitch"]) for n in notes]
    period = 0
    for p in (3, 4):
        matches = sum(1 for i in range(p, len(pitches)) if pitches[i] == pitches[i - p])
        # >70% Wiederholungsquote über die Periode -> mechanischer Loop
        if matches / max(1, len(pitches) - p) >= 0.7:
            period = p
            break
    if not period:
        return notes

    allowed_pcs = set(harmony.get("allowed_pitch_classes") or [])
    low = int(harmony.get("register_low", 0))
    high = int(harmony.get("register_high", 127))
    if not allowed_pcs:
        return notes

    pool = [p for p in range(low, high + 1) if (p % 12) in allowed_pcs]
    if len(pool) < 4:
        return notes

    # Häufigste Töne ermitteln (typisch Root/3rd/5th im Endlos-Loop)
    counts: dict[int, int] = {}
    for p in pitches:
        counts[p] = counts.get(p, 0) + 1
    dominant = {p for p, _ in sorted(counts.items(), key=lambda it: it[1], reverse=True)[:3]}
    alt_pool = [p for p in pool if p not in dominant] or pool

    out: list[dict] = []
    for i, n in enumerate(notes):
        step = float(n.get("step", 0.0))
        pitch = int(n["pitch"])
        vel = float(n.get("vel", 0.8))
        dur = float(n.get("dur", 0.5))

        # Nur Offbeats/Schwachzeiten anfassen, damit Downbeat-Anker erhalten bleiben.
        is_offbeat = abs(step - round(step)) > 1e-6
        if is_offbeat and (i % period == period - 1):
            repl = min(alt_pool, key=lambda p: abs(p - pitch))
            if repl != pitch:
                pitch = repl
                vel = min(1.0, vel + 0.08)
                dur = 0.25 if dur >= 0.5 else dur

        out.append({**n, "pitch": pitch, "vel": vel, "dur": dur})

    return out


def _inject_missing_scale_tones(notes: list[dict], harmony: dict) -> list[dict]:
    """Sorgt dafür, dass nicht nur 2-3 Akkordtöne benutzt werden."""
    if len(notes) < 8:
        return notes

    allowed_pcs = list(harmony.get("allowed_pitch_classes") or [])
    if not allowed_pcs:
        return notes

    low = int(harmony.get("register_low", 0))
    high = int(harmony.get("register_high", 127))
    used_pcs = {int(n["pitch"]) % 12 for n in notes}
    missing_pcs = [pc for pc in allowed_pcs if pc not in used_pcs]
    if not missing_pcs:
        return notes

    out = [dict(n) for n in notes]
    offbeat_idx = [
        i for i, n in enumerate(out)
        if abs(float(n.get("step", 0.0)) - round(float(n.get("step", 0.0)))) > 1e-6
    ]
    if not offbeat_idx:
        return notes

    for j, pc in enumerate(missing_pcs):
        idx = offbeat_idx[j % len(offbeat_idx)]
        cur = int(out[idx]["pitch"])
        candidates = [p for p in range(low, high + 1) if (p % 12) == pc]
        if not candidates:
            continue
        repl = min(candidates, key=lambda p: abs(p - cur))
        out[idx]["pitch"] = repl
        out[idx]["vel"] = min(1.0, float(out[idx].get("vel", 0.8)) + 0.06)

    return out


def _shape_rhythm(notes: list[dict]) -> list[dict]:
    """Bricht monotone 1/8-Raster auf (ohne Step-Positionen umzubauen)."""
    if len(notes) < 8:
        return notes

    uniq_dur = {float(n.get("dur", 0.5)) for n in notes}
    if len(uniq_dur) > 1:
        return notes

    out = [dict(n) for n in notes]
    for i, n in enumerate(out):
        step = float(n.get("step", 0.0))
        # Kurzer Ghost-Hit auf ausgewählten Offbeats
        if abs(step - round(step)) > 1e-6 and i % 4 == 1:
            n["dur"] = 0.25
            n["vel"] = max(0.45, float(n.get("vel", 0.7)) - 0.08)
        # Langer Akzent auf Taktmitte
        if abs(step - 4.0) < 1e-6:
            n["dur"] = 1.0
            n["vel"] = min(1.0, float(n.get("vel", 0.9)) + 0.04)

    return out


def _score_notes(notes: list[dict], harmony: dict, user_text: str) -> float:
    """Bewertet musikalische Qualität für Candidate-Selection."""
    if not notes:
        return -1e9

    score = 0.0
    pitches = [int(n["pitch"]) for n in notes]
    durs = [float(n.get("dur", 0.5)) for n in notes]
    vels = [float(n.get("vel", 0.8)) for n in notes]
    steps = [float(n.get("step", 0.0)) for n in notes]

    unique_pitches = len(set(pitches))
    unique_durs = len(set(durs))
    offbeats = sum(1 for s in steps if abs(s - round(s)) > 1e-6)
    leaps = sum(1 for a, b in zip(pitches, pitches[1:]) if abs(b - a) >= 3)
    vel_span = max(vels) - min(vels) if vels else 0.0

    score += min(7, unique_pitches) * 1.2
    score += min(3, unique_durs) * 1.5
    score += min(8, offbeats) * 0.35
    score += min(6, leaps) * 0.25
    score += min(0.5, vel_span) * 2.0

    # Wiederholungsstrafen für mechanische Periodik
    for p in (2, 3, 4):
        if len(pitches) <= p:
            continue
        matches = sum(1 for i in range(p, len(pitches)) if pitches[i] == pitches[i - p])
        ratio = matches / max(1, len(pitches) - p)
        if ratio > 0.7:
            score -= (ratio - 0.7) * 10.0

    txt = user_text.lower()
    if any(k in txt for k in ("riff", "rock", "metal", "blues", "guitar")):
        if unique_pitches < 4:
            score -= 2.5
        if unique_durs < 2:
            score -= 1.5

    # Leichte Belohnung für Harmonie-Fit (falls Kontext vorhanden)
    allowed_pcs = set(harmony.get("allowed_pitch_classes") or [])
    if allowed_pcs:
        fit = sum(1 for p in pitches if (p % 12) in allowed_pcs) / max(1, len(pitches))
        score += fit * 1.2

    return score


def run_note_slave(state: AgentState) -> dict:
    """Node-Funktion für den Master-Graph.

    Liest slave_plan aus dem State, ruft LLM mit fokussiertem Noten-Prompt auf.
    """
    plan = state.get("slave_plan") or {}
    retry = (state.get("slave_retry_counts") or {}).get("notes", 0)
    user_text = plan.get("user_text", "")
    bpm = plan.get("bpm", 120)
    beat_count = plan.get("beat_count", 8)
    scale = plan.get("scale", "")
    technique = plan.get("technique", "")
    rhythm_pattern = plan.get("rhythm_pattern", "")
    string_register = plan.get("string_register", "")
    dynamics_shape = plan.get("dynamics_shape", "")
    harmony = _find_harmony_context(state)

    hint_parts = [user_text]
    if scale:
        hint_parts.append(f"Tonleiter/Skala: {scale}")
    if technique:
        hint_parts.append(f"Technik: {technique}")
    if rhythm_pattern:
        hint_parts.append(f"Rhythmusmuster: {rhythm_pattern}")
    if string_register:
        hint_parts.append(f"Saitenbereich: {string_register}")
    if dynamics_shape:
        hint_parts.append(f"Dynamikform: {dynamics_shape}")
    if harmony:
        hint_parts.append(
            "Harmonie-Kontext: "
            f"key={harmony.get('key', '')}, scale={harmony.get('scale_name', '')}, "
            f"allowed_pitch_classes={harmony.get('allowed_pitch_classes', [])}, "
            f"register={harmony.get('register_low', 0)}-{harmony.get('register_high', 127)}"
        )
    hint_parts.append(f"BPM: {bpm}, Clip-Länge: {beat_count} Beats (max. 16 Noten, Pattern wird wiederholt)")

    user_msg = "\n".join(hint_parts)

    candidate_count = _resolve_candidate_count(user_text)
    log.info(
        "NoteSlave — LLM-Candidate-Search (retry=%d, bpm=%s, beats=%s, candidates=%d)",
        retry,
        bpm,
        beat_count,
        candidate_count,
    )

    llm = _get_llm()
    best: dict | None = None
    best_score = -1e9
    last_raw = ""

    for i in range(candidate_count):
        response: AIMessage = llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])

        raw = response.content or ""
        last_raw = raw
        parsed = _parse_notes_json(raw)
        if not parsed:
            log.debug("NoteSlave — Kandidat %d/%d: parse_failed", i + 1, candidate_count)
            continue

        notes = _validate_notes(parsed.get("notes", []))
        if harmony:
            notes = _enforce_harmony(notes, harmony)
            notes = _break_repetitive_loop(notes, harmony)
            notes = _inject_missing_scale_tones(notes, harmony)
        notes = _shape_rhythm(notes)
        notes = apply_register_hint(notes, string_register)
        notes = apply_technique(notes, technique)
        notes = apply_rhythm_pattern(notes, rhythm_pattern)
        notes = apply_dynamics(notes, dynamics_shape)
        if not notes:
            log.debug("NoteSlave — Kandidat %d/%d: empty_after_validation", i + 1, candidate_count)
            continue

        score = _score_notes(notes, harmony, user_text)
        log.debug("NoteSlave — Kandidat %d/%d: score=%.3f notes=%d", i + 1, candidate_count, score, len(notes))
        if score > best_score:
            best_score = score
            best = {
                "bpm": float(parsed.get("bpm", bpm)),
                "length_beats": float(parsed.get("length_beats", beat_count)),
                "notes": notes,
            }

    if best:
        log.info("NoteSlave — OK: %d Noten, bpm=%s, best_score=%.3f", len(best["notes"]), best["bpm"], best_score)
        return {
            "slave_results": [{
                "type": "notes",
                "bpm": best["bpm"],
                "length_beats": best["length_beats"],
                "notes": best["notes"],
            }],
            "slave_retry_counts": {"notes": retry},
        }

    log.warning("NoteSlave — Parse-Fehler (retry=%d): %s", retry, last_raw[:100])
    return {
        "slave_results": [{"type": "notes", "error": "parse_failed", "raw": last_raw[:200], "retry": True}],
        "slave_retry_counts": {"notes": retry + 1},
    }

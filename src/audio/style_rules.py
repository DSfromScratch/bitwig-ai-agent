"""Deterministische Stilregeln fuer Note-Postprocessing.

Diese Regeln sind bewusst LLM-unabhaengig und damit stabil testbar.
"""

from __future__ import annotations


def apply_register_hint(notes: list[dict], register_hint: str) -> list[dict]:
    hint = (register_hint or "").lower()
    if not hint:
        return notes

    low, high = 40, 64
    if "low" in hint:
        low, high = 40, 50
    elif "mid" in hint:
        low, high = 50, 55
    elif "lead" in hint:
        low, high = 55, 64

    out: list[dict] = []
    for n in notes:
        p = int(n["pitch"])
        out.append({**n, "pitch": max(low, min(high, p))})
    return out


def apply_rhythm_pattern(notes: list[dict], rhythm_pattern: str) -> list[dict]:
    patt = (rhythm_pattern or "").lower()
    if not patt:
        return notes

    out = [dict(n) for n in notes]
    if "gallop" in patt:
        seq = [0.25, 0.25, 0.5]
        for i, n in enumerate(out):
            n["dur"] = seq[i % len(seq)]
    elif "triplet" in patt:
        seq = [0.33, 0.33, 0.34]
        for i, n in enumerate(out):
            n["dur"] = seq[i % len(seq)]
    elif "chug" in patt:
        for i, n in enumerate(out):
            n["dur"] = 0.25 if i % 2 == 0 else 0.125
            n["vel"] = min(1.0, float(n.get("vel", 0.8)) + (0.08 if i % 2 == 0 else -0.05))
    elif "syncop" in patt:
        for n in out:
            step = float(n.get("step", 0.0))
            if abs(step - round(step)) > 1e-6:
                n["vel"] = min(1.0, float(n.get("vel", 0.8)) + 0.12)
    return out


def apply_technique(notes: list[dict], technique: str) -> list[dict]:
    t = (technique or "").lower()
    if not t:
        return notes

    out = [dict(n) for n in notes]

    if "palm" in t:
        for n in out:
            n["dur"] = min(float(n.get("dur", 0.5)), 0.25)
            n["pitch"] = max(40, min(52, int(n["pitch"])))
            n["vel"] = min(1.0, max(0.45, float(n.get("vel", 0.8))))
    elif "legato" in t:
        prev_pitch = None
        for n in out:
            n["dur"] = max(float(n.get("dur", 0.5)), 0.5)
            p = int(n["pitch"])
            if prev_pitch is not None and abs(p - prev_pitch) > 7:
                p = p - 12 if p > prev_pitch else p + 12
            n["pitch"] = p
            prev_pitch = p
    elif "bend" in t or "vibrato" in t:
        for i, n in enumerate(out):
            if i % 4 == 3 or i == len(out) - 1:
                n["dur"] = max(float(n.get("dur", 0.5)), 0.75)
                n["vel"] = min(1.0, float(n.get("vel", 0.8)) + 0.12)
    elif "arpeggio" in t:
        for i, n in enumerate(out):
            n["vel"] = min(1.0, float(n.get("vel", 0.8)) + (0.08 if i % 3 == 0 else 0.0))

    return out


def apply_dynamics(notes: list[dict], dynamics_shape: str) -> list[dict]:
    d = (dynamics_shape or "").lower()
    if not d:
        return notes

    out = [dict(n) for n in notes]
    if "crescendo" in d:
        count = max(1, len(out) - 1)
        for i, n in enumerate(out):
            n["vel"] = min(1.0, max(0.3, 0.5 + (0.4 * i / count)))
    elif "accent 1&3" in d:
        for n in out:
            beat = int(float(n.get("step", 0.0))) % 4
            if beat in (0, 2):
                n["vel"] = min(1.0, float(n.get("vel", 0.8)) + 0.12)
    elif "accent 2&4" in d:
        for n in out:
            beat = int(float(n.get("step", 0.0))) % 4
            if beat in (1, 3):
                n["vel"] = min(1.0, float(n.get("vel", 0.8)) + 0.12)
    return out

#!/usr/bin/env python3
"""Trial-Harness: Composer ↔ Validator Closed-Loop mit iterativem Self-Refine.

Architektur:
  * Composer  = Fine-tuned MLX-Agent (Mac, Port 8080) → generiert write_pattern_raw
  * Validator = score_completion (deterministischer musikalischer Reward + Neo4j)
  * Referenz  = (:Song)/(:GenrePattern)-Knoten aus Neo4j als Constraint (--with-kb)

Pro Trial:
  1. Ziehe (optional) eine Referenz aus Neo4j (Song mit Genre/Key/BPM ODER GenrePattern)
  2. Baue Prompt mit Constraints (BPM/Key/Genre/Energie)
  3. Composer generiert Pattern → Validator scort
  4. Score < Threshold → Feedback anhängen, erneut (bis max_iterations)
  5. Logge jede Iteration als JSONL-Zeile + CSV

Vergleich KB-Effekt:
  python -m scripts.trial_compose_validate --trials 8 --with-kb   --out-tag with_kb
  python -m scripts.trial_compose_validate --trials 8 --no-kb     --out-tag no_kb
  python -m scripts.analyze_trials   # wertet beide aus

Usage:
  python -m scripts.trial_compose_validate --trials 8 --max-iterations 3 --threshold 0.8
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv

load_dotenv()

import requests

from src.agent.tools.music.reward import score_completion

COMPOSER_URL = os.getenv(
    "COMPOSER_URL", "http://192.168.0.4:8080/v1/chat/completions")
COMPOSER_MODEL = os.getenv("COMPOSER_MODEL", "mlx-community/Qwen3-8B-4bit")

OUT_DIR = Path("training_data/trials")

SYSTEM_PROMPT = """/no_think
Du bist ein Bitwig Studio AI-Komponist. Erzeuge Patterns mit dem Tool
write_pattern_raw. Antworte NUR mit einem JSON-Tool-Aufruf:
{"tool": "write_pattern_raw", "args": {"track_index": 0, "notes": [...],
 "length_beats": 4, "bpm": <int>, "genre": "<genre>"}}

notes ist eine Liste endlicher Dicts (max ~24), je:
  {"pitch": 0-127, "start": <beat-offset float>, "dur": <beat float>, "vel": 0.0-1.0}
Drums (GM): Kick=36, Snare=38, HiHat=42. Beende das JSON sauber.
Niemals endlose Wiederholungen — halte dich an length_beats."""


# ── Referenz aus Neo4j (w3-ref-songs) ────────────────────────────────────────

def fetch_references(with_kb: bool, n: int) -> list[dict[str, Any]]:
    """Zieht bis zu n Referenzen aus Neo4j: bevorzugt GenrePattern (Drum-fokus),
    fällt auf Songs zurück. Ohne KB: generische Genre-Liste ohne Neo4j-Features."""
    generic = [
        {"name": "Techno", "bpm": 130, "key": None, "energy": 0.8, "ref": None},
        {"name": "House", "bpm": 124, "key": None, "energy": 0.7, "ref": None},
        {"name": "Hip Hop", "bpm": 90, "key": None, "energy": 0.6, "ref": None},
        {"name": "Funk", "bpm": 105, "key": None, "energy": 0.7, "ref": None},
        {"name": "Drum and Bass", "bpm": 174, "key": None, "energy": 0.9, "ref": None},
        {"name": "Disco", "bpm": 120, "key": None, "energy": 0.7, "ref": None},
        {"name": "Trap", "bpm": 140, "key": None, "energy": 0.6, "ref": None},
        {"name": "Dubstep", "bpm": 140, "key": None, "energy": 0.8, "ref": None},
    ]
    if not with_kb:
        return (generic * ((n // len(generic)) + 1))[:n]

    refs: list[dict[str, Any]] = []
    try:
        from scripts._neo4j_song_prompts import fetch_genre_patterns
        for g in fetch_genre_patterns(limit=n * 2):
            keys = g.get("keys") or []
            refs.append({
                "name": g["name"],
                "bpm": int(round(float(g.get("bpm") or 120))),
                "key": keys[0] if keys else None,
                "energy": float(g.get("energy") or 0.6),
                "onset_steps": g.get("onset_steps") or [],
                "ref": "GenrePattern",
            })
    except Exception as exc:
        print(f"⚠ GenrePattern-Referenzen nicht verfügbar: {exc}")

    if len(refs) < n:
        try:
            from scripts._neo4j_song_prompts import fetch_song_anchors
            for s in fetch_song_anchors(limit=n * 2):
                refs.append({
                    "name": s.get("title") or "Song",
                    "artist": s.get("artist"),
                    "bpm": int(round(float(s.get("bpm") or 120))),
                    "key": s.get("key"),
                    "energy": 0.6,
                    "ref": "Song",
                })
        except Exception as exc:
            print(f"⚠ Song-Referenzen nicht verfügbar: {exc}")

    if not refs:
        print("⚠ Neo4j leer — falle auf generische Referenzen zurück")
        return (generic * ((n // len(generic)) + 1))[:n]
    return (refs * ((n // len(refs)) + 1))[:n]


def build_prompt(ref: dict[str, Any], with_kb: bool) -> str:
    """Baut den Composer-Prompt. Mit KB: reichhaltige Constraints aus Neo4j."""
    genre = ref["name"]
    bpm = ref["bpm"]
    if with_kb and ref.get("ref"):
        parts = [f"Schreibe ein {genre} Drum-Pattern, {bpm} BPM, 1 Takt (4 Beats)."]
        if ref.get("energy") is not None:
            lvl = "dicht/energetisch" if ref["energy"] >= 0.7 else "sparsam/relaxed"
            parts.append(f"Energie: {ref['energy']:.0%} ({lvl}).")
        if ref.get("onset_steps"):
            parts.append(
                f"Orientiere die Akzente am Rhythmus-Skelett (16tel-Steps): "
                f"{ref['onset_steps']}.")
        parts.append("Kick/Snare/HiHat, write_pattern_raw, sauber terminiert.")
        return " ".join(parts)
    return (f"Schreibe ein {genre} Drum-Pattern, {bpm} BPM, 1 Takt (4 Beats), "
            f"mit Kick, Snare und HiHat. Nutze write_pattern_raw.")


# ── Composer (MLX) ───────────────────────────────────────────────────────────

def compose(messages: list[dict], max_tokens: int = 1200,
            temperature: float = 0.4) -> tuple[str, float]:
    """Ruft den Composer auf. Gibt (output_text, latency_s) zurück."""
    t0 = time.time()
    try:
        r = requests.post(COMPOSER_URL, json={
            "model": COMPOSER_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }, timeout=120)
        dt = time.time() - t0
        if r.status_code != 200:
            return "", dt
        msg = r.json()["choices"][0]["message"]
        content = msg.get("content") or ""
        if not content.strip() and msg.get("reasoning"):
            content = msg["reasoning"]
        return content.strip(), dt
    except Exception as exc:
        print(f"  ⚠ Composer-Fehler: {exc}")
        return "", time.time() - t0


def _feedback(score: float, breakdown: dict) -> str:
    """Baut eine kurze Korrektur-Anweisung aus dem Validator-Breakdown."""
    hints = []
    if not breakdown.get("json"):
        hints.append("Dein JSON war ungültig oder unvollständig (nicht terminiert). "
                     "Gib ein KOMPLETTES, kurzes JSON aus.")
    if breakdown.get("notes_ok") is False:
        hints.append("Die notes-Liste fehlte oder war leer.")
    if breakdown.get("rhythm_density", 1.0) < 0.4:
        hints.append("Die Notendichte passt nicht — weniger/mehr Onsets, "
                     "aber bleibe innerhalb 4 Beats.")
    if breakdown.get("key_conformance", 1.0) < 0.6:
        hints.append("Halte die Tonhöhen in der angegebenen Tonart.")
    if not hints:
        hints.append("Verbessere das Pattern leicht und halte es kompakt.")
    return ("Der vorige Versuch erreichte Score "
            f"{score:.2f}. " + " ".join(hints) +
            " Antworte erneut NUR mit dem JSON-Tool-Aufruf.")


# ── Trial-Loop ───────────────────────────────────────────────────────────────

def run_trial(trial_id: int, ref: dict[str, Any], with_kb: bool,
              max_iterations: int, threshold: float) -> list[dict[str, Any]]:
    """Führt einen Trial mit bis zu max_iterations Composer↔Validator-Runden aus."""
    prompt = build_prompt(ref, with_kb)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    rows: list[dict[str, Any]] = []
    best_score = 0.0

    for it in range(1, max_iterations + 1):
        output, latency = compose(messages)
        score, breakdown = score_completion(prompt, output)
        best_score = max(best_score, score)
        rows.append({
            "trial_id": trial_id,
            "iteration": it,
            "genre": ref["name"],
            "with_kb": with_kb,
            "ref_type": ref.get("ref"),
            "score": round(score, 3),
            "best_score": round(best_score, 3),
            "latency_s": round(latency, 2),
            "finish_ok": breakdown.get("json", False),
            "musical_score": breakdown.get("musical_score"),
            "prompt": prompt,
            "output": output[:2000],
        })
        flag = "✅" if score >= threshold else "·"
        print(f"  T{trial_id} it{it} {flag} score={score:.2f} "
              f"({ref['name']}, {latency:.1f}s)")
        if score >= threshold:
            break
        # Feedback für nächste Iteration anhängen
        messages = messages + [
            {"role": "assistant", "content": output or "(leer)"},
            {"role": "user", "content": _feedback(score, breakdown)},
        ]
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", type=int, default=8)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=0.8)
    kb = ap.add_mutually_exclusive_group()
    kb.add_argument("--with-kb", dest="with_kb", action="store_true", default=True,
                    help="Neo4j-Referenzen als Constraint nutzen (Default)")
    kb.add_argument("--no-kb", dest="with_kb", action="store_false",
                    help="Ohne Neo4j-Constraints (Baseline)")
    ap.add_argument("--out-tag", default=None,
                    help="Suffix für Output-Dateien (Default: with_kb/no_kb)")
    args = ap.parse_args(argv)

    tag = args.out_tag or ("with_kb" if args.with_kb else "no_kb")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = OUT_DIR / f"trials_{tag}.jsonl"
    csv_path = OUT_DIR / f"trials_{tag}.csv"

    refs = fetch_references(args.with_kb, args.trials)
    print(f"🎼 {args.trials} Trials | KB={'an' if args.with_kb else 'aus'} | "
          f"max_iter={args.max_iterations} | threshold={args.threshold}")
    print(f"   Composer: {COMPOSER_URL}")

    all_rows: list[dict[str, Any]] = []
    for tid in range(1, args.trials + 1):
        ref = refs[(tid - 1) % len(refs)]
        all_rows.extend(run_trial(tid, ref, args.with_kb,
                                  args.max_iterations, args.threshold))

    # JSONL (vollständig) + CSV (kompakt, für Stats)
    with jsonl_path.open("w") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    csv_cols = ["trial_id", "iteration", "genre", "with_kb", "ref_type",
                "score", "best_score", "latency_s", "finish_ok", "musical_score"]
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_cols)
        w.writeheader()
        for row in all_rows:
            w.writerow({k: row.get(k) for k in csv_cols})

    # Kurz-Auswertung
    by_trial: dict[int, float] = {}
    for row in all_rows:
        by_trial[row["trial_id"]] = max(
            by_trial.get(row["trial_id"], 0.0), row["score"])
    solved = sum(1 for s in by_trial.values() if s >= args.threshold)
    mean_best = sum(by_trial.values()) / max(len(by_trial), 1)
    print(f"\n✅ {len(all_rows)} Iterationen, {len(by_trial)} Trials")
    print(f"   gelöst (≥{args.threshold}): {solved}/{len(by_trial)}")
    print(f"   mean best-score: {mean_best:.3f}")
    print(f"   → {jsonl_path}\n   → {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

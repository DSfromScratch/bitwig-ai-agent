#!/usr/bin/env python3
"""
Extrahiert DPO-Paare aus Live-PatternAttempts in Neo4j.

Idee: validate_and_learn() schreibt seit dieser Version JEDEN Versuch als
:PatternAttempt mit Score + Noten. Wenn für dieselbe context_signature
mehrere Attempts mit Score-Differenz ≥ MIN_CONTRAST existieren, ist das
ein natürliches DPO-Paar (chosen = bester Attempt, rejected = schlechtester).

Im Gegensatz zu scripts/generate_dpo_pairs.py:
  - keine LLM-Generierung nötig (Daten kommen aus echten Agent-Runs)
  - keine fixe Ground-Truth — Validator entscheidet
  - idempotent: bereits exportierte Attempts werden via a.exported_to_dpo=true markiert

Run:
    python scripts/extract_dpo_from_attempts.py
    python scripts/extract_dpo_from_attempts.py --min-contrast 0.25 --out training_data/dpo_train.jsonl
    python scripts/extract_dpo_from_attempts.py --reset-exported   (alle Attempts wieder exportierbar)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.knowledge.neo4j_graph import session  # noqa: E402

_SYSTEM_PROMPT = (
    "/no_think\n"
    "Du bist ein Bitwig Studio AI-Assistent. Du erzeugst MIDI-Patterns als "
    "JSON Tool-Aufrufe für write_pattern.\n\n"
    "Antworte NUR mit einem JSON Tool-Aufruf im Format:\n"
    '{"tool": "write_pattern", "args": {"track_name": "...", "notes": [...], '
    '"length_beats": N, "key": "..."}}\n\n'
    'notes MUSS eine Liste von Dicts sein: '
    '[{"step": 0, "pitch": 60, "velocity": 80, "duration": 0.4}, ...]\n'
)


def _user_prompt(instrument: str, genre: str, key: str, scale: str,
                 bpm: int | None, bars: int | None) -> str:
    """Rekonstruiert den User-Prompt aus dem Pattern-Kontext."""
    parts = [f"Schreibe ein {genre}-Pattern für {instrument}"]
    parts.append(f"in {key} {scale}")
    if bars:
        parts.append(f"über {bars} Takte")
    if bpm:
        parts.append(f"bei {bpm} BPM")
    return " ".join(parts) + "."


def _completion_for(notes_json: str, instrument: str, key: str,
                    bars: int | None) -> str:
    """Wandelt rohe Noten in die erwartete Tool-Call-Struktur."""
    try:
        notes = json.loads(notes_json)
    except Exception:
        return notes_json
    length_beats = float((bars or 2) * 4)  # 4 Beats pro Takt
    return json.dumps({
        "tool": "write_pattern",
        "args": {
            "track_name": instrument,
            "notes": notes,
            "length_beats": length_beats,
            "key": key,
        },
    }, ensure_ascii=False)


def _pair_hash(prompt: str, chosen: str, rejected: str) -> str:
    h = hashlib.sha256()
    h.update(prompt.encode())
    h.update(b"|")
    h.update(chosen.encode())
    h.update(b"|")
    h.update(rejected.encode())
    return h.hexdigest()[:16]


def _load_existing_hashes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
            seen.add(_pair_hash(obj["prompt"], obj["chosen"], obj["rejected"]))
        except Exception:
            continue
    return seen


def extract_pairs(min_contrast: float, max_per_context: int) -> list[dict]:
    """Holt aus Neo4j alle Attempt-Cluster und baut DPO-Paare."""
    query = """
        MATCH (a:PatternAttempt)
        WHERE a.exported_to_dpo = false OR a.exported_to_dpo IS NULL
        WITH a.context_signature AS sig, collect(a) AS attempts
        WHERE size(attempts) >= 2
        RETURN sig, attempts
    """
    pairs: list[dict] = []
    used_attempt_ids: list[str] = []

    with session() as s:
        rows = s.run(query).data()
        for row in rows:
            attempts = sorted(
                [dict(a) for a in row["attempts"]],
                key=lambda x: x.get("score") or 0.0,
            )
            worst, best = attempts[0], attempts[-1]
            if (best.get("score") or 0) - (worst.get("score") or 0) < min_contrast:
                continue
            if not worst.get("notes_json") or not best.get("notes_json"):
                continue
            if worst["notes_json"] == best["notes_json"]:
                continue

            user_msg = _user_prompt(
                best["instrument"], best["genre"], best["key"], best["scale"],
                best.get("bpm"), best.get("bars"),
            )
            prompt = _SYSTEM_PROMPT + "\n" + user_msg
            chosen = _completion_for(
                best["notes_json"], best["instrument"], best["key"], best.get("bars"),
            )
            rejected = _completion_for(
                worst["notes_json"], worst["instrument"], worst["key"], worst.get("bars"),
            )

            pairs.append({
                "prompt": prompt,
                "chosen": chosen,
                "rejected": rejected,
                "user_message": user_msg,
                "metadata": {
                    "context_signature": row["sig"],
                    "chosen_score": best["score"],
                    "rejected_score": worst["score"],
                    "score_delta": round(best["score"] - worst["score"], 3),
                    "rejected_issues": worst.get("issues") or [],
                    "best_suggestions": best.get("suggestions") or [],
                },
            })
            used_attempt_ids.extend([best["attempt_id"], worst["attempt_id"]])

            if len(pairs) >= max_per_context * len(rows):
                break

    return pairs, used_attempt_ids


def _mark_exported(attempt_ids: list[str]) -> None:
    if not attempt_ids:
        return
    with session() as s:
        s.run(
            "MATCH (a:PatternAttempt) WHERE a.attempt_id IN $ids "
            "SET a.exported_to_dpo = true",
            ids=attempt_ids,
        )


def _reset_exported() -> int:
    with session() as s:
        r = s.run(
            "MATCH (a:PatternAttempt) WHERE a.exported_to_dpo = true "
            "SET a.exported_to_dpo = false RETURN count(a) AS n"
        ).single()
        return int(r["n"]) if r else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--min-contrast", type=float, default=0.20,
                   help="Mindest-Score-Differenz für gültiges Paar (Default 0.20)")
    p.add_argument("--max-per-context", type=int, default=3,
                   help="Wie viele Paare pro Kontext maximal (Default 3)")
    p.add_argument("--out", type=Path, default=Path("training_data/dpo_train.jsonl"),
                   help="Ziel-JSONL (append-only mit Dedup)")
    p.add_argument("--reset-exported", action="store_true",
                   help="Setzt alle exported_to_dpo Flags zurück und beendet sich")
    p.add_argument("--dry-run", action="store_true",
                   help="Findet Paare, schreibt aber nichts (keine Markierung)")
    args = p.parse_args()

    if args.reset_exported:
        n = _reset_exported()
        print(f"✓ {n} PatternAttempts wieder exportierbar")
        return 0

    print(f"→ Suche Paare mit Score-Delta ≥ {args.min_contrast} …")
    pairs, attempt_ids = extract_pairs(args.min_contrast, args.max_per_context)
    print(f"  {len(pairs)} Paar-Kandidaten gefunden")

    if not pairs:
        print("(nichts zu exportieren)")
        return 0

    existing_hashes = _load_existing_hashes(args.out)
    new_lines: list[str] = []
    skipped = 0
    for pair in pairs:
        h = _pair_hash(pair["prompt"], pair["chosen"], pair["rejected"])
        if h in existing_hashes:
            skipped += 1
            continue
        new_lines.append(json.dumps(pair, ensure_ascii=False))
        existing_hashes.add(h)

    print(f"  {len(new_lines)} neu, {skipped} bereits in {args.out.name}")

    if args.dry_run:
        for line in new_lines[:3]:
            obj = json.loads(line)
            print(f"  • Δ={obj['metadata']['score_delta']} ctx={obj['metadata']['context_signature']}")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as f:
        for line in new_lines:
            f.write(line + "\n")

    _mark_exported(attempt_ids)
    print(f"✓ Geschrieben: {args.out}")
    print(f"✓ {len(attempt_ids)} Attempts als exportiert markiert")
    return 0


if __name__ == "__main__":
    sys.exit(main())

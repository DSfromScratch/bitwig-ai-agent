"""Analysiert Trainings-Fehler und Wiederholungen.

Zwei Datenquellen:
  1. Neo4j (:PatternAttempt) — Self-Refine-Retries (gleiche context_signature ≥ 2× = Modell hat
     beim ersten Versuch gepatzt). Felder: score, issues, suggestions.
  2. training_data/dpo_train.jsonl — alle `rejected`-Samples sind by-definition Fails;
     wir clustern sie nach user_message-Prefix + häufigen Fehlermustern (leere args,
     write_pattern ohne notes, falsche key-Strings, etc.).

Output: Top-N Problemcluster mit Beispiel-Prompts, sortiert nach Häufigkeit.
Nutzen: gezielt weitere DPO-Pairs für die schwierigen Fälle generieren.

Beispiel:
    python -m scripts.analyze_training_failures
    python -m scripts.analyze_training_failures --top 20 --min-retries 2
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


# ── Quelle 1: Neo4j PatternAttempts ───────────────────────────────────────────

def fetch_retry_clusters(min_retries: int = 2) -> list[dict]:
    """Findet context_signatures mit ≥ min_retries Attempts. Returns sorted by count desc."""
    try:
        from src.knowledge.neo4j_graph import is_available, session
    except Exception as e:
        print(f"⚠ Neo4j-Import fehlgeschlagen: {e}")
        return []
    if not is_available():
        print("⚠ Neo4j nicht erreichbar")
        return []

    query = """
    MATCH (a:PatternAttempt)
    WITH a.context_signature AS sig,
         collect({score: a.score, issues: a.issues, suggestions: a.suggestions,
                  instrument: a.instrument, genre: a.genre, key: a.key,
                  bpm: a.bpm, bars: a.bars, created_at: a.created_at}) AS attempts
    WHERE size(attempts) >= $min_retries
    RETURN sig, attempts, size(attempts) AS n
    ORDER BY n DESC
    """
    with session() as s:
        rows = list(s.run(query, min_retries=min_retries))
    return [{"signature": r["sig"], "n_attempts": r["n"], "attempts": r["attempts"]}
            for r in rows]


def fetch_low_score_attempts(threshold: float = 0.5, limit: int = 50) -> list[dict]:
    """Alle PatternAttempts mit score < threshold."""
    try:
        from src.knowledge.neo4j_graph import is_available, session
    except Exception:
        return []
    if not is_available():
        return []
    query = """
    MATCH (a:PatternAttempt)
    WHERE a.score < $thr
    RETURN a.context_signature AS sig, a.score AS score,
           a.issues AS issues, a.suggestions AS suggestions,
           a.instrument AS instrument, a.genre AS genre,
           a.key AS key, a.bpm AS bpm, a.bars AS bars
    ORDER BY a.score ASC
    LIMIT $limit
    """
    with session() as s:
        return [dict(r) for r in s.run(query, thr=threshold, limit=limit)]


# ── Quelle 2: DPO jsonl ───────────────────────────────────────────────────────

_FAIL_PATTERNS = [
    ("rejected_empty",        re.compile(r'^\s*$')),
    ("rejected_no_json",      re.compile(r'^(?!.*\{).*', re.DOTALL)),
    ("rejected_no_tool",      re.compile(r'\{[^}]*\}', re.DOTALL)),
    ("write_pattern_no_notes",
        re.compile(r'"tool"\s*:\s*"write_pattern".*?"args"\s*:\s*\{[^}]*\}(?![^}]*"notes")', re.DOTALL)),
    ("invalid_key_string",
        re.compile(r'"key"\s*:\s*"[^"]*(?:dur|minor[_ ]minor|major[_ ]minor)', re.IGNORECASE)),
    ("missing_tool_field",
        re.compile(r'^\{(?:(?!"tool").)*\}\s*$', re.DOTALL)),
]


def classify_rejected(rejected: str) -> str:
    """Heuristik: welches Fehlermuster matched?"""
    if not rejected.strip():
        return "empty"
    if "{" not in rejected:
        return "no_json"
    if '"tool"' not in rejected:
        return "missing_tool_field"
    if '"tool":"write_pattern"' in rejected.replace(" ", "") and '"notes"' not in rejected:
        return "write_pattern_no_notes"
    if re.search(r'"key"\s*:\s*"[^"]*dur', rejected, re.IGNORECASE):
        return "german_key_string"
    if re.search(r'"args"\s*:\s*\{\s*\}', rejected):
        return "empty_args"
    return "other"


def analyze_dpo_jsonl(path: Path) -> dict:
    if not path.exists():
        return {"total": 0, "by_pattern": {}, "samples": {}}

    by_pattern: Counter = Counter()
    samples: dict[str, list[dict]] = defaultdict(list)
    by_prompt_prefix: Counter = Counter()

    with path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            rejected = row.get("rejected", "")
            user_msg = row.get("user_message", "")
            cls = classify_rejected(rejected)
            by_pattern[cls] += 1
            if len(samples[cls]) < 3:
                samples[cls].append({"user_message": user_msg[:120],
                                     "rejected": rejected[:200]})
            # Prefix-Cluster (erste 6 Wörter)
            prefix = " ".join(user_msg.split()[:6]).lower()
            if prefix:
                by_prompt_prefix[prefix] += 1

    return {
        "total":            sum(by_pattern.values()),
        "by_pattern":       dict(by_pattern.most_common()),
        "samples":          dict(samples),
        "top_prompt_prefixes": dict(by_prompt_prefix.most_common(15)),
    }


# ── Issue-Aggregation aus PatternAttempts ─────────────────────────────────────

def aggregate_issues(attempts: list[dict]) -> Counter:
    """Issues sind in PatternAttempts als JSON-String gespeichert."""
    counter: Counter = Counter()
    for a in attempts:
        raw = a.get("issues")
        if not raw:
            continue
        try:
            issues = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue
        if isinstance(issues, list):
            for i in issues:
                counter[str(i)[:80]] += 1
        elif isinstance(issues, str):
            counter[issues[:80]] += 1
    return counter


# ── Main ──────────────────────────────────────────────────────────────────────

def main(top: int = 10, min_retries: int = 2,
         dpo_path: str = "training_data/dpo_train.jsonl",
         score_threshold: float = 0.5) -> dict:
    print("═" * 70)
    print(" TRAININGS-FEHLER-ANALYSE")
    print("═" * 70)

    # ── 1. PatternAttempt-Retries ──────────────────────────────────────────────
    print(f"\n[1] Self-Refine-Retries (Neo4j PatternAttempts, ≥ {min_retries} pro Kontext)")
    print("─" * 70)
    retries = fetch_retry_clusters(min_retries=min_retries)
    if not retries:
        print("  (keine — entweder Neo4j leer oder noch keine Retries passiert)")
    else:
        for i, c in enumerate(retries[:top], 1):
            atts = c["attempts"]
            scores = [a.get("score") or 0 for a in atts]
            print(f"  {i:2}. {c['n_attempts']:>2}× sig={c['signature'][:40]}…")
            print(f"      scores: {[f'{s:.2f}' for s in scores]}")
            issues_cnt = aggregate_issues(atts)
            if issues_cnt:
                top_issue = issues_cnt.most_common(1)[0]
                print(f"      häufigstes Issue: {top_issue[0]} ({top_issue[1]}×)")
            first = atts[0]
            print(f"      Kontext: instrument={first.get('instrument')} "
                  f"genre={first.get('genre')} key={first.get('key')} "
                  f"bpm={first.get('bpm')} bars={first.get('bars')}")

    # ── 2. Low-Score-Attempts ──────────────────────────────────────────────────
    print(f"\n[2] Low-Score-Attempts (score < {score_threshold})")
    print("─" * 70)
    lows = fetch_low_score_attempts(threshold=score_threshold, limit=top)
    if not lows:
        print("  (keine)")
    else:
        for i, a in enumerate(lows, 1):
            print(f"  {i:2}. score={a['score']:.2f}  {a['instrument']}/{a['genre']}/"
                  f"{a['key']}/{a['bpm']}bpm/{a['bars']}bars")
            if a.get("issues"):
                print(f"      issues: {str(a['issues'])[:100]}")

    # ── 3. DPO-rejected-Cluster ───────────────────────────────────────────────
    print(f"\n[3] DPO rejected-Samples-Cluster ({dpo_path})")
    print("─" * 70)
    dpo = analyze_dpo_jsonl(Path(dpo_path))
    print(f"  Gesamt rejected: {dpo['total']}")
    if dpo["by_pattern"]:
        print("  Fehlermuster-Verteilung:")
        for cls, n in dpo["by_pattern"].items():
            pct = 100.0 * n / max(dpo["total"], 1)
            print(f"    {cls:30s} {n:>4}  ({pct:5.1f}%)")
        print("\n  Beispiele pro Cluster:")
        for cls, exs in dpo["samples"].items():
            if cls == "other":
                continue
            print(f"    ── {cls} ──")
            for ex in exs[:2]:
                print(f"       prompt:   {ex['user_message']}")
                print(f"       rejected: {ex['rejected'][:100]}")
    print("\n  Top-Prompt-Prefixes (häufigste Anfragen, die zu Pairs führten):")
    for prefix, n in list(dpo["top_prompt_prefixes"].items())[:top]:
        print(f"    {n:>4}× {prefix}")

    # ── Empfehlungen ──────────────────────────────────────────────────────────
    print(f"\n[4] Empfehlung")
    print("─" * 70)
    if retries:
        print(f"  → {len(retries)} Kontext(e) mit Self-Refine-Retries gefunden.")
        print(f"    Gezielt DPO-Pairs für diese Kontexte generieren (run with --target-retries).")
    if dpo["by_pattern"].get("write_pattern_no_notes", 0) > 0:
        print(f"  → {dpo['by_pattern']['write_pattern_no_notes']} 'write_pattern_no_notes' "
              f"Fails → write_pattern-Schema im SYSTEM_PROMPT verstärken.")
    if dpo["by_pattern"].get("german_key_string", 0) > 0:
        print(f"  → {dpo['by_pattern']['german_key_string']} 'german_key_string' "
              f"Fails → key-Format-Beispiele (C minor, nicht C-Moll) in Hard-Prompts.")

    print("═" * 70)
    return {"retries": retries, "low_score": lows, "dpo": dpo}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min-retries", type=int, default=2)
    p.add_argument("--score-threshold", type=float, default=0.5)
    p.add_argument("--dpo-path", default="training_data/dpo_train.jsonl")
    args = p.parse_args()
    main(top=args.top, min_retries=args.min_retries,
         dpo_path=args.dpo_path, score_threshold=args.score_threshold)

"""Agent-Driven Training: Den echten Agenten anrufen, nach Song/Genre fragen,
seine Antwort als DPO-Pair extrahieren.

Im Gegensatz zu generate_dpo_pairs.py (das direkt gegen MLX-API geht und keinen
LangGraph-State sieht) nutzt dieses Script den vollen agent.chat()-Pfad inkl.
Tool-Calls, Self-Refine und PatternAttempt-Storage.

Modi:
  --mode interactive       Frage live nach Song/Genre, schreibe Pair pro Runde
  --mode batch             Fahre Liste von Song/Genre-Kombos automatisch durch
  --mode neo4j-anchors     Nutze (:Song)-Knoten aus Neo4j als Prompt-Quelle

Output:
  training_data/agent_session_pairs.jsonl   (append-only)
  Plus für jedes Pair landet automatisch ein (:PatternAttempt) in Neo4j
  (via music_learning._store_learning_feedback) — dadurch greift später
  analyze_training_failures.py und extract_dpo_from_attempts.py.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _format_prompt(song: str | None, genre: str, bars: int = 4,
                   key: str = "C minor", style: str | None = None) -> str:
    """Baut einen User-Prompt im Format das der Agent gut versteht."""
    if song:
        return (f"Schreibe ein {bars}-Takt Pattern im Stil von {song} "
                f"(Genre: {genre}, {key}). Nutze write_pattern_raw wenn du das "
                f"konkrete Riff kennst, sonst write_pattern.")
    s = f" {style}" if style else ""
    return (f"Schreibe ein {bars}-Takt {genre}{s} Pattern in {key}. "
            f"Wähle den passenden Track und das beste Tool.")


def _read_policy_feedback_since(offset: int) -> tuple[list[dict], int]:
    """Liest neue policy_feedback-Einträge ab Byte-offset. Gibt
    (final_tool_calls-Liste, neuer_offset) zurück. Robuste Tool-Call-Quelle,
    weil core.py sie nach dem XML-Recovery-Parser schreibt."""
    from src.agent.core import POLICY_LOG_FILE
    import os as _os

    if not _os.path.exists(POLICY_LOG_FILE):
        return [], offset
    calls: list[dict] = []
    with open(POLICY_LOG_FILE) as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            for tc in (entry.get("final_tool_calls") or []):
                name = tc.get("name") or tc.get("tool") or ""
                args = tc.get("args") or {}
                if name:
                    calls.append({"tool": name, "args": args})
        new_offset = f.tell()
    return calls, new_offset


def _ask_agent(prompt: str) -> tuple[str, dict]:
    """Ruft den echten Agenten auf. Gibt (best_tool_call_json, metadata) zurück.

    Statt der finalen Prosa-Antwort extrahieren wir die ECHTEN Tool-Calls aus
    dem policy_feedback-Log (das core.py nach dem XML-Recovery schreibt) — nur
    die sind via score_completion bewertbar. Wir geben den am höchsten gescorten
    Pattern-Tool-Call zurück (write_pattern[_raw]), fallback letzter Tool-Call,
    fallback Prosa.
    """
    import json as _json
    import os as _os
    from langchain_core.messages import HumanMessage

    from src.agent.core import get_graph, _default_state, POLICY_LOG_FILE
    from src.agent.tools.music.reward import score_completion

    print(f"\n  → Agent-Anfrage: {prompt[:80]}…")

    offset = _os.path.getsize(POLICY_LOG_FILE) if _os.path.exists(POLICY_LOG_FILE) else 0
    try:
        graph = get_graph()
        state = _default_state()
        state["messages"] = [HumanMessage(content=prompt)]
        result = graph.invoke(state)
    except Exception as e:
        return "", {"error": str(e), "exception": type(e).__name__}

    messages = result.get("messages", [])
    final_text = messages[-1].content if messages else ""

    tool_calls, _ = _read_policy_feedback_since(offset)

    if not tool_calls:
        return final_text or "", {"length": len(final_text or ""),
                                  "n_tool_calls": 0, "captured": "prose"}

    pattern_calls = [tc for tc in tool_calls
                     if tc["tool"] in ("write_pattern", "write_pattern_raw")]
    candidates = pattern_calls or tool_calls
    scored = []
    for tc in candidates:
        js = _json.dumps(tc, ensure_ascii=False)
        s, _ = score_completion(prompt, js)
        scored.append((s, js, tc["tool"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_json, best_tool = scored[0]

    return best_json, {
        "length":        len(best_json),
        "n_tool_calls":  len(tool_calls),
        "captured":      "tool_call",
        "best_tool":     best_tool,
        "all_tools":     [tc["tool"] for tc in tool_calls],
        "final_text":    final_text[:200],
    }


def _score_answer(prompt: str, answer: str) -> tuple[float, dict]:
    try:
        from src.agent.tools.music.reward import score_completion
        return score_completion(prompt, answer)
    except Exception as e:
        return 0.0, {"error": str(e)}


# ── Pair-Generierung ──────────────────────────────────────────────────────────

def _append_pair(out_path: Path, prompt: str, answer: str,
                 score: float, meta: dict) -> None:
    """Speichert eine Session-Zeile (kein DPO-Pair-Format, sondern Roh-Log).
    Aus diesen Logs lassen sich später via extract_dpo_from_attempts oder
    manuell echte chosen/rejected-Pairs ableiten."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": _ts(),
        "prompt":    prompt,
        "answer":    answer,
        "score":     score,
        "meta":      meta,
    }
    with out_path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_interactive(out_path: Path) -> int:
    """Interaktiver Loop: User gibt Song / Genre an, Agent antwortet, Pair wird geloggt."""
    print("─" * 70)
    print(" AGENT-TRAINING: Interaktiv")
    print(" Antworte mit leerer Zeile zum Beenden.")
    print("─" * 70)
    n = 0
    while True:
        try:
            song = input("\n  Song (Artist - Title, leer = nur Genre): ").strip()
        except EOFError:
            break
        if not song and not input("  ohne Song fortfahren? (y/n): ").lower().startswith("y"):
            break
        genre = input("  Genre [rock]: ").strip() or "rock"
        bars  = int(input("  Takte [4]: ").strip() or 4)
        key   = input("  Tonart [C minor]: ").strip() or "C minor"

        prompt = _format_prompt(song or None, genre, bars=bars, key=key)
        answer, meta = _ask_agent(prompt)
        score, sm = _score_answer(prompt, answer)
        meta.update({"score_meta": sm, "song": song, "genre": genre,
                     "bars": bars, "key": key})

        print(f"  📊 Score: {score:.2f}")
        print(f"  📝 Antwort: {answer[:200]}{'…' if len(answer) > 200 else ''}")
        _append_pair(out_path, prompt, answer, score, meta)
        n += 1
    return n


def run_batch(out_path: Path, recipes: list[dict]) -> int:
    """Fährt eine Liste von {song, genre, bars, key, style}-Dicts ab."""
    print("─" * 70)
    print(f" AGENT-TRAINING: Batch ({len(recipes)} Items)")
    print("─" * 70)
    n = 0
    for i, r in enumerate(recipes, 1):
        prompt = _format_prompt(
            song=r.get("song"),
            genre=r.get("genre", "rock"),
            bars=int(r.get("bars", 4)),
            key=r.get("key", "C minor"),
            style=r.get("style"),
        )
        print(f"\n  [{i}/{len(recipes)}] {prompt[:70]}…")
        answer, meta = _ask_agent(prompt)
        score, sm = _score_answer(prompt, answer)
        meta.update({"score_meta": sm, **r})
        print(f"     score={score:.2f}  len={len(answer)}")
        _append_pair(out_path, prompt, answer, score, meta)
        n += 1
    return n


def run_neo4j_anchors(out_path: Path, max_anchors: int = 20) -> int:
    """Nutzt die (:Song)-Knoten als Trainings-Anker — automatisierter Loop."""
    try:
        from scripts._neo4j_song_prompts import fetch_song_anchors
    except Exception as e:
        print(f"⚠ Neo4j-Helper fehlt: {e}")
        return 0
    songs = fetch_song_anchors(limit=max_anchors)
    if not songs:
        print("⚠ Keine Songs in Neo4j")
        return 0
    print("─" * 70)
    print(f" AGENT-TRAINING: Neo4j-Anker ({len(songs)} Songs)")
    print("─" * 70)

    recipes: list[dict] = []
    for sg in songs:
        title  = sg.get("title")
        artist = sg.get("artist")
        if not title or not artist:
            continue
        key = sg.get("key") or "C"
        if key and " " not in key:
            key = f"{key} minor"
        recipes.append({
            "song":  f"{artist} - {title}",
            "genre": (sg.get("metadata") or {}).get("musicbrainz_tags", ["rock"])[0]
                     if (sg.get("metadata") or {}).get("musicbrainz_tags") else "rock",
            "bars":  4,
            "key":   key,
        })
    return run_batch(out_path, recipes)


# ── Stats ─────────────────────────────────────────────────────────────────────

def _print_stats(path: Path) -> None:
    if not path.exists():
        return
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if not rows:
        return
    scores = [r["score"] for r in rows]
    high   = sum(1 for s in scores if s >= 0.8)
    low    = sum(1 for s in scores if s <  0.5)
    print("\n" + "═" * 70)
    print(f"  Sessions gesamt: {len(rows)}")
    print(f"  Avg-Score:       {sum(scores)/len(scores):.3f}")
    print(f"  High (≥0.8):     {high}  ({100*high/len(rows):.0f}%)")
    print(f"  Low  (<0.5):     {low}  ({100*low/len(rows):.0f}%)")
    print(f"  Log:             {path}")
    print("═" * 70)
    print("\n  → Nächster Schritt:")
    print("    python -m scripts.extract_dpo_from_attempts  (PatternAttempts → DPO-Pairs)")
    print("    python -m scripts.analyze_training_failures  (Fehler-Cluster zeigen)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("interactive", "batch", "neo4j-anchors"),
                   default="neo4j-anchors")
    p.add_argument("--out", default="training_data/agent_session_pairs.jsonl")
    p.add_argument("--max-anchors", type=int, default=20)
    p.add_argument("--recipes-file", default=None,
                   help="JSON-Datei mit Liste von {song,genre,bars,key,style}-Dicts (für mode=batch)")
    args = p.parse_args()

    out_path = Path(args.out)

    if args.mode == "interactive":
        n = run_interactive(out_path)
    elif args.mode == "batch":
        if not args.recipes_file:
            print("⚠ --recipes-file erforderlich für mode=batch")
            return 1
        recipes = json.loads(Path(args.recipes_file).read_text())
        n = run_batch(out_path, recipes)
    else:
        n = run_neo4j_anchors(out_path, max_anchors=args.max_anchors)

    print(f"\n✅ {n} Sessions geloggt → {out_path}")
    _print_stats(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Bereitet MLX LoRA Training-Daten vor.

Kombiniert:
  - Neo4j Patterns + Theory + Projects (via mlx_export)
  - data/training/format_pairs.jsonl   (1416 Paare)
  - data/training/genre_pairs.jsonl    (128 Paare)
  - data/training/theory_pairs.jsonl   (912 Paare)
  - data/training/context_pairs.jsonl  (6 Paare)

Output: training_data/train.jsonl + training_data/valid.jsonl
Format: {"messages": [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}]}
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SYSTEM_PROMPT = """/no_think
Du bist ein Bitwig Studio AI-Assistent. Verfügbare Tools:
- write_pattern(track_name, notes, length_beats, key)
- create_track_from_recipe(track_name, project_name, scene_name, include_notes, include_params)
- reconstruct_project(project_name, include_notes, include_params, dry_run)
- scan_and_learn_project()
- web_search(query)
- find_audio_example(genre_query)
- query_bitwig_docs(query)"""

TRAINING_DIR = Path(__file__).parent.parent / "data" / "training"
OUTPUT_DIR   = Path(__file__).parent.parent / "training_data"


def _jsonl_to_messages(record: dict) -> dict:
    """Konvertiert prompt/completion/(context/cot) → MLX messages-Format."""
    prompt  = record.get("prompt", "")
    context = record.get("context", "")
    cot     = record.get("chain_of_thought", "")
    completion = record.get("completion", "")

    # User-Message: Prompt + optionaler Kontext
    user_parts = []
    if context and context.strip():
        user_parts.append(f"Kontext:\n{context.strip()}")
    user_parts.append(prompt)
    user_content = "\n\n".join(user_parts)

    # Assistant-Message: CoT + Completion
    assistant_parts = []
    if cot and cot.strip():
        assistant_parts.append(f"<think>\n{cot.strip()}\n</think>")
    assistant_parts.append(completion)
    assistant_content = "\n".join(assistant_parts)

    return {"messages": [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]}


def load_jsonl_files() -> list[dict]:
    """Lädt alle JSONL-Dateien aus data/training/."""
    examples = []
    for jf in sorted(TRAINING_DIR.glob("*.jsonl")):
        count = 0
        with open(jf, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Bereits im messages-Format? Direkt übernehmen
                    if "messages" in rec:
                        examples.append(rec)
                    elif "prompt" in rec and "completion" in rec:
                        examples.append(_jsonl_to_messages(rec))
                    count += 1
                except json.JSONDecodeError:
                    continue
        print(f"  {jf.name}: {count} Paare")
    return examples


def load_neo4j_examples() -> list[dict]:
    """Lädt Beispiele aus Neo4j via mlx_export."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from src.agent.tools.meta.mlx_export import (
            _fetch_patterns, _build_prompt, _build_completion,
            _theory_examples, _project_examples, _chord_progression_examples,
            _song_context_examples,
        )
        examples = []

        # Patterns aus Neo4j
        patterns = _fetch_patterns(min_score=0.70, limit=500)
        for p in patterns:
            examples.append({"messages": [
                {"role": "system",    "content": SYSTEM_PROMPT},
                {"role": "user",      "content": _build_prompt(p)},
                {"role": "assistant", "content": _build_completion(p)},
            ]})
        print(f"  Neo4j Patterns: {len(patterns)}")

        # Theory-Beispiele
        theory = _theory_examples()
        for ex in theory:
            if "messages" in ex:
                examples.append(ex)
        print(f"  Theory: {len(theory)}")

        # Projekt-Beispiele
        proj_ex = _project_examples()
        for ex in proj_ex:
            if "messages" in ex:
                examples.append(ex)
        print(f"  Projekt-Beispiele: {len(proj_ex)}")

        # Akkordfolgen
        chord_ex = _chord_progression_examples()
        for ex in chord_ex:
            if "messages" in ex:
                examples.append(ex)
        print(f"  Akkordfolgen: {len(chord_ex)}")

        # Song-Kontext
        ctx_ex = _song_context_examples()
        for ex in ctx_ex:
            if "messages" in ex:
                examples.append(ex)
        print(f"  Song-Kontext: {len(ctx_ex)}")

        return examples

    except Exception as e:
        print(f"  Neo4j nicht verfügbar: {e}")
        return []


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    print("\n=== MLX Training-Daten vorbereiten ===\n")
    print("JSONL-Dateien aus data/training/:")
    jsonl_examples = load_jsonl_files()

    print(f"\nNeo4j-Beispiele:")
    neo4j_examples = load_neo4j_examples()

    all_examples = jsonl_examples + neo4j_examples
    random.shuffle(all_examples)

    total = len(all_examples)
    split = max(1, int(total * 0.9))
    train_ex = all_examples[:split]
    valid_ex  = all_examples[split:]

    print(f"\nGesamt: {total} Beispiele")
    print(f"  Train: {len(train_ex)}")
    print(f"  Valid: {len(valid_ex)}")

    (OUTPUT_DIR / "train.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in train_ex) + "\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "valid.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in valid_ex) + "\n",
        encoding="utf-8",
    )

    stats = {
        "total": total,
        "train": len(train_ex),
        "valid": len(valid_ex),
        "jsonl_sources": len(jsonl_examples),
        "neo4j_sources": len(neo4j_examples),
    }
    (OUTPUT_DIR / "export_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n✓ training_data/train.jsonl ({len(train_ex)} Zeilen)")
    print(f"✓ training_data/valid.jsonl ({len(valid_ex)} Zeilen)")
    print(f"✓ training_data/export_stats.json")


if __name__ == "__main__":
    main()

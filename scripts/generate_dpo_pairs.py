"""
DPO-Paar-Generator — zwei Strategien:

A) Ground-Truth-Paare: Modell-Output (rejected) vs. perfekte Antwort aus
   Training (chosen). Funktioniert auch wenn Modell gut ist.

B) Kontrast-Paare: Mehrere Antworten pro Prompt, beste vs. schlechteste.
   Nur sinnvoll wenn Modell Fehler macht (Score-Differenz > MIN_CONTRAST).

Run: python scripts/generate_dpo_pairs.py [--model-url URL] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

import requests

from src.agent.tools.reward import score_completion

MLX_URL      = "http://192.168.0.4:8080/v1/chat/completions"
MODEL_ID     = "mlx-community/Qwen3-8B-4bit"
COMPLETIONS  = 2        # Antworten pro Prompt (Strategie B)
TEMPERATURE  = 0.7
MAX_TOKENS   = 600
MIN_CONTRAST = 0.20     # Mindestunterschied für Strategie B

SYSTEM_PROMPT = """/no_think
Du bist ein Bitwig Studio AI-Assistent. Verfügbare Tools:
- get_song_context(project_name) → Tempo, Szenen, Energie-Level, Track-Rollen
- create_track_from_recipe(track_name, project_name, scene_name, include_notes, include_params)
- reconstruct_project(project_name, include_notes, include_params, dry_run)
- write_pattern(track_name, notes, length_beats, key, append)
- scan_and_learn_project()

Bekannte Projekte: "Chee - Hey Now"
Bekannte Szenen: "Intro", "Raise", "Garage", "Peak", "Break", "Trap", "Impro", "Outro"
Szenen-Energie: Intro=spärlich(33%), Peak/Break=voll(95-100%)

notes MUSS eine Liste von max 32 Dicts sein:
[{"step": 0, "pitch": 60, "velocity": 80, "duration": 0.4}, ...]
Niemals notes als String oder Notennamen ausgeben.

Tonarten (Deutsch→Englisch): C-Moll=C minor, D-Moll=D minor, E-Moll=E minor,
F-Moll=F minor, G-Moll=G minor, A-Moll=A minor, H-Moll=B minor,
Cis-Moll=C# minor, Dis-Moll=D# minor, Fis-Moll=F# minor, Gis-Moll=G# minor,
B-Moll=Bb minor, C-Dur=C major, D-Dur=D major, E-Dur=E major.

Antworte NUR mit einem JSON Tool-Aufruf im Format:
{"tool": "<name>", "args": {<parameter>}}"""


# ── Prompt-Quellen ────────────────────────────────────────────────────────────

def _load_prompt_answer_pairs(data_dir: str) -> list[tuple[str, str]]:
    """Lädt (prompt, ground_truth_answer) aus train.jsonl — nur Tool-Prompts."""
    path = os.path.join(data_dir, "train.jsonl")
    pairs: list[tuple[str, str]] = []
    if not os.path.exists(path):
        return pairs
    seen: set[str] = set()
    with open(path) as f:
        for line in f:
            try:
                ex = json.loads(line)
                msgs = ex.get("messages", [])
                user = next((m["content"] for m in msgs if m["role"] == "user"), None)
                asst = next((m["content"] for m in msgs if m["role"] == "assistant"), None)
                if not user or not asst:
                    continue
                # Nur Tool-relevante Prompts
                if not any(kw in user.lower() for kw in [
                    "erstelle", "füge", "einfüge", "schreibe", "rekonstruiere",
                    "create", "insert", "write", "reconstruct", "pattern",
                ]):
                    continue
                # Nur wenn Antwort echten Tool-Aufruf enthält
                if "tool" not in asst:
                    continue
                if user not in seen:
                    seen.add(user)
                    pairs.append((user, asst))
            except json.JSONDecodeError:
                pass
    return pairs


def _hard_prompts() -> list[tuple[str, str]]:
    """
    Herausfordernde Prompts die das Modell zum Fehler verleiten —
    jeweils mit korrekter Antwort.
    Testet: falscher Projektname, falsche Tonart, unbekannte Szene, etc.
    """
    return [
        # Falsch formuliert → richtiger Tool-Aufruf
        (
            "Mach einen Sound wie Dissonant Pad aus Hey Now von Chee.",
            json.dumps({"tool": "create_track_from_recipe",
                        "args": {"track_name": "Dissonant Pad",
                                 "project_name": "Chee - Hey Now",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Ich will Sharp Arp aus dem Break einfügen.",
            json.dumps({"tool": "create_track_from_recipe",
                        "args": {"track_name": "Sharp Arp",
                                 "project_name": "Chee - Hey Now",
                                 "scene_name": "Break",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Baue Chee Hey Now neu auf.",
            json.dumps({"tool": "reconstruct_project",
                        "args": {"project_name": "Chee - Hey Now",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Schreibe ein Pattern für Sine Pluck in Cis-Moll.",
            json.dumps({"tool": "write_pattern",
                        "args": {"track_name": "Sine Pluck 1",
                                 "notes": [{"step": 0, "pitch": 61, "velocity": 80, "duration": 0.4},
                                           {"step": 2, "pitch": 63, "velocity": 80, "duration": 0.4},
                                           {"step": 4, "pitch": 64, "velocity": 80, "duration": 0.4}],
                                 "length_beats": 8.0, "key": "C# minor"}}),
        ),
        (
            "Arpeggio-Pattern in H-Moll, 4 Schläge.",
            json.dumps({"tool": "write_pattern",
                        "args": {"track_name": "Arp",
                                 "notes": [{"step":  0, "pitch": 59, "velocity": 90, "duration": 0.5},
                                           {"step":  4, "pitch": 62, "velocity": 75, "duration": 0.5},
                                           {"step":  8, "pitch": 66, "velocity": 75, "duration": 0.5},
                                           {"step": 12, "pitch": 71, "velocity": 80, "duration": 0.5}],
                                 "length_beats": 4.0, "key": "B minor"}}),
        ),
        (
            "Lerne das aktuelle Bitwig-Projekt.",
            json.dumps({"tool": "scan_and_learn_project", "args": {}}),
        ),
        (
            "Füge Sawtooth Pluck aus der Peak-Szene ein.",
            json.dumps({"tool": "create_track_from_recipe",
                        "args": {"track_name": "Sawtooth Pluck",
                                 "project_name": "Chee - Hey Now",
                                 "scene_name": "Peak",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Erstelle ein Es-Dur Pattern, 8 Beats.",
            json.dumps({"tool": "write_pattern",
                        "args": {"track_name": "Synth",
                                 "notes": [{"step": 0, "pitch": 63, "velocity": 80, "duration": 0.4},
                                           {"step": 2, "pitch": 65, "velocity": 80, "duration": 0.4},
                                           {"step": 4, "pitch": 67, "velocity": 80, "duration": 0.4},
                                           {"step": 6, "pitch": 68, "velocity": 80, "duration": 0.4}],
                                 "length_beats": 8.0, "key": "Eb major"}}),
        ),
        # notes-Format Training: Modell neigt zu String-Output
        (
            "Schreibe ein C-Moll Pattern für Sine Pluck 1, 8 Beats.",
            json.dumps({"tool": "write_pattern",
                        "args": {"track_name": "Sine Pluck 1",
                                 "notes": [{"step": 0, "pitch": 60, "velocity": 80, "duration": 0.4},
                                           {"step": 2, "pitch": 62, "velocity": 80, "duration": 0.4},
                                           {"step": 4, "pitch": 63, "velocity": 80, "duration": 0.4},
                                           {"step": 6, "pitch": 65, "velocity": 80, "duration": 0.4},
                                           {"step": 8, "pitch": 67, "velocity": 80, "duration": 0.4},
                                           {"step": 10, "pitch": 68, "velocity": 80, "duration": 0.4}],
                                 "length_beats": 8.0, "key": "C minor"}}),
        ),
        (
            "Erstelle Sharp Arp wie in der Break-Szene von Chee - Hey Now.",
            json.dumps({"tool": "create_track_from_recipe",
                        "args": {"track_name": "Sharp Arp",
                                 "project_name": "Chee - Hey Now",
                                 "scene_name": "Break",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Mach einen Sound wie Dissonant Pad aus Chee - Hey Now.",
            json.dumps({"tool": "create_track_from_recipe",
                        "args": {"track_name": "Dissonant Pad",
                                 "project_name": "Chee - Hey Now",
                                 "include_notes": True, "include_params": True}}),
        ),
        (
            "Fis-Moll Arpeggio für Arp Track, 4 Beats.",
            json.dumps({"tool": "write_pattern",
                        "args": {"track_name": "Arp",
                                 "notes": [{"step":  0, "pitch": 66, "velocity": 90, "duration": 0.5},
                                           {"step":  4, "pitch": 69, "velocity": 75, "duration": 0.5},
                                           {"step":  8, "pitch": 73, "velocity": 75, "duration": 0.5},
                                           {"step": 12, "pitch": 78, "velocity": 80, "duration": 0.5}],
                                 "length_beats": 4.0, "key": "F# minor"}}),
        ),
    ]


# ── Generierung ───────────────────────────────────────────────────────────────

def _ask(url: str, prompt: str, temperature: float = TEMPERATURE) -> str | None:
    try:
        r = requests.post(url, json={
            "model":       MODEL_ID,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            "max_tokens":  MAX_TOKENS,
            "temperature": temperature,
        }, timeout=60)
        if r.status_code == 200:
            msg = r.json()["choices"][0]["message"]
            content = msg.get("content") or ""
            # Qwen3-thinking-mode: wenn content leer, reasoning-Feld nehmen
            if not content.strip() and msg.get("reasoning"):
                content = msg["reasoning"]
            return content.strip() or None
    except Exception as e:
        print(f"  ⚠ Request fehlgeschlagen: {e}")
        time.sleep(1)
    return None


# ── Paar-Strategien ───────────────────────────────────────────────────────────

def _strategy_A_ground_truth(
    url: str,
    pairs: list[tuple[str, str]],
    examples: list[dict],
) -> int:
    """
    Strategie A: Modell-Output vs. Ground-Truth.
    Funktioniert immer — kein Kontrast-Problem.
    """
    added = 0
    for prompt, ground_truth in pairs:
        output = _ask(url, prompt, temperature=0.3)
        if not output:
            continue
        score, _ = score_completion(prompt, output)

        if score >= 1.0:
            # Modell ist bereits perfekt → kein Lernbedarf für diesen Prompt
            continue

        gt_score, _ = score_completion(prompt, ground_truth)
        if gt_score < score:
            # Ground truth schlechter als Modell → übersprungen
            continue

        examples.append({
            "prompt":        SYSTEM_PROMPT + "\n\n" + prompt,
            "chosen":        ground_truth,
            "rejected":      output,
            "user_message":  prompt,
            "_meta": {"strategy": "A", "model_score": score, "gt_score": gt_score},
        })
        added += 1
        print(f"  A✅ score={score:.2f}→gt={gt_score:.2f}  {prompt[:50]}…")
    return added


def _strategy_B_contrast(
    url: str,
    prompts: list[str],
    examples: list[dict],
) -> int:
    """
    Strategie B: Mehrere Antworten pro Prompt, beste vs. schlechteste.
    Nur wenn echter Kontrast vorhanden.
    """
    added = 0
    for prompt in prompts:
        completions: list[tuple[float, str]] = []
        for _ in range(COMPLETIONS):
            output = _ask(url, prompt, temperature=TEMPERATURE)
            if output:
                s, _ = score_completion(prompt, output)
                completions.append((s, output))

        if len(completions) < 2:
            continue

        completions.sort(key=lambda x: x[0], reverse=True)
        best_s,  best_c  = completions[0]
        worst_s, worst_c = completions[-1]
        contrast = best_s - worst_s

        if contrast < MIN_CONTRAST:
            print(f"  B✗ Δ={contrast:.2f} (zu gering)  {prompt[:50]}…")
            continue

        examples.append({
            "prompt":       SYSTEM_PROMPT + "\n\n" + prompt,
            "chosen":       best_c,
            "rejected":     worst_c,
            "user_message": prompt,
            "_meta": {"strategy": "B", "best": best_s, "worst": worst_s},
        })
        added += 1
        print(f"  B✅ best={best_s:.2f} worst={worst_s:.2f} Δ={contrast:.2f}  {prompt[:50]}…")
    return added


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def generate_pairs(
    model_url: str = MLX_URL,
    data_dir: str = "./training_data",
    out_dir: str | None = None,
    max_prompts: int = 50,
    song_anchors: int = 20,
    song_prompts_per_anchor: int = 2,
    genre_patterns: bool = True,
) -> dict:
    out_dir = out_dir or data_dir
    os.makedirs(out_dir, exist_ok=True)

    train_pairs = _load_prompt_answer_pairs(data_dir)[:max_prompts]
    hard         = _hard_prompts()

    # Neo4j-Anker: echte (:Song)-Knoten als stilistische Constraint-Quelle
    try:
        from scripts._neo4j_song_prompts import load_prompts as _load_song_prompts
        from scripts._neo4j_song_prompts import (
            build_ground_truth_pairs_from_songs as _load_song_gt_pairs,
        )
        neo_prompts  = _load_song_prompts(
            limit=song_anchors,
            n_per_song=song_prompts_per_anchor,
        )
        neo_gt_pairs = _load_song_gt_pairs(max_pairs_per_song=3)
    except Exception as exc:
        print(f"⚠ Neo4j-Anker übersprungen: {exc}")
        neo_prompts  = []
        neo_gt_pairs = []

    # Freesound-GenrePatterns → finite Drum-Ground-Truth (Anti-Runaway-Signal)
    genre_gt_pairs: list[tuple[str, str]] = []
    if genre_patterns:
        try:
            from scripts._neo4j_song_prompts import build_genre_groundtruth_pairs
            genre_gt_pairs = build_genre_groundtruth_pairs(max_per_genre=1)
        except Exception as exc:
            print(f"⚠ Genre-Pattern-GT übersprungen: {exc}")

    print(f"📋 {len(train_pairs)} Trainings-Prompts + {len(hard)} Hard-Prompts "
          f"+ {len(neo_prompts)} Neo4j-Song-Prompts "
          f"+ {len(neo_gt_pairs)} Neo4j-GroundTruth-Pairs (write_pattern_raw) "
          f"+ {len(genre_gt_pairs)} Freesound-Genre-Drum-GT-Pairs")

    examples: list[dict] = []

    # Strategie A: Ground-Truth-Paare (Trainings-Prompts + Hard-Prompts + note_plan-GT + Genre-Drum-GT)
    print(f"\n── Strategie A: Ground-Truth-Paare ──────────────────────────")
    n_a    = _strategy_A_ground_truth(model_url, train_pairs, examples)
    n_ah   = _strategy_A_ground_truth(model_url, hard, examples)
    n_a_np = _strategy_A_ground_truth(model_url, neo_gt_pairs, examples)
    n_a_g  = _strategy_A_ground_truth(model_url, genre_gt_pairs, examples)
    print(f"   {n_a + n_ah + n_a_np + n_a_g} Paare "
          f"(Train: {n_a}, Hard: {n_ah}, Neo4j-note_plan: {n_a_np}, "
          f"Freesound-Genre: {n_a_g})")

    # Strategie B: Kontrast-Paare (Hard-Prompts + Neo4j-Song-Prompts)
    print(f"\n── Strategie B: Kontrast-Paare ──────────────────────────────")
    n_b   = _strategy_B_contrast(model_url, [p for p, _ in hard], examples)
    n_b_n = _strategy_B_contrast(model_url, neo_prompts, examples)
    print(f"   {n_b + n_b_n} Paare (Hard: {n_b}, Neo4j-Songs: {n_b_n})")

    if not examples:
        print("\n⚠ Keine Paare generiert — Modell ist bereits sehr gut oder Server nicht erreichbar")
        return {"pairs_generated": 0}

    # 90/10 Split
    split       = max(1, int(len(examples) * 0.9))
    train_ex    = examples[:split]
    valid_ex    = examples[split:]

    def _write(path: str, data: list[dict]) -> None:
        with open(path, "w") as f:
            for row in data:
                out = {k: v for k, v in row.items() if k != "_meta"}
                f.write(json.dumps(out, ensure_ascii=False) + "\n")

    _write(os.path.join(out_dir, "dpo_train.jsonl"), train_ex)
    _write(os.path.join(out_dir, "dpo_valid.jsonl"), valid_ex)

    stats = {
        "pairs_generated": len(examples),
        "strategy_A":      n_a + n_ah + n_a_np + n_a_g,
        "strategy_B":      n_b + n_b_n,
        "train_pairs":     len(train_ex),
        "valid_pairs":     len(valid_ex),
    }
    print(f"\n✅ {len(examples)} DPO-Paare gespeichert "
          f"(A={n_a + n_ah + n_a_np + n_a_g}, B={n_b + n_b_n}) → {out_dir}/dpo_train.jsonl")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-url",   default=MLX_URL)
    parser.add_argument("--data-dir",    default="./training_data")
    parser.add_argument("--out-dir",     default=None)
    parser.add_argument("--max-prompts", type=int, default=50)
    parser.add_argument("--song-anchors", type=int, default=20,
                        help="Wie viele (:Song)-Knoten aus Neo4j als Stil-Anker ziehen")
    parser.add_argument("--song-prompts-per-anchor", type=int, default=2,
                        help="Prompt-Varianten pro Song-Anker")
    parser.add_argument("--no-genre-patterns", action="store_true",
                        help="Freesound-GenrePattern-Drum-GT NICHT einbeziehen")
    args = parser.parse_args()
    generate_pairs(
        model_url=args.model_url,
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        max_prompts=args.max_prompts,
        song_anchors=args.song_anchors,
        song_prompts_per_anchor=args.song_prompts_per_anchor,
        genre_patterns=not args.no_genre_patterns,
    )

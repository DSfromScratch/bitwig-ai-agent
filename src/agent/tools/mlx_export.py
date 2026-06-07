"""
MLX Training Data Export: exportiert validierte Patterns aus Neo4j als JSONL
für MLX LoRA Fine-Tuning auf Apple Silicon (Mac).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

log = logging.getLogger("bitwig-agent")

_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _midi_to_name(midi: int) -> str:
    return f"{_NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"


def _build_prompt(pattern: dict) -> str:
    inst  = pattern.get("instrument", "synth")
    genre = pattern.get("genre", "electronic")
    key   = pattern.get("key", "C")
    scale = pattern.get("scale", "major")
    bars  = pattern.get("bars") or 2
    bpm   = pattern.get("bpm") or 120
    return (
        f"Erstelle ein {bars}-taktiges Pattern für {inst} im Genre {genre}, "
        f"Tonart {key}-{scale}, {bpm} BPM."
    )


def _build_completion(pattern: dict) -> str:
    score       = pattern.get("avg_score", 0.0)
    suggestions = pattern.get("last_suggestions") or []
    notes_json  = pattern.get("notes_json")

    parts = [f"Score: {score:.2f}"]

    if suggestions:
        if isinstance(suggestions, str):
            suggestions = [suggestions]
        parts.append("Verbesserungen: " + "; ".join(suggestions))

    if notes_json:
        try:
            notes = json.loads(notes_json) if isinstance(notes_json, str) else notes_json
            note_names = [_midi_to_name(n["note"]) for n in notes[:8] if "note" in n]
            if note_names:
                parts.append("Noten: " + ", ".join(note_names))
            parts.append("Pattern:\n" + json.dumps(notes, ensure_ascii=False))
        except Exception:
            pass

    return "\n".join(parts)


def _fetch_patterns(min_score: float, limit: int) -> list[dict]:
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            result = s.run(
                """
                MATCH (p:ProductionPattern)
                WHERE p.avg_score >= $min_score AND p.iteration >= 2
                RETURN p.instrument AS instrument, p.genre AS genre,
                       p.key AS key, p.scale AS scale,
                       p.avg_score AS avg_score, p.iteration AS iteration,
                       p.last_suggestions AS last_suggestions,
                       p.last_issues AS last_issues,
                       p.last_score AS last_score,
                       p.notes_json AS notes_json,
                       p.bpm AS bpm, p.bars AS bars
                ORDER BY p.avg_score DESC
                LIMIT $limit
                """,
                min_score=min_score, limit=limit,
            ).data()
        driver.close()
        return result
    except Exception as exc:
        log.warning("Neo4j-Export fehlgeschlagen: %s", exc)
        return []


_GENRE_BPM = {
    "Techno":  "130–145 BPM, 4-on-the-floor Kick, minimale Melodien, kurze repetitive Patterns",
    "House":   "120–128 BPM, Off-Beat HiHats, Chord-Stabs auf 2+4, Bass-Groove",
    "DnB":     "160–180 BPM, Amen-Break Variation, Reese Bass, Synth Stabs",
    "Ambient": "60–90 BPM, lange Pads, Reverb-heavy, keine Percussion",
    "Rock":    "100–140 BPM, Gitarren-Riffs, Snare auf 2+4, E-Bass Grundton",
}

_WRITE_PATTERN_TOOL = "write_pattern"


def _scale_pattern(notes: list[int], beats: float = 8.0) -> list[dict]:
    """Einfaches aufsteigendes Pattern aus Skala-Noten (16th-note Steps)."""
    return [
        {"step": i * 2, "pitch": n, "velocity": 80, "duration": 0.4}
        for i, n in enumerate(notes[:8])
    ]


def _arp_pattern(notes: list[int]) -> list[dict]:
    """Arpeggio aus Grundton + Terz + Quinte + Oktave (4 Schläge)."""
    root = notes[0]
    third = notes[2] if len(notes) > 2 else root + 3
    fifth = notes[4] if len(notes) > 4 else root + 7
    octave = root + 12
    return [
        {"step":  0, "pitch": root,   "velocity": 90, "duration": 0.5},
        {"step":  4, "pitch": third,  "velocity": 75, "duration": 0.5},
        {"step":  8, "pitch": fifth,  "velocity": 75, "duration": 0.5},
        {"step": 12, "pitch": octave, "velocity": 80, "duration": 0.5},
    ]


def _theory_examples() -> list[dict]:
    """Skalen + Akkorde + write_pattern-Beispiele aus Neo4j (alle 24 Tonarten)."""
    try:
        from src.knowledge.neo4j_graph import is_available
        neo4j_ok = is_available()
    except Exception:
        neo4j_ok = False

    examples: list[dict] = []

    if neo4j_ok:
        examples.extend(_theory_from_neo4j())
    else:
        examples.extend(_theory_fallback())

    # Genre-Beispiele (bleiben hardcodiert — kein Neo4j-Mehrwert)
    for genre, desc in _GENRE_BPM.items():
        examples.append({"messages": [
            {"role": "user",      "content": f"Genre {genre} — typische Eigenschaften"},
            {"role": "assistant", "content": f"{genre}: {desc}"},
        ]})

    return examples


def _theory_from_neo4j() -> list[dict]:
    """Generiert Theory-Beispiele aus Scale + Chord Nodes in Neo4j."""
    from src.knowledge.neo4j_graph import session as neo4j_session
    examples: list[dict] = []

    with neo4j_session() as s:
        # ── Skalen (alle 24) ──────────────────────────────────────────────────
        scales = s.run("""
            MATCH (sc:Scale)
            RETURN sc.name_de AS name_de, sc.name_en AS name_en,
                   sc.notes AS notes, sc.note_names_de AS names_de,
                   sc.note_names_en AS names_en,
                   sc.relative_de AS rel_de, sc.type AS type
            ORDER BY sc.midi_root, sc.type
        """).data()

        for sc in scales:
            notes    = list(sc["notes"])
            midi_str = ", ".join(str(n) for n in notes)
            de_str   = ", ".join(sc["names_de"])
            en_str   = ", ".join(sc["names_en"])

            # Skala-Lookup (deutsch)
            examples.append({"messages": [
                {"role": "user",
                 "content": f"{sc['name_de']} Skala — MIDI-Noten"},
                {"role": "assistant",
                 "content": (f"{sc['name_de']}: [{midi_str}]\n"
                             f"Noten: {de_str}\n"
                             f"Relativ: {sc['rel_de']}")},
            ]})

            # Skala-Lookup (englisch)
            examples.append({"messages": [
                {"role": "user",
                 "content": f"Notes in {sc['name_en']} scale"},
                {"role": "assistant",
                 "content": f"{sc['name_en']}: [{midi_str}]\nNotes: {en_str}"},
            ]})

            # write_pattern — aufsteigendes Skala-Pattern
            asc_pattern = _scale_pattern(notes)
            examples.append({"messages": [
                {"role": "user",
                 "content": f"Schreibe ein Pattern in {sc['name_de']} (8 Beats)"},
                {"role": "assistant",
                 "content": json.dumps({
                     "tool": _WRITE_PATTERN_TOOL,
                     "args": {
                         "track_name":   "Synth",
                         "notes":        asc_pattern,
                         "length_beats": 8.0,
                         "key":          sc["name_en"],
                     }
                 }, ensure_ascii=False)},
            ]})

            # write_pattern — Arpeggio-Pattern
            arp_pattern = _arp_pattern(notes)
            examples.append({"messages": [
                {"role": "user",
                 "content": f"Arpeggio-Pattern in {sc['name_de']}, 4 Beats"},
                {"role": "assistant",
                 "content": json.dumps({
                     "tool": _WRITE_PATTERN_TOOL,
                     "args": {
                         "track_name":   "Arp",
                         "notes":        arp_pattern,
                         "length_beats": 4.0,
                         "key":          sc["name_en"],
                     }
                 }, ensure_ascii=False)},
            ]})

        # ── Akkorde ───────────────────────────────────────────────────────────
        chords = s.run("""
            MATCH (ch:Chord)
            WHERE ch.quality IN ['major', 'minor', 'dom7', 'maj7', 'min7']
            RETURN ch.symbol AS symbol, ch.name_de AS name_de,
                   ch.notes AS notes, ch.note_names_de AS names_de
            ORDER BY ch.midi_root, ch.quality
        """).data()

        for ch in chords:
            notes_str = str(list(ch["notes"]))
            names_str = ", ".join(ch["names_de"])
            examples.append({"messages": [
                {"role": "user",
                 "content": f"Akkord {ch['symbol']} — MIDI-Noten"},
                {"role": "assistant",
                 "content": f"{ch['symbol']} ({ch['name_de']}): {notes_str} ({names_str})"},
            ]})

    return examples


def _theory_fallback() -> list[dict]:
    """Minimaler Fallback wenn Neo4j nicht erreichbar."""
    SCALES = {
        "C-Dur":  [60, 62, 64, 65, 67, 69, 71, 72],
        "A-Moll": [57, 59, 60, 62, 64, 65, 67, 69],
        "G-Dur":  [55, 57, 59, 60, 62, 64, 66, 67],
        "D-Moll": [50, 52, 53, 55, 57, 58, 60, 62],
        "E-Moll": [52, 54, 55, 57, 59, 60, 62, 64],
        "C-Moll": [60, 62, 63, 65, 67, 68, 70, 72],
    }
    examples = []
    for name, notes in SCALES.items():
        midi_str  = ", ".join(str(n) for n in notes)
        names_str = ", ".join(_midi_to_name(n) for n in notes)
        examples.append({"messages": [
            {"role": "user",      "content": f"{name} Skala — MIDI-Noten"},
            {"role": "assistant", "content": f"{name}: [{midi_str}]\nNoten: {names_str}"},
        ]})
    return examples


def export_training_data(
    output_path: str = "./training_data",
    min_score: float = 0.70,
    limit: int = 500,
    include_theory: bool = True,
) -> dict[str, Any]:
    """Exportiert validierte Patterns aus Neo4j als MLX JSONL Training-Daten.

    Erstellt train.jsonl, valid.jsonl und export_stats.json im output_path.
    Format: Chat-Format kompatibel mit mlx-lm LoRA Fine-Tuning.
    """
    out_dir = Path(output_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    patterns = _fetch_patterns(min_score, limit)
    log.info("[MLX Export] %d Patterns aus Neo4j (min_score=%.2f)", len(patterns), min_score)

    examples: list[dict] = []

    for p in patterns:
        examples.append({"messages": [
            {"role": "user",      "content": _build_prompt(p)},
            {"role": "assistant", "content": _build_completion(p)},
        ]})

        # Fehler-Feedback-Beispiel wenn score < 0.7
        issues = p.get("last_issues") or []
        if issues and (p.get("last_score") or 1.0) < 0.7:
            if isinstance(issues, str):
                issues = [issues]
            examples.append({"messages": [
                {"role": "user",      "content": f"Probleme im Pattern: {'; '.join(issues)}"},
                {"role": "assistant", "content": _build_completion(p)},
            ]})

    if include_theory:
        theory = _theory_examples()
        examples.extend(theory)
        log.info("[MLX Export] +%d Theory-Beispiele", len(theory))

    # Neue Projekt-Beispiele aus SoundRecipe + MidiClip + Template
    project_ex = _project_examples()
    examples.extend(project_ex)
    log.info("[MLX Export] +%d Projekt-Beispiele", len(project_ex))

    # Akkordfolgen-Beispiele aus DIATONIC_CHORD Relations
    chord_ex = _chord_progression_examples()
    examples.extend(chord_ex)
    log.info("[MLX Export] +%d Akkordfolgen-Beispiele", len(chord_ex))

    # Song-Kontext-Beispiele (get_song_context + Szenen-Verständnis)
    context_ex = _song_context_examples()
    examples.extend(context_ex)
    log.info("[MLX Export] +%d Song-Kontext-Beispiele", len(context_ex))

    if not examples:
        return {
            "exported":    False,
            "error":       "Keine Patterns gefunden — Neo4j leer oder min_score zu hoch",
            "train_count": 0,
            "valid_count": 0,
        }

    split_idx = max(1, int(len(examples) * 0.9))
    train_ex  = examples[:split_idx]
    valid_ex  = examples[split_idx:]

    (out_dir / "train.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in train_ex) + "\n",
        encoding="utf-8",
    )
    (out_dir / "valid.jsonl").write_text(
        "\n".join(json.dumps(ex, ensure_ascii=False) for ex in valid_ex) + "\n",
        encoding="utf-8",
    )

    stats = {
        "exported_at":        datetime.utcnow().isoformat(),
        "neo4j_patterns":     len(patterns),
        "theory_examples":    len(_theory_examples()) if include_theory else 0,
        "project_examples":   len(project_ex),
        "chord_examples":     len(chord_ex),
        "context_examples":   len(context_ex),
        "total_examples":     len(examples),
        "train_count":        len(train_ex),
        "valid_count":        len(valid_ex),
        "min_score":          min_score,
        "output_path":        str(out_dir.resolve()),
    }
    (out_dir / "export_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # DPO-Paare als zusätzliche SFT-Beispiele einbinden (wenn vorhanden)
    dpo_added = _merge_dpo_pairs(out_dir)
    if dpo_added:
        stats["dpo_examples"] = dpo_added
        stats["train_count"] += dpo_added
        log.info("[MLX Export] +%d DPO→SFT Beispiele aus dpo_train.jsonl", dpo_added)

    log.info("[MLX Export] %d Train + %d Valid → %s", stats["train_count"], len(valid_ex), out_dir)
    return {"exported": True, "error": None, **stats}


_DPO_SYSTEM = """/no_think
Du bist ein Bitwig Studio AI-Assistent. Verfügbare Tools:
- create_track_from_recipe(track_name, project_name, scene_name, include_notes, include_params)
- reconstruct_project(project_name, include_notes, include_params, dry_run)
- write_pattern(track_name, notes, length_beats, key)
- scan_and_learn_project()

Bekannte Projekte: "Chee - Hey Now"
Bekannte Szenen: "Intro", "Raise", "Garage", "Peak", "Break", "Trap", "Impro", "Outro"

notes MUSS eine Liste von max 32 Dicts sein:
[{"step": 0, "pitch": 60, "velocity": 80, "duration": 0.4}, ...]
Niemals notes als String oder Notennamen ausgeben.

Tonarten (Deutsch→Englisch): C-Moll=C minor, D-Moll=D minor, E-Moll=E minor,
F-Moll=F minor, G-Moll=G minor, A-Moll=A minor, H-Moll=B minor,
Cis-Moll=C# minor, Dis-Moll=D# minor, Fis-Moll=F# minor, Gis-Moll=G# minor,
B-Moll=Bb minor, C-Dur=C major, D-Dur=D major, E-Dur=E major.

Antworte NUR mit einem JSON Tool-Aufruf im Format:
{"tool": "<name>", "args": {<parameter>}}"""


def _merge_dpo_pairs(out_dir: Path) -> int:
    """
    Liest dpo_train.jsonl und fügt chosen-Antworten als SFT-Beispiele
    an train.jsonl an. Gibt Anzahl hinzugefügter Beispiele zurück.
    """
    dpo_path   = out_dir / "dpo_train.jsonl"
    train_path = out_dir / "train.jsonl"

    if not dpo_path.exists():
        return 0

    new_examples: list[str] = []
    seen: set[str] = set()

    # Bestehende Prompts laden (Duplikate vermeiden)
    if train_path.exists():
        for line in train_path.read_text(encoding="utf-8").splitlines():
            try:
                ex = json.loads(line)
                msgs = ex.get("messages", [])
                user = next((m["content"] for m in msgs if m["role"] == "user"), "")
                if user:
                    seen.add(user.strip())
            except Exception:
                pass

    for line in dpo_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            user_msg = row.get("user_message") or ""
            chosen   = row.get("chosen") or ""
            if not user_msg or not chosen:
                # Fallback: user_message aus prompt extrahieren (letzter \n\n-Block)
                prompt = row.get("prompt", "")
                user_msg = prompt.rsplit("\n\n", 1)[-1].strip() if "\n\n" in prompt else prompt.strip()

            if not user_msg or user_msg in seen:
                continue

            sft_ex = {
                "messages": [
                    {"role": "system",    "content": _DPO_SYSTEM},
                    {"role": "user",      "content": user_msg},
                    {"role": "assistant", "content": chosen},
                ]
            }
            new_examples.append(json.dumps(sft_ex, ensure_ascii=False))
            seen.add(user_msg)
        except Exception:
            pass

    if new_examples:
        with train_path.open("a", encoding="utf-8") as f:
            for line in new_examples:
                f.write(line + "\n")

    return len(new_examples)


def _project_examples() -> list[dict]:
    """Generiert Trainingsbeispiele aus SoundRecipe, MidiClip, ProjectTemplate, Timeline."""
    from src.knowledge.neo4j_graph import is_available, session
    if not is_available():
        return []

    examples: list[dict] = []

    with session() as s:

        # ── Typ 1: Track-Erstellung aus SoundRecipe ────────────────────────
        # "Erstelle [Role]-Track mit [Instrument]" → execute_setup Steps
        recipes = s.run("""
            MATCH (sr:SoundRecipe)
            WHERE sr.params_json IS NOT NULL AND sr.primary_device IS NOT NULL
            RETURN sr.track_name AS name, sr.role AS role,
                   sr.primary_device AS inst, sr.device_chain AS chain,
                   sr.project AS project, sr.params_json AS pj
            LIMIT 50
        """).data()

        for r in recipes:
            if not r["inst"] or not r["chain"]:
                continue
            chain = r["chain"] or ""
            # FX-Kette parsen
            fx_str = ""
            if "FX-Kette:" in chain:
                fx_str = chain.split("FX-Kette:")[1].strip()
            role = r["role"] or r["name"]
            project = r["project"] or "Bitwig"

            # Prompt-Varianten
            prompts = [
                f"Erstelle einen {role}-Track mit {r['inst']} für {project}.",
                f"Füge einen {r['name']} Sound ein (wie in {project}).",
                f"Ich brauche einen {role}-Sound mit {r['inst']}{' und FX: ' + fx_str if fx_str else ''}.",
            ]

            # Antwort: Tool-Aufruf
            answer_dict = {
                "tool": "create_track_from_recipe",
                "args": {
                    "track_name": r["name"],
                    "project_name": project,
                    "include_notes": False,
                    "include_params": True,
                }
            }
            answer = json.dumps(answer_dict, ensure_ascii=False)

            for prompt in prompts[:2]:
                examples.append({"messages": [
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": answer},
                ]})

        # ── Typ 1b: Szenen-spezifische Track-Erstellung ────────────────────
        # "Füge [Track] aus [Szene]-Szene ein" → create_track_from_recipe mit scene_name
        scene_clips = s.run("""
            MATCH (mc:MidiClip)
            WHERE mc.notes_json IS NOT NULL AND mc.scene_name IS NOT NULL
            MATCH (sr:SoundRecipe)
            WHERE sr.track_name = mc.track_name AND sr.project = mc.project
            RETURN mc.track_name AS track, mc.scene_name AS scene,
                   mc.project AS project
            LIMIT 30
        """).data()

        for sc in scene_clips:
            track   = sc["track"]
            scene   = sc["scene"]
            project = sc["project"] or "Chee - Hey Now"
            prompts = [
                f"Füge den {track} Track aus der {scene}-Szene ein.",
                f"Erstelle {track} wie in der {scene}-Szene von {project}.",
                f"Ich möchte den {track} Sound aus {scene} haben.",
            ]
            answer = json.dumps({
                "tool": "create_track_from_recipe",
                "args": {
                    "track_name":    track,
                    "project_name":  project,
                    "scene_name":    scene,
                    "include_notes": True,
                    "include_params": True,
                }
            }, ensure_ascii=False)
            for prompt in prompts:
                examples.append({"messages": [
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": answer},
                ]})

        # ── Typ 2: MIDI-Pattern aus MidiClip ──────────────────────────────
        # "Schreibe Pattern für [Track] in [Key] [Szene]" → notes_json
        clips = s.run("""
            MATCH (mc:MidiClip)
            WHERE mc.notes_json IS NOT NULL AND mc.note_count > 0
            RETURN mc.track_name AS track, mc.scene_name AS scene,
                   mc.full_key AS key, mc.rhythm_pattern AS rhythm,
                   mc.note_count AS n, mc.loop_beats AS lb,
                   mc.notes_json AS nj, mc.project AS project,
                   mc.chords AS chords
            LIMIT 30
        """).data()

        for c in clips:
            if not c["nj"]:
                continue
            key   = c["key"] or "C major"
            scene = c["scene"] or "Intro"
            track = c["track"] or "Synth"
            rhythm = c["rhythm"] or "rhythmisch"
            notes = json.loads(c["nj"])
            lb    = float(c["lb"] or 8.0)

            chords_str = ""
            if c["chords"]:
                chords_str = f", Akkorde: {', '.join(c['chords'][:4])}"

            prompts = [
                f"Schreibe ein {lb:.0f}-Beat Pattern für {track} in {key}, "
                f"{rhythm}{chords_str}.",
                f"Pattern für {track} aus {scene}-Szene ({key}, {c['n']} Noten).",
            ]

            answer = json.dumps({
                "tool": "write_pattern",
                "args": {
                    "track_name": track,
                    "notes": notes[:32],
                    "length_beats": lb,
                    "key": key,
                }
            }, ensure_ascii=False)

            for prompt in prompts[:1]:
                examples.append({"messages": [
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": answer},
                ]})

        # ── Typ 3: Projekt-Überblick ───────────────────────────────────────
        # "Beschreibe das Projekt X" → strukturierte Antwort
        projects = s.run("""
            MATCH (p:BitwigProject)
            OPTIONAL MATCH (p)-[:HAS_TIMELINE]->(ts:TimelineSection)
            OPTIONAL MATCH (p)-[:HAS_GROUP]->(g:TrackGroup)
            WITH p, collect(DISTINCT ts.name + '(T' + toString(toInteger(ts.bar)) + ')') AS tl,
                 collect(DISTINCT g.name) AS groups
            RETURN p.name AS name, p.tempo AS tempo, tl AS timeline, groups
            LIMIT 5
        """).data()

        # Für jedes Projekt Tracks + Szenen holen
        for proj in projects:
            if not proj["timeline"]:
                continue
            name   = proj["name"]
            tempo  = proj["tempo"] or 120
            tl_str = ", ".join(proj["timeline"][:6])
            grp_str = ", ".join(proj["groups"])

            # Track-Liste
            track_rows = s.run("""
                MATCH (sr:SoundRecipe {project: $p})
                RETURN sr.track_name AS t ORDER BY sr.track_index LIMIT 8
            """, p=name).data()
            track_str = ", ".join(r["t"] for r in track_rows)

            description = (
                f"Das Projekt **{name}** läuft mit {tempo:.0f} BPM. "
                f"Gruppen: {grp_str}. "
                f"Tracks: {track_str}. "
                f"Timeline: {tl_str}."
            )

            examples.append({"messages": [
                {"role": "user",      "content": f"Beschreibe das Projekt {name}."},
                {"role": "assistant", "content": description},
            ]})
            examples.append({"messages": [
                {"role": "user",      "content": f"Was ist in {name} enthalten?"},
                {"role": "assistant", "content": description},
            ]})

        # ── Typ 4: Rekonstruktion ──────────────────────────────────────────
        templates = s.run("""
            MATCH (pt:ProjectTemplate)
            RETURN pt.name AS name, pt.tempo AS tempo, pt.genre AS genre,
                   pt.scene_names AS scenes, pt.track_names AS tracks
            LIMIT 5
        """).data()

        for tmpl in templates:
            name   = tmpl["name"]
            tempo  = tmpl["tempo"] or 120
            genre  = tmpl["genre"] or "electronic"
            tracks = str(len(tmpl["tracks"] or []))

            prompts = [
                f"Rekonstruiere das Projekt {name!r}.",
                f"Baue {name} neu auf in Bitwig ({tracks} Tracks, {tempo:.0f} BPM).",
                f"Erstelle das {genre} Projekt {name!r} in Bitwig.",
            ]

            answer = json.dumps({
                "tool": "reconstruct_project",
                "args": {
                    "project_name": name,
                    "include_notes": True,
                    "include_params": True,
                }
            }, ensure_ascii=False)

            for prompt in prompts:
                examples.append({"messages": [
                    {"role": "user",      "content": prompt},
                    {"role": "assistant", "content": answer},
                ]})

        # ── Typ 5: Sound-Design Fragen ─────────────────────────────────────
        audio = s.run("""
            MATCH (a:AudioSample)
            WHERE a.content IS NOT NULL
            RETURN a.filename AS file, a.category AS cat,
                   a.key_note AS key, a.key_conf AS conf,
                   a.content AS content
            LIMIT 20
        """).data()

        for a in audio:
            if not a["content"]:
                continue
            fname = a["file"].replace(".wav", "").replace("-bounce-1", "")
            key   = f"{a['key']} ({a['conf']:.0%})" if a["key"] and a["conf"] else ""
            # Erste Zeile des content als Kurzinfo
            first_line = a["content"].split("\n")[0] if a["content"] else ""

            answer = f"{first_line}"
            if key:
                answer += f"\nTonart: {key}"

            examples.append({"messages": [
                {"role": "user",      "content": f"Was für ein Sound ist {fname!r}?"},
                {"role": "assistant", "content": answer},
            ]})

    log.info("[MLX Export] %d Projekt-Beispiele generiert", len(examples))
    return examples


_PROGRESSIONS: list[tuple[list[int], str, str]] = [
    # (degree-indices 1-based, label, scale_type)
    ([1, 4, 5, 1], "i-iv-v-i",     "minor"),
    ([1, 7, 6, 7], "i-VII-VI-VII", "minor"),
    ([1, 6, 3, 7], "i-VI-III-VII", "minor"),
    ([1, 4, 5, 4], "I-IV-V-IV",   "major"),
    ([1, 4, 5, 1], "I-IV-V-I",    "major"),
    ([2, 5, 1, 1], "ii-V-I-I",    "major"),
]

_STEPS_PER_BEAT = 4   # 16th-note resolution


def _song_context_examples() -> list[dict]:
    """Trainingsbeispiele die get_song_context + write_pattern kombinieren."""
    try:
        from src.knowledge.neo4j_graph import is_available, session as neo4j_session
        if not is_available():
            return []
    except Exception:
        return []

    examples: list[dict] = []

    with neo4j_session() as s:
        # Alle Projekte mit Szenen-Energie-Daten
        projects = s.run("""
            MATCH (p:BitwigProject)-[:HAS_SCENE]->(sc:Scene)
            WHERE sc.energy_level IS NOT NULL
            WITH p, sc ORDER BY sc.idx
            WITH p, collect({name: sc.name, energy: sc.energy_level,
                             active: sc.active_tracks, total: sc.total_tracks}) AS scenes
            RETURN p.name AS project, scenes
        """).data()

        for proj in projects:
            pname  = proj["project"]
            scenes = proj["scenes"]
            if not scenes:
                continue

            # Schwächste + stärkste Szene bestimmen
            sorted_scenes = sorted(scenes, key=lambda x: x["energy"] or 0)
            sparse_scene  = sorted_scenes[0]
            dense_scene   = sorted_scenes[-1]

            # Tracks pro Szene holen
            for sc in scenes[:4]:   # max 4 Szenen pro Projekt
                tracks_in_scene = s.run("""
                    MATCH (sr:SoundRecipe {project: $proj})-[:HAS_CLIP_IN_SCENE]->(sc:Scene {name: $scene, project: $proj})
                    RETURN sr.track_name AS name, sr.role AS role
                    ORDER BY sr.track_index LIMIT 6
                """, proj=pname, scene=sc["name"]).data()

                if not tracks_in_scene:
                    continue

                track_list = ", ".join(r["name"] for r in tracks_in_scene)
                energy_pct = int((sc["energy"] or 0) * 100)

                # Beispiel 1: get_song_context Aufruf
                examples.append({"messages": [
                    {"role": "user",
                     "content": f"Was spielt in der {sc['name']}-Szene von {pname}?"},
                    {"role": "assistant",
                     "content": json.dumps({
                         "tool": "get_song_context",
                         "args": {"project_name": pname}
                     }, ensure_ascii=False)},
                ]})

                # Beispiel 2: Kontext-bewusstes Pattern (spärliche Szene)
                if sc["name"] == sparse_scene["name"]:
                    examples.append({"messages": [
                        {"role": "user",
                         "content": (f"Schreibe ein Pattern für die {sc['name']}-Szene von {pname}. "
                                     f"Die Szene ist spärlich ({energy_pct}% Energie), "
                                     f"aktive Tracks: {track_list}.")},
                        {"role": "assistant",
                         "content": json.dumps({
                             "tool": "get_song_context",
                             "args": {"project_name": pname}
                         }, ensure_ascii=False)},
                    ]})

            # Szenen-Vergleich
            if sparse_scene and dense_scene and sparse_scene["name"] != dense_scene["name"]:
                examples.append({"messages": [
                    {"role": "user",
                     "content": (f"Erkläre den Unterschied zwischen {sparse_scene['name']}- "
                                 f"und {dense_scene['name']}-Szene in {pname}.")},
                    {"role": "assistant",
                     "content": (
                         f"In '{pname}':\n"
                         f"• **{sparse_scene['name']}**: {int((sparse_scene['energy'] or 0)*100)}% Energie "
                         f"— spärlich, {sparse_scene['active'] or '?'} von {sparse_scene['total'] or '?'} Tracks aktiv. "
                         f"Ideal für ruhige, minimalistische Patterns.\n"
                         f"• **{dense_scene['name']}**: {int((dense_scene['energy'] or 0)*100)}% Energie "
                         f"— voll, {dense_scene['active'] or '?'} von {dense_scene['total'] or '?'} Tracks aktiv. "
                         f"Patterns sollen dicht und energetisch sein."
                     )},
                ]})

    return examples


def _chord_progression_examples() -> list[dict]:
    """Akkordfolge-Trainingsbeispiele aus Neo4j DIATONIC_CHORD Relations."""
    try:
        from src.knowledge.neo4j_graph import is_available, session as neo4j_session
        if not is_available():
            return []
    except Exception:
        return []

    examples: list[dict] = []
    beats_per_chord = 2.0

    with neo4j_session() as s:
        scales = s.run("""
            MATCH (sc:Scale)
            WHERE sc.type IN ['major', 'minor']
            RETURN sc.name_de AS name_de, sc.name_en AS name_en, sc.type AS type
            ORDER BY sc.midi_root, sc.type
        """).data()

        for sc in scales:
            chords_data = s.run("""
                MATCH (sc:Scale {name_en: $en})-[r:DIATONIC_CHORD]->(ch:Chord)
                RETURN r.degree AS degree, ch.notes AS notes, ch.symbol AS symbol
                ORDER BY r.degree
            """, en=sc["name_en"]).data()

            if len(chords_data) < 5:
                continue

            degree_notes   = {cd["degree"]: list(cd["notes"]) for cd in chords_data}
            degree_symbols = {cd["degree"]: cd["symbol"]       for cd in chords_data}

            for deg_list, roman, prog_type in _PROGRESSIONS:
                if prog_type != sc["type"]:
                    continue
                if not all(d in degree_notes for d in deg_list):
                    continue

                notes: list[dict] = []
                for beat_idx, deg in enumerate(deg_list):
                    step = int(beat_idx * beats_per_chord * _STEPS_PER_BEAT)
                    for pitch in degree_notes[deg]:
                        notes.append({
                            "step":     step,
                            "pitch":    pitch,
                            "velocity": 75,
                            "duration": beats_per_chord - 0.1,
                        })

                length_beats = len(deg_list) * beats_per_chord
                symbols = "-".join(degree_symbols.get(d, "?") for d in deg_list)

                prompts = [
                    f"Schreibe eine {roman} Akkordfolge in {sc['name_de']}, {length_beats:.0f} Beats.",
                    f"{roman} Progression in {sc['name_de']} ({symbols}), {length_beats:.0f} Beats für Chord-Track.",
                ]
                answer = json.dumps({
                    "tool": "write_pattern",
                    "args": {
                        "track_name":   "Chord",
                        "notes":        notes,
                        "length_beats": length_beats,
                        "key":          sc["name_en"],
                    }
                }, ensure_ascii=False)

                for prompt in prompts:
                    examples.append({"messages": [
                        {"role": "user",      "content": prompt},
                        {"role": "assistant", "content": answer},
                    ]})

    return examples


def get_export_stats(output_path: str = "./training_data") -> dict[str, Any]:
    """Liest Export-Statistiken des letzten Exports."""
    stats_path = Path(output_path) / "export_stats.json"
    if not stats_path.exists():
        return {"error": "Noch kein Export — export_mlx_training_data zuerst aufrufen"}
    try:
        return json.loads(stats_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": str(exc)}


@tool
def export_mlx_training_data(
    output_path: str = "./training_data",
    min_score: float = 0.70,
    limit: int = 500,
) -> str:
    """Exportiert validierte Patterns aus Neo4j als JSONL für MLX LoRA Fine-Tuning auf Mac.

    Erstellt train.jsonl + valid.jsonl (Chat-Format) + export_stats.json.
    Enthält: Pattern-Generierungs-Beispiele aus Neo4j + Music-Theory-Beispiele.
    Empfehlung: Mindestens 20–30 validate_and_learn-Iterationen vor dem Export.
    """
    result = export_training_data(output_path, min_score, limit)

    if not result.get("exported"):
        return f"[MLX Export] Fehlgeschlagen: {result.get('error')}"

    lines = [
        f"[MLX Export] ✓ {result['train_count']} Train + {result['valid_count']} Valid Beispiele",
        f"Neo4j Patterns: {result['neo4j_patterns']} | Theory: {result['theory_examples']}",
        f"Ausgabe: {result['output_path']}/",
        "",
        "Nächste Schritte (auf Mac Terminal):",
        "  make mlx-setup        # MLX + mlx-lm installieren",
        "  make mlx-sync-data    # Daten auf Mac übertragen",
        "  make mlx-train        # LoRA Fine-Tuning starten",
    ]
    return "\n".join(lines)

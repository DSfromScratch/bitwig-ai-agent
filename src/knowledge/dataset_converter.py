"""
Dataset-Konverter für MLX Fine-tuning.

Konvertiert verschiedene Musik-Datasets in das einheitliche Format:
  {"prompt": "...", "completion": "..."}

Unterstützte Datasets:
  - drums-with-llm (Drum-Pattern Generation)
  - MusicTheoryBench (Musik-Theorie QA)
  - SynTheory (Akkorde, Skalen, Progressionen)
  - Eigene Neo4j ProductionPattern Daten
"""
from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Iterator

log = logging.getLogger("bitwigbridge.training")

RAW_DIR    = Path(__file__).parent.parent.parent / "training_data" / "raw"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "training_data"

# ── Drum-Note-Namen für Konvertierung ─────────────────────────────────────────

_DRUM_ROWS = ["kick", "snare", "hi-hat", "open-hat", "crash", "ride", "tom1", "tom2"]
_DRUM_MIDI = {"kick": 36, "snare": 38, "hi-hat": 42, "open-hat": 46,
              "crash": 49, "ride": 51, "tom1": 45, "tom2": 47}


def _drumroll_to_midi_notes(drumroll: str) -> list[dict]:
    """Konvertiert Text-Drumroll (drums-with-llm Format) zu MIDI-Noten.

    Format: jede Zeile = ein Drum-Instrument, o = Hit, - = Pause
    Zeilen getrennt durch SEP
    """
    notes = []
    bars  = drumroll.strip().split("SEP\n")
    for bar_idx, bar in enumerate(bars):
        lines = [l for l in bar.strip().split("\n") if l]
        for row_idx, line in enumerate(lines[:len(_DRUM_ROWS)]):
            drum  = _DRUM_ROWS[row_idx]
            pitch = _DRUM_MIDI.get(drum, 36)
            for step_idx, char in enumerate(line):
                if char == "o":
                    step = bar_idx * 4.0 + step_idx * 0.25
                    notes.append({"step": step, "pitch": pitch, "vel": 0.85, "dur": 0.25})
    return notes


def _notes_to_summary(notes: list[dict]) -> str:
    """Kurzbeschreibung eines Note-Patterns."""
    from collections import Counter
    _NAMES = {36:"Kick",38:"Snare",42:"HH",46:"OpenHH",49:"Crash",51:"Ride",45:"Tom1",47:"Tom2"}
    pitches = Counter(n["pitch"] for n in notes)
    parts   = [f"{_NAMES.get(p,f'MIDI{p}')}({c}×)" for p, c in sorted(pitches.items())]
    return ", ".join(parts)


# ── Konverter: drums-with-llm ─────────────────────────────────────────────────

def convert_drums_with_llm(max_examples: int = 400) -> Iterator[dict]:
    """Konvertiert drums-with-llm JSONL zu Bewertungs-Prompt/Completion."""
    path = RAW_DIR / "drums-with-llm" / "gpt3_train.jsonl"
    if not path.exists():
        log.warning("drums-with-llm nicht gefunden: %s", path)
        return

    count = 0
    with open(path) as f:
        for line in f:
            if count >= max_examples:
                break
            item = json.loads(line)
            prompt_roll = item.get("prompt", "")
            comp_roll   = item.get("completion", "")

            notes = _drumroll_to_midi_notes(prompt_roll)
            if not notes:
                continue

            summary     = _notes_to_summary(notes)
            bars        = prompt_roll.count("SEP")
            kick_count  = sum(1 for n in notes if n["pitch"] == 36)
            snare_count = sum(1 for n in notes if n["pitch"] == 38)
            hh_count    = sum(1 for n in notes if n["pitch"] == 42)
            total       = len(notes)
            hh_ratio    = hh_count / max(total, 1)

            # Kontext-Hinweise basierend auf Pattern-Qualität
            context = ""
            if kick_count >= 2 and snare_count >= 2:
                context = "Hinweis: Pattern hat Kick UND Snare — Grundstruktur vorhanden."
            elif kick_count == 0:
                context = "Hinweis: KEIN Kick — das ist ein wesentliches Problem."
            elif snare_count == 0:
                context = "Hinweis: KEINE Snare — das ist ein wesentliches Problem."

            # Prompt: Pattern-Bewertungsaufgabe
            prompt = (
                f"Du bist ein Musik-Produzent. Bewerte dieses {bars}-Takt Drum-Pattern objektiv.\n"
                f"Genre: Rock | {bars} Takte | 120 BPM\n"
                f"Pattern: {summary}\n"
                f"{context}\n\n"
                f"Bewertungskriterien: Kick auf Beat 1+3, Snare auf Beat 2+4 = gut (score >= 0.65).\n"
                f"Antworte als JSON mit: score (0-1), rhythmic_ok (bool), "
                f"issues (Liste, max 2), suggestions (Liste, max 2), summary (1 Satz)."
            )

            issues      = []
            suggestions = []

            # Basis-Score: vollständiges Kit = gut
            if kick_count >= 2 and snare_count >= 2 and hh_count >= 4:
                score = 0.80  # Vollständiges Kit mit ausreichend Noten
            elif kick_count >= 2 and snare_count >= 2:
                score = 0.72  # Kick + Snare vorhanden, HH sparsam
            elif kick_count >= 1 and snare_count >= 1:
                score = 0.60  # Mindeststruktur
            else:
                score = 0.35  # Fehlt Kick oder Snare

            # Abzüge
            if hh_ratio > 0.7:
                issues.append("HiHat dominiert das Pattern")
                suggestions.append("HiHat-Dichte reduzieren, mehr Kick/Snare-Dynamik")
                score -= 0.15
            elif hh_ratio > 0.6:
                issues.append("HiHat leicht überrepräsentiert")
                suggestions.append("HiHat-Variationen einbauen")
                score -= 0.05
            if kick_count < 2:
                issues.append("Zu wenig Kick-Noten für Rock-Pattern")
                suggestions.append("Kick auf Beat 1 und 3 setzen")
                score -= 0.15
            if snare_count < 2:
                issues.append("Snare fehlt oder zu selten")
                suggestions.append("Snare auf Beat 2 und 4 für klaren Backbeat")
                score -= 0.20
            if total < 4:
                issues.append("Pattern zu minimal")
                suggestions.append("Mehr Rhythmus-Elemente hinzufügen")
                score -= 0.15

            score    = round(max(0.2, min(1.0, score)), 2)
            rhythmic = kick_count >= 2 and snare_count >= 2

            completion = json.dumps({
                "score":        score,
                "rhythmic_ok":  rhythmic,
                "harmonic_ok":  True,
                "genre_fit":    True,
                "issues":       issues,
                "suggestions":  suggestions,
                "summary":      f"Pattern mit {total} Noten, Score {score:.2f}.",
            }, ensure_ascii=False)

            yield {"prompt": prompt, "completion": completion}
            count += 1

    log.info("drums-with-llm: %d Beispiele konvertiert", count)


# ── Konverter: MusicTheoryBench ───────────────────────────────────────────────

def convert_music_theory_bench(max_examples: int = 300) -> Iterator[dict]:
    """Konvertiert MusicTheoryBench QA zu Instruction-Following Format."""
    path = RAW_DIR / "music_theory_bench" / "data.jsonl"
    if not path.exists():
        log.warning("MusicTheoryBench nicht gefunden: %s", path)
        return

    count = 0
    with open(path) as f:
        for line in f:
            if count >= max_examples:
                break
            item = json.loads(line)
            stem     = item.get("stem", "")
            options  = item.get("options", {})
            answer   = item.get("answer", "")
            analysis = item.get("analysis", "")
            subject  = item.get("subject", "")

            if not stem or not answer:
                continue

            # Nur produktionsrelevante Fragen
            relevant_subjects = {"rhythm", "harmony", "chord", "melody", "mixing",
                                  "dynamics", "form", "orchestration", "music production"}
            if not any(s in subject.lower() for s in relevant_subjects):
                if not any(kw in stem.lower() for kw in
                           ["chord", "rhythm", "beat", "tempo", "key", "scale",
                            "bass", "drum", "mix", "eq", "compress"]):
                    count += 1  # Zählen aber überspringen
                    continue

            opts_str = "\n".join(f"{k}) {v}" for k, v in options.items())
            prompt   = f"Musikfrage: {stem}\n\nOptionen:\n{opts_str}\n\nWelche Antwort ist korrekt?"
            comp     = f"Antwort: {answer}"
            if analysis:
                comp += f"\n\nErklärung: {analysis}"

            yield {"prompt": prompt, "completion": comp}
            count += 1

    log.info("MusicTheoryBench: %d Beispiele konvertiert", count)


# ── Konverter: SynTheory ──────────────────────────────────────────────────────

def convert_syntheory(max_examples: int = 300) -> Iterator[dict]:
    """Konvertiert SynTheory Annotationen zu Musik-Theorie Training-Daten."""
    configs = ["chords", "scales", "simple_progressions", "time_signatures"]
    count   = 0

    for config in configs:
        path = RAW_DIR / "syntheory" / f"{config}.jsonl"
        if not path.exists():
            continue

        with open(path) as f:
            for line in f:
                if count >= max_examples:
                    break
                item = json.loads(line)

                if config == "chords":
                    root  = item.get("root_note", "C")
                    ctype = item.get("chord_type", "major")
                    notes = item.get("notes", [])
                    prompt = (
                        f"Erkläre den {root} {ctype} Akkord für die Musikproduktion:\n"
                        f"Welche Noten enthält er und wie klingt er?"
                    )
                    completion = (
                        f"Der {root} {ctype} Akkord besteht aus den Noten: "
                        f"{', '.join(str(n) for n in notes[:5])}. "
                        f"Er klingt {'hell und dur-artig' if 'major' in ctype else 'dunkel und moll-artig'}."
                    )

                elif config == "scales":
                    root  = item.get("root_note", "C")
                    stype = item.get("scale_type", "major")
                    notes = item.get("notes", [])
                    prompt = (
                        f"Beschreibe die {root} {stype} Tonleiter für die DAW-Produktion:\n"
                        f"Welche Noten enthält sie?"
                    )
                    completion = (
                        f"Die {root} {stype} Tonleiter enthält: "
                        f"{', '.join(str(n) for n in notes[:8])}. "
                        f"Geeignet für: {'helle, positive Melodien' if 'major' in stype else 'emotionale, dunkle Musik'}."
                    )

                elif config == "simple_progressions":
                    prog  = item.get("progression", [])
                    key   = item.get("key", "C major")
                    prompt = (
                        f"Bewerte diese Akkordfolge in {key} für einen Song:\n"
                        f"Progression: {' - '.join(str(c) for c in prog)}"
                    )
                    completion = (
                        f"Die Akkordfolge {' - '.join(str(c) for c in prog)} in {key} "
                        f"ist {'harmonisch stimmig' if len(prog) >= 3 else 'sehr kurz'}. "
                        f"Empfehlung: 4-takt Loop mit gleichmäßigen Chord-Wechseln pro Takt."
                    )

                elif config == "time_signatures":
                    num  = item.get("numerator", 4)
                    den  = item.get("denominator", 4)
                    prompt = (
                        f"Erkläre den {num}/{den} Takt für die DAW-Produktion:\n"
                        f"Wie beeinflusst er Drums und Bassline?"
                    )
                    completion = (
                        f"Im {num}/{den} Takt gibt es {num} Schläge pro Takt. "
                        f"{'Standard für Rock/Pop/Electronic' if num == 4 else 'Walzer-Feeling' if num == 3 else 'Ungerader Rhythmus'}. "
                        f"Kick-Muster: Beat 1 und {num//2+1 if num > 2 else 2}."
                    )
                else:
                    continue

                yield {"prompt": prompt, "completion": completion}
                count += 1

    log.info("SynTheory: %d Beispiele konvertiert", count)


# ── Konverter: Neo4j ProductionPattern ───────────────────────────────────────

def convert_neo4j_patterns(min_score: float = 0.0) -> Iterator[dict]:
    """Konvertiert Neo4j ProductionPattern-Knoten zu Training-Daten."""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "neo4jllm")),
        )
        with driver.session() as s:
            patterns = s.run(
                "MATCH (p:ProductionPattern) WHERE p.iteration IS NOT NULL "
                "RETURN p.instrument AS instrument, p.genre AS genre, "
                "       p.key AS key, p.scale AS scale, "
                "       p.avg_score AS score, p.last_issues AS issues, "
                "       p.last_suggestions AS suggestions, p.iteration AS iter"
            ).data()
        driver.close()
    except Exception as exc:
        log.debug("Neo4j nicht verfügbar: %s", exc)
        return

    for p in patterns:
        inst = p.get("instrument", "?")
        genre = p.get("genre", "rock")
        score = p.get("score", 0.5) or 0.5
        issues = p.get("issues") or []
        suggestions = p.get("suggestions") or []

        prompt = (
            f"Bewerte ein MIDI-Pattern:\n"
            f"Instrument: {inst} | Genre: {genre} | "
            f"Key: {p.get('key','C')} {p.get('scale','minor')} | 2 Takte | 120 BPM\n"
            f"Antworte als JSON."
        )
        completion = json.dumps({
            "score":       round(score, 2),
            "rhythmic_ok": score >= 0.6,
            "harmonic_ok": True,
            "genre_fit":   score >= 0.5,
            "issues":      issues,
            "suggestions": suggestions,
            "summary":     f"Score {score:.2f} für {inst} im {genre} Genre.",
        }, ensure_ascii=False)

        yield {"prompt": prompt, "completion": completion}

    log.info("Neo4j: %d ProductionPattern-Knoten konvertiert", len(patterns))


# ── Gold-Standard Positive-Beispiele ─────────────────────────────────────────

def generate_gold_standard_examples(count_per_genre: int = 30) -> Iterator[dict]:
    """Generiert explizit gute Patterns mit hohen Scores (0.75-0.90).

    Ziel: Ausgleich des Score-Ungleichgewichts (bisher 68% < 0.65).
    Erzeugt ca. 250 positive Beispiele aus bekannt-guten Pattern-Kombinationen.
    """
    try:
        from src.agent.tools.pattern_generators import (
            _drums, _bass, _chords, _808_kick, _808_snare
        )
        from src.agent.tools.music_data import _root_midi
    except ImportError:
        log.warning("pattern_generators nicht verfügbar")
        return

    _NAMES = {36:"Kick",37:"Rim",38:"Snare",39:"Clap",42:"HH",44:"PedHH",
              46:"OpenHH",49:"Crash",51:"Ride",45:"Tom1",47:"Tom2"}

    # Genre-Konfigurationen: (genre, instrument, bars, style, key, expected_score)
    genre_configs = [
        # Drums — vollständige Kits mit Kick+Snare+HH
        ("rock",    "VD-HEAVY",  2, "full",    "A", 0.82),
        ("rock",    "VD-HEAVY",  2, "basic",   "A", 0.75),
        ("hip-hop", "VD-HEAVY",  2, "basic",   "C", 0.77),
        ("trap",    "VD-HEAVY",  2, "basic",   "A", 0.76),
        ("funk",    "VD-HEAVY",  2, "basic",   "D", 0.78),
        ("pop",     "VD-HEAVY",  2, "basic",   "C", 0.75),
        # Bass — Root+Quinte Patterns
        ("rock",    "VB-ROYAL",  2, "basic",   "A", 0.75),
        ("rock",    "VB-ROYAL",  2, "full",    "E", 0.80),
        ("hip-hop", "VB-MELLOW", 2, "basic",   "A", 0.76),
        ("funk",    "VB-ROYAL",  2, "funk",    "G", 0.82),
        ("jazz",    "VB-MELLOW", 2, "jazz",    "C", 0.78),
        # Chords — harmonisch korrekte Progressionen
        ("rock",    "VG-IRON2",  2, "staccato", "A", 0.77),
        ("pop",     "VG-SILK2",  2, "arpeggio", "C", 0.79),
        ("jazz",    "Dexed",     2, "sustained","C", 0.80),
    ]

    count = 0
    for genre, instrument, bars, style, key, base_score in genre_configs:
        for _ in range(count_per_genre):
            try:
                inst_lower = instrument.lower().replace("-","").replace(" ","")
                if any(k in inst_lower for k in ["vdheavy","drum","percussion"]):
                    notes = _drums(genre, bars, style)
                elif any(k in inst_lower for k in ["vb","bass","fm4","surge"]):
                    notes = _bass(genre, bars, _root_midi(key, octave=2), style)
                elif any(k in inst_lower for k in ["vg","guitar","phase4","dexed"]):
                    from src.agent.tools.music_data import _DEFAULT_PROGRESSIONS
                    chords_list = _DEFAULT_PROGRESSIONS.get(genre, ["C","Am","F","G"])
                    from src.agent.tools.pattern_generators import _chords
                    notes = _chords(genre, bars, chords_list, style)
                else:
                    continue

                if not notes:
                    continue

                from collections import Counter
                pitches = Counter(n.get("pitch",0) for n in notes)
                parts   = [f"{_NAMES.get(p,f'MIDI{p}')}({c}×)" for p,c in sorted(pitches.items())]
                summary = ", ".join(parts[:6])

                # Kontexthinweis für vollständige Drum-Kits
                context = ""
                kick_c  = pitches.get(36,0) + pitches.get(40,0)
                snare_c = pitches.get(38,0) + pitches.get(39,0)
                hh_c    = pitches.get(42,0) + pitches.get(44,0) + pitches.get(46,0)
                if kick_c >= 2 and snare_c >= 2:
                    context = "Hinweis: Pattern hat Kick UND Snare — Grundstruktur vorhanden.\n"

                prompt = (
                    f"Du bist ein Musik-Produzent. Bewerte dieses {bars}-Takt {genre}-Pattern objektiv.\n"
                    f"Instrument: {instrument} | Key: {key} | {bars} Takte | 120 BPM\n"
                    f"Pattern: {summary}\n"
                    f"{context}"
                    f"Bewertungskriterien: Kick auf Beat 1+3, Snare auf Beat 2+4 = gut (score >= 0.65).\n"
                    f"Antworte als JSON mit: score (0-1), rhythmic_ok (bool), "
                    f"issues (Liste, max 2), suggestions (Liste, max 2), summary (1 Satz)."
                )

                # Score leicht variieren für Diversität
                import random
                score = round(base_score + random.uniform(-0.05, 0.05), 2)
                score = max(0.65, min(0.95, score))

                rhythmic = kick_c >= 2 and snare_c >= 2 or len(notes) >= 6
                issues   = []
                suggestions = []
                if hh_c == 0 and any(k in inst_lower for k in ["vdheavy","drum"]):
                    issues.append("Kein HiHat — könnte rhythmisch flacher klingen")
                    suggestions.append("HiHat auf Achtel oder Sechzehntel hinzufügen")
                    score = round(score - 0.05, 2)

                completion = json.dumps({
                    "score":       score,
                    "rhythmic_ok": rhythmic,
                    "harmonic_ok": True,
                    "genre_fit":   True,
                    "issues":      issues,
                    "suggestions": suggestions,
                    "summary":     f"Gut strukturiertes {genre}-Pattern mit {len(notes)} Noten, Score {score:.2f}.",
                }, ensure_ascii=False)

                yield {"prompt": prompt, "completion": completion}
                count += 1
            except Exception as exc:
                log.debug("Gold-Standard Beispiel fehlgeschlagen: %s", exc)

    log.info("Gold-Standard: %d positive Beispiele generiert", count)


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def prepare_all_datasets(
    output_file: str | None = None,
    shuffle: bool = True,
    val_split: float = 0.1,
) -> dict[str, int]:
    """Konvertiert alle verfügbaren Datasets und erstellt Train/Val JSONL.

    Returns: {"train": N, "val": M, "total": N+M}
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_examples = []

    converters = [
        ("drums-with-llm",    convert_drums_with_llm,      400),
        ("MusicTheoryBench",  convert_music_theory_bench,  300),
        ("SynTheory",         convert_syntheory,            300),
        ("Gold-Standard",     generate_gold_standard_examples, None),  # Positive-Ausgleich
        ("Neo4j",             convert_neo4j_patterns,       None),
    ]

    for name, converter_fn, max_ex in converters:
        before = len(all_examples)
        try:
            kwargs = {"max_examples": max_ex} if max_ex else {}
            for ex in converter_fn(**kwargs):
                all_examples.append(ex)
        except Exception as exc:
            log.warning("%s Konvertierung fehlgeschlagen: %s", name, exc)
        added = len(all_examples) - before
        log.info("%s: +%d Beispiele (gesamt: %d)", name, added, len(all_examples))
        print(f"  {name}: +{added} Beispiele")

    if shuffle:
        random.shuffle(all_examples)

    # Train/Val Split
    val_size   = max(1, int(len(all_examples) * val_split))
    val_data   = all_examples[:val_size]
    train_data = all_examples[val_size:]

    train_path = OUTPUT_DIR / "train.jsonl"
    val_path   = OUTPUT_DIR / "valid.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for ex in train_data:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    with open(val_path, "w", encoding="utf-8") as f:
        for ex in val_data:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\n✓ Train: {len(train_data)} → {train_path}")
    print(f"✓ Val:   {len(val_data)} → {val_path}")

    return {"train": len(train_data), "val": len(val_data), "total": len(all_examples)}

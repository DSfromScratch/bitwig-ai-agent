#!/usr/bin/env python3
"""
Generiert Genre-Translation-Trainingspairs:
  web_search + find_audio_example → write_pattern() Chain-of-Thought

Jedes Paar zeigt dem Modell wie es aus Genre-Stil-Wissen konkrete MIDI-Notes ableitet.
→ data/training/genre_pairs.jsonl  (~90 Paare)
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(42)

# ── MIDI-Konstanten ────────────────────────────────────────────────────────────
KICK = 36; SNARE = 38; CLAP = 39; HIHAT_C = 42; OPEN_HAT = 46; RIDE = 51; TOM = 47
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SCALE_INTERVALS = {
    "major":    [0, 2, 4, 5, 7, 9, 11],
    "minor":    [0, 2, 3, 5, 7, 8, 10],
    "dorian":   [0, 2, 3, 5, 7, 9, 10],
    "phrygian": [0, 1, 3, 5, 7, 8, 10],
}


def root_midi(root: str, octave: int = 3) -> int:
    return NOTE_NAMES.index(root) + (octave + 1) * 12


def scale_pitches(root: str, scale_type: str, octave: int = 3) -> list[int]:
    base = root_midi(root, octave)
    return [base + i for i in SCALE_INTERVALS.get(scale_type, SCALE_INTERVALS["minor"])]


def make_note(pitch: int, step: int, duration: int = 2,
              velocity: float = 0.85, channel: int = 0) -> dict:
    return {"pitch": pitch, "step": step,
            "duration": duration, "velocity": round(velocity, 2), "channel": channel}


# ── Genre-Datenbank ────────────────────────────────────────────────────────────
GENRES: dict[str, dict] = {
    "Dark Techno": {
        "bpm_range": (130, 140), "energy": 0.9,
        "keys": [("D", "minor"), ("E", "minor"), ("A", "minor"), ("F#", "minor")],
        "web_snippet": "Dark Techno: 130–140 BPM, schwerer verzerrter Kick (4-on-the-floor), industrielle Atmosphäre, Moll-Tonarten, treibende Bassline, sparsame Melodie, Berlin-Stil",
        "kick_steps": [0, 4, 8, 12], "snare_steps": [4, 12],
        "hat_steps": [2, 6, 10, 14], "bass_rhythm": [0, 6, 10],
        "onset_steps": [0, 4, 8, 12], "hat_vel": 0.55,
    },
    "UK Garage": {
        "bpm_range": (130, 135), "energy": 0.75,
        "keys": [("C", "minor"), ("G", "minor"), ("D", "minor"), ("A", "minor")],
        "web_snippet": "UK Garage: 130–135 BPM, synkopierter 2-Step-Beat (nicht 4-on-floor), Swing, Off-Beat-Bassline, kurze Vocal-Chops, Moll-Akkorde",
        "kick_steps": [0, 3, 10], "snare_steps": [4, 14],
        "hat_steps": [0, 2, 4, 6, 8, 10, 12, 14], "bass_rhythm": [0, 3, 8, 11],
        "onset_steps": [0, 3, 10, 14], "hat_vel": 0.5,
    },
    "Drum and Bass": {
        "bpm_range": (170, 180), "energy": 0.95,
        "keys": [("D", "minor"), ("G", "minor"), ("B", "minor"), ("E", "minor")],
        "web_snippet": "Drum and Bass: 170–180 BPM, Breakbeat (Kick 0+2.5, Snare 2+3), rollende 16tel-Bassline, tiefer Sub-Bass, energetisch",
        "kick_steps": [0, 5, 8, 13], "snare_steps": [4, 12],
        "hat_steps": list(range(16)), "bass_rhythm": [0, 2, 4, 6, 8, 10, 12],
        "onset_steps": [0, 5, 8, 13], "hat_vel": 0.45,
    },
    "Lo-fi Hip Hop": {
        "bpm_range": (75, 90), "energy": 0.45,
        "keys": [("C", "major"), ("F", "major"), ("G", "major"), ("A", "minor"), ("D", "minor")],
        "web_snippet": "Lo-fi Hip Hop: 75–90 BPM, geschwungener Boom-Bap-Beat (Kick 1+3, Snare 2+4), warme Vinyl-Textur, Jazz-Akkorde, entspannte Atmosphäre",
        "kick_steps": [0, 10], "snare_steps": [4, 12],
        "hat_steps": [0, 3, 6, 9, 12, 15], "bass_rhythm": [0, 4, 8],
        "onset_steps": [0, 4, 10, 12], "hat_vel": 0.4,
    },
    "House": {
        "bpm_range": (120, 130), "energy": 0.7,
        "keys": [("C", "minor"), ("G", "minor"), ("F", "minor"), ("A", "minor")],
        "web_snippet": "House: 120–130 BPM, 4-on-the-Floor Kick, Clap/Snare auf 2+4, 8tel Hi-Hats, soulful Akkorde, Off-Beat-Bassline, Chicago-Roots",
        "kick_steps": [0, 4, 8, 12], "snare_steps": [4, 12],
        "hat_steps": [0, 2, 4, 6, 8, 10, 12, 14], "bass_rhythm": [0, 2, 6, 10],
        "onset_steps": [0, 4, 8, 12], "hat_vel": 0.5,
    },
    "Trap": {
        "bpm_range": (130, 150), "energy": 0.85,
        "keys": [("C", "minor"), ("A", "minor"), ("G", "minor"), ("D", "minor")],
        "web_snippet": "Trap: 130–150 BPM, schwerer 808-Bass (lang ausgehaltene Töne), Snare auf 2+4, 16tel und 32tel Hi-Hat-Rolls, Atlanta-Stil",
        "kick_steps": [0, 6, 10], "snare_steps": [4, 12],
        "hat_steps": list(range(16)), "bass_rhythm": [0, 6, 10, 14],
        "onset_steps": [0, 4, 6, 10, 12], "hat_vel": 0.35,
    },
    "Ambient": {
        "bpm_range": (60, 90), "energy": 0.2,
        "keys": [("C", "major"), ("G", "major"), ("D", "major"), ("A", "major"), ("F", "major")],
        "web_snippet": "Ambient: 60–90 BPM oder kein Tempo, lange Pad-Flächen, keine oder sehr sparsame Percussion, atmosphärische Texturen, Dur-Tonarten, langsame Akkordwechsel",
        "kick_steps": [], "snare_steps": [],
        "hat_steps": [], "bass_rhythm": [0, 8],
        "onset_steps": [0, 8], "hat_vel": 0.3,
    },
    "Kuduro": {
        "bpm_range": (140, 155), "energy": 1.0,
        "keys": [("A", "minor"), ("E", "minor"), ("D", "minor")],
        "web_snippet": "Kuduro: 140–155 BPM, angolanische Roots, synkopierte Kicks (nicht 4-on-floor), aggressive Percussion, sehr energetisch, Tanzmusik aus Luanda",
        "kick_steps": [0, 3, 7, 12], "snare_steps": [4, 14],
        "hat_steps": [0, 2, 6, 8, 10, 14], "bass_rhythm": [0, 3, 8, 12],
        "onset_steps": [0, 3, 7, 12], "hat_vel": 0.6,
    },
    "Minimal Techno": {
        "bpm_range": (124, 130), "energy": 0.6,
        "keys": [("C", "minor"), ("D", "minor"), ("F", "minor")],
        "web_snippet": "Minimal Techno: 124–130 BPM, sehr sparsame Elemente, 4-on-floor Kick, subtile Percussion-Details, Hypnotik durch Wiederholung, Frankfurt/Detroit",
        "kick_steps": [0, 4, 8, 12], "snare_steps": [8],
        "hat_steps": [2, 10], "bass_rhythm": [0, 8],
        "onset_steps": [0, 4, 8, 12], "hat_vel": 0.35,
    },
    "Neurofunk": {
        "bpm_range": (172, 180), "energy": 0.95,
        "keys": [("D", "minor"), ("F#", "minor"), ("G", "minor")],
        "web_snippet": "Neurofunk: 172–180 BPM, komplexe Breakbeat-Muster, modulierende FM/Reese-Basslines, dunkle industrielle Atmosphäre, technische Drum-Programmierung",
        "kick_steps": [0, 3, 7, 9, 13], "snare_steps": [4, 11, 14],
        "hat_steps": [1, 3, 5, 7, 9, 11, 13], "bass_rhythm": [0, 1, 3, 5, 7, 9, 11],
        "onset_steps": [0, 3, 7, 9, 13], "hat_vel": 0.4,
    },
    "Deep House": {
        "bpm_range": (120, 126), "energy": 0.6,
        "keys": [("F", "minor"), ("G", "minor"), ("C", "minor"), ("A#", "minor")],
        "web_snippet": "Deep House: 120–126 BPM, warme Bassline, subtiler 4-on-floor Kick, jazzy Akkorde, Piano-Chords, atmosphärische Vocals, soulful",
        "kick_steps": [0, 4, 8, 12], "snare_steps": [4, 12],
        "hat_steps": [1, 3, 5, 7, 9, 11, 13, 15], "bass_rhythm": [0, 2, 6, 10, 14],
        "onset_steps": [0, 4, 8, 12], "hat_vel": 0.45,
    },
    "Juke / Footwork": {
        "bpm_range": (158, 162), "energy": 0.9,
        "keys": [("C", "minor"), ("G", "minor"), ("A", "minor")],
        "web_snippet": "Juke/Footwork: 160 BPM, polyrhythmische Percussion, Kick auf unerwarteten Positionen (nicht quantisiert), 16tel Hi-Hat-Rolls, Chicago-Roots, Vocal-Samples",
        "kick_steps": [0, 2, 5, 8, 11, 13], "snare_steps": [3, 7, 12, 15],
        "hat_steps": list(range(16)), "bass_rhythm": [0, 4, 8, 10],
        "onset_steps": [0, 2, 5, 8, 11, 13], "hat_vel": 0.45,
    },
    "Detroit Techno": {
        "bpm_range": (120, 132), "energy": 0.75,
        "keys": [("D", "minor"), ("A", "minor"), ("G", "minor")],
        "web_snippet": "Detroit Techno: 120–132 BPM, funkige Bassline, 4-on-floor mit Swing, soulful Synthesizer-Melodien, afroamerikanische Wurzeln, Roland TR-808/909",
        "kick_steps": [0, 4, 8, 12], "snare_steps": [4, 12],
        "hat_steps": [0, 2, 4, 6, 8, 10, 12, 14], "bass_rhythm": [0, 2, 5, 8, 11, 14],
        "onset_steps": [0, 4, 8, 12], "hat_vel": 0.5,
    },
}

SECTIONS = {
    "Intro":   {"energy_factor": 0.5,  "desc": "sparsam, Aufbau"},
    "Drop":    {"energy_factor": 1.0,  "desc": "volle Energie, alle Elemente"},
    "Bridge":  {"energy_factor": 0.7,  "desc": "Variation, mittlere Dichte"},
    "Outro":   {"energy_factor": 0.4,  "desc": "ausdünnend, wenige Elemente"},
}


# ── Paar-Generator ─────────────────────────────────────────────────────────────

def drum_notes(g: dict, section_energy: float) -> list[dict]:
    notes = []
    vel_base = g["energy"] * section_energy
    for s in g["kick_steps"]:
        notes.append(make_note(KICK, s, duration=2, velocity=min(1.0, vel_base * 1.1)))
    for s in g["snare_steps"]:
        notes.append(make_note(SNARE, s, duration=2, velocity=min(1.0, vel_base * 0.95)))
    if section_energy >= 0.5:
        for s in g["hat_steps"]:
            notes.append(make_note(HIHAT_C, s, duration=1, velocity=g["hat_vel"] * section_energy))
    return sorted(notes, key=lambda n: n["step"])


def bass_notes(g: dict, root: str, scale_type: str, section_energy: float) -> list[dict]:
    pitches = scale_pitches(root, scale_type, octave=2)
    rhythm = g["bass_rhythm"]
    # Fülle 16 Steps durch Wiederholung des Bass-Rhythmus (min 8 Noten)
    while len(rhythm) < 8:
        rhythm = rhythm + [s + 16 for s in rhythm if s + 16 < 16]
        if len(rhythm) < 8:
            rhythm = (rhythm * 3)[:8]
    notes = []
    for i, s in enumerate(rhythm):
        p = pitches[i % len(pitches)] if i % 2 == 0 else pitches[0]
        dur = 4 if section_energy < 0.6 else 2
        notes.append(make_note(p, s % 16, duration=dur,
                               velocity=round(max(0.35, 0.75 * section_energy), 2), channel=0))
    return sorted(notes, key=lambda n: n["step"])


def melody_notes(root: str, scale_type: str, onset_steps: list[int],
                 section_energy: float) -> list[dict]:
    pitches = scale_pitches(root, scale_type, octave=4)
    if not onset_steps:
        onset_steps = [0, 4, 8, 12]
    # Fülle auf min. 8 Noten durch zyklische Wiederholung der onset_steps
    active_steps = list(onset_steps)
    offset = 16
    while len(active_steps) < 8:
        new_steps = [s % 16 for s in onset_steps]
        for s in sorted(new_steps):
            candidate = (s + offset) % 16
            if candidate not in active_steps:
                active_steps.append(candidate)
        # Fallback: direkte Verdopplung wenn keine neuen Steps gefunden
        if len(active_steps) < 8:
            active_steps = sorted(set(active_steps + [s + 2 for s in active_steps
                                                       if s + 2 < 16 and s + 2 not in active_steps]))
        offset += 2
        if offset > 30:
            break
    active_steps = sorted(set(active_steps))[:16]
    notes = []
    melody_seq = [0, 2, 4, 3, 5, 1, 6, 0, 2, 4, 5, 3, 1, 6, 4, 2]
    for i, s in enumerate(active_steps):
        p = pitches[melody_seq[i % len(melody_seq)] % len(pitches)]
        dur = 3 if section_energy >= 0.7 else 5
        notes.append(make_note(p, s % 16, duration=dur,
                               velocity=round(max(0.35, 0.65 * section_energy), 2), channel=0))
    return sorted(notes, key=lambda n: n["step"])


def make_context(genre_name: str, g: dict, bpm: int, root: str,
                 scale_type: str, section: str) -> str:
    onset_str = str(g["onset_steps"])
    grid = "".join("X" if i in g["onset_steps"] else "." for i in range(16))
    return (
        f"web_search(\"{genre_name} genre characteristics BPM instruments\"):\n"
        f"→ {g['web_snippet']}\n\n"
        f"find_audio_example(\"{genre_name} drum loop\"):\n"
        f"→ BPM: {bpm}  |  Tonart: {root} {scale_type}  |  Energie: {g['energy']}\n"
        f"→ Takt 1: {grid}\n"
        f"→ Onset-Steps: {onset_str}\n\n"
        f"Szene: {section} ({SECTIONS[section]['desc']})"
    )


def make_cot_drum(genre_name: str, bpm: int, root: str, scale_type: str,
                  section: str, g: dict, ef: float) -> str:
    kick_str = str(g["kick_steps"]) if g["kick_steps"] else "keine (Ambient)"
    return (
        f"[Genre: {genre_name}] "
        f"[BPM: {bpm} aus find_audio_example] "
        f"[Tonart: {root} {scale_type}] "
        f"[Kick-Pattern: {kick_str} — typisch für {genre_name}] "
        f"[Snare: {g['snare_steps']}] "
        f"[Hi-Hat: {'alle 8tel' if len(g['hat_steps']) >= 8 else 'sparsam'}] "
        f"[Energie {section}: {round(ef*100)}% → {'alle Elemente' if ef >= 0.8 else 'reduzierte Dichte'}]"
    )


def make_cot_bass(genre_name: str, bpm: int, root: str, scale_type: str,
                  section: str, g: dict, ef: float) -> str:
    return (
        f"[Genre: {genre_name}] "
        f"[BPM: {bpm}] "
        f"[Tonart: {root} {scale_type} → Root auf Oktave 2] "
        f"[Bassline-Rhythmus: {g['bass_rhythm']} — typisch für {genre_name}] "
        f"[Energie {section}: {round(ef*100)}% → "
        f"{'volle Dichte' if ef >= 0.7 else 'sparsam, nur Root-Noten'}]"
    )


def make_cot_melody(genre_name: str, bpm: int, root: str, scale_type: str,
                    section: str, g: dict, ef: float) -> str:
    return (
        f"[Genre: {genre_name}] "
        f"[BPM: {bpm}] "
        f"[Tonart: {root} {scale_type} → diatonische Skala auf Oktave 4] "
        f"[Onset-Steps aus Analyse: {g['onset_steps']}] "
        f"[Energie {section}: {round(ef*100)}% → "
        f"{'vollständige Phrase' if ef >= 0.7 else 'sparsam, halbe Steps'}]"
    )


def completion(notes: list[dict], bpm: int, key: str) -> str:
    return json.dumps({
        "tool": "write_pattern",
        "args": {
            "bpm": bpm,
            "key": key,
            "notes": json.dumps(notes),
        }
    }, ensure_ascii=False)


# ── Paare generieren ───────────────────────────────────────────────────────────

def generate_pairs() -> list[dict]:
    pairs = []

    for genre_name, g in GENRES.items():
        bpm_min, bpm_max = g["bpm_range"]
        keys = g["keys"]

        for section, sec_info in SECTIONS.items():
            ef = sec_info["energy_factor"]
            root, scale_type = random.choice(keys)
            bpm = random.randint(bpm_min, bpm_max)
            key_label = f"{root} {scale_type}"
            ctx = make_context(genre_name, g, bpm, root, scale_type, section)

            # ── Drum-Paar ──────────────────────────────────────────────────────
            notes_d = drum_notes(g, ef)
            if notes_d or genre_name == "Ambient":
                pairs.append({
                    "prompt": f"Erstelle einen {genre_name} Drum-Track für den {section}-Abschnitt.",
                    "context": ctx,
                    "chain_of_thought": make_cot_drum(genre_name, bpm, root, scale_type, section, g, ef),
                    "completion": completion(notes_d, bpm, key_label),
                    "source": f"genre_translation/{genre_name}/drums/{section}",
                })

            # ── Bass-Paar ──────────────────────────────────────────────────────
            if g["bass_rhythm"]:
                notes_b = bass_notes(g, root, scale_type, ef)
                pairs.append({
                    "prompt": f"Schreibe eine {genre_name} Bassline in {key_label} für den {section}-Abschnitt.",
                    "context": ctx,
                    "chain_of_thought": make_cot_bass(genre_name, bpm, root, scale_type, section, g, ef),
                    "completion": completion(notes_b, bpm, key_label),
                    "source": f"genre_translation/{genre_name}/bass/{section}",
                })

            # ── Melodie-Paar (nur Drop + Bridge, nur melodische Genres) ───────
            if section in ("Drop", "Bridge") and genre_name not in ("Ambient",):
                notes_m = melody_notes(root, scale_type, g["onset_steps"], ef)
                pairs.append({
                    "prompt": f"Schreibe eine {genre_name} Synth-Melodie in {key_label} für den {section}-Abschnitt.",
                    "context": ctx,
                    "chain_of_thought": make_cot_melody(genre_name, bpm, root, scale_type, section, g, ef),
                    "completion": completion(notes_m, bpm, key_label),
                    "source": f"genre_translation/{genre_name}/melody/{section}",
                })

    return pairs


if __name__ == "__main__":
    out = Path("data/training/genre_pairs.jsonl")
    pairs = generate_pairs()
    random.shuffle(pairs)
    out.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n")
    print(f"✓ {len(pairs)} Genre-Translation-Paare → {out}")

    # Statistik
    from collections import Counter
    sources = Counter(p["source"].split("/")[1] for p in pairs)
    print("\nPaare pro Genre:")
    for genre, n in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {genre}: {n}")

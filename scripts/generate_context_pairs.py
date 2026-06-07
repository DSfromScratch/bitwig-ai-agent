"""
Ebene 3 Trainingsdaten: Kontext-bewusste write_pattern()-Paare aus echten Projekten.

Lädt alle Projekte aus Neo4j → generiert Chain-of-Thought-Paare:
  Song-Kontext (Tonart + Szene + bestehende Clips) → musikalisch informierter write_pattern()-Aufruf

Output: data/training/context_pairs.jsonl
"""
from __future__ import annotations
import os, sys, json, random
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

from src.knowledge.neo4j_graph import session

OUTPUT = Path("data/training/context_pairs.jsonl")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

MIDI_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def midi_name(midi: int) -> str:
    octave = (midi // 12) - 1
    return f"{MIDI_NAMES[midi % 12]}{octave}"


def load_projects(s) -> list[str]:
    rows = s.run("MATCH (p:BitwigProject) RETURN p.name AS name ORDER BY p.name").data()
    return [r["name"] for r in rows if r["name"]]


def load_clips_for_project(s, project: str) -> list[dict]:
    return s.run("""
        MATCH (mc:MidiClip {project: $project})
        WHERE mc.notes_json IS NOT NULL
        RETURN mc.track_name AS track, mc.scene_name AS scene,
               mc.full_key AS key, mc.loop_beats AS beats,
               mc.notes_json AS notes_json
        ORDER BY mc.track_name, mc.scene_name
    """, project=project).data()


def load_scenes_for_project(s, project: str) -> list[dict]:
    return s.run("""
        MATCH (sc:Scene {project: $project})
        RETURN sc.name AS name, sc.energy_level AS energy,
               sc.clip_count AS clip_count
        ORDER BY sc.energy_level DESC
    """, project=project).data()


def load_tracks_for_project(s, project: str) -> list[dict]:
    return s.run("""
        MATCH (sr:SoundRecipe {project: $project})
        RETURN sr.track_name AS track, sr.device_chain AS chain
        ORDER BY sr.track_index
    """, project=project).data()


def load_key_for_project(s, project: str) -> str:
    """Häufigste Tonart aus MidiClips."""
    rows = s.run("""
        MATCH (mc:MidiClip {project: $project})
        WHERE mc.full_key IS NOT NULL AND mc.full_key <> ''
        RETURN mc.full_key AS k, count(*) AS n
        ORDER BY n DESC LIMIT 1
    """, project=project).data()
    return rows[0]["k"] if rows else ""


def chord_from_notes(notes: list[dict], scale_notes: list[int] | None = None) -> str:
    """Einfache Akkord-Beschreibung aus ersten simultaneen Noten."""
    if not notes:
        return ""
    step0 = min(n["step"] for n in notes)
    chord_notes = sorted({n["pitch"] for n in notes if n["step"] == step0})
    if not chord_notes:
        return ""
    names = "+".join(midi_name(p) for p in chord_notes[:4])
    return names


def build_context_summary(project: str, key: str, scenes: list[dict],
                           tracks: list[dict], clips: list[dict]) -> str:
    """Kompakter Kontext-String für Prompt."""
    lines = [
        f"Projekt: {project}",
        f"Tonart: {key or 'unbekannt'}",
    ]

    if scenes:
        energies = " | ".join(
            f"{sc['name']}={int((sc['energy'] or 0)*100)}%"
            for sc in scenes[:6]
        )
        lines.append(f"Szenen-Energie: {energies}")

    if tracks:
        track_list = ", ".join(t["track"] for t in tracks[:10])
        lines.append(f"Tracks: {track_list}")
        if len(tracks) > 10:
            lines[-1] += f" … +{len(tracks)-10} weitere"

    return "\n".join(lines)


def generate_pairs_for_project(project: str, key: str, scenes: list[dict],
                                tracks: list[dict], clips: list[dict]) -> list[dict]:
    """Generiert kontext-bewusste Paare für ein Projekt."""
    pairs = []

    # Clips nach Szene gruppieren
    clips_by_scene: dict[str, list[dict]] = defaultdict(list)
    for c in clips:
        clips_by_scene[c["scene"] or ""].append(c)

    # Tracks ohne Clips in manchen Szenen (Lücken)
    active_track_names = {c["track"] for c in clips}
    all_track_names = {t["track"] for t in tracks}
    tracks_without_clips = list(all_track_names - active_track_names)

    ctx_summary = build_context_summary(project, key, scenes, tracks, clips)

    # ── Paar 1: Ergänze einen Track in einer energiereichen Szene ───────────
    if scenes and clips:
        high_energy_scene = max(scenes, key=lambda s: s["energy"] or 0)
        scene_clips = clips_by_scene.get(high_energy_scene["name"], [])

        # Einen existierenden Clip als Basis nehmen
        if scene_clips:
            base_clip = scene_clips[0]
            notes_raw = base_clip.get("notes_json") or "[]"
            try:
                base_notes = json.loads(notes_raw)
            except Exception:
                base_notes = []

            if base_notes:
                # Erzeuge neue Noten: Transposition des gleichen Musters
                new_notes = []
                for n in base_notes[:8]:
                    new_pitch = n["pitch"] + 12  # Oktave höher
                    new_notes.append({
                        "pitch": new_pitch,
                        "step": n.get("step", 0),
                        "duration": n.get("duration", 8),
                        "velocity": round(n.get("velocity", 0.7) * 0.85, 2),
                        "channel": 0,
                    })

                energy = high_energy_scene["energy"] or 0.5

                pairs.append({
                    "prompt": (
                        f"Schreibe ein neues Pattern für den {base_clip['track']} "
                        f"im {high_energy_scene['name']}-Abschnitt "
                        f"(Energie {int(energy*100)}%, Tonart {key})"
                    ),
                    "context": ctx_summary,
                    "chain_of_thought": (
                        f"[Tonart: {key}] "
                        f"[Szene '{high_energy_scene['name']}' hat {int(energy*100)}% Energie] "
                        f"[Bestehende Noten: {chord_from_notes(base_notes)}] "
                        f"[Eine Oktave höher ergänzt harmonisch ohne Konflikt] "
                        f"[Velocity reduziert für Schichtungs-Balance]"
                    ),
                    "completion": json.dumps({
                        "tool": "write_pattern",
                        "args": {
                            "track_name": base_clip["track"],
                            "project_name": project,
                            "notes": json.dumps(new_notes),
                            "length_beats": base_clip.get("beats") or 4,
                            "key": key,
                            "scene_energy": energy,
                        },
                    }, ensure_ascii=False),
                    "source": "context_octave_layer",
                })

    # ── Paar 2: Variante — leise intro vs. energiereicher Abschnitt ──────────
    scenes_with_clips = [sc for sc in scenes if clips_by_scene.get(sc["name"])]
    if len(scenes_with_clips) >= 2 and clips:
        low_scene  = min(scenes_with_clips, key=lambda s: s["energy"] or 0)
        high_scene = max(scenes_with_clips, key=lambda s: s["energy"] or 0)

        if low_scene["name"] != high_scene["name"]:
            low_clips  = clips_by_scene.get(low_scene["name"], [])
            high_clips = clips_by_scene.get(high_scene["name"], [])

            if low_clips:
                base = low_clips[0]
                try:
                    base_notes = json.loads(base.get("notes_json") or "[]")
                except Exception:
                    base_notes = []

                if base_notes:
                    # Dichte Version für hohe Energie
                    dense_notes = []
                    for n in base_notes[:6]:
                        dur = n.get("duration", 8)
                        step = n.get("step", 0)
                        dense_notes.append({**n, "duration": dur, "velocity": 0.9})
                        # Zusatz: 8tel-Versatz
                        if step + 2 < 64:
                            dense_notes.append({
                                **n,
                                "step": step + 2,
                                "duration": max(2, dur // 2),
                                "velocity": 0.7,
                            })

                    pairs.append({
                        "prompt": (
                            f"Adaptiere das {base['track']}-Pattern von '{low_scene['name']}' "
                            f"für den energiereichen '{high_scene['name']}'-Abschnitt"
                        ),
                        "context": ctx_summary,
                        "chain_of_thought": (
                            f"[{low_scene['name']} = {int((low_scene['energy'] or 0)*100)}% Energie: spärlich] "
                            f"[{high_scene['name']} = {int((high_scene['energy'] or 0)*100)}% Energie: dicht] "
                            f"[Strategie: gleiche Noten + Versatz + höhere Velocity = mehr Dichte] "
                            f"[Tonart {key} bleibt erhalten]"
                        ),
                        "completion": json.dumps({
                            "tool": "write_pattern",
                            "args": {
                                "track_name": base["track"],
                                "project_name": project,
                                "notes": json.dumps(dense_notes),
                                "length_beats": base.get("beats") or 4,
                                "key": key,
                                "scene_energy": high_scene["energy"] or 0.8,
                            },
                        }, ensure_ascii=False),
                        "source": "context_energy_adapt",
                    })

    # ── Paar 3: Kontext-Analyse-Paar (get_song_context → erklären) ───────────
    if clips and key:
        clip_count = len(clips)
        scene_count = len(scenes)
        track_count = len(tracks)
        pairs.append({
            "prompt": f"Analysiere den Song '{project}' — was charakterisiert ihn harmonisch?",
            "context": ctx_summary,
            "chain_of_thought": (
                f"[Tonart: {key}] "
                f"[{clip_count} MIDI-Clips auf {track_count} Tracks] "
                f"[{scene_count} Szenen mit unterschiedlicher Energie]"
            ),
            "completion": (
                f"Der Song '{project}' ist in {key}. "
                f"Er hat {clip_count} MIDI-Clips über {track_count} Tracks "
                f"und {scene_count} Szenen."
            ),
            "source": "context_analysis",
        })

    return pairs


def load_artists(s) -> list[dict]:
    return s.run("""
        MATCH (a:Artist)
        WHERE a.quality_score >= 0.7 AND a.note_plan IS NOT NULL AND a.note_plan <> ''
        RETURN a.name AS name, a.genre AS genre, a.bpm AS bpm,
               a.key AS key, a.style AS style,
               a.devices_json AS devices_json, a.note_plan AS note_plan,
               a.quality_score AS score
        ORDER BY a.quality_score DESC
    """).data()


def load_songs(s) -> list[dict]:
    return s.run("""
        MATCH (s:Song)
        WHERE s.quality_score >= 0.7 AND s.note_plan IS NOT NULL AND s.note_plan <> ''
        RETURN s.name AS name, s.artist AS artist, s.bpm AS bpm,
               s.key AS key, s.chord_progression AS chords,
               s.note_plan AS note_plan, s.quality_score AS score
        ORDER BY s.quality_score DESC
    """).data()


def generate_artist_context_pairs(artists: list[dict]) -> list[dict]:
    """Aus gespeicherten Artist-Profilen kontext-bewusste write_pattern-Paare."""
    pairs = []
    questions = [
        "Mach etwas wie {name}",
        "Ich will im Stil von {name} produzieren",
        "Erstelle einen {name}-inspirierten Beat in Bitwig",
        "Zeig mir wie {name} klingt — baue das in Bitwig nach",
    ]
    for a in artists:
        try:
            devices = json.loads(a.get("devices_json") or "[]")
        except Exception:
            devices = []

        ctx = (
            f"KB-Eintrag Artist: {a['name']}\n"
            f"Genre: {a.get('genre','')} | BPM: {a.get('bpm','')} | "
            f"Tonart: {a.get('key','')}\n"
            f"Stil: {a.get('style','')[:200]}\n"
            f"Devices: {', '.join(devices[:5])}"
        )

        for q_tmpl in random.sample(questions, min(2, len(questions))):
            pairs.append({
                "prompt": q_tmpl.format(name=a["name"]),
                "context": ctx,
                "chain_of_thought": (
                    f"[Artist '{a['name']}' in KB gefunden (Score: {a.get('score',0):.2f})] "
                    f"[Genre: {a.get('genre','')} | BPM: {a.get('bpm','')} | Tonart: {a.get('key','')}] "
                    f"[Notenplan aus KB verwenden — kein Web-Aufruf nötig] "
                    f"[Devices: {', '.join(devices[:3])}]"
                ),
                "completion": (
                    f"Ich habe '{a['name']}' in meiner Wissensdatenbank gefunden "
                    f"(Score: {a.get('score',0):.2f}).\n\n"
                    f"**{a['name']}-Stil** ({a.get('genre','')}): {a.get('style','')[:200]}\n\n"
                    f"**Notenplan:**\n{a.get('note_plan','')}\n\n"
                    f"Soll ich das Setup in Bitwig anlegen?"
                ),
                "source": "artist_kb_context",
            })

    return pairs


def generate_song_context_pairs(songs: list[dict]) -> list[dict]:
    """Aus gespeicherten Song-Analysen kontext-bewusste write_pattern-Paare."""
    pairs = []
    questions = [
        "Kannst du {name} von {artist} in Bitwig nachbauen?",
        "Ich möchte {name} ({artist}) nachproduzieren",
        "Wie baue ich die Bassline von {name} nach?",
        "Baue mir {name} von {artist} in Bitwig",
    ]
    for sg in songs:
        ctx = (
            f"KB-Eintrag Song: {sg['name']} von {sg.get('artist','')}\n"
            f"BPM: {sg.get('bpm','')} | Tonart: {sg.get('key','')}\n"
            f"Akkordfolge: {sg.get('chords','')}"
        )

        for q_tmpl in random.sample(questions, min(2, len(questions))):
            pairs.append({
                "prompt": q_tmpl.format(name=sg["name"], artist=sg.get("artist","")),
                "context": ctx,
                "chain_of_thought": (
                    f"[Song '{sg['name']}' in KB gefunden (Score: {sg.get('score',0):.2f})] "
                    f"[{sg.get('bpm','')} BPM | {sg.get('key','')} | "
                    f"Akkorde: {sg.get('chords','')}] "
                    f"[Notenplan direkt verwenden — kein web_search nötig]"
                ),
                "completion": (
                    f"'{sg['name']}' von {sg.get('artist','')} ist in meiner KB "
                    f"(Score: {sg.get('score',0):.2f}).\n\n"
                    f"**{sg.get('bpm','')} BPM | {sg.get('key','')}**"
                    + (f"\nAkkordfolge: {sg['chords']}" if sg.get("chords") else "")
                    + f"\n\n**Notenplan:**\n{sg.get('note_plan','')}\n\n"
                    f"Soll ich das in Bitwig anlegen?"
                ),
                "source": "song_kb_context",
            })

    return pairs


def main():
    print("=== Kontext-Paare generieren (Ebene 3) ===\n")

    with session() as s:
        projects = load_projects(s)
        artists  = load_artists(s)
        songs    = load_songs(s)

        print(f"  Projekte: {len(projects)} | Artists in KB: {len(artists)} | Songs in KB: {len(songs)}")

        all_pairs = []

        # ── Projekt-basierte Paare (bestehende Logik) ─────────────────────
        for project in projects:
            clips  = load_clips_for_project(s, project)
            scenes = load_scenes_for_project(s, project)
            tracks = load_tracks_for_project(s, project)
            key    = load_key_for_project(s, project)

            if not clips and not tracks:
                print(f"  Überspringe '{project}' — keine Daten")
                continue

            pairs = generate_pairs_for_project(project, key, scenes, tracks, clips)
            print(f"  '{project}': {len(clips)} Clips → {len(pairs)} Paare")
            all_pairs.extend(pairs)

        # ── Artist-basierte Paare (aus Neo4j Artist-Nodes) ────────────────
        if artists:
            artist_pairs = generate_artist_context_pairs(artists)
            print(f"  Artists: {len(artists)} Einträge → {len(artist_pairs)} Paare")
            all_pairs.extend(artist_pairs)
        else:
            print("  Keine Artist-Nodes in KB — übersprungen (wächst mit store_result_in_kb)")

        # ── Song-basierte Paare (aus Neo4j Song-Nodes) ────────────────────
        if songs:
            song_pairs = generate_song_context_pairs(songs)
            print(f"  Songs: {len(songs)} Einträge → {len(song_pairs)} Paare")
            all_pairs.extend(song_pairs)
        else:
            print("  Keine Song-Nodes in KB — übersprungen (wächst mit store_result_in_kb)")

    random.seed(42)
    random.shuffle(all_pairs)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        for p in all_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"\n✅ {len(all_pairs)} Paare → {OUTPUT}")
    if all_pairs:
        ex = all_pairs[0]
        print(f"  Beispiel [{ex.get('source','')}]: {ex['prompt'][:80]}")


if __name__ == "__main__":
    main()

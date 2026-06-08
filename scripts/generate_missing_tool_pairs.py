#!/usr/bin/env python3
"""
Generiert Trainingspaare für alle fehlenden/unterrepräsentierten Tools.

Abgedeckte Tools (19):
  control_bitwig, get_bitwig_track_state, suggest_notes, get_launchpad_mode,
  listen_played_notes, play_notes, arm_track, analyze_song, validate_music,
  get_song_context, get_artist_context, learn_song_from_youtube,
  search_artist_song, validate_and_learn, write_pattern_raw,
  export_mlx_training_data, compose_notes, scan_vst_plugins,
  scan_and_learn_project

Format: OpenAI tool_calls (identisch zu generate_tool_call_pairs.py)
Output: data/training/missing_tool_pairs.jsonl
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

# ── System-Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """/no_think
Du bist ein erfahrener Bitwig Studio 6 Assistent und Musiker.

## Verfügbare Tools

### Wissen
- **query_bitwig_docs(query)** — Bitwig-KB: Genre-Devices, Parameter, Workflows.
  IMMER aufrufen bei Genre-, Device- oder Workflow-Fragen.
- **web_search(query)** — Websuche für Künstler, Songs, aktuelle Infos.
- **find_audio_example(query)** — Sucht Referenz-Audiobeispiele für einen Genre/Stil.
- **get_artist_context(artist_name)** — Künstler-Stil aus Neo4j-Wissensbasis.
- **get_song_context(project_name)** — Song-Kontext aus aktivem Bitwig-Projekt.
- **search_artist_song(artist, title)** — Song-Metadaten (BPM, Tonart, Akkorde).
- **learn_song_from_youtube(artist, title, youtube_url)** — Lernt Song aus YouTube.
- **scan_and_learn_project(project_name)** — Lernt geöffnetes Bitwig-Projekt.
- **scan_vst_plugins()** — Scannt installierte VST-Plugins.
- **analyze_song(file_path)** — Analysiert Audio-Datei (BPM, Tonart, Genre).

### Bitwig-Steuerung
- **check_bitwig_connection()** — Prüft Verbindung zum BitwigStepPlugin.
  IMMER aufrufen VOR execute_setup oder control_bitwig.
- **execute_setup(result)** — Legt Tracks, Instrumente, FX und Tempo an.
- **control_bitwig(action, ...)** — Steuert Transport, Tracks, Devices, EQ.
  Actions: play, stop, record, set_tempo, mute, solo, arm, set_volume,
           set_pan, set_param, open_browser, close_browser, add_device,
           set_eq_band, undo
- **get_bitwig_track_state()** — Liest aktuelle Track-Namen und Note-Counts.
- **compose_notes(result)** — Phase-2: Schreibt Noten in einen Track.
- **write_pattern_raw(track_index, notes, ...)** — Schreibt explizite MIDI-Noten.

### Launchpad / Live
- **suggest_notes(notes, r, g, b)** — Hebt Noten auf dem Launchpad hervor.
- **get_launchpad_mode()** — Liest aktuellen Launchpad-Modus.
- **listen_played_notes(duration)** — Nimmt gespielte Noten vom Launchpad auf.
- **arm_track(arm)** — Aktiviert/deaktiviert Aufnahme-Bereitschaft.
- **play_notes(notes, bpm)** — Spielt Notenfolge direkt ab.

### Validierung & Training
- **validate_music(notes, instrument, genre, key, scale, bars, bpm)** — Bewertet Noten.
- **validate_and_learn(notes, instrument, genre, key, scale, bars, bpm)** — Bewertet + speichert.
- **export_mlx_training_data(output_path, min_score, limit)** — Exportiert für LoRA.

## Workflow-Regeln
1. Genre/Device/Workflow → query_bitwig_docs ZUERST
2. Künstler/Song → web_search DIREKT (KB kennt keine Künstler)
3. Vor Bitwig-Aktionen → check_bitwig_connection
4. Nach Komposition → validate_and_learn (speichert + lernt)
5. Launchpad-Workflow: get_launchpad_mode → suggest_notes → listen_played_notes"""

# ── Hilfsfunktionen ──────────────────────────────────────────────────────────


def tc_id() -> str:
    return f"call_{uuid.uuid4().hex[:8]}"


def assistant_call(tool_name: str, args: dict) -> tuple[dict, str]:
    """Erstellt tool_call-Nachricht und gibt (msg, call_id) zurück."""
    cid = tc_id()
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": cid,
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(args, ensure_ascii=False),
            }
        }]
    }, cid


def tool_result(call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def pair(user: str, messages: list[dict]) -> dict:
    return {"messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        *messages,
    ]}


# ── 1. control_bitwig ─────────────────────────────────────────────────────────

def control_bitwig_pairs() -> list[dict]:
    pairs = []

    # play / stop
    call, cid = assistant_call("check_bitwig_connection", {})
    pairs.append(pair(
        "Starte die Wiedergabe in Bitwig.",
        [
            call, tool_result(cid, '{"status": "connected", "version": "6.1"}'),
            *[m for m in [
                *[x for x in [assistant_call("control_bitwig", {"action": "play"})] for _ in [None]],
            ][:0]],  # placeholder — build inline below
        ]
    ))
    # rebuild properly
    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "play"})
    pairs[-1] = pair("Starte die Wiedergabe in Bitwig.", [
        c1, tool_result(id1, '{"status": "connected", "version": "6.1"}'),
        c2, tool_result(id2, '{"status": "ok", "action": "play"}'),
        {"role": "assistant", "content": "▶ Wiedergabe gestartet."},
    ])

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "stop"})
    pairs.append(pair("Stop!", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "action": "stop"}'),
        {"role": "assistant", "content": "⏹ Wiedergabe gestoppt."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "set_tempo", "bpm": 128.0})
    pairs.append(pair("Setze das Tempo auf 128 BPM.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "bpm": 128.0}'),
        {"role": "assistant", "content": "Tempo auf **128 BPM** gesetzt."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "mute", "track_index": 2})
    pairs.append(pair("Mute Track 2.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "track_index": 2, "muted": true}'),
        {"role": "assistant", "content": "Track 2 ist jetzt **gemutet**."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "solo", "track_index": 1})
    pairs.append(pair("Solo auf Track 1 setzen.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "track_index": 1, "solo": true}'),
        {"role": "assistant", "content": "Track 1 ist jetzt **solo** aktiv."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "set_volume", "track_index": 3, "value": 0.8})
    pairs.append(pair("Erhöhe die Lautstärke von Track 3 auf 80%.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "track_index": 3, "volume": 0.8}'),
        {"role": "assistant", "content": "Lautstärke von Track 3 auf **80%** gesetzt."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "undo"})
    pairs.append(pair("Mach die letzte Aktion rückgängig.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "action": "undo"}'),
        {"role": "assistant", "content": "Letzte Aktion rückgängig gemacht (Undo)."},
    ]))

    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("control_bitwig", {"action": "record"})
    pairs.append(pair("Starte die Aufnahme.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, '{"status": "ok", "action": "record"}'),
        {"role": "assistant", "content": "⏺ Aufnahme gestartet."},
    ]))

    return pairs


# ── 2. get_bitwig_track_state ─────────────────────────────────────────────────

def get_bitwig_track_state_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("get_bitwig_track_state", {})
    pairs.append(pair("Welche Tracks sind gerade in meinem Projekt?", [
        c1, tool_result(id1, json.dumps({
            "tracks": [
                {"index": 1, "name": "Kick", "note_count": 16},
                {"index": 2, "name": "Bass", "note_count": 8},
                {"index": 3, "name": "Lead Synth", "note_count": 0},
            ]
        })),
        {"role": "assistant", "content": (
            "Dein Projekt hat 3 Tracks:\n"
            "1. **Kick** — 16 Noten\n"
            "2. **Bass** — 8 Noten\n"
            "3. **Lead Synth** — 0 Noten (noch leer)"
        )},
    ]))

    c1, id1 = assistant_call("get_bitwig_track_state", {})
    pairs.append(pair("Habe ich schon Noten im Lead-Track?", [
        c1, tool_result(id1, json.dumps({
            "tracks": [
                {"index": 1, "name": "Drums", "note_count": 32},
                {"index": 2, "name": "Lead", "note_count": 0},
            ]
        })),
        {"role": "assistant", "content": "Track 2 **Lead** hat noch **0 Noten** — der Clip ist leer."},
    ]))

    c1, id1 = assistant_call("get_bitwig_track_state", {})
    pairs.append(pair("Zeig mir den aktuellen Projektstatus.", [
        c1, tool_result(id1, json.dumps({
            "tracks": [
                {"index": 1, "name": "Kick", "note_count": 16},
                {"index": 2, "name": "Snare", "note_count": 8},
                {"index": 3, "name": "Bass", "note_count": 12},
                {"index": 4, "name": "Arp", "note_count": 16},
                {"index": 5, "name": "Pad", "note_count": 4},
            ],
            "bpm": 130,
            "key": "A minor"
        })),
        {"role": "assistant", "content": (
            "**Projektstatus** (130 BPM, A-Moll):\n"
            "| Track | Noten |\n|---|---|\n"
            "| Kick | 16 |\n| Snare | 8 |\n| Bass | 12 |\n| Arp | 16 |\n| Pad | 4 |"
        )},
    ]))

    return pairs


# ── 3. suggest_notes ──────────────────────────────────────────────────────────

def suggest_notes_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("suggest_notes", {"notes": [60, 62, 64, 65, 67, 69, 71], "r": 0, "g": 63, "b": 0})
    pairs.append(pair("Zeig mir die C-Dur-Tonleiter auf dem Launchpad.", [
        c1, tool_result(id1, '{"highlighted": 7, "notes": [60, 62, 64, 65, 67, 69, 71]}'),
        {"role": "assistant", "content": (
            "Die **C-Dur-Tonleiter** (7 Noten) ist jetzt grün auf dem Launchpad hervorgehoben:\n"
            "C4, D4, E4, F4, G4, A4, B4"
        )},
    ]))

    c1, id1 = assistant_call("suggest_notes", {"notes": [57, 60, 64], "r": 0, "g": 0, "b": 63})
    pairs.append(pair("Markiere einen A-Moll-Akkord auf dem Launchpad.", [
        c1, tool_result(id1, '{"highlighted": 3, "notes": [57, 60, 64]}'),
        {"role": "assistant", "content": "**A-Moll** (A3, C4, E4) ist blau auf dem Launchpad markiert."},
    ]))

    c1, id1 = assistant_call("suggest_notes", {"notes": [60, 63, 67, 70], "r": 63, "g": 20, "b": 0})
    pairs.append(pair("Hebe den Cm7-Akkord auf dem Launchpad orange hervor.", [
        c1, tool_result(id1, '{"highlighted": 4, "notes": [60, 63, 67, 70]}'),
        {"role": "assistant", "content": "**Cm7** (C4, Eb4, G4, Bb4) ist orange auf dem Launchpad markiert."},
    ]))

    return pairs


# ── 4. get_launchpad_mode ─────────────────────────────────────────────────────

def get_launchpad_mode_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("get_launchpad_mode", {})
    pairs.append(pair("In welchem Modus ist das Launchpad gerade?", [
        c1, tool_result(id1, '{"mode": "note", "scale": "minor", "root": "A", "octave": 4}'),
        {"role": "assistant", "content": (
            "Das Launchpad ist im **Note-Modus**:\n"
            "- Tonleiter: A-Moll\n- Oktave: 4"
        )},
    ]))

    c1, id1 = assistant_call("get_launchpad_mode", {})
    pairs.append(pair("Ist das Launchpad im richtigen Modus zum Spielen?", [
        c1, tool_result(id1, '{"mode": "session", "scale": null, "root": null}'),
        {"role": "assistant", "content": (
            "Das Launchpad ist im **Session-Modus** — für das Spielen von Noten wechsle auf **Note-Modus**."
        )},
    ]))

    c1, id1 = assistant_call("get_launchpad_mode", {})
    pairs.append(pair("Welche Tonart ist auf dem Launchpad aktiv?", [
        c1, tool_result(id1, '{"mode": "note", "scale": "major", "root": "G", "octave": 3}'),
        {"role": "assistant", "content": "Aktive Tonart: **G-Dur** (Note-Modus, Oktave 3)."},
    ]))

    return pairs


# ── 5. listen_played_notes ────────────────────────────────────────────────────

def listen_played_notes_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("listen_played_notes", {"duration": 4.0})
    pairs.append(pair("Nimm auf, was ich gerade auf dem Launchpad spiele (4 Sekunden).", [
        c1, tool_result(id1, json.dumps({
            "notes": [
                {"pitch": 60, "velocity": 80, "duration": 0.5, "onset": 0.0},
                {"pitch": 64, "velocity": 75, "duration": 0.5, "onset": 0.5},
                {"pitch": 67, "velocity": 85, "duration": 0.5, "onset": 1.0},
            ],
            "duration_recorded": 4.0
        })),
        {"role": "assistant", "content": (
            "Aufgezeichnet (4s):\n"
            "- C4 (vel 80, 0.0s)\n"
            "- E4 (vel 75, 0.5s)\n"
            "- G4 (vel 85, 1.0s)\n\n"
            "Das klingt wie ein **C-Dur-Arpeggio**. Soll ich daraus ein Pattern erstellen?"
        )},
    ]))

    c1, id1 = assistant_call("listen_played_notes", {"duration": 8.0})
    pairs.append(pair("Hör 8 Sekunden zu, was ich spiele.", [
        c1, tool_result(id1, json.dumps({
            "notes": [
                {"pitch": 57, "velocity": 90, "duration": 1.0, "onset": 0.0},
                {"pitch": 60, "velocity": 85, "duration": 1.0, "onset": 1.0},
                {"pitch": 64, "velocity": 88, "duration": 1.0, "onset": 2.0},
                {"pitch": 60, "velocity": 82, "duration": 1.0, "onset": 3.0},
            ],
            "duration_recorded": 8.0
        })),
        {"role": "assistant", "content": (
            "Aufgezeichnet (8s) — 4 Noten:\n"
            "A3 → C4 → E4 → C4\n\n"
            "Das ist ein **A-Moll-Arpeggio** (Am: A, C, E). Soll ich es in Bitwig schreiben?"
        )},
    ]))

    return pairs


# ── 6. play_notes ─────────────────────────────────────────────────────────────

def play_notes_pairs() -> list[dict]:
    pairs = []

    notes_cmaj = [
        {"pitch": 60, "velocity": 80, "duration": 0.5, "onset": 0.0},
        {"pitch": 64, "velocity": 80, "duration": 0.5, "onset": 0.5},
        {"pitch": 67, "velocity": 80, "duration": 0.5, "onset": 1.0},
    ]
    c1, id1 = assistant_call("play_notes", {"notes": notes_cmaj, "bpm": 120.0})
    pairs.append(pair("Spiel mir kurz ein C-Dur-Arpeggio als Vorschau.", [
        c1, tool_result(id1, '{"status": "ok", "notes_played": 3}'),
        {"role": "assistant", "content": "▶ C-Dur-Arpeggio (C4–E4–G4) abgespielt — klingt das gut?"},
    ]))

    notes_bass = [
        {"pitch": 36, "velocity": 100, "duration": 0.25, "onset": 0.0},
        {"pitch": 36, "velocity": 90,  "duration": 0.25, "onset": 0.5},
        {"pitch": 38, "velocity": 95,  "duration": 0.25, "onset": 1.0},
        {"pitch": 36, "velocity": 85,  "duration": 0.25, "onset": 1.5},
    ]
    c1, id1 = assistant_call("play_notes", {"notes": notes_bass, "bpm": 140.0})
    pairs.append(pair("Zeig mir wie diese Bassline klingt bevor ich sie speichere.", [
        c1, tool_result(id1, '{"status": "ok", "notes_played": 4}'),
        {"role": "assistant", "content": "▶ Bassline abgespielt (140 BPM). Soll ich sie so in Track 2 schreiben?"},
    ]))

    return pairs


# ── 7. arm_track ──────────────────────────────────────────────────────────────

def arm_track_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("arm_track", {"arm": 1})
    pairs.append(pair("Aktiviere die Aufnahmebereitschaft für den aktuellen Track.", [
        c1, tool_result(id1, '{"status": "ok", "armed": true}'),
        {"role": "assistant", "content": "🔴 Track ist jetzt **aufnahmebereit**. Drück Record oder spiel auf dem Launchpad."},
    ]))

    c1, id1 = assistant_call("arm_track", {"arm": 0})
    pairs.append(pair("Deaktiviere die Aufnahmebereitschaft.", [
        c1, tool_result(id1, '{"status": "ok", "armed": false}'),
        {"role": "assistant", "content": "Aufnahmebereitschaft **deaktiviert**."},
    ]))

    # Full workflow: launchpad → arm → listen
    c1, id1 = assistant_call("get_launchpad_mode", {})
    c2, id2 = assistant_call("arm_track", {"arm": 1})
    c3, id3 = assistant_call("listen_played_notes", {"duration": 8.0})
    pairs.append(pair("Ich möchte eine Melodie live auf dem Launchpad einspielen.", [
        c1, tool_result(id1, '{"mode": "note", "scale": "minor", "root": "A", "octave": 4}'),
        c2, tool_result(id2, '{"status": "ok", "armed": true}'),
        c3, tool_result(id3, json.dumps({
            "notes": [
                {"pitch": 69, "velocity": 85, "duration": 0.5, "onset": 0.0},
                {"pitch": 71, "velocity": 80, "duration": 0.5, "onset": 0.5},
                {"pitch": 72, "velocity": 88, "duration": 0.5, "onset": 1.0},
            ],
            "duration_recorded": 8.0
        })),
        {"role": "assistant", "content": (
            "Launchpad ist im Note-Modus (A-Moll). Track ist aufnahmebereit.\n"
            "Aufgezeichnet: A4 → B4 → C5 — eine schöne Moll-Melodielinie!\n"
            "Soll ich die Noten in Bitwig schreiben?"
        )},
    ]))

    return pairs


# ── 8. analyze_song ──────────────────────────────────────────────────────────

def analyze_song_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("analyze_song", {"file_path": "/Users/sija/Music/loop.wav"})
    pairs.append(pair("Analysiere diese Audio-Datei: /Users/sija/Music/loop.wav", [
        c1, tool_result(id1, json.dumps({
            "genre": "Techno",
            "bpm": 132.0,
            "key": "F minor",
            "mood": "dark, driving",
            "instruments": ["kick", "bass", "synth pad"],
            "duration": 8.0
        })),
        {"role": "assistant", "content": (
            "**Audio-Analyse:**\n"
            "- Genre: Techno\n"
            "- BPM: 132\n"
            "- Tonart: F-Moll\n"
            "- Stimmung: dark, driving\n"
            "- Instrumente: Kick, Bass, Synth Pad\n\n"
            "Soll ich ein ähnliches Pattern in Bitwig erstellen?"
        )},
    ]))

    c1, id1 = assistant_call("analyze_song", {"file_path": "/tmp/reference.mp3"})
    pairs.append(pair("Was ist das Genre und Tempo dieser MP3?", [
        c1, tool_result(id1, json.dumps({
            "genre": "House",
            "bpm": 124.0,
            "key": "G major",
            "mood": "euphoric, groovy",
            "instruments": ["four-on-the-floor kick", "hi-hat", "bass", "piano"],
            "duration": 32.0
        })),
        {"role": "assistant", "content": (
            "Das ist **House** bei **124 BPM** in G-Dur.\n"
            "Stimmung: euphorisch und groovig — typische House-Elemente: 4-on-the-floor Kick, Piano-Chords."
        )},
    ]))

    c1, id1 = assistant_call("analyze_song", {"file_path": "/Downloads/sample.flac"})
    pairs.append(pair("Analysiere /Downloads/sample.flac und sag mir die Tonart.", [
        c1, tool_result(id1, json.dumps({
            "genre": "Drum and Bass",
            "bpm": 174.0,
            "key": "D minor",
            "mood": "energetic, aggressive",
            "instruments": ["amen break", "reese bass", "pad"],
        })),
        {"role": "assistant", "content": (
            "Tonart: **D-Moll** (Drum and Bass, 174 BPM).\n"
            "Typische DnB-Elemente: Amen Break, Reese-Bass."
        )},
    ]))

    return pairs


# ── 9. validate_music ────────────────────────────────────────────────────────

def validate_music_pairs() -> list[dict]:
    pairs = []

    notes_ok = [
        {"pitch": 45, "velocity": 100, "duration": 0.25, "onset": 0.0},
        {"pitch": 45, "velocity": 90,  "duration": 0.25, "onset": 0.5},
        {"pitch": 47, "velocity": 95,  "duration": 0.25, "onset": 1.0},
        {"pitch": 45, "velocity": 85,  "duration": 0.25, "onset": 1.5},
        {"pitch": 42, "velocity": 80,  "duration": 0.25, "onset": 2.0},
        {"pitch": 42, "velocity": 75,  "duration": 0.25, "onset": 2.5},
        {"pitch": 45, "velocity": 90,  "duration": 0.25, "onset": 3.0},
        {"pitch": 47, "velocity": 100, "duration": 0.25, "onset": 3.5},
    ]
    c1, id1 = assistant_call("validate_music", {
        "notes": notes_ok, "instrument": "bass",
        "genre": "techno", "key": "A", "scale": "minor", "bars": 2, "bpm": 130
    })
    pairs.append(pair("Ist diese Bassline für Techno in A-Moll gut?", [
        c1, tool_result(id1, json.dumps({
            "score": 0.88,
            "feedback": "Gute rhythmische Dichte, Noten bleiben in A-Moll-Pentatonik. Empfehlung: mehr Synkopen.",
            "issues": []
        })),
        {"role": "assistant", "content": (
            "Validierung: **Score 0.88/1.0** ✅\n"
            "Die Bassline ist harmonisch korrekt in A-Moll. "
            "Tipp: Mehr Synkopen würden den Techno-Groove verstärken."
        )},
    ]))

    notes_bad = [
        {"pitch": 61, "velocity": 80, "duration": 0.5, "onset": 0.0},  # C#, kein A-Moll
        {"pitch": 63, "velocity": 80, "duration": 0.5, "onset": 0.5},  # Eb, kein A-Moll
    ]
    c1, id1 = assistant_call("validate_music", {
        "notes": notes_bad, "instrument": "bass",
        "genre": "house", "key": "A", "scale": "minor", "bars": 1, "bpm": 124
    })
    pairs.append(pair("Prüf ob diese Bass-Noten für House in A-Moll passen.", [
        c1, tool_result(id1, json.dumps({
            "score": 0.42,
            "feedback": "C# und Eb liegen außerhalb der A-Moll-Tonleiter. Verwende A, B, C, D, E, F, G.",
            "issues": ["out_of_scale: pitch 61 (C#)", "out_of_scale: pitch 63 (Eb)"]
        })),
        {"role": "assistant", "content": (
            "Validierung: **Score 0.42/1.0** ⚠️\n"
            "C# (61) und Eb (63) liegen **außerhalb** der A-Moll-Tonleiter.\n"
            "Erlaubte Noten: A, B, C, D, E, F, G. Soll ich die Bassline korrigieren?"
        )},
    ]))

    notes_drums = [
        {"pitch": 36, "velocity": 100, "duration": 0.1, "onset": 0.0},
        {"pitch": 38, "velocity": 90,  "duration": 0.1, "onset": 1.0},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 0.5},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 1.5},
        {"pitch": 36, "velocity": 100, "duration": 0.1, "onset": 2.0},
        {"pitch": 38, "velocity": 90,  "duration": 0.1, "onset": 3.0},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 2.5},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 3.5},
    ]
    c1, id1 = assistant_call("validate_music", {
        "notes": notes_drums, "instrument": "drums",
        "genre": "techno", "key": "C", "scale": "minor", "bars": 2, "bpm": 130
    })
    pairs.append(pair("Validiere dieses Techno-Drum-Pattern.", [
        c1, tool_result(id1, json.dumps({
            "score": 0.91,
            "feedback": "Klassisches 4-on-the-floor mit Snare auf 2/4 und Off-Beat Hi-Hat. Sehr typisch für Techno.",
            "issues": []
        })),
        {"role": "assistant", "content": (
            "Validierung: **Score 0.91/1.0** ✅\n"
            "Klassisches Techno-Pattern: 4-on-the-floor Kick, Snare auf 2 & 4, Off-Beat Hi-Hat."
        )},
    ]))

    return pairs


# ── 10. get_song_context ──────────────────────────────────────────────────────

def get_song_context_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("get_song_context", {"project_name": ""})
    pairs.append(pair("Was ist das aktuelle Bitwig-Projekt?", [
        c1, tool_result(id1, json.dumps({
            "project": "Chee - Hey Now",
            "bpm": 138,
            "key": "A minor",
            "tracks": [
                {"name": "Kick", "device": "VD-Heavy Kick"},
                {"name": "Bass", "device": "FM-4"},
                {"name": "Lead", "device": "Phase-4"},
            ]
        })),
        {"role": "assistant", "content": (
            "Aktives Projekt: **Chee - Hey Now** (138 BPM, A-Moll)\n"
            "- Kick: VD-Heavy Kick\n"
            "- Bass: FM-4\n"
            "- Lead: Phase-4"
        )},
    ]))

    c1, id1 = assistant_call("get_song_context", {"project_name": "My Track"})
    pairs.append(pair("Zeig mir den Kontext von 'My Track'.", [
        c1, tool_result(id1, json.dumps({
            "project": "My Track",
            "bpm": 120,
            "key": "C major",
            "tracks": [{"name": "Piano", "device": "Polymer"}],
            "notes": 24
        })),
        {"role": "assistant", "content": "Projekt **My Track**: 120 BPM, C-Dur, 1 Track (Piano/Polymer), 24 Noten."},
    ]))

    c1, id1 = assistant_call("get_song_context", {"project_name": ""})
    pairs.append(pair("Welche Instrumente nutze ich im aktuellen Projekt?", [
        c1, tool_result(id1, json.dumps({
            "project": "Techno Session",
            "bpm": 135,
            "key": "F minor",
            "tracks": [
                {"name": "Kick",  "device": "VD-Kick Classic"},
                {"name": "Bass",  "device": "Operator"},
                {"name": "Synth", "device": "Wavetable"},
                {"name": "Pad",   "device": "Drift"},
            ]
        })),
        {"role": "assistant", "content": (
            "**Techno Session** (135 BPM, F-Moll) nutzt:\n"
            "- VD-Kick Classic (Kick)\n- Operator (Bass)\n- Wavetable (Synth)\n- Drift (Pad)"
        )},
    ]))

    c1, id1 = assistant_call("get_song_context", {"project_name": ""})
    pairs.append(pair("Was hat mein Projekt für ein Tempo und welche Tonart?", [
        c1, tool_result(id1, json.dumps({"project": "My Groove", "bpm": 125, "key": "G minor"})),
        {"role": "assistant", "content": "**My Groove**: Tempo **125 BPM**, Tonart **G-Moll**."},
    ]))

    return pairs


# ── 11. get_artist_context ────────────────────────────────────────────────────

def get_artist_context_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("get_artist_context", {"artist_name": "Aphex Twin"})
    pairs.append(pair("Welchen Stil hat Aphex Twin? Ich will etwas ähnliches machen.", [
        c1, tool_result(id1, json.dumps({
            "artist": "Aphex Twin",
            "genres": ["IDM", "Ambient Techno", "Acid"],
            "bpm_range": "80–160",
            "characteristics": "Komplexe Polyrhythmen, verzerrte Drums, FM-Synthese, unregelmäßige Taktarten, dystopische Atmosphäre.",
            "key_tracks": ["Windowlicker", "Come to Daddy", "Alberto Balsalm"],
            "devices": ["FM-4", "Phase-4", "Polysynth", "VD-Distorted Kick"]
        })),
        {"role": "assistant", "content": (
            "**Aphex Twin** — IDM/Ambient Techno/Acid:\n"
            "- BPM: 80–160 (sehr variabel)\n"
            "- Komplexe Polyrhythmen, verzerrte Drums, FM-Synthese\n"
            "- Geeignete Bitwig-Devices: FM-4, Phase-4, Polysynth\n\n"
            "Soll ich ein IDM-Pattern in seinem Stil erstellen?"
        )},
    ]))

    c1, id1 = assistant_call("get_artist_context", {"artist_name": "Daft Punk"})
    pairs.append(pair("Erkläre mir den typischen Sound von Daft Punk.", [
        c1, tool_result(id1, json.dumps({
            "artist": "Daft Punk",
            "genres": ["French House", "Electronic", "Disco"],
            "bpm_range": "120–128",
            "characteristics": "Vocoder-Stimmen, Filtered House, Sidechain-Kompression, Disco-Samples, robotische Ästhetik.",
            "key_tracks": ["Around the World", "One More Time", "Da Funk"],
            "devices": ["Polysynth", "Chorus", "Compressor", "Vocoder"]
        })),
        {"role": "assistant", "content": (
            "**Daft Punk** — French House/Disco:\n"
            "- BPM: 120–128\n"
            "- Vocoder, Filtered House, Sidechain-Kompression, Disco-Samples\n"
            "- Bitwig: Polysynth + Chorus + Compressor"
        )},
    ]))

    c1, id1 = assistant_call("get_artist_context", {"artist_name": "Four Tet"})
    pairs.append(pair("Was macht den Sound von Four Tet aus?", [
        c1, tool_result(id1, json.dumps({
            "artist": "Four Tet",
            "genres": ["Folktronica", "IDM", "Ambient House"],
            "bpm_range": "120–140",
            "characteristics": "Organische Samples, microsound-Texturen, Breakbeats, Wärme, Vinyl-Crackle.",
            "devices": ["Granulator", "Sampler", "Reverb", "Delay-2"]
        })),
        {"role": "assistant", "content": (
            "**Four Tet** — Folktronica/Ambient House:\n"
            "- Organische Samples, Microsound, Vinyl-Wärme\n"
            "- Bitwig: Granulator II + Sampler + Reverb"
        )},
    ]))

    c1, id1 = assistant_call("get_artist_context", {"artist_name": "Burial"})
    pairs.append(pair("Ich will etwas im Stil von Burial machen. Was ist sein Sound?", [
        c1, tool_result(id1, json.dumps({
            "artist": "Burial",
            "genres": ["UK Garage", "Dubstep", "Ambient"],
            "bpm_range": "130–140",
            "characteristics": "Broken beats, Vinyl-Rauschen, Ghostly vocals, subdued bass, melancholische Atmosphäre.",
            "devices": ["Sampler", "Grain Sampler", "Reverb", "Delay-2", "Saturator"]
        })),
        {"role": "assistant", "content": (
            "**Burial** — UK Garage/Ambient:\n"
            "- Broken beats, Vinyl-Noise, ghostly Vocals, melancholischer Bass\n"
            "- Bitwig: Grain Sampler + Reverb + Delay-2\n\n"
            "Soll ich ein Burial-inspiriertes Pattern erstellen?"
        )},
    ]))

    return pairs


# ── 12. learn_song_from_youtube ───────────────────────────────────────────────

def learn_song_from_youtube_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("learn_song_from_youtube", {
        "artist": "Daft Punk",
        "title": "Da Funk",
        "youtube_url": "https://www.youtube.com/watch?v=XaMpT1oMKKQ",
        "transcribe_midi": False,
    })
    pairs.append(pair("Lerne Daft Punk - Da Funk aus YouTube: https://www.youtube.com/watch?v=XaMpT1oMKKQ", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "artist": "Daft Punk",
            "title": "Da Funk",
            "bpm": 100,
            "key": "D minor",
            "genre": "French House",
            "stored_in_neo4j": True,
            "patterns_extracted": 3
        })),
        {"role": "assistant", "content": (
            "✅ **Daft Punk - Da Funk** gelernt und in Neo4j gespeichert:\n"
            "- BPM: 100, Tonart: D-Moll, Genre: French House\n"
            "- 3 Patterns extrahiert\n\n"
            "Der Song steht jetzt für zukünftige Pattern-Generierung zur Verfügung."
        )},
    ]))

    c1, id1 = assistant_call("learn_song_from_youtube", {
        "artist": "Avicii",
        "title": "Levels",
        "youtube_url": "https://www.youtube.com/watch?v=_ovdm2yX4MA",
        "transcribe_midi": True,
    })
    pairs.append(pair("Lern Levels von Avicii inklusive MIDI-Transkription.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "artist": "Avicii",
            "title": "Levels",
            "bpm": 126,
            "key": "A major",
            "genre": "Progressive House",
            "stored_in_neo4j": True,
            "midi_transcribed": True,
            "patterns_extracted": 5
        })),
        {"role": "assistant", "content": (
            "✅ **Avicii - Levels** gelernt (inkl. MIDI):\n"
            "- BPM: 126, A-Dur, Progressive House\n"
            "- 5 Patterns + MIDI-Transkription in Neo4j"
        )},
    ]))

    c1, id1 = assistant_call("learn_song_from_youtube", {
        "artist": "M83",
        "title": "Midnight City",
        "youtube_url": "https://www.youtube.com/watch?v=dX3k_QDnzHE",
        "transcribe_midi": False,
    })
    pairs.append(pair("Füge M83 - Midnight City zur Wissensbasis hinzu.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "artist": "M83",
            "title": "Midnight City",
            "bpm": 108,
            "key": "E minor",
            "genre": "Synthwave",
            "stored_in_neo4j": True,
            "patterns_extracted": 4
        })),
        {"role": "assistant", "content": (
            "✅ **M83 - Midnight City** gelernt:\n"
            "- BPM: 108, E-Moll, Synthwave\n"
            "- 4 Patterns in Neo4j gespeichert"
        )},
    ]))

    return pairs


# ── 13. search_artist_song ────────────────────────────────────────────────────

def search_artist_song_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("search_artist_song", {"artist": "Kraftwerk", "title": "Autobahn"})
    pairs.append(pair("Such nach Metadaten für Kraftwerk - Autobahn.", [
        c1, tool_result(id1, json.dumps({
            "found": True,
            "artist": "Kraftwerk",
            "title": "Autobahn",
            "bpm": 116,
            "key": "F major",
            "genre": "Krautrock / Electronic",
            "year": 1974,
            "chords": ["F", "C", "Gm", "Bb"]
        })),
        {"role": "assistant", "content": (
            "**Kraftwerk - Autobahn** (1974):\n"
            "- BPM: 116, F-Dur\n"
            "- Genre: Krautrock/Electronic\n"
            "- Akkorde: F – C – Gm – Bb"
        )},
    ]))

    c1, id1 = assistant_call("search_artist_song", {"artist": "Burial", "title": "Archangel"})
    pairs.append(pair("Welche Tonart hat Burial - Archangel?", [
        c1, tool_result(id1, json.dumps({
            "found": True,
            "artist": "Burial",
            "title": "Archangel",
            "bpm": 139,
            "key": "D minor",
            "genre": "UK Garage / Dubstep",
        })),
        {"role": "assistant", "content": "**Burial - Archangel**: **D-Moll**, 139 BPM, UK Garage/Dubstep."},
    ]))

    c1, id1 = assistant_call("search_artist_song", {"artist": "Unknown Artist", "title": "Unknown Song"})
    pairs.append(pair("Hast du Daten zu Unknown Artist - Unknown Song?", [
        c1, tool_result(id1, json.dumps({"found": False, "message": "Kein Eintrag in der Wissensbasis."})),
        {"role": "assistant", "content": (
            "Kein Eintrag gefunden. Ich kann mit `learn_song_from_youtube` einen YouTube-Link lernen "
            "oder eine Web-Suche starten."
        )},
    ]))

    return pairs


# ── 14. validate_and_learn ────────────────────────────────────────────────────

def validate_and_learn_pairs() -> list[dict]:
    pairs = []

    notes = [
        {"pitch": 45, "velocity": 100, "duration": 0.25, "onset": 0.0},
        {"pitch": 45, "velocity": 90,  "duration": 0.25, "onset": 0.5},
        {"pitch": 47, "velocity": 95,  "duration": 0.25, "onset": 1.0},
        {"pitch": 48, "velocity": 85,  "duration": 0.25, "onset": 1.5},
        {"pitch": 45, "velocity": 100, "duration": 0.25, "onset": 2.0},
        {"pitch": 43, "velocity": 90,  "duration": 0.25, "onset": 2.5},
        {"pitch": 45, "velocity": 95,  "duration": 0.25, "onset": 3.0},
        {"pitch": 47, "velocity": 88,  "duration": 0.25, "onset": 3.5},
    ]
    c1, id1 = assistant_call("validate_and_learn", {
        "notes": notes, "instrument": "bass",
        "genre": "techno", "key": "A", "scale": "minor", "bars": 2, "bpm": 130
    })
    pairs.append(pair("Validiere und speichere diese Techno-Bassline in der Wissensbasis.", [
        c1, tool_result(id1, json.dumps({
            "score": 0.92,
            "feedback": "Exzellente Bassline — A-Moll pentatonisch, gute rhythmische Variation.",
            "stored": True,
            "neo4j_id": "pattern_7a3f2b"
        })),
        {"role": "assistant", "content": (
            "✅ **Score 0.92/1.0** — in Neo4j gespeichert (ID: pattern_7a3f2b).\n"
            "Die Bassline ist harmonisch korrekt und wird für zukünftiges Training genutzt."
        )},
    ]))

    notes_lead = [
        {"pitch": 69, "velocity": 85, "duration": 0.5,  "onset": 0.0},
        {"pitch": 71, "velocity": 80, "duration": 0.5,  "onset": 0.5},
        {"pitch": 72, "velocity": 88, "duration": 0.5,  "onset": 1.0},
        {"pitch": 71, "velocity": 82, "duration": 0.25, "onset": 1.5},
        {"pitch": 69, "velocity": 85, "duration": 0.5,  "onset": 2.0},
        {"pitch": 67, "velocity": 78, "duration": 0.5,  "onset": 2.5},
        {"pitch": 69, "velocity": 90, "duration": 1.0,  "onset": 3.0},
    ]
    c1, id1 = assistant_call("validate_and_learn", {
        "notes": notes_lead, "instrument": "lead",
        "genre": "house", "key": "A", "scale": "minor", "bars": 2, "bpm": 124
    })
    pairs.append(pair("Prüf und lern diese House-Melodie.", [
        c1, tool_result(id1, json.dumps({
            "score": 0.87,
            "feedback": "Schöne Melodiebewegung in A-Moll. Score leicht unter 0.9 wegen fehlender Synkopen.",
            "stored": True,
            "neo4j_id": "pattern_c9d1e4"
        })),
        {"role": "assistant", "content": (
            "Score: **0.87/1.0** — gespeichert ✅\n"
            "Tipp: Mehr Synkopen würden den House-Feel verstärken."
        )},
    ]))

    return pairs


# ── 15. write_pattern_raw ─────────────────────────────────────────────────────

def write_pattern_raw_pairs() -> list[dict]:
    pairs = []

    jazz_notes = [
        {"pitch": 65, "velocity": 75, "duration": 1.0, "onset": 0.0},   # F4
        {"pitch": 69, "velocity": 80, "duration": 0.5, "onset": 1.0},   # A4
        {"pitch": 71, "velocity": 70, "duration": 0.5, "onset": 1.5},   # B4
        {"pitch": 72, "velocity": 85, "duration": 1.0, "onset": 2.0},   # C5
        {"pitch": 71, "velocity": 75, "duration": 0.5, "onset": 3.0},   # B4
        {"pitch": 69, "velocity": 80, "duration": 0.5, "onset": 3.5},   # A4
        {"pitch": 67, "velocity": 85, "duration": 1.0, "onset": 4.0},   # G4
        {"pitch": 65, "velocity": 78, "duration": 0.5, "onset": 5.0},   # F4
        {"pitch": 64, "velocity": 72, "duration": 0.5, "onset": 5.5},   # E4
        {"pitch": 65, "velocity": 88, "duration": 2.0, "onset": 6.0},   # F4
    ]
    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("write_pattern_raw", {
        "track_index": 2,
        "notes": jazz_notes,
        "length_beats": 8.0,
        "bpm": 90,
        "genre": "jazz",
        "key": "F",
        "instrument": "piano",
    })
    pairs.append(pair("Schreibe dieses Jazz-Piano-Solo in Track 2 (90 BPM, F-Dur, 8 Beats).", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, json.dumps({
            "status": "ok",
            "track_index": 2,
            "notes_written": 10,
            "length_beats": 8.0
        })),
        {"role": "assistant", "content": (
            "✅ Jazz-Piano-Solo (10 Noten, 8 Beats, F-Dur) in Track 2 geschrieben.\n"
            "90 BPM — klassische Jazz-Melodielinie von F4 nach oben."
        )},
    ]))

    kick_notes = [
        {"pitch": 36, "velocity": 110, "duration": 0.1, "onset": 0.0},
        {"pitch": 36, "velocity": 105, "duration": 0.1, "onset": 2.0},
        {"pitch": 36, "velocity": 108, "duration": 0.1, "onset": 4.0},
        {"pitch": 36, "velocity": 100, "duration": 0.1, "onset": 6.0},
        {"pitch": 38, "velocity": 90,  "duration": 0.1, "onset": 2.0},
        {"pitch": 38, "velocity": 85,  "duration": 0.1, "onset": 6.0},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 1.0},
        {"pitch": 42, "velocity": 65,  "duration": 0.1, "onset": 3.0},
        {"pitch": 42, "velocity": 70,  "duration": 0.1, "onset": 5.0},
        {"pitch": 42, "velocity": 65,  "duration": 0.1, "onset": 7.0},
        {"pitch": 46, "velocity": 60,  "duration": 0.1, "onset": 1.5},
        {"pitch": 46, "velocity": 55,  "duration": 0.1, "onset": 3.5},
        {"pitch": 46, "velocity": 60,  "duration": 0.1, "onset": 5.5},
        {"pitch": 46, "velocity": 55,  "duration": 0.1, "onset": 7.5},
    ]
    c1, id1 = assistant_call("check_bitwig_connection", {})
    c2, id2 = assistant_call("write_pattern_raw", {
        "track_index": 1,
        "notes": kick_notes,
        "length_beats": 8.0,
        "bpm": 130,
        "genre": "techno",
        "key": None,
        "instrument": "drums",
    })
    pairs.append(pair("Schreibe ein 2-Takt Techno Drum-Pattern mit Kick, Snare und Hi-Hat in Track 1.", [
        c1, tool_result(id1, '{"status": "connected"}'),
        c2, tool_result(id2, json.dumps({
            "status": "ok", "track_index": 1, "notes_written": 14, "length_beats": 8.0
        })),
        {"role": "assistant", "content": (
            "✅ 2-Takt Techno-Drum-Pattern (14 Noten) in Track 1:\n"
            "- 4-on-the-floor Kick (36)\n"
            "- Snare auf 2&4 (38)\n"
            "- Closed Hi-Hat Off-Beat (42)\n"
            "- Open Hi-Hat (46)"
        )},
    ]))

    # Full workflow: query → write_pattern_raw → validate_and_learn
    c1, id1 = assistant_call("query_bitwig_docs", {"query": "Afrobeat bass pattern characteristics"})
    c2, id2 = assistant_call("check_bitwig_connection", {})
    afro_bass = [
        {"pitch": 45, "velocity": 95, "duration": 0.5,  "onset": 0.0},
        {"pitch": 47, "velocity": 85, "duration": 0.25, "onset": 0.5},
        {"pitch": 48, "velocity": 90, "duration": 0.5,  "onset": 1.0},
        {"pitch": 47, "velocity": 80, "duration": 0.25, "onset": 1.5},
        {"pitch": 45, "velocity": 95, "duration": 0.5,  "onset": 2.0},
        {"pitch": 43, "velocity": 85, "duration": 0.5,  "onset": 2.5},
        {"pitch": 45, "velocity": 90, "duration": 0.5,  "onset": 3.0},
        {"pitch": 48, "velocity": 88, "duration": 0.5,  "onset": 3.5},
    ]
    c3, id3 = assistant_call("write_pattern_raw", {
        "track_index": 2,
        "notes": afro_bass,
        "length_beats": 4.0,
        "bpm": 102,
        "genre": "afrobeat",
        "key": "A",
        "instrument": "bass",
    })
    pairs.append(pair("Erstelle einen Afrobeat-Bass in A-Moll, 102 BPM.", [
        c1, tool_result(id1, (
            '{"genre": "Afrobeat", "bpm_range": "90–115", '
            '"characteristics": "Synkopierte Bass-Linien, off-beat Rhythmik, pentatonische Melodien", '
            '"devices": ["FM-4", "EQ-5", "Compressor"]}'
        )),
        c2, tool_result(id2, '{"status": "connected"}'),
        c3, tool_result(id3, json.dumps({"status": "ok", "track_index": 2, "notes_written": 8})),
        {"role": "assistant", "content": (
            "✅ Afrobeat-Bassline (8 Noten, A-Moll, 102 BPM) in Track 2.\n"
            "Synkopiert und pentatonisch — typisch für den Afrobeat-Groove."
        )},
    ]))

    return pairs


# ── 16. export_mlx_training_data ──────────────────────────────────────────────

def export_mlx_training_data_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("export_mlx_training_data", {
        "output_path": "./training_data",
        "min_score": 0.75,
        "limit": 500,
    })
    pairs.append(pair("Exportiere die Trainingsdaten für MLX Fine-Tuning.", [
        c1, tool_result(id1, json.dumps({
            "status": "ok",
            "exported": 347,
            "skipped_low_score": 83,
            "output_path": "./training_data",
            "files": ["train.jsonl", "valid.jsonl"]
        })),
        {"role": "assistant", "content": (
            "✅ **347 Patterns** exportiert nach `./training_data/`:\n"
            "- train.jsonl + valid.jsonl\n"
            "- 83 Patterns übersprungen (Score < 0.75)\n\n"
            "Nächster Schritt: `make mlx-train`"
        )},
    ]))

    c1, id1 = assistant_call("export_mlx_training_data", {
        "output_path": "./training_data",
        "min_score": 0.90,
        "limit": 200,
    })
    pairs.append(pair("Exportiere nur hochqualitative Patterns (Score ≥ 0.90) für das Training.", [
        c1, tool_result(id1, json.dumps({
            "status": "ok",
            "exported": 112,
            "skipped_low_score": 318,
            "output_path": "./training_data",
            "files": ["train.jsonl", "valid.jsonl"]
        })),
        {"role": "assistant", "content": (
            "✅ **112 Patterns** mit Score ≥ 0.90 exportiert.\n"
            "Kleinerer, dafür sehr hochwertiger Datensatz für präzises Fine-Tuning."
        )},
    ]))

    return pairs


# ── 17. compose_notes ─────────────────────────────────────────────────────────

def compose_notes_pairs() -> list[dict]:
    pairs = []

    result_bass = {
        "track_index": 2,
        "instrument": "bass",
        "genre": "house",
        "key": "G",
        "scale": "minor",
        "bpm": 124,
        "bars": 2,
        "notes": [
            {"pitch": 43, "velocity": 95, "duration": 0.5, "onset": 0.0},
            {"pitch": 43, "velocity": 85, "duration": 0.5, "onset": 0.5},
            {"pitch": 46, "velocity": 90, "duration": 0.5, "onset": 1.0},
            {"pitch": 43, "velocity": 80, "duration": 0.5, "onset": 1.5},
            {"pitch": 41, "velocity": 95, "duration": 0.5, "onset": 2.0},
            {"pitch": 43, "velocity": 88, "duration": 0.5, "onset": 2.5},
            {"pitch": 46, "velocity": 92, "duration": 0.5, "onset": 3.0},
            {"pitch": 48, "velocity": 85, "duration": 0.5, "onset": 3.5},
        ]
    }
    c1, id1 = assistant_call("compose_notes", result_bass)
    pairs.append(pair("Schreibe jetzt die House-Bassline in Track 2.", [
        c1, tool_result(id1, json.dumps({
            "status": "ok",
            "track_index": 2,
            "notes_written": 8,
            "clip_length": 4.0
        })),
        {"role": "assistant", "content": (
            "✅ House-Bassline (8 Noten, G-Moll, 124 BPM) in Track 2 geschrieben."
        )},
    ]))

    result_lead = {
        "track_index": 3,
        "instrument": "lead",
        "genre": "techno",
        "key": "A",
        "scale": "minor",
        "bpm": 135,
        "bars": 1,
        "notes": [
            {"pitch": 69, "velocity": 90, "duration": 0.25, "onset": 0.0},
            {"pitch": 72, "velocity": 85, "duration": 0.25, "onset": 0.25},
            {"pitch": 74, "velocity": 88, "duration": 0.5,  "onset": 0.5},
            {"pitch": 72, "velocity": 80, "duration": 0.25, "onset": 1.0},
            {"pitch": 69, "velocity": 85, "duration": 0.25, "onset": 1.25},
            {"pitch": 67, "velocity": 90, "duration": 0.5,  "onset": 1.5},
        ]
    }
    c1, id1 = assistant_call("compose_notes", result_lead)
    pairs.append(pair("Schreib den Lead-Synth in Track 3 (Techno, A-Moll, 135 BPM).", [
        c1, tool_result(id1, json.dumps({"status": "ok", "track_index": 3, "notes_written": 6})),
        {"role": "assistant", "content": "✅ Techno Lead-Synth (6 Noten, A-Moll) in Track 3 geschrieben."},
    ]))

    return pairs


# ── 18. scan_vst_plugins ──────────────────────────────────────────────────────

def scan_vst_plugins_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("scan_vst_plugins", {})
    pairs.append(pair("Welche VST-Plugins habe ich installiert?", [
        c1, tool_result(id1, json.dumps({
            "plugins": [
                {"name": "Serum", "type": "VST3", "manufacturer": "Xfer Records"},
                {"name": "Massive X", "type": "VST3", "manufacturer": "Native Instruments"},
                {"name": "FabFilter Pro-Q 3", "type": "VST3", "manufacturer": "FabFilter"},
                {"name": "Valhalla Room", "type": "VST2", "manufacturer": "Valhalla DSP"},
                {"name": "Kontakt 7", "type": "VST3", "manufacturer": "Native Instruments"},
            ],
            "total": 5,
            "scanned_paths": ["/Library/Audio/Plug-Ins/VST3", "~/Library/Audio/Plug-Ins/VST3"]
        })),
        {"role": "assistant", "content": (
            "**5 VST-Plugins** gefunden:\n"
            "- Serum (VST3, Xfer Records)\n"
            "- Massive X (VST3, Native Instruments)\n"
            "- FabFilter Pro-Q 3 (VST3)\n"
            "- Valhalla Room (VST2)\n"
            "- Kontakt 7 (VST3, Native Instruments)"
        )},
    ]))

    c1, id1 = assistant_call("scan_vst_plugins", {})
    pairs.append(pair("Scanne meine Plugins und sag mir welche Synths ich habe.", [
        c1, tool_result(id1, json.dumps({
            "plugins": [
                {"name": "Vital", "type": "VST3", "manufacturer": "Matt Tytel", "category": "Synth"},
                {"name": "LABS", "type": "VST3", "manufacturer": "Spitfire Audio", "category": "Sampler"},
                {"name": "Diva", "type": "VST3", "manufacturer": "u-he", "category": "Synth"},
            ],
            "total": 3
        })),
        {"role": "assistant", "content": (
            "Synths: **Vital** (Wavetable) und **Diva** (u-he Analogsimulation).\n"
            "Außerdem LABS (Spitfire Audio Sampler)."
        )},
    ]))

    c1, id1 = assistant_call("scan_vst_plugins", {})
    pairs.append(pair("Aktualisiere die Plugin-Liste nach meiner neuen Installation.", [
        c1, tool_result(id1, json.dumps({
            "plugins": [
                {"name": "Serum 2", "type": "VST3", "manufacturer": "Xfer Records"},
                {"name": "Pigments 4", "type": "VST3", "manufacturer": "Arturia"},
            ],
            "total": 2,
            "new_plugins_detected": ["Pigments 4"]
        })),
        {"role": "assistant", "content": "Neue Plugins erkannt: **Pigments 4** (Arturia). Insgesamt 2 Plugins gefunden."},
    ]))

    return pairs


# ── 19. scan_and_learn_project ────────────────────────────────────────────────

def scan_and_learn_project_pairs() -> list[dict]:
    pairs = []

    c1, id1 = assistant_call("scan_and_learn_project", {"project_name": ""})
    pairs.append(pair("Lern das aktuelle Bitwig-Projekt kennen.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "project": "Techno Session 01",
            "bpm": 132,
            "key": "F minor",
            "tracks_learned": 5,
            "patterns_stored": 12,
            "devices_found": ["VD-Kick Classic", "FM-4", "Phase-4", "Reverb", "Compressor"]
        })),
        {"role": "assistant", "content": (
            "✅ **Techno Session 01** gelernt:\n"
            "- 132 BPM, F-Moll\n"
            "- 5 Tracks, 12 Patterns in Neo4j gespeichert\n"
            "- Devices: VD-Kick Classic, FM-4, Phase-4, Reverb, Compressor"
        )},
    ]))

    c1, id1 = assistant_call("scan_and_learn_project", {"project_name": "Chee Hey Now Rebuild"})
    pairs.append(pair("Scanne und lerne das Projekt 'Chee Hey Now Rebuild'.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "project": "Chee Hey Now Rebuild",
            "bpm": 138,
            "key": "A minor",
            "tracks_learned": 7,
            "patterns_stored": 18,
            "devices_found": ["VD-Heavy Kick", "FM-4 Wobble", "Phase-4 Lead", "Polysynth Pad"]
        })),
        {"role": "assistant", "content": (
            "✅ **Chee Hey Now Rebuild** gelernt:\n"
            "- 138 BPM, A-Moll — 7 Tracks, 18 Patterns\n"
            "- Devices: FM-4 (Wobble), Phase-4 (Lead), Polysynth (Pad)"
        )},
    ]))

    c1, id1 = assistant_call("scan_and_learn_project", {"project_name": ""})
    pairs.append(pair("Ich hab gerade ein neues Projekt geöffnet. Bitte lern es.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "project": "My New Track",
            "bpm": 120,
            "key": "C major",
            "tracks_learned": 3,
            "patterns_stored": 6
        })),
        {"role": "assistant", "content": (
            "✅ **My New Track** gelernt (120 BPM, C-Dur, 3 Tracks, 6 Patterns).\n"
            "Der Projektkontext ist jetzt in der Wissensbasis verfügbar."
        )},
    ]))

    c1, id1 = assistant_call("scan_and_learn_project", {"project_name": ""})
    pairs.append(pair("Analysiere mein aktuelles Projekt und sag mir was drin ist.", [
        c1, tool_result(id1, json.dumps({
            "status": "learned",
            "project": "House Groove v2",
            "bpm": 124,
            "key": "G minor",
            "tracks_learned": 8,
            "patterns_stored": 24,
            "devices_found": ["Polysynth", "Operator", "Chorus", "Reverb", "Delay-2", "Compressor"],
            "note_counts": {"Kick": 16, "Bass": 32, "Lead": 16, "Chord": 8, "Arp": 32}
        })),
        {"role": "assistant", "content": (
            "**House Groove v2** (124 BPM, G-Moll):\n"
            "- 8 Tracks, 24 Patterns gelernt\n"
            "- Kick: 16n | Bass: 32n | Lead: 16n | Chord: 8n | Arp: 32n\n"
            "- Devices: Polysynth, Operator, Chorus, Reverb, Delay-2"
        )},
    ]))

    return pairs


# ── Alle Paare zusammenführen ─────────────────────────────────────────────────

def build_all_pairs() -> list[dict]:
    generators = [
        ("control_bitwig",          control_bitwig_pairs),
        ("get_bitwig_track_state",   get_bitwig_track_state_pairs),
        ("suggest_notes",            suggest_notes_pairs),
        ("get_launchpad_mode",       get_launchpad_mode_pairs),
        ("listen_played_notes",      listen_played_notes_pairs),
        ("play_notes",               play_notes_pairs),
        ("arm_track",                arm_track_pairs),
        ("analyze_song",             analyze_song_pairs),
        ("validate_music",           validate_music_pairs),
        ("get_song_context",         get_song_context_pairs),
        ("get_artist_context",       get_artist_context_pairs),
        ("learn_song_from_youtube",  learn_song_from_youtube_pairs),
        ("search_artist_song",       search_artist_song_pairs),
        ("validate_and_learn",       validate_and_learn_pairs),
        ("write_pattern_raw",        write_pattern_raw_pairs),
        ("export_mlx_training_data", export_mlx_training_data_pairs),
        ("compose_notes",            compose_notes_pairs),
        ("scan_vst_plugins",         scan_vst_plugins_pairs),
        ("scan_and_learn_project",   scan_and_learn_project_pairs),
    ]
    all_pairs: list[dict] = []
    counts: dict[str, int] = {}
    for name, fn in generators:
        p = fn()
        counts[name] = len(p)
        all_pairs.extend(p)
    return all_pairs, counts


def validate_pairs(pairs: list[dict]) -> None:
    errors = 0
    for i, p in enumerate(pairs):
        msgs = p.get("messages", [])
        if not msgs or msgs[0]["role"] != "system":
            print(f"  ⚠ Pair {i}: kein system-Message")
            errors += 1
        last = msgs[-1] if msgs else {}
        if last.get("role") != "assistant" or last.get("tool_calls"):
            print(f"  ⚠ Pair {i}: letzter Message ist kein assistant-Text")
            errors += 1
        # Prüfe tool_call ↔ tool_result Konsistenz
        call_ids = set()
        for m in msgs:
            for tc in m.get("tool_calls", []):
                call_ids.add(tc["id"])
            if m.get("role") == "tool":
                tid = m.get("tool_call_id", "")
                if tid not in call_ids:
                    print(f"  ⚠ Pair {i}: tool_call_id {tid!r} ohne passenden tool_call")
                    errors += 1
    if errors == 0:
        print(f"  ✓ Alle {len(pairs)} Paare valide")
    else:
        print(f"  ✗ {errors} Fehler gefunden")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    out_file = Path(__file__).parent.parent / "data" / "training" / "missing_tool_pairs.jsonl"
    out_file.parent.mkdir(parents=True, exist_ok=True)

    pairs, counts = build_all_pairs()

    print(f"Generiere Trainingspaare für fehlende Tools")
    print(f"{'─' * 45}")
    total = 0
    for name, n in counts.items():
        print(f"  {name:<30} {n:>3} Paare")
        total += n
    print(f"{'─' * 45}")
    print(f"  {'TOTAL':<30} {total:>3} Paare")

    print("\nFormat-Validierung:")
    validate_pairs(pairs)

    out_file.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
        encoding="utf-8",
    )
    print(f"\n✓ {out_file} ({total} Zeilen)")
    print("\nNächster Schritt: python scripts/prepare_mlx_training.py")


if __name__ == "__main__":
    main()

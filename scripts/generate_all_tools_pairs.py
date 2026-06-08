#!/usr/bin/env python3
"""Generates training pairs for all currently under-represented tools.

Covers 19 tools with 0 or very few training examples:
  control_bitwig, get_bitwig_track_state, get_song_context, get_artist_context,
  analyze_song, validate_music, compose_notes, write_pattern_raw,
  search_artist_song, learn_song_from_youtube, validate_and_learn,
  scan_and_learn_project, scan_vst_plugins, export_mlx_training_data,
  suggest_notes, get_launchpad_mode, listen_played_notes, play_notes, arm_track

Format: OpenAI tool_calls (multi-turn conversations)
Output: appended to training_data/train.jsonl

Usage:
    python scripts/generate_all_tools_pairs.py            # an train.jsonl anhängen
    python scripts/generate_all_tools_pairs.py --dry-run  # nur Vorschau
    python scripts/generate_all_tools_pairs.py --print 3  # erste 3 Pairs zeigen
"""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

TRAIN_FILE = Path(__file__).resolve().parent.parent / "training_data" / "train.jsonl"

# ── System-Prompt (erweiterte Version mit allen Tools) ────────────────────────

SYSTEM_PROMPT = """/no_think
Du bist ein erfahrener Bitwig Studio 6 Assistent und Musiker.

## Verfügbare Tools

### Wissen & Recherche
- **query_bitwig_docs(query)** — Bitwig-Wissensdatenbank (Neo4j). IMMER bei Genre/Device/Workflow.
- **web_search(query)** — Websuche für Künstler, Songs, aktuelle Infos.
- **find_audio_example(genre_query)** — Audio-Samples in KB suchen.
- **get_artist_context(artist_name)** — Künstlerprofil (Stil, BPM, Devices) aus KB.
- **search_artist_song(artist, title)** — Song-Metadaten via MusicBrainz/AcousticBrainz.
- **get_song_context(project_name)** — Projektzustand aus KB: Tempo, Tracks, Clips, Struktur.

### Bitwig-Steuerung
- **check_bitwig_connection()** — Bridge-Verbindung prüfen. VOR execute_setup aufrufen.
- **control_bitwig(action, ...)** — Transport/Tracks/Mix via OSC (play, stop, tempo, mute, solo, volume, pan, add_track, select_track, eq_freq, eq_gain, launch_clip, ...).
- **get_bitwig_track_state()** — Aktuelle Track-Namen und -Anzahl lesen.
- **execute_setup(result)** — Phase 1: Tracks, Instrumente, FX, Tempo anlegen.
- **compose_notes(result)** — Phase 2: MIDI-Noten in Track schreiben.
- **write_pattern(track_index, notes, bpm, key)** — Noten-Template in Clip schreiben.
- **write_pattern_raw(track_index, notes, length_beats, bpm, genre, key)** — Exakte LLM-spezifizierte Noten schreiben.

### Launchpad
- **suggest_notes(notes, r, g, b)** — Noten auf Launchpad hervorheben (INSTRUMENT-Modus).
- **get_launchpad_mode()** — Aktuellen Launchpad-Modus abfragen (CONTROL/DRUM/INSTRUMENT).
- **listen_played_notes(duration)** — Gespielte Noten aufzeichnen (DRUM/INSTRUMENT-Modus).
- **play_notes(notes, bpm)** — Notenfolge über Launchpad vorspielen.
- **arm_track(arm)** — Track für Aufnahme scharf schalten (1=arm, 0=disarm).

### Lernen & Qualität
- **analyze_song(file_path)** — Audio analysieren: Genre, Key, BPM, Mood via Mac-LLM.
- **validate_music(notes, instrument, genre, key, scale, bars, bpm)** — Noten auf Qualität prüfen.
- **validate_and_learn(notes, instrument, genre, key, scale, bars, bpm)** — Validieren + Feedback in Neo4j speichern.
- **learn_song_from_youtube(artist, title, youtube_url, transcribe_midi)** — Song aus YouTube lernen und in KB speichern.
- **scan_and_learn_project()** — Aktuelles Bitwig-Projekt in KB einlesen.
- **scan_vst_plugins()** — Installierte VST3-Plugins scannen und in KB speichern.
- **store_result_in_kb(data, category)** — Ergebnis in Wissensdatenbank speichern.

### Meta
- **reconstruct_project(project_name, include_notes, include_params, dry_run)** — Projekt aus KB neu aufbauen.
- **create_track_from_recipe(track_name, project_name, scene_name, include_notes, include_params)** — Track aus Template anlegen.
- **export_mlx_training_data(output_path, min_score, limit)** — Trainingsdaten für MLX LoRA exportieren.

## Grundregeln
- Genre/Device/Workflow → IMMER zuerst query_bitwig_docs
- Künstler/Songs → get_artist_context oder search_artist_song (nicht aus Gedächtnis)
- Vor execute_setup → check_bitwig_connection
- Noten schreiben → validate_music danach aufrufen"""


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _tc_id() -> str:
    return f"call_{uuid.uuid4().hex[:8]}"


def _tc_msg(name: str, args: dict) -> tuple[dict, str]:
    """Erstellt eine tool_calls Assistent-Message. Gibt (msg, tc_id) zurück."""
    tc = _tc_id()
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": tc,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
        }]
    }, tc


def _tool_result(tc_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tc_id, "content": content}


def _pair(user: str, *steps) -> dict:
    """Baut eine vollständige Message-Sequenz.

    steps: abwechselnd (tc_msg, result_content) Tupel, dann optional finale
    Assistent-Antwort als letzter str.
    """
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    final_answer = ""
    it = iter(steps)
    for step in it:
        if isinstance(step, str):
            final_answer = step
            break
        tc_msg, tc_id = step
        msgs.append(tc_msg)
        result_content = next(it)
        msgs.append(_tool_result(tc_id, result_content))
    if final_answer:
        msgs.append({"role": "assistant", "content": final_answer})
    return {"messages": msgs}


# ── control_bitwig ────────────────────────────────────────────────────────────

def _control_bitwig_pairs() -> list[dict]:
    pairs = []

    # Play
    m, tc = _tc_msg("control_bitwig", {"action": "play"})
    pairs.append(_pair(
        "Starte die Wiedergabe",
        (m, tc), '{"status": "ok", "sent": ["/play"], "host": "127.0.0.1", "port": 8001}',
        "Wiedergabe gestartet."
    ))

    # Stop
    m, tc = _tc_msg("control_bitwig", {"action": "stop"})
    pairs.append(_pair(
        "Stop bitte",
        (m, tc), '{"status": "ok", "sent": ["/stop"]}',
        "Wiedergabe gestoppt."
    ))

    # Tempo setzen
    m, tc = _tc_msg("control_bitwig", {"action": "tempo", "bpm": 135.0})
    pairs.append(_pair(
        "Setz das Tempo auf 135 BPM",
        (m, tc), '{"status": "ok", "sent": ["/tempo 135.0"]}',
        "Tempo auf 135 BPM gesetzt."
    ))

    # Mute Track 2
    m, tc = _tc_msg("control_bitwig", {"action": "mute", "track_index": 2})
    pairs.append(_pair(
        "Mute Track 2",
        (m, tc), '{"status": "ok", "sent": ["/track/2/mute 1"]}',
        "Track 2 gemutet."
    ))

    # Solo Track 1
    m, tc = _tc_msg("control_bitwig", {"action": "solo", "track_index": 1})
    pairs.append(_pair(
        "Solo auf Track 1 schalten",
        (m, tc), '{"status": "ok", "sent": ["/track/1/solo 1"]}',
        "Track 1 in Solo-Modus."
    ))

    # Volume Track 3
    m, tc = _tc_msg("control_bitwig", {"action": "volume", "track_index": 3, "value": 0.7})
    pairs.append(_pair(
        "Setz die Lautstärke von Track 3 auf 70%",
        (m, tc), '{"status": "ok", "sent": ["/track/3/volume 0.7"]}',
        "Lautstärke von Track 3 auf 70% gesetzt."
    ))

    # EQ Frequenz anpassen
    m, tc = _tc_msg("control_bitwig", {"action": "eq_gain", "track_index": 2, "eq_band": 2, "eq_gain": -3.0})
    pairs.append(_pair(
        "Senke bei Track 2 das zweite EQ-Band um 3 dB ab",
        (m, tc), '{"status": "ok", "sent": ["/eq/2/band/2/gain -3.0"]}',
        "EQ-Band 2 auf Track 2 um −3 dB abgesenkt."
    ))

    # Add instrument track
    m, tc = _tc_msg("control_bitwig", {"action": "add_track", "track_type": "instrument", "track_name": "Strings"})
    pairs.append(_pair(
        "Füge einen neuen Instrument-Track namens 'Strings' hinzu",
        (m, tc), '{"status": "ok", "sent": ["/track/add instrument Strings"]}',
        "Instrument-Track 'Strings' hinzugefügt."
    ))

    # Record toggle
    m, tc = _tc_msg("control_bitwig", {"action": "record"})
    pairs.append(_pair(
        "Aktiviere die Aufnahme",
        (m, tc), '{"status": "ok", "sent": ["/record 1"]}',
        "Aufnahme aktiviert."
    ))

    # Select track
    m, tc = _tc_msg("control_bitwig", {"action": "select_track", "track_index": 4})
    pairs.append(_pair(
        "Wähle Track 4 aus",
        (m, tc), '{"status": "ok", "sent": ["/track/4/select"]}',
        "Track 4 ausgewählt."
    ))

    return pairs


# ── get_bitwig_track_state ────────────────────────────────────────────────────

def _get_bitwig_track_state_pairs() -> list[dict]:
    pairs = []

    # Leer
    m, tc = _tc_msg("get_bitwig_track_state", {})
    pairs.append(_pair(
        "Wie viele Tracks hat mein aktuelles Projekt?",
        (m, tc),
        "Bitwig Track-Zustand:\n  Track 1: Kick\n  Track 2: Bass\n  Track 3: Chords\nVorhandene Tracks: 3\n→ Neue Tracks (falls nötig) ab track_index=4.",
        "Dein Projekt hat aktuell 3 Tracks: Kick, Bass und Chords. Neue Tracks können ab track_index=4 hinzugefügt werden."
    ))

    # Vor execute_setup
    m1, tc1 = _tc_msg("check_bitwig_connection", {})
    m2, tc2 = _tc_msg("get_bitwig_track_state", {})
    pairs.append(_pair(
        "Zeig mir den aktuellen Projektstatus bevor wir weitermachen",
        (m1, tc1), "connected: true | BitwigStepPlugin Port 8002 erreichbar",
        (m2, tc2), "Bitwig Track-Zustand:\n  Track 1: Drums\n  Track 2: Sub-Bass\nVorhandene Tracks: 2\n→ Neue Tracks ab track_index=3.",
        "Bitwig ist erreichbar. Aktuell 2 Tracks: Drums und Sub-Bass. Neue Tracks ab Index 3 möglich."
    ))

    # Leeres Projekt
    m, tc = _tc_msg("get_bitwig_track_state", {})
    pairs.append(_pair(
        "Ist das Projekt leer?",
        (m, tc),
        "Track-Zustand unbekannt — Annahme: leeres Projekt, start_track_index=1",
        "Das Projekt scheint leer zu sein. Alle Tracks beginnen ab track_index=1."
    ))

    # Nach Setup
    m, tc = _tc_msg("get_bitwig_track_state", {})
    pairs.append(_pair(
        "Prüfe welche Tracks bereits angelegt wurden",
        (m, tc),
        "Bitwig Track-Zustand:\n  Track 1: Kick\n  Track 2: Bass\n  Track 3: Lead\n  Track 4: Pad\n  Track 5: FX\nVorhandene Tracks: 5\n→ Neue Tracks ab track_index=6.",
        "Es sind bereits 5 Tracks angelegt: Kick, Bass, Lead, Pad und FX. Neue Tracks können ab track_index=6 hinzugefügt werden."
    ))

    # Für Pattern-Schreiben
    m, tc = _tc_msg("get_bitwig_track_state", {})
    pairs.append(_pair(
        "Auf welchem Track-Index liegt die Bassline?",
        (m, tc),
        "Bitwig Track-Zustand:\n  Track 1: Drums\n  Track 2: Bass\n  Track 3: Melody\nVorhandene Tracks: 3\n→ Neue Tracks ab track_index=4.",
        "Die Bassline liegt auf Track 2 (track_index=2)."
    ))

    return pairs


# ── get_song_context ──────────────────────────────────────────────────────────

def _get_song_context_pairs() -> list[dict]:
    pairs = []

    FULL_CONTEXT = (
        "🎵 **Techno Session**\n"
        "   Tempo: 132 BPM | Tonart: D minor\n\n"
        "**Arranger-Struktur:**\n"
        "  Takt   0  (Beat    0)   8 Takte — Intro\n"
        "  Takt   8  (Beat   32)  16 Takte — Build\n"
        "  Takt  24  (Beat   96)  32 Takte — Peak\n\n"
        "**Szenen (Energie):**\n"
        "  Intro  [███░░░░░░] 30%\n"
        "  Build  [██████░░░] 60%\n"
        "  Peak   [██████████] 100%\n\n"
        "**Tracks:**\n"
        "  1. Kick      — VD-HEAVY Kick, MIDI 36\n"
        "  2. Bass      — FM-4, D1–A1 rollend\n"
        "  3. Lead      — Phase-4, D4–F4–A4\n"
        "  4. FX        — Reverb + Delay-2"
    )

    m, tc = _tc_msg("get_song_context", {"project_name": ""})
    pairs.append(_pair(
        "Was ist gerade in meinem Bitwig-Projekt?",
        (m, tc), FULL_CONTEXT,
        "Dein Projekt 'Techno Session' läuft bei 132 BPM in D minor. Es hat 3 Sektionen (Intro/Build/Peak) und 4 Tracks: Kick (VD-HEAVY), Bass (FM-4), Lead (Phase-4) und FX."
    ))

    m, tc = _tc_msg("get_song_context", {"project_name": "Dark Techno"})
    pairs.append(_pair(
        "Zeig mir den Kontext für das Projekt 'Dark Techno'",
        (m, tc),
        "🎵 **Dark Techno**\n   Tempo: 138 BPM | Tonart: C minor\n\n**Tracks:**\n  1. Kick (VD-HEAVY)\n  2. Sub-Bass (FM-4)\n  3. Bassline (Ladder-Filter)\n  4. Pad (Polymer)\n  5. FX-Bus",
        "Das Projekt 'Dark Techno' läuft bei 138 BPM in C minor mit 5 Tracks: Kick, Sub-Bass, Bassline (Ladder-Filter), Pad (Polymer) und einem FX-Bus."
    ))

    m, tc = _tc_msg("get_song_context", {"project_name": ""})
    pairs.append(_pair(
        "Bevor ich Noten schreibe — was hat das Projekt gerade für Tracks und Keys?",
        (m, tc),
        "🎵 **House Track**\n   Tempo: 124 BPM | Tonart: F minor\n\n**Tracks:**\n  1. Kick\n  2. Bass\n  3. Piano (Polysynth)\n  4. Pad",
        "Das Projekt 'House Track' hat 124 BPM in F minor. Es gibt 4 Tracks: Kick, Bass, Piano (Polysynth) und Pad. Perfekte Basis für neue Patterns."
    ))

    m, tc = _tc_msg("get_song_context", {"project_name": ""})
    pairs.append(_pair(
        "Welche Szenen-Energie haben die einzelnen Abschnitte?",
        (m, tc),
        "🎵 **DnB Session**\n   Tempo: 174 BPM | Tonart: G minor\n\n**Szenen:**\n  Intro  [█░░░░░░░░] 10%\n  Verse  [████░░░░░] 45%\n  Drop   [██████████] 100%\n  Outro  [███░░░░░░] 30%",
        "Dein Projekt hat 4 Szenen mit diesen Energie-Werten:\n- Intro: 10%\n- Verse: 45%\n- Drop: 100% (volle Energie)\n- Outro: 30%"
    ))

    m, tc = _tc_msg("get_song_context", {"project_name": "Chee - Hey Now"})
    pairs.append(_pair(
        "Analysiere das Projekt 'Chee - Hey Now' für mich",
        (m, tc),
        "🎵 **Chee - Hey Now**\n   Tempo: 120 BPM | Tonart: A minor\n\n**Arranger:**\n  Takt   0 — Intro (8 Takte)\n  Takt   8 — Verse (16 Takte)\n  Takt  24 — Chorus (16 Takte)\n\n**Tracks:** 6 Tracks (Drums, Bass, Keys, Lead, Vocal, FX)",
        "Das Projekt 'Chee - Hey Now' läuft bei 120 BPM in A minor. Struktur: Intro (8 Takte) → Verse (16 Takte) → Chorus (16 Takte). Insgesamt 6 Tracks inkl. Vocals."
    ))

    return pairs


# ── get_artist_context ────────────────────────────────────────────────────────

def _get_artist_context_pairs() -> list[dict]:
    pairs = []

    APHEX_CONTEXT = (
        "**Künstler: Aphex Twin**\n"
        "  Genre: IDM / Ambient Techno | BPM: 120–160 | Tonart: A minor\n"
        "  Stil: Experimentell, glitchig, komplexe Polyrhythmen, Acid-Basslines.\n"
        "  Typische Devices: FM-4 (Acid-Bass), Phase-4 (Glitch-Lead), Polymer (Granular)\n"
        "  Assoziierte Genres: IDM, Breakbeat, Ambient\n"
        "  Referenz-Songs: Come To Daddy (155 BPM), Windowlicker (155 BPM)"
    )

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Aphex Twin"})
    pairs.append(_pair(
        "Ich möchte etwas im Stil von Aphex Twin machen — was charakterisiert seinen Sound?",
        (m, tc), APHEX_CONTEXT,
        "Aphex Twin steht für IDM mit sehr komplexen Polyrhythmen, Acid-Basslines (FM-4 mit Ladder-Filter) und glitchigen Breaks. Typisch: 120–160 BPM in A minor, stark prozessierte Drums. Willst du direkt ein Setup anlegen?"
    ))

    BURIAL_CONTEXT = (
        "**Künstler: Burial**\n"
        "  Genre: UK Garage / Dark Ambient | BPM: 138–142 | Tonart: D minor\n"
        "  Stil: Gebrochene 2-Step-Beats, Vinyl Crackle, detunte Vocal-Chops, dunkel.\n"
        "  Typische Devices: FM-4 (Sub-Bass), Sampler (Vinyl/Vocals), Phase-4 (Pad)\n"
        "  Referenz-Songs: Archangel (140 BPM, D minor)"
    )

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Burial"})
    pairs.append(_pair(
        "Erkläre mir den Burial-Sound",
        (m, tc), BURIAL_CONTEXT,
        "Burial produziert einen dunklen UK-Garage-Sound mit gebrochenen 2-Step-Beats (kein 4-on-floor), Vinyl-Crackle als Textur, und sehr tiefem Sub-Bass (FM-4 Sinus, D1). BPM: 138–142, Tonart meist D minor. Sehr charakteristisch: stark detunte Vocal-Chops."
    ))

    FOUR_TET_CONTEXT = (
        "**Künstler: Four Tet**\n"
        "  Genre: IDM / Deep House / Folktronica | BPM: 118–126 | Tonart: C major\n"
        "  Stil: Organische Samples, granulare Verarbeitung, warme Pads, dezent.\n"
        "  Typische Devices: Sampler, Polymer (Granular), Phase-4 (Pad), FM-4 (Bass)\n"
        "  Referenz-Songs: Baby (120 BPM, C major)"
    )

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Four Tet"})
    pairs.append(_pair(
        "Was macht Four Tet musikalisch aus?",
        (m, tc), FOUR_TET_CONTEXT,
        "Four Tet kombiniert organische Samples (granular bearbeitet via Polymer) mit Jazz-Harmonik und warmen Pads. BPM: 118–126, Tonart oft C major. Percussion ist nicht quantisiert und real klingend. Sehr subtile, atmosphärische Produktion."
    ))

    DAFT_PUNK_CONTEXT = (
        "**Künstler: Daft Punk**\n"
        "  Genre: French House / Electro | BPM: 120–128 | Tonart: F minor\n"
        "  Stil: French Filter-Sweeps, Vocoder, Funk-Bass, 4-on-floor, phased Pads.\n"
        "  Typische Devices: Phase-4 (Filter-Sweep), FM-4 (Funk-Bass), Polysynth (Chords)\n"
        "  Referenz-Songs: Around The World (121 BPM, F minor), Da Funk (121 BPM)"
    )

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Daft Punk"})
    pairs.append(_pair(
        "Ich will einen French House Track wie Daft Punk machen",
        (m, tc), DAFT_PUNK_CONTEXT,
        "Daft Punk steht für French House mit dem charakteristischen Filter-Sweep (Hochpass öffnet langsam), Funk-Basslines (FM-4, F minor Pentatonik), 4-on-floor Kick und breiten Chord-Stabs. BPM: 120–128. Soll ich ein Setup anlegen?"
    ))

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Bonobo"})
    pairs.append(_pair(
        "Analysiere den Stil von Bonobo für mich",
        (m, tc),
        "**Künstler: Bonobo**\n  Genre: Downtempo / Nu-Jazz | BPM: 85–100 | Tonart: D minor\n  Stil: Live-Instrumente, Jazz-Akkorde, entspannte Grooves, atmosphärische Pads.\n  Typische Devices: Polysynth (Piano), Sampler (Live), Phase-4 (Pad)",
        "Bonobo produziert entspannten Downtempo/Nu-Jazz mit echten Instrumenten (gesampelt), Jazz-Akkorden (Dm9, Fm11) und Swing-Drums. BPM 85–100, meist D minor. Sehr organisch und lebendig."
    ))

    m, tc = _tc_msg("get_artist_context", {"artist_name": "Moderat"})
    pairs.append(_pair(
        "Wie klingt Moderat?",
        (m, tc),
        "**Künstler: Moderat**\n  Genre: Electro-Pop / IDM | BPM: 120–130 | Tonart: A minor\n  Stil: Dunkle Elektro-Sounds, Berlin-Melancholie, pulsierende Bässe, schwebende Vocals.\n  Typische Devices: Phase-4 (Industrial-Lead), FM-4 (Puls-Bass), Polysynth (Pad)",
        "Moderat klingt nach dunklem Berliner Electro-Pop: pulsierende Bässe (synchron zum Kick), metallische Industrial-Leads (Phase-4), fallende Akkordfolge Am→G→F→E. BPM 124–126, A minor. Typisch: lange schwebende Vocals über harten Beats."
    ))

    return pairs


# ── analyze_song ──────────────────────────────────────────────────────────────

def _analyze_song_pairs() -> list[dict]:
    pairs = []

    TECHNO_RESULT = (
        "[analyze_song] track.mp3\n"
        "Genre: Techno / Tech House (Konfidenz: 92%)\n"
        "Tonart: G minor | BPM: 132.4 | Energie: high\n"
        "Stimmung: energetic, hypnotic, dark\n"
        "Helligkeit: 4200 Hz | RMS: 0.14\n"
        "Empfohlene Devices: FM-4, Ladder-Filter, VD-HEAVY Kick"
    )

    m, tc = _tc_msg("analyze_song", {"file_path": "/Users/sija/Music/track.mp3"})
    pairs.append(_pair(
        "Analysiere die Datei /Users/sija/Music/track.mp3 für mich",
        (m, tc), TECHNO_RESULT,
        "Analyse abgeschlossen:\n- **Genre:** Techno/Tech House (92% Konfidenz)\n- **Tonart:** G minor\n- **BPM:** 132.4\n- **Energie:** hoch, hypnotisch, dunkel\n\nEmpfohlene Bitwig-Devices: FM-4 für Bass, Ladder-Filter, VD-HEAVY Kick."
    ))

    LOFI_RESULT = (
        "[analyze_song] lofi_beat.wav\n"
        "Genre: Lo-fi Hip Hop (Konfidenz: 87%)\n"
        "Tonart: C major | BPM: 82.1 | Energie: low\n"
        "Stimmung: relaxed, nostalgic, warm\n"
        "Empfohlene Devices: Polysynth (Jazz-Chords), Sampler (Vinyl), FM-4 (Bass)"
    )

    m, tc = _tc_msg("analyze_song", {"file_path": "/tmp/lofi_beat.wav"})
    pairs.append(_pair(
        "Was für ein Genre ist die Datei /tmp/lofi_beat.wav?",
        (m, tc), LOFI_RESULT,
        "Die Datei ist Lo-fi Hip Hop (87% Konfidenz): 82 BPM, C major, entspannte warme Stimmung. Passende Bitwig-Devices: Polysynth für Jazz-Chords, Sampler für Vinyl-Crackle."
    ))

    DnB_RESULT = (
        "[analyze_song] dnb_sample.flac\n"
        "Genre: Drum and Bass (Konfidenz: 95%)\n"
        "Tonart: D minor | BPM: 174.2 | Energie: very high\n"
        "Stimmung: energetic, dark, intense\n"
        "Empfohlene Devices: FM-4 (Sub-Bass), Phase-4 (Reese)"
    )

    m, tc = _tc_msg("analyze_song", {"file_path": "/tmp/dnb_sample.flac"})
    pairs.append(_pair(
        "Erkenne das Genre und BPM von /tmp/dnb_sample.flac",
        (m, tc), DnB_RESULT,
        "Genre erkannt: **Drum and Bass** (95%) — 174 BPM, D minor, sehr hohe Energie. Klassische DnB-Signatur mit Breakbeat und Sub-Bass."
    ))

    m, tc = _tc_msg("analyze_song", {"file_path": "/Users/sija/Samples/reference.mp3"})
    pairs.append(_pair(
        "Ich hab hier ein Referenz-Track als MP3 — schau mal was das für ein Genre ist: /Users/sija/Samples/reference.mp3",
        (m, tc),
        "[analyze_song] reference.mp3\nGenre: House (Konfidenz: 89%)\nTonart: F minor | BPM: 124.0 | Energie: medium-high\nStimmung: groovy, uplifting\nEmpfohlene Devices: FM-4 (Bass), Polysynth (Chords), 4-on-floor Kick",
        "Dein Referenztrack ist **House** (89%): 124 BPM in F minor, mittlere bis hohe Energie, groovy und uplifting. Passt gut zu FM-4 Bass und Polysynth-Chords."
    ))

    return pairs


# ── validate_music ────────────────────────────────────────────────────────────

def _validate_music_pairs() -> list[dict]:
    pairs = []

    notes_sample = [
        {"pitch": 36, "step": 0, "vel": 0.9, "dur": 2},
        {"pitch": 38, "step": 4, "vel": 0.8, "dur": 2},
        {"pitch": 42, "step": 0, "vel": 0.5, "dur": 1},
        {"pitch": 42, "step": 2, "vel": 0.5, "dur": 1},
    ]

    m, tc = _tc_msg("validate_music", {
        "notes": notes_sample, "instrument": "VD-HEAVY",
        "genre": "techno", "key": "D", "scale": "minor", "bars": 1, "bpm": 132
    })
    pairs.append(_pair(
        "Validiere dieses Drum-Pattern für Techno in D minor, 132 BPM",
        (m, tc),
        "[validate_music] Score: 0.82 ✓ Gut\nMuster: Kick [0], Snare [4], HH [0,2]\nProbleme: HH-Dichte niedrig für Techno\nVorschläge: add more hi-hats on 16th positions; consider 16th-hat rolls",
        "Das Pattern hat einen Score von **0.82** — gut! Kick und Snare sitzen korrekt. Verbesserungsvorschlag: mehr 16tel-HiHats für typischen Techno-Flow. Soll ich das Pattern erweitern?"
    ))

    bass_notes = [
        {"pitch": 38, "step": 0, "vel": 0.85, "dur": 4},
        {"pitch": 45, "step": 8, "vel": 0.8, "dur": 4},
    ]
    m, tc = _tc_msg("validate_music", {
        "notes": bass_notes, "instrument": "FM-4",
        "genre": "house", "key": "F", "scale": "minor", "bars": 2, "bpm": 124
    })
    pairs.append(_pair(
        "Prüfe ob diese Bassline für House in F minor passt",
        (m, tc),
        "[validate_music] Score: 0.65 — Ausbaufähig\nTonarten-Konformität: 100% (F minor ✓)\nProbleme: sehr wenig rhythmische Variation, Off-Beat fehlt\nVorschläge: add off-beat notes on step 2+10; increase note density",
        "Score: **0.65** — die Tonart stimmt (F minor), aber die Bassline ist rhythmisch sehr statisch. Empfehlung: Off-Beat Noten auf Step 2 und 10 ergänzen für typischen House-Groove."
    ))

    m, tc = _tc_msg("validate_music", {
        "notes": notes_sample, "instrument": "VD-HEAVY",
        "genre": "dnb", "key": "G", "scale": "minor", "bars": 1, "bpm": 174
    })
    pairs.append(_pair(
        "Ist dieses Pattern gut für Drum and Bass?",
        (m, tc),
        "[validate_music] Score: 0.58 — Verbesserung nötig\nProbleme: kein Breakbeat-Pattern, Kick nicht synkopiert\nVorschläge: use syncopated kick pattern [0,5,8,13]; add extra snare on step 14",
        "Score **0.58** — für DnB braucht man einen Breakbeat, keinen 4-on-floor-Kick. Empfehlung: Kick auf [0,5,8,13], Snare auf [4,12,14] für den typischen DnB-Swing."
    ))

    return pairs


# ── compose_notes ─────────────────────────────────────────────────────────────

def _compose_notes_pairs() -> list[dict]:
    pairs = []

    BASS_RESULT = {"context_type": "track", "target": {"bpm": 132, "genre": "techno"}, "track": {"index": 2, "name": "Bass", "instrument": "FM-4"}, "summary": "Techno Bass", "steps": [{"type": "write_notes", "args": {"track_index": 2, "slot": 0, "length_beats": 8.0, "notes": [{"step": 0, "pitch": 38, "vel": 0.9, "dur": 2}, {"step": 4, "pitch": 33, "vel": 0.85, "dur": 2}, {"step": 8, "pitch": 38, "vel": 0.9, "dur": 2}, {"step": 12, "pitch": 36, "vel": 0.85, "dur": 2}]}, "status": "pending"}]}

    m, tc = _tc_msg("compose_notes", BASS_RESULT)
    pairs.append(_pair(
        "Schreib jetzt die Bassline in Track 2",
        (m, tc), "[compose_notes] ✓ 4 Noten geschrieben auf Track 2 (Bass, slot 0, 8 Beats)",
        "Bassline geschrieben: 4 Noten auf Track 2 (FM-4 Bass), 8 Beats lang, Slot 0."
    ))

    # Drum pattern via compose_notes
    DRUM_RESULT = {"context_type": "track", "target": {"bpm": 124, "genre": "house"}, "track": {"index": 1, "name": "Drums", "instrument": "VD-HEAVY"}, "summary": "House Drums", "steps": [{"type": "write_notes", "args": {"track_index": 1, "slot": 0, "length_beats": 8.0, "notes": [{"step": 0, "pitch": 36, "vel": 0.9, "dur": 2}, {"step": 4, "pitch": 38, "vel": 0.8, "dur": 2}, {"step": 8, "pitch": 36, "vel": 0.9, "dur": 2}, {"step": 12, "pitch": 38, "vel": 0.8, "dur": 2}]}, "status": "pending"}]}

    m, tc = _tc_msg("compose_notes", DRUM_RESULT)
    pairs.append(_pair(
        "Schreibe das Drum-Pattern jetzt in Track 1",
        (m, tc), "[compose_notes] ✓ 4 Noten geschrieben auf Track 1 (Drums, slot 0, 8 Beats)",
        "Drum-Pattern wurde geschrieben: 4-on-floor Kick + Snare auf Track 1, 8 Beats, Slot 0."
    ))

    # Nach execute_setup
    m1, tc1 = _tc_msg("check_bitwig_connection", {})
    setup_result = {"context_type": "song", "target": {"bpm": 174, "genre": "dnb"}, "summary": "DnB Setup", "steps": [{"type": "set_tempo", "args": {"bpm": 174}}, {"type": "add_track", "args": {}}, {"type": "load_instrument", "args": {"name": "VD-HEAVY"}}]}
    m2, tc2 = _tc_msg("execute_setup", {"result": setup_result})
    notes_result = {"context_type": "track", "target": {"bpm": 174, "genre": "dnb"}, "track": {"index": 1, "name": "Drums", "instrument": "VD-HEAVY"}, "summary": "DnB Drums", "steps": [{"type": "write_notes", "args": {"track_index": 1, "slot": 0, "length_beats": 4.0, "notes": [{"step": 0, "pitch": 36, "vel": 0.9, "dur": 2}, {"step": 5, "pitch": 36, "vel": 0.8, "dur": 2}, {"step": 8, "pitch": 36, "vel": 0.9, "dur": 2}, {"step": 4, "pitch": 38, "vel": 0.8, "dur": 2}, {"step": 12, "pitch": 38, "vel": 0.8, "dur": 2}]}, "status": "pending"}]}
    m3, tc3 = _tc_msg("compose_notes", notes_result)
    pairs.append(_pair(
        "Erstelle einen DnB-Track: erst Setup anlegen, dann Drums schreiben (174 BPM)",
        (m1, tc1), "connected: true | BitwigStepPlugin Port 8002 erreichbar",
        (m2, tc2), "[song] target={'bpm': 174, 'genre': 'dnb'}\n✓ 3 Steps: set_tempo✓, add_track✓, load_instrument✓",
        (m3, tc3), "[compose_notes] ✓ 5 Noten geschrieben auf Track 1 (Drums, slot 0, 4 Beats)",
        "DnB-Setup komplett: Tempo auf 174 BPM gesetzt, Drums-Track mit VD-HEAVY angelegt, Breakbeat-Pattern geschrieben (Kick [0,5,8], Snare [4,12])."
    ))

    m, tc = _tc_msg("compose_notes", {"context_type": "track", "target": {"bpm": 120, "genre": "jazz"}, "track": {"index": 2, "name": "Piano", "instrument": "Polysynth"}, "summary": "Jazz Chords", "steps": [{"type": "write_notes", "args": {"track_index": 2, "slot": 0, "length_beats": 8.0, "notes": [{"step": 0, "pitch": 65, "vel": 0.7, "dur": 3}, {"step": 4, "pitch": 62, "vel": 0.7, "dur": 3}, {"step": 8, "pitch": 60, "vel": 0.7, "dur": 3}]}, "status": "pending"}]})
    pairs.append(_pair(
        "Schreib die Jazz-Piano-Akkorde in Track 2",
        (m, tc), "[compose_notes] ✓ 3 Noten geschrieben auf Track 2 (Piano, slot 0, 8 Beats)",
        "Jazz-Piano-Akkorde geschrieben: 3 Noten (F4, D4, C4) auf Track 2 (Polysynth), 8 Beats."
    ))

    return pairs


# ── write_pattern_raw ─────────────────────────────────────────────────────────

def _write_pattern_raw_pairs() -> list[dict]:
    pairs = []

    # Einfaches Bass-Pattern
    m, tc = _tc_msg("write_pattern_raw", {
        "track_index": 2,
        "notes": [
            {"pitch": 38, "start": 0.0, "dur": 0.5, "vel": 0.9},
            {"pitch": 38, "start": 0.5, "dur": 0.5, "vel": 0.8},
            {"pitch": 33, "start": 1.0, "dur": 1.0, "vel": 0.85},
            {"pitch": 36, "start": 2.0, "dur": 0.5, "vel": 0.9},
        ],
        "length_beats": 4.0,
        "bpm": 132,
        "genre": "techno",
        "key": "D minor"
    })
    pairs.append(_pair(
        "Schreib diese exakten Noten auf Track 2: D2 auf Beat 0 und 0.5, A1 auf Beat 1, B1 auf Beat 2 — Techno-Bassline, 132 BPM, D minor",
        (m, tc),
        "[write_pattern_raw] 4 Noten geschrieben (len=4.0b) | key_conformance(D minor)=0.95 | bpm=132 | track=2 slot=0",
        "Exakte Bassline auf Track 2 geschrieben: D2→D2→A1→B1, 4 Beats, D minor, 132 BPM. Key-Konformität: 95%."
    ))

    # Jazzy Chord Voicing
    m, tc = _tc_msg("write_pattern_raw", {
        "track_index": 3,
        "notes": [
            {"pitch": 53, "start": 0.0, "dur": 2.0, "vel": 0.65},
            {"pitch": 57, "start": 0.0, "dur": 2.0, "vel": 0.6},
            {"pitch": 60, "start": 0.0, "dur": 2.0, "vel": 0.55},
            {"pitch": 64, "start": 0.0, "dur": 2.0, "vel": 0.5},
        ],
        "length_beats": 8.0,
        "bpm": 120,
        "genre": "jazz",
        "key": "F minor"
    })
    pairs.append(_pair(
        "Schreibe einen Fm7-Akkord (F3-Ab3-C4-Eb4) auf Track 3, 2 Beats lang, Jazz, 120 BPM",
        (m, tc),
        "[write_pattern_raw] 4 Noten geschrieben (len=8.0b) | key_conformance(F minor)=1.0 | bpm=120 | track=3 slot=0",
        "Fm7-Akkord auf Track 3 geschrieben: F3+Ab3+C4+Eb4, 2 Beats. Key-Konformität: 100% (alle Noten in F minor)."
    ))

    # Melodie-Linie
    m, tc = _tc_msg("write_pattern_raw", {
        "track_index": 4,
        "notes": [
            {"pitch": 69, "start": 0.0, "dur": 0.25, "vel": 0.8},
            {"pitch": 71, "start": 0.25, "dur": 0.25, "vel": 0.75},
            {"pitch": 72, "start": 0.5, "dur": 0.5, "vel": 0.85},
            {"pitch": 74, "start": 1.0, "dur": 1.0, "vel": 0.8},
        ],
        "length_beats": 4.0,
        "bpm": 120,
        "genre": "pop",
        "key": "A minor"
    })
    pairs.append(_pair(
        "Schreibe eine aufsteigende Melodie: A4→B4→C5→D5, 120 BPM, A minor, auf Track 4",
        (m, tc),
        "[write_pattern_raw] 4 Noten geschrieben (len=4.0b) | key_conformance(A minor)=1.0 | bpm=120 | track=4 slot=0",
        "Aufsteigende Melodie auf Track 4: A4→B4→C5→D5, alle Noten in A minor (100% Konformität)."
    ))

    # Komplexes Drum-Pattern
    m, tc = _tc_msg("write_pattern_raw", {
        "track_index": 1,
        "notes": [
            {"pitch": 36, "start": 0.0, "dur": 0.125, "vel": 1.0},
            {"pitch": 36, "start": 1.25, "dur": 0.125, "vel": 0.8},
            {"pitch": 36, "start": 2.0, "dur": 0.125, "vel": 0.9},
            {"pitch": 38, "start": 1.0, "dur": 0.125, "vel": 0.85},
            {"pitch": 38, "start": 3.0, "dur": 0.125, "vel": 0.85},
            {"pitch": 42, "start": 0.5, "dur": 0.0625, "vel": 0.6},
            {"pitch": 42, "start": 1.5, "dur": 0.0625, "vel": 0.55},
            {"pitch": 42, "start": 2.5, "dur": 0.0625, "vel": 0.6},
        ],
        "length_beats": 4.0,
        "bpm": 140,
        "genre": "brostep",
        "key": None
    })
    pairs.append(_pair(
        "Schreib ein Brostep Halbzeit-Drum-Pattern auf Track 1: Kick auf Beat 0, 1.25, 2 — Snare auf Beat 1 und 3 — HH auf den 8teln. 140 BPM",
        (m, tc),
        "[write_pattern_raw] 8 Noten geschrieben (len=4.0b) | bpm=140 | track=1 slot=0",
        "Brostep Halbzeit-Drums auf Track 1: Kick [0, 1.25, 2], Snare [1, 3], HH [0.5, 1.5, 2.5] — 8 Noten, 4 Beats, 140 BPM."
    ))

    return pairs


# ── search_artist_song ────────────────────────────────────────────────────────

def _search_artist_song_pairs() -> list[dict]:
    pairs = []

    m, tc = _tc_msg("search_artist_song", {"artist": "Radiohead", "title": "Idioteque"})
    pairs.append(_pair(
        "Suche Metadaten für 'Idioteque' von Radiohead",
        (m, tc),
        "**Song-Metadaten:** Radiohead — Idioteque\nMBID: ecde206d-3e41-4e5f-9e5b-...\nLänge: 303s\nMB-Tags: electronic, ambient, IDM, Kid A\nBPM (AB): 150.5\nTonart (AB): D minor\nRelease: Kid A (2000-10-02)\nLast.fm-Tags: radiohead, electronic, experimental",
        "Metadaten gefunden: **Idioteque** (Radiohead) — 150 BPM, D minor, 303s, aus dem Album Kid A (2000). Tags: electronic, ambient, IDM."
    ))

    m, tc = _tc_msg("search_artist_song", {"artist": "Daft Punk", "title": "Da Funk"})
    pairs.append(_pair(
        "Was sind die Metadaten von 'Da Funk' von Daft Punk?",
        (m, tc),
        "**Song-Metadaten:** Daft Punk — Da Funk\nMBID: abc123...\nLänge: 282s\nMB-Tags: french house, electronic, funk\nBPM (AB): 121.0\nTonart (AB): C minor\nRelease: Homework (1997-01-20)",
        "**Da Funk** (Daft Punk): 121 BPM, C minor, 282s, aus Homework (1997). French House / Electronic."
    ))

    m, tc = _tc_msg("search_artist_song", {"artist": "Massive Attack", "title": "Teardrop"})
    pairs.append(_pair(
        "Finde Infos zu 'Teardrop' von Massive Attack",
        (m, tc),
        "**Song-Metadaten:** Massive Attack — Teardrop\nLänge: 327s\nBPM (AB): 96.3\nTonart (AB): D minor\nMB-Tags: trip hop, electronic, ambient\nRelease: Mezzanine (1998-04-20)",
        "**Teardrop** (Massive Attack): 96 BPM, D minor, 327s, aus Mezzanine (1998). Trip Hop / Electronic."
    ))

    m, tc = _tc_msg("search_artist_song", {"artist": "Burial", "title": "Archangel"})
    pairs.append(_pair(
        "Suche mir Infos zu Burial - Archangel",
        (m, tc),
        "**Song-Metadaten:** Burial — Archangel\nLänge: 410s\nBPM (AB): 139.8\nTonart (AB): D minor\nMB-Tags: UK garage, ambient, dubstep\nRelease: Untrue (2007-11-05)",
        "**Archangel** (Burial): 140 BPM, D minor, 6:50 min, aus Untrue (2007). UK Garage / Dark Ambient."
    ))

    m, tc = _tc_msg("search_artist_song", {"artist": "Aphex Twin", "title": "Come To Daddy"})
    pairs.append(_pair(
        "Was kann ich über 'Come To Daddy' von Aphex Twin herausfinden?",
        (m, tc),
        "**Song-Metadaten:** Aphex Twin — Come To Daddy\nLänge: 267s\nBPM (AB): 154.8\nTonart (AB): A minor\nMB-Tags: IDM, breakbeat, experimental\nRelease: Come To Daddy EP (1997-10-06)",
        "**Come To Daddy** (Aphex Twin): 155 BPM, A minor, 267s, EP (1997). IDM / Breakbeat mit starkem Tempo."
    ))

    return pairs


# ── learn_song_from_youtube ───────────────────────────────────────────────────

def _learn_song_from_youtube_pairs() -> list[dict]:
    pairs = []

    # Erst suchen, dann lernen
    m1, tc1 = _tc_msg("search_artist_song", {"artist": "Daft Punk", "title": "Da Funk"})
    m2, tc2 = _tc_msg("learn_song_from_youtube", {
        "artist": "Daft Punk", "title": "Da Funk",
        "youtube_url": "https://www.youtube.com/watch?v=XaMiZQhm1Xk",
        "transcribe_midi": False
    })
    pairs.append(_pair(
        "Lerne den Song 'Da Funk' von Daft Punk aus YouTube: https://www.youtube.com/watch?v=XaMiZQhm1Xk",
        (m1, tc1), "**Song-Metadaten:** Daft Punk — Da Funk\nBPM: 121.0 | Tonart: C minor\nMB-Tags: french house",
        (m2, tc2),
        "✓ Song gelernt: **Daft Punk — Da Funk** (125.3s)\n  BPM=121 | Key=C | Dauer=282.0s\n  Helligkeit: 3200 Hz | RMS: 0.15\n  Tags: french house, electronic, funk\n  → Neo4j: (:Song {name:'Da Funk', artist:'Daft Punk'})",
        "**Da Funk** erfolgreich gelernt! BPM=121, C minor, 282s. Metadaten + Audiofeatures sind jetzt in der KB. Mit `query_bitwig_docs('Da Funk Daft Punk')` kannst du die Features abrufen."
    ))

    m, tc = _tc_msg("learn_song_from_youtube", {
        "artist": "Burial", "title": "Archangel",
        "youtube_url": "https://www.youtube.com/watch?v=3q1JTHfGQiM",
        "transcribe_midi": False
    })
    pairs.append(_pair(
        "Speichere 'Archangel' von Burial in der Wissensdatenbank: https://www.youtube.com/watch?v=3q1JTHfGQiM",
        (m, tc),
        "✓ Song gelernt: **Burial — Archangel** (189.2s)\n  BPM=140 | Key=D | Dauer=410.0s\n  Tags: uk garage, ambient, dark\n  → Neo4j gespeichert",
        "**Archangel** (Burial) in KB gespeichert: 140 BPM, D minor. Audiofeatures und Tags sind jetzt abrufbar."
    ))

    m, tc = _tc_msg("learn_song_from_youtube", {
        "artist": "Aphex Twin", "title": "Windowlicker",
        "youtube_url": "https://www.youtube.com/watch?v=M9xMuPWAZW8",
        "transcribe_midi": True
    })
    pairs.append(_pair(
        "Lerne 'Windowlicker' von Aphex Twin mit MIDI-Transkription: https://www.youtube.com/watch?v=M9xMuPWAZW8",
        (m, tc),
        "✓ Song gelernt: **Aphex Twin — Windowlicker** (345.1s)\n  BPM=155 | Key=F# | Dauer=613.0s\n  MIDI-Transkription: 142 Noten erkannt\n  Tags: IDM, acid, experimental\n  → Neo4j gespeichert",
        "**Windowlicker** (Aphex Twin) mit MIDI-Transkription gelernt: 155 BPM, F# minor, 142 Noten erkannt. Jetzt in der KB verfügbar."
    ))

    return pairs


# ── validate_and_learn ────────────────────────────────────────────────────────

def _validate_and_learn_pairs() -> list[dict]:
    pairs = []

    notes = [{"pitch": 36, "step": 0, "vel": 0.9, "dur": 2}, {"pitch": 38, "step": 4, "vel": 0.8, "dur": 2}]

    m, tc = _tc_msg("validate_and_learn", {
        "notes": notes, "instrument": "VD-HEAVY",
        "genre": "techno", "key": "D", "scale": "minor", "bars": 1, "bpm": 132
    })
    pairs.append(_pair(
        "Validiere dieses Pattern und lerne aus dem Feedback",
        (m, tc),
        "[validate_and_learn] Score: 0.75 ✓ Gut\nProbleme: wenig HiHat-Aktivität\nVorschläge: add 16th hi-hats\nLernhistorie: 3 Iterationen gespeichert, Ø Score: 0.71",
        "Pattern validiert (Score **0.75**) und in Neo4j gespeichert. 3 Iterationen bisher, Ø 0.71. Feedback: mehr 16tel-HiHats für besseren Techno-Flow."
    ))

    m, tc = _tc_msg("validate_and_learn", {
        "notes": [{"pitch": 38, "step": 0, "vel": 0.85, "dur": 4}, {"pitch": 45, "step": 8, "vel": 0.8, "dur": 4}],
        "instrument": "FM-4",
        "genre": "house", "key": "F", "scale": "minor", "bars": 2, "bpm": 124
    })
    pairs.append(_pair(
        "Diese Bassline validieren und Feedback in die KB schreiben",
        (m, tc),
        "[validate_and_learn] Score: 0.68 — Ausbaufähig\nProbleme: Off-Beat fehlt, zu statisch\nVorschläge: add off-beat notes steps 2+10\nLernhistorie: 1. Iteration gespeichert",
        "Score **0.68** — ausbaufähig. Feedback gespeichert (1. Iteration). Hauptproblem: Off-Beat fehlt. Empfehlung: Noten auf Step 2 und 10 für House-typischen Groove."
    ))

    m, tc = _tc_msg("validate_and_learn", {
        "notes": [{"pitch": 36, "step": 0, "vel": 0.9, "dur": 2}, {"pitch": 36, "step": 5, "vel": 0.8, "dur": 2}, {"pitch": 36, "step": 8, "vel": 0.9, "dur": 2}, {"pitch": 38, "step": 4, "vel": 0.85, "dur": 2}, {"pitch": 38, "step": 12, "vel": 0.85, "dur": 2}],
        "instrument": "VD-HEAVY",
        "genre": "dnb", "key": "G", "scale": "minor", "bars": 1, "bpm": 174
    })
    pairs.append(_pair(
        "Validiere und lerne: DnB Breakbeat Pattern, 174 BPM",
        (m, tc),
        "[validate_and_learn] Score: 0.88 ✓ Sehr gut\nMuster: Breakbeat ✓ (Kick [0,5,8], Snare [4,12])\nLernhistorie: 5 Iterationen, Ø Score: 0.81 (steigend)",
        "Ausgezeichnet — Score **0.88**! Breakbeat-Pattern korrekt: Kick [0,5,8], Snare [4,12]. Lernhistorie: 5 Iterationen, steigender Trend (Ø 0.81)."
    ))

    return pairs


# ── scan_and_learn_project ────────────────────────────────────────────────────

def _scan_and_learn_project_pairs() -> list[dict]:
    pairs = []

    m, tc = _tc_msg("scan_and_learn_project", {})
    pairs.append(_pair(
        "Scanne mein aktuelles Bitwig-Projekt und lern seine Struktur",
        (m, tc),
        "[scan_and_learn_project] ✓ Projekt 'Techno Session' gescannt\n  Tracks: 5 (Kick, Bass, Lead, Pad, FX)\n  Tempo: 132 BPM | Tonart: D minor\n  Szenen: Intro/Build/Peak/Outro\n  → Neo4j: 5 Track-Nodes, 4 Szenen-Nodes, 12 Clip-Nodes erstellt",
        "Projekt 'Techno Session' erfolgreich gescannt: 5 Tracks, 132 BPM, D minor, 4 Szenen. Struktur in Neo4j gespeichert — ab jetzt mit `get_song_context` abrufbar."
    ))

    m, tc = _tc_msg("scan_and_learn_project", {})
    pairs.append(_pair(
        "Lass die KI mein Projekt verstehen bevor wir Noten schreiben",
        (m, tc),
        "[scan_and_learn_project] ✓ Projekt 'Deep House Session' gescannt\n  Tracks: 4 (Drums, Bass, Piano, Pad)\n  Tempo: 124 BPM | Tonart: F minor\n  → Neo4j: Clips, Devices, Szenen gespeichert",
        "Projekt 'Deep House Session' gescannt (124 BPM, F minor, 4 Tracks). Jetzt kann ich mit `get_song_context` den vollen Kontext abrufen bevor ich Noten schreibe."
    ))

    m, tc = _tc_msg("scan_and_learn_project", {})
    pairs.append(_pair(
        "Lerne das aktuelle Bitwig-Projekt für spätere Verwendung",
        (m, tc),
        "[scan_and_learn_project] ✓ Projekt 'Ambient Textures' gescannt\n  Tracks: 6 (Pad1, Pad2, Bass, Texture, FX, Sub)\n  Tempo: 72 BPM | Tonart: C major\n  → Neo4j gespeichert",
        "Projekt 'Ambient Textures' in KB gespeichert: 6 Tracks, 72 BPM, C major. Mit `reconstruct_project('Ambient Textures')` kann ich es jederzeit neu aufbauen."
    ))

    m1, tc1 = _tc_msg("scan_and_learn_project", {})
    m2, tc2 = _tc_msg("get_song_context", {"project_name": ""})
    pairs.append(_pair(
        "Scanne erst das Projekt, dann zeig mir eine Zusammenfassung",
        (m1, tc1), "[scan_and_learn_project] ✓ Projekt 'DnB WIP' gescannt\n  Tracks: 3 (Drums, Bass, Reese)\n  Tempo: 174 BPM | Tonart: G minor",
        (m2, tc2), "🎵 **DnB WIP**\n   Tempo: 174 BPM | Tonart: G minor\n\n**Tracks:** 3 (Drums, Bass, Reese)\n**Szenen:** Intro, Drop",
        "Projekt 'DnB WIP' gescannt und Kontext geladen: 174 BPM, G minor, 3 Tracks (Drums/Bass/Reese), 2 Szenen (Intro/Drop)."
    ))

    return pairs


# ── scan_vst_plugins ──────────────────────────────────────────────────────────

def _scan_vst_plugins_pairs() -> list[dict]:
    pairs = []

    m, tc = _tc_msg("scan_vst_plugins", {})
    pairs.append(_pair(
        "Scanne alle installierten VST-Plugins und speichere sie in der KB",
        (m, tc),
        "[VST Scan] ✓ 143 Plugins gefunden | 12 neu | in Neo4j gespeichert\nNeu: Serum 2, Pigments 5, Hive 2, Phase Plant, ...",
        "VST-Scan abgeschlossen: 143 Plugins gefunden, 12 neue (u.a. Serum 2, Pigments 5, Hive 2, Phase Plant). Jetzt mit `query_bitwig_docs('Serum 2')` abfragbar."
    ))

    m, tc = _tc_msg("scan_vst_plugins", {})
    pairs.append(_pair(
        "Ich habe neue Plugins installiert — aktualisiere die Plugin-Liste",
        (m, tc),
        "[VST Scan] ✓ 156 Plugins gefunden | 3 neu | in Neo4j gespeichert\nNeu: Arturia Jup-8V4, Valhalla Room, FabFilter Pro-Q4",
        "Plugin-Liste aktualisiert: 3 neue Plugins gefunden — Arturia Jup-8V4, Valhalla Room und FabFilter Pro-Q4. Alle in KB gespeichert."
    ))

    m, tc = _tc_msg("scan_vst_plugins", {})
    pairs.append(_pair(
        "Welche VSTs sind bei mir installiert?",
        (m, tc),
        "[VST Scan] ✓ 128 Plugins gefunden | 0 neu | Daten aktuell\nBekannte Plugins: FM-4, Phase-4, Polysynth, Polymer, Serum, Massive X, ...",
        "128 VST-Plugins gefunden (keine neuen). Bekannte Plugins in der KB: Bitwig Natives (FM-4, Phase-4, Polysynth), Serum, Massive X und viele mehr."
    ))

    return pairs


# ── export_mlx_training_data ──────────────────────────────────────────────────

def _export_mlx_training_data_pairs() -> list[dict]:
    pairs = []

    m, tc = _tc_msg("export_mlx_training_data", {"output_path": "./training_data", "min_score": 0.70, "limit": 500})
    pairs.append(_pair(
        "Exportiere Trainingsdaten für MLX LoRA Fine-Tuning",
        (m, tc),
        "[MLX Export] ✓ 380 Train + 55 Valid Beispiele\nNeo4j Patterns: 280 | Theory: 100\nAusgabe: /Users/sija/bitwig-ai-agent/training_data/\n\nNächste Schritte:\n  make mlx-setup\n  make mlx-sync-data\n  make mlx-train",
        "Export abgeschlossen: 380 Training + 55 Validierungs-Beispiele. Nächste Schritte:\n1. `make mlx-setup` — MLX installieren\n2. `make mlx-sync-data` — Daten auf Mac übertragen\n3. `make mlx-train` — LoRA Fine-Tuning starten"
    ))

    m, tc = _tc_msg("export_mlx_training_data", {"output_path": "./training_data", "min_score": 0.80, "limit": 200})
    pairs.append(_pair(
        "Exportiere nur hochwertige Patterns (Score >= 0.8) für das Training",
        (m, tc),
        "[MLX Export] ✓ 145 Train + 20 Valid Beispiele (min_score=0.80)\nGefiltert: 87 Patterns unter 0.80 ausgeschlossen\nAusgabe: ./training_data/",
        "Hochwertiger Export: 145 Train + 20 Valid (min_score=0.80). 87 Patterns mit Score < 0.80 wurden ausgeschlossen — kompaktes, qualitativ hochwertiges Dataset."
    ))

    m, tc = _tc_msg("export_mlx_training_data", {"output_path": "./training_data", "min_score": 0.70, "limit": 1000})
    pairs.append(_pair(
        "Bereite das Training-Dataset vor — ich will so viele Beispiele wie möglich",
        (m, tc),
        "[MLX Export] ✓ 612 Train + 88 Valid Beispiele\nNeo4j Patterns: 500 | Theory: 112 | Limit erreicht\nAusgabe: ./training_data/",
        "Maximaler Export: 612 Training + 88 Validierungsbeispiele (Limit 1000 erreicht). Dataset bereit für `make mlx-train`."
    ))

    return pairs


# ── suggest_notes ─────────────────────────────────────────────────────────────

def _suggest_notes_pairs() -> list[dict]:
    pairs = []

    m, tc = _tc_msg("suggest_notes", {"notes": [48, 52, 55], "r": 0, "g": 50, "b": 63})
    pairs.append(_pair(
        "Hebe einen C-Dur-Dreiklang (C3-E3-G3) auf dem Launchpad hervor",
        (m, tc),
        "[suggest_notes] 3 Noten hervorgehoben (Pads: [11, 14, 22, 24, ...])",
        "C-Dur-Dreiklang (C3, E3, G3) leuchtet jetzt auf dem Launchpad in Cyan."
    ))

    m, tc = _tc_msg("suggest_notes", {"notes": [57, 60, 64, 67], "r": 63, "g": 20, "b": 0})
    pairs.append(_pair(
        "Zeige mir die Noten von A-Moll-7 (A3-C4-E4-G4) auf dem Launchpad in Orange",
        (m, tc),
        "[suggest_notes] 4 Noten hervorgehoben (Pads: 12 Pads leuchten)",
        "Am7-Akkord (A3, C4, E4, G4) leuchtet in Orange auf dem Launchpad."
    ))

    m, tc = _tc_msg("suggest_notes", {"notes": [36, 38, 42, 46, 49], "r": 63, "g": 0, "b": 0})
    pairs.append(_pair(
        "Markiere die Standard-Drum-Noten (Kick, Snare, HH, Crash) in Rot auf dem Launchpad",
        (m, tc),
        "[suggest_notes] 5 Noten hervorgehoben (MIDI 36, 38, 42, 46, 49)",
        "Drum-Noten markiert in Rot: Kick (36), Snare (38), Closed HH (42), Open HH (46), Crash (49)."
    ))

    m, tc = _tc_msg("suggest_notes", {"notes": [60, 62, 64, 65, 67, 69, 71, 72], "r": 0, "g": 63, "b": 0})
    pairs.append(_pair(
        "Zeige alle Noten der C-Dur-Tonleiter auf dem Launchpad in Grün",
        (m, tc),
        "[suggest_notes] 8 Noten hervorgehoben (C-Dur Tonleiter, 8 Pads)",
        "C-Dur-Tonleiter (C4–D4–E4–F4–G4–A4–B4–C5) leuchtet in Grün auf dem Launchpad."
    ))

    return pairs


# ── Launchpad-Tools ───────────────────────────────────────────────────────────

def _launchpad_misc_pairs() -> list[dict]:
    pairs = []

    # get_launchpad_mode
    m, tc = _tc_msg("get_launchpad_mode", {})
    pairs.append(_pair(
        "In welchem Modus ist das Launchpad gerade?",
        (m, tc), "[get_launchpad_mode] Aktueller Modus: DRUM",
        "Das Launchpad ist im **DRUM**-Modus."
    ))

    m, tc = _tc_msg("get_launchpad_mode", {})
    pairs.append(_pair(
        "Prüfe den Launchpad-Modus bevor ich Noten vorspielen kann",
        (m, tc), "[get_launchpad_mode] Aktueller Modus: INSTRUMENT",
        "Launchpad ist im **INSTRUMENT**-Modus — ideal für `play_notes` und `suggest_notes`."
    ))

    m, tc = _tc_msg("get_launchpad_mode", {})
    pairs.append(_pair(
        "Ist das Launchpad im richtigen Modus für Drum-Eingabe?",
        (m, tc), "[get_launchpad_mode] Aktueller Modus: CONTROL",
        "Das Launchpad ist im **CONTROL**-Modus — für Drum-Eingabe bitte in den DRUM-Modus wechseln."
    ))

    # listen_played_notes
    m, tc = _tc_msg("listen_played_notes", {"duration": 4.0})
    pairs.append(_pair(
        "Zeichne 4 Sekunden lang die gespielten Noten auf dem Launchpad auf",
        (m, tc),
        "[listen_played_notes] 6 Noten gespielt:\n  MIDI 36 — Kick (vel=127)\n  MIDI 38 — Snare (vel=100)\n  MIDI 42 — HH closed (vel=80)\n  MIDI 36 — Kick (vel=120)\n  MIDI 38 — Snare (vel=95)\n  MIDI 46 — HH open (vel=75)",
        "In 4 Sekunden gespielt: Kick (36) zweimal, Snare (38) zweimal, Closed HH (42), Open HH (46). Soll ich daraus ein Pattern schreiben?"
    ))

    m, tc = _tc_msg("listen_played_notes", {"duration": 3.0})
    pairs.append(_pair(
        "Hör kurz zu was ich auf dem Launchpad spiele",
        (m, tc),
        "[listen_played_notes] 4 Noten gespielt:\n  MIDI 60 — C4 (vel=100)\n  MIDI 64 — E4 (vel=95)\n  MIDI 67 — G4 (vel=90)\n  MIDI 72 — C5 (vel=85)",
        "Du hast gespielt: C4→E4→G4→C5 — das ist ein C-Dur-Arpeggio. Soll ich das als Pattern schreiben?"
    ))

    # play_notes
    m, tc = _tc_msg("play_notes", {
        "notes": [{"note": 60, "vel": 100, "dur": 0.5}, {"note": 64, "vel": 95, "dur": 0.5}, {"note": 67, "vel": 90, "dur": 0.5}],
        "bpm": 120.0
    })
    pairs.append(_pair(
        "Spiel mir einen C-Dur-Dreiklang (C4-E4-G4) vor",
        (m, tc), "[play_notes] 3 Noten gespielt: C4, E4, G4",
        "C-Dur-Dreiklang gespielt: C4 → E4 → G4 bei 120 BPM."
    ))

    m, tc = _tc_msg("play_notes", {
        "notes": [{"note": 36, "vel": 127, "dur": 0.25}, {"note": 42, "vel": 80, "dur": 0.125}, {"note": 38, "vel": 100, "dur": 0.25}],
        "bpm": 130.0
    })
    pairs.append(_pair(
        "Spiele ein kurzes Drum-Pattern vor: Kick, HH, Snare bei 130 BPM",
        (m, tc), "[play_notes] 3 Noten gespielt: Kick (36), HH (42), Snare (38)",
        "Drum-Preview gespielt: Kick→HH→Snare bei 130 BPM."
    ))

    # arm_track
    m, tc = _tc_msg("arm_track", {"arm": 1})
    pairs.append(_pair(
        "Bereite Track 1 für die Aufnahme vor",
        (m, tc), "[arm_track] Track gearmt.",
        "Track 1 ist jetzt für die Aufnahme scharf gestellt. Starte die Wiedergabe mit `control_bitwig(action='record')`."
    ))

    m, tc = _tc_msg("arm_track", {"arm": 0})
    pairs.append(_pair(
        "Heb die Aufnahmebereitschaft auf",
        (m, tc), "[arm_track] Track disarmt.",
        "Aufnahmebereitschaft aufgehoben."
    ))

    return pairs


# ── Alle Pairs zusammenfassen ─────────────────────────────────────────────────

def build_pairs() -> list[dict]:
    pairs = []
    pairs += _control_bitwig_pairs()
    pairs += _get_bitwig_track_state_pairs()
    pairs += _get_song_context_pairs()
    pairs += _get_artist_context_pairs()
    pairs += _analyze_song_pairs()
    pairs += _validate_music_pairs()
    pairs += _compose_notes_pairs()
    pairs += _write_pattern_raw_pairs()
    pairs += _search_artist_song_pairs()
    pairs += _learn_song_from_youtube_pairs()
    pairs += _validate_and_learn_pairs()
    pairs += _scan_and_learn_project_pairs()
    pairs += _scan_vst_plugins_pairs()
    pairs += _export_mlx_training_data_pairs()
    pairs += _suggest_notes_pairs()
    pairs += _launchpad_misc_pairs()
    return pairs


def _validate_pair(pair: dict) -> None:
    msgs = pair["messages"]
    assert len(msgs) >= 3, "mindestens 3 Messages"
    roles = [m["role"] for m in msgs]
    assert roles[0] == "system", "erste Message muss system sein"
    assert roles[1] == "user", "zweite Message muss user sein"
    assert roles[-1] == "assistant", "letzte Message muss assistant sein"
    # Keine leere finale Antwort
    assert msgs[-1].get("content", "").strip(), "finale Assistent-Antwort darf nicht leer sein"


def _existing_user_messages() -> set[str]:
    seen: set[str] = set()
    if not TRAIN_FILE.exists():
        return seen
    with TRAIN_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            for m in d.get("messages", []):
                if m.get("role") == "user":
                    seen.add(m["content"])
    return seen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="nur validieren, nicht schreiben")
    ap.add_argument("--print", type=int, default=0, metavar="N", help="erste N Pairs zeigen")
    args = ap.parse_args()

    pairs = build_pairs()
    for p in pairs:
        _validate_pair(p)
    print(f"✓ {len(pairs)} Pairs gebaut & validiert.")

    # Statistik pro Tool
    from collections import Counter
    tool_stats: Counter = Counter()
    for p in pairs:
        for m in p["messages"]:
            for tc in m.get("tool_calls", []):
                name = tc.get("function", {}).get("name", "")
                if name:
                    tool_stats[name] += 1
    print("\nTool-Verteilung:")
    for tool, count in sorted(tool_stats.items()):
        print(f"  {count:3d}x  {tool}")

    if args.print:
        for p in pairs[: args.print]:
            print("-" * 70)
            for m in p["messages"]:
                role = m["role"].upper()
                content = m.get("content", "")
                tcs = m.get("tool_calls", [])
                if tcs:
                    print(f"[{role}] tool_calls: {[tc['function']['name'] for tc in tcs]}")
                elif content:
                    print(f"[{role}] {content[:200]}")

    existing = _existing_user_messages()
    new_pairs = [p for p in pairs if p["messages"][1]["content"] not in existing]
    dupes = len(pairs) - len(new_pairs)

    if args.dry_run:
        print(f"\n[dry-run] {len(new_pairs)} neu, {dupes} bereits vorhanden — nichts geschrieben.")
        return

    if not new_pairs:
        print(f"\nNichts anzuhängen — alle {len(pairs)} Pairs bereits in {TRAIN_FILE.name}.")
        return

    with TRAIN_FILE.open("a") as f:
        for p in new_pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"\n✓ {len(new_pairs)} neue Pairs an {TRAIN_FILE} angehängt ({dupes} Duplikate übersprungen).")


if __name__ == "__main__":
    main()

"""
Song-Erstellungs-Tools für den LangGraph-Agenten.

Ersetzt die Audio-Extraktions-Pipeline vollständig durch KB-gestützte
LLM-Komposition direkt in Bitwig via OSC.
"""

from __future__ import annotations
import os
import time
from langchain_core.tools import tool


OSC_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_PORT = int(os.getenv("BITWIG_PORT", "8001"))
OSC_REPLY_PORT = int(os.getenv("BITWIG_REPLY_PORT", "9001"))


def _osc_client():
    from pythonosc import udp_client
    return udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)


def _bound_osc_client(timeout: float | None = None):
    from pythonosc import udp_client

    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT, allow_broadcast=False)
    sock = client._sock
    if timeout is not None:
        sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_REPLY_PORT))
    except OSError:
        pass
    return client


def _get_current_track_count() -> int:
    """Holt aktuelle Track-Anzahl via OSC. Gibt 0 zurück wenn nicht erreichbar."""
    import socket, struct
    client = _bound_osc_client(timeout=1.5)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(512)
        raw = data.decode("latin-1")
        tag_idx = raw.find(",i")
        if tag_idx >= 0:
            padded = (tag_idx + 4) & ~3
            if padded + 4 <= len(data):
                count = struct.unpack(">i", data[padded:padded + 4])[0]
                if 0 <= count <= 64:
                    return count
    except (socket.timeout, OSError):
        pass
    finally:
        try:
            client._sock.close()
        except Exception:
            pass
    return 0


def _check_bridge(timeout: float = 1.5) -> bool:
    """Ping/Pong Verbindungstest. Meldet Fehler an Circuit Breaker."""
    import socket
    from src.agent.osc.circuit_breaker import get_circuit

    circuit = get_circuit()
    client = _bound_osc_client(timeout=timeout)
    sock = client._sock
    try:
        client.send_message("/ping", 1)
        sock.recvfrom(64)
        circuit._on_success()
        return True
    except (socket.timeout, OSError):
        circuit._on_failure()
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


@tool
def check_bitwig_connection() -> dict:
    """Prüft ob die BitwigAgentBridge erreichbar ist.

    Muss vor allen Song-Operationen aufgerufen werden.
    Returns: {"connected": bool, "message": str}
    """
    ok = _check_bridge()
    return {
        "connected": ok,
        "message": (
            "BitwigAgentBridge erreichbar ✓" if ok else
            "Bridge nicht erreichbar — Bitwig starten + Extension aktivieren"
        ),
    }


@tool
def get_bitwig_track_state() -> str:
    """Liest den aktuellen Bitwig-UI-Zustand via Screenshot aus.

    Macht einen Screenshot des Bildschirms, analysiert welche Tracks
    sichtbar sind, wie viele es gibt und was geladen ist.
    Gibt start_track_index für den nächsten create_song_from_genre Aufruf zurück.

    Funktioniert NUR auf Windows mit Bitwig im Vordergrund.
    """
    import subprocess, struct, os
    from pathlib import Path

    ok = _check_bridge(timeout=1.0)
    if not ok:
        return "Bridge nicht erreichbar. Bitwig starten und Extension aktivieren."

    # ── Strategie 1: OSC-Rückkanal für Track-Count ───────────────────────────
    result_holder = {}
    client = _bound_osc_client(timeout=2.0)
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(4096)
        raw = data.decode("latin-1")
        idx = raw.find(",i")
        if idx > 0:
            count_bytes = data[idx + 4 : idx + 8]
            if len(count_bytes) == 4:
                result_holder["count"] = struct.unpack(">i", count_bytes)[0]
        idx_s = raw.find(",is")
        if idx_s > 0:
            after = data[idx_s + 4:]
            name_start = after.find(b"\x00\x00") + 2
            names_raw = after[name_start:]
            end = names_raw.find(b"\x00")
            if end > 0:
                result_holder["names"] = names_raw[:end].decode("utf-8", errors="ignore")
    except OSError:
        pass
    finally:
        try:
            client._sock.close()
        except Exception:
            pass

    if "count" in result_holder:
        count = result_holder["count"]
        names = result_holder.get("names", "")
        next_idx = count + 1
        track_list = names.split(",") if names else []
        return (
            f"Bitwig Track-Zustand:\n"
            f"  Vorhandene Tracks: {count}\n"
            f"  Track-Namen: {', '.join(track_list) if track_list else '(keine)'}\n"
            f"  start_track_index für nächsten Song: {next_idx}\n"
            f"  {'Leeres Projekt → start_track_index=1 verwenden' if count == 0 else f'{count} Tracks vorhanden → start_track_index={next_idx}'}"
        )

    # ── Strategie 2: Screenshot als Fallback ──────────────────────────────────
    tmp_win = r"C:\Users\Admin\AppData\Local\Temp\bitwig_state.png"
    tmp_wsl = "/mnt/c/Users/Admin/AppData/Local/Temp/bitwig_state.png"
    try:
        subprocess.run(["powershell.exe", "-Command",
            f"Add-Type -AssemblyName System.Windows.Forms;"
            f"$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            f"$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
            f"$g=[System.Drawing.Graphics]::FromImage($b);"
            f"$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
            f"$b.Save('{tmp_win}');"],
            capture_output=True, timeout=8)
        if Path(tmp_wsl).exists():
            size_kb = Path(tmp_wsl).stat().st_size // 1024
            return (
                f"OSC-Rückkanal nicht erreichbar (Extension zu alt?).\n"
                f"Screenshot erstellt: {tmp_wsl} ({size_kb}KB)\n"
                f"Annahme: Projekt ist leer → start_track_index=1\n"
                f"Tipp: Extension neu laden für OSC-Track-Count."
            )
    except Exception:
        pass

    return "Track-Zustand unbekannt — Annahme: leeres Projekt, start_track_index=1"


@tool
def create_song_from_genre(
    genre: str,
    bpm: float = 0.0,
    section: str = "verse_1",
    start_track_index: int = 1,
    num_tracks: int = 6,  # INTERN — nicht vom Agent setzen, immer 6
) -> dict:
    """Erstellt einen vollständigen Song in Bitwig.

    FÜR ROCK/METAL/HARD ROCK: Leitet automatisch an create_song_with_sections weiter!
    → Mehrere Scenes (Intro/Verse/Chorus/Solo/Outro)
    → Echte Gitarren-Loops (2 Rhythmus + 1 Lead)
    → Kein Synth für Gitarre
    → Keine Pausen (beat-genaue Loop-Länge)

    FÜR POP/JAZZ: 6 Tracks mit Synths (Polysynth/Phase-4/FM-4).

    Args:
        genre:             "pop", "rock", "metal", "jazz", "hard rock", "metal" ...
        bpm:               0 = aus Genre-KB automatisch
        section:           ignoriert für Rock/Metal (alle Sections werden erstellt)
        start_track_index: aus get_bitwig_track_state() holen
    """
    import os, sys
    sys.path.insert(0, str(__file__).split("/src/")[0])

    # Rock/Metal/Blues → echte Gitarren-Loops via create_song_with_sections
    _GUITAR_GENRES = {"rock", "metal", "hard rock", "heavy metal", "blues", "grunge",
                      "punk rock", "classic rock", "indie rock", "progressive rock"}
    _g = genre.lower().strip()
    if _g in _GUITAR_GENRES or any(kw in _g for kw in ("rock", "metal", "blues")):
        return create_song_with_sections.invoke({
            "genre": genre,
            "start_track_index": start_track_index,
        })

    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    from src.audio.chord_to_bitwig import query_chordonomicon, progression_to_pattern
    from pythonosc import udp_client

    # Immer 6 Tracks — ignoriere num_tracks vom Agent
    num_tracks = 6

    # Genre-Fallback-Mapping für Chordonomicon
    GENRE_MAP = {
        "hard rock": "rock", "hardrock": "rock", "heavy metal": "metal",
        "heavymetal": "metal", "progressive rock": "rock", "indie rock": "rock",
        "classic rock": "rock", "punk rock": "rock", "grunge": "rock",
        "jazz rock": "rock", "jazz fusion": "jazz", "bossa nova": "jazz",
        "electro pop": "pop", "synth pop": "pop", "dance pop": "pop",
        "hip hop": "hip-hop", "r&b": "hip-hop", "edm": "house",
    }
    genre_query = GENRE_MAP.get(genre.lower().strip(), genre)

    # ── 1. Verbindung ────────────────────────────────────────────────────────
    if not _check_bridge():
        return {"error": "BitwigAgentBridge nicht erreichbar — Bitwig starten"}

    # ── 2. BPM aus KB ────────────────────────────────────────────────────────
    from src.knowledge.neo4j_graph import get_driver as _neo4j_driver
    try:
        _driver = _neo4j_driver()
    except ConnectionError as e:
        return {"error": str(e)}

    if bpm <= 0:
        with _driver.session() as s:
            row = s.run(
                "MATCH (g:Genre) WHERE toLower(g.name) CONTAINS $g "
                "RETURN g.bpm_min AS mn, g.bpm_max AS mx LIMIT 1",
                g=genre.lower(),
            ).single()
        bpm = (row["mn"] + row["mx"]) / 2 if row else 120.0

    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message("/transport/tempo", float(bpm))
    time.sleep(0.1)

    # ── 3. Akkordprogression ─────────────────────────────────────────────────
    results = query_chordonomicon(genre=genre_query, n=1)
    if not results and genre_query != genre:
        results = query_chordonomicon(genre=genre_query.split()[0], n=1)  # Kurzform versuchen
    if not results:
        return {"error": f"Keine Akkordprogression für Genre '{genre}' in der KB gefunden. "
                         f"KB befüllen: `make ingest`"}

    parsed   = results[0]
    sections = parsed["sections"]
    chords   = sections.get(section) or next(iter(sections.values()), [])
    chords   = chords[:8]

    if not chords:
        return {"error": f"Keine Akkorde gefunden (Sektionen: {list(sections.keys())})"}

    # ── 4. Tracks anlegen ────────────────────────────────────────────────────────
    # Instrument-Layout aus Registry (Genre-Overrides werden automatisch berücksichtigt)
    from src.audio.instrument_registry import build_track_layout
    from src.agent.events import get_event_bus

    bus = get_event_bus()
    layout = build_track_layout(genre=genre)
    instruments = [(t["device_name"], t["role"]) for t in layout]
    track_indices = list(range(start_track_index, start_track_index + len(instruments)))

    for _ in instruments:
        client.send_message("/track/add/instrument", 1)
        time.sleep(0.3)

    # ── 5. Instrumente via UUID laden (sofort, kein Browser) ─────────────────
    for idx, (instr, _) in zip(track_indices, instruments):
        client.send_message(f"/track/{idx}/select", 1)
        time.sleep(0.2)
        client.send_message("/browser/device/load", instr)
        time.sleep(0.5)  # UUID → sofort geladen

    # ── 6. Pattern-Hilfsfunktion ─────────────────────────────────────────────
    step_size = 0.25
    pat    = progression_to_pattern(chords, beats_per_chord=2.0)
    length = pat["length_beats"]

    def write_pattern(track_idx, notes, slot=0):
        client.send_message(f"/track/{track_idx}/select", 1); time.sleep(0.5)
        client.send_message("/clip/create", [float(slot), float(length)]); time.sleep(0.6)
        client.send_message("/clip/step_size", step_size); time.sleep(0.05)
        for n in notes:
            step_idx = int(round(float(n["step"]) / step_size))
            client.send_message("/clip/note",
                [float(n["step"]), float(n["pitch"]), float(n["vel"]), float(n["dur"])])
            time.sleep(0.02)

    # ── 7. Drum-Patterns (separate Tracks, je eigene Tonhöhe) ────────────────
    from src.audio.instrument_registry import get_instrument

    kick_idx, snare_idx, hihat_idx = track_indices[0], track_indices[1], track_indices[2]
    kick_pitch  = get_instrument("kick",  genre=genre)["midi_low"]
    snare_pitch = get_instrument("snare", genre=genre)["midi_low"]
    hihat_pitch = get_instrument("hihat", genre=genre)["midi_low"]
    kick_vel    = get_instrument("kick",  genre=genre)["default_velocity"]
    snare_vel   = get_instrument("snare", genre=genre)["default_velocity"]
    hihat_vel   = get_instrument("hihat", genre=genre)["default_velocity"]

    kick_notes = [{"step": b, "pitch": kick_pitch,  "vel": kick_vel,  "dur": 0.25}
                  for b in [0, 2, 4, 6]]
    write_pattern(kick_idx, kick_notes)
    bus.emit("track_done", {"role": "kick", "notes": len(kick_notes)})

    snare_notes = [{"step": b, "pitch": snare_pitch, "vel": snare_vel, "dur": 0.25}
                   for b in [1, 3, 5, 7]]
    write_pattern(snare_idx, snare_notes)
    bus.emit("track_done", {"role": "snare", "notes": len(snare_notes)})

    hihat_notes = [{"step": b * 0.25, "pitch": hihat_pitch,
                    "vel": hihat_vel if b % 2 == 0 else hihat_vel * 0.75, "dur": 0.1}
                   for b in range(32)]
    write_pattern(hihat_idx, hihat_notes)
    bus.emit("track_done", {"role": "hihat", "notes": len(hihat_notes)})

    # ── 8. Bass + Chords ─────────────────────────────────────────────────────
    write_pattern(track_indices[3], pat["bass"])
    bus.emit("track_done", {"role": "bass", "notes": len(pat["bass"])})
    write_pattern(track_indices[4], pat["chords"])
    bus.emit("track_done", {"role": "chords", "notes": len(pat["chords"])})

    # ── 9. Lead-Melodie automatisch generieren (FM-4, Track 6) ──────────────
    if len(track_indices) >= 6:
        from src.audio.chord_to_bitwig import generate_melody
        melody_notes = generate_melody(chords, length_beats=length, seed=42, genre=genre)
        if melody_notes:
            write_pattern(track_indices[5], melody_notes)
            bus.emit("track_done", {"role": "lead", "notes": len(melody_notes)})

    chord_str = " → ".join(chords)
    names = [i[0] for i in instruments]
    bus.emit("song_done", {"genre": genre, "bpm": bpm, "track_count": len(instruments)})
    # Explizit "FERTIG" + Tracks — verhindert Doppelaufruf und setup_instrument_track danach
    return {
        "status": "SONG FERTIG ERSTELLT. KEINE weiteren create_song/setup_instrument Aufrufe nötig.",
        "genre": genre,
        "bpm": bpm,
        "progression": chord_str,
        "tracks": " | ".join(f"Track {i}: {n}" for i, n in zip(track_indices, names))
    }


@tool
def setup_instrument_track(track_index: int, instrument_name: str) -> dict:
    """Erstellt einen Instrument-Track und lädt ein Instrument per Browser.

    Für spezifische Songs (z.B. Kinderlieder) wo create_song_from_genre
    nicht passt. Immer zuerst check_bitwig_connection() aufrufen.

    Args:
        track_index:     Track-Nummer (1-basiert, muss nach vorhandenen Tracks kommen)
        instrument_name: Bitwig-Device-Name z.B. "Polysynth", "FM-4", "Phase-4",
                         "Organ", "v9 Kick", "v9 Snare", "v9 Hat Closed",
                         "Reverb", "Compressor", "EQ-5", "Saturator"
    """
    if not _check_bridge():
        return {"error": "BitwigAgentBridge nicht erreichbar"}
    client = _osc_client()
    client.send_message("/track/add/instrument", 1)
    time.sleep(0.3)
    client.send_message(f"/track/{track_index}/select", 1)
    time.sleep(0.2)
    # UUID-basiertes Laden — sofort für alle 146 Bitwig Built-in Devices
    client.send_message("/browser/device/load", instrument_name)
    time.sleep(1.5)  # Browser-Fallback: 3 flush-Zyklen (à ~150ms) + Navigation + Commit
    return {"status": "OK", "instrument": instrument_name, "track": track_index}


@tool
def write_notes_to_clip(
    track_index: int,
    notes_json: str,
    length_beats: float = 16.0,
    slot: int = 0,
    tempo_bpm: float = 0.0,
) -> dict:
    """Schreibt beliebige MIDI-Noten in einen Bitwig-Clip.

    Für spezifische Melodien (Kinderlieder, klassische Stücke, eigene Kompositionen).
    Der Agent kann damit jede Melodie in Noten übersetzen und in Bitwig schreiben.

    notes_json Format (Beats als Zeiteinheit, 1 Beat = 1 Viertelnote):
        [
          {"step": 0,   "pitch": 60, "vel": 0.8, "dur": 1.0},
          {"step": 1,   "pitch": 62, "vel": 0.8, "dur": 1.0},
          ...
        ]

    MIDI-Referenz (C-Dur-Tonleiter):
        C4=60  D4=62  E4=64  F4=65  G4=67  A4=69  B4=71  C5=72
        C3=48  D3=50  E3=52  F3=53  G3=55  A3=57  B3=59

    Drum-Noten (für Drum Machine):
        Kick=36  Snare=38  HiHat=42  OpenHat=46  Clap=39  Crash=49

    Args:
        track_index:   Track-Nummer (1-basiert)
        notes_json:    JSON-Array mit Noten (step in Beats, pitch MIDI 0-127,
                       vel 0.0-1.0, dur in Beats)
        length_beats:  Clip-Länge in Beats (4=1 Takt, 8=2 Takte, 16=4 Takte)
        slot:          Clip-Slot (0=Scene 1, 1=Scene 2 ...)
        tempo_bpm:     Tempo setzen (0=nicht ändern)
    """
    import json

    # ── MIDI-Hilfsfunktionen ──────────────────────────────────────────────────
    NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

    def midi_to_name(midi: int) -> str:
        """Konvertiert MIDI-Pitch zu Notenname (C4=60, A4=69)."""
        octave = (midi // 12) - 1
        name   = NOTE_NAMES[midi % 12]
        return f"{name}{octave}"

    def validate_pitch(pitch: int, claimed_name: str | None = None) -> str | None:
        """Prüft ob pitch im gültigen Bereich ist und gibt Korrektur zurück."""
        if not (0 <= pitch <= 127):
            return f"MIDI {pitch} außerhalb 0-127"
        actual = midi_to_name(pitch)
        if claimed_name and claimed_name.replace("b","#") != actual:
            # Grobe Plausibilitätsprüfung auf Oktave
            pass
        return None

    if not _check_bridge():
        return {"error": "BitwigAgentBridge nicht erreichbar"}

    # ── JSON-Repair ───────────────────────────────────────────────────────────
    try:
        notes = json.loads(notes_json)
    except json.JSONDecodeError:
        try:
            trimmed = notes_json[:notes_json.rfind("}") + 1] + "]"
            notes = json.loads(trimmed)
            if not notes:
                return {"error": "notes_json ist leer oder ungültig"}
        except Exception as e:
            return {"error": f"Ungültiges JSON — {e}. Kürzere Note-Liste verwenden."}

    # ── MIDI-Validierung ──────────────────────────────────────────────────────
    errors   = []
    warnings = []
    valid_notes = []

    for i, n in enumerate(notes):
        pitch = int(n.get("pitch", -1))
        step  = float(n.get("step", 0))
        dur   = float(n.get("dur", 1.0))
        vel   = float(n.get("vel", 0.8))

        if not (0 <= pitch <= 127):
            errors.append(f"Note {i}: pitch={pitch} ungültig (0-127)")
            continue
        if not (0.0 < vel <= 1.0):
            warnings.append(f"Note {i}: vel={vel} außerhalb 0-1, wird geclippt")
            vel = max(0.01, min(1.0, vel))
        if dur <= 0:
            warnings.append(f"Note {i}: dur={dur} ≤ 0, übersprungen")
            continue
        if step < 0 or step >= length_beats:
            warnings.append(f"Note {i}: step={step} außerhalb Clip ({length_beats} Beats), übersprungen")
            continue

        valid_notes.append({**n, "pitch": pitch, "vel": vel, "dur": dur})

    if errors:
        return {"error": "Fehler in notes_json:\n" + "\n".join(errors) + \
               f"\n\nMIDI-Referenz: C4=60 D4=62 E4=64 F4=65 G4=67 A4=69 B4=71 C5=72\n" + \
               f"Halbtonschritte: C=0 C#=1 D=2 D#=3 E=4 F=5 F#=6 G=7 G#=8 A=9 A#=10 B=11"}

    # ── In Bitwig schreiben ───────────────────────────────────────────────────
    client = _osc_client()
    step_size = 0.25

    if tempo_bpm > 0:
        client.send_message("/transport/tempo", float(tempo_bpm))
        time.sleep(0.1)

    client.send_message(f"/track/{track_index}/select", 1); time.sleep(0.15)
    client.send_message("/clip/create", [float(slot), float(length_beats)]); time.sleep(0.4)
    client.send_message("/clip/step_size", step_size); time.sleep(0.05)

    note_log = []
    for n in valid_notes:
        pitch    = int(n["pitch"])
        step_idx = int(round(float(n["step"]) / step_size))
        client.send_message("/clip/note/beat", [
            float(n["step"]),
            float(pitch),   # Float — nicht Int, sonst argFloat→default 60
            float(n["vel"]),
            float(n["dur"]),
        ])
        note_log.append(f"{midi_to_name(pitch)}({pitch})@{n['step']}")
        time.sleep(0.02)

    # ── Validierungs-Report ───────────────────────────────────────────────────
    result = f"OK: {len(valid_notes)} Noten auf Track {track_index}\n"
    result += f"Noten: {' | '.join(note_log)}\n"
    if warnings:
        result += f"Warnungen: {'; '.join(warnings)}\n"
    if len(valid_notes) < len(notes):
        result += f"Übersprungen: {len(notes)-len(valid_notes)} ungültige Noten"
    return {"ok": True, "message": result}


@tool
def verify_song(
    play_seconds: float = 5.0,
    slot: int = 0,
    expected_tracks: int = 1,
) -> dict:
    """Spielt den erstellten Song ab und überprüft das Ergebnis.

    Workflow:
      1. Projekt-Status via OSC abfragen (Tracks, Tempo, Device)
      2. Scene/Clip starten
      3. Screenshot für visuelle Verifikation
      4. Nach play_seconds stoppen
      5. Verifikations-Bericht zurückgeben

    Immer nach create_song_from_genre aufrufen um zu prüfen ob alles korrekt ist.

    Args:
        play_seconds: Wiedergabedauer für Test (Standard: 5s)
        expected_tracks: Mindestanzahl erwarteter Tracks (Standard: 1)
        slot:         Clip-Slot der abgespielt werden soll (0=Scene 1)
    """
    import subprocess, struct
    from pathlib import Path

    if not _check_bridge():
        return {
            "ok": False,
            "error": "BitwigAgentBridge nicht erreichbar — Bitwig starten",
            "track_count": None,
            "warnings": ["Bridge nicht erreichbar"],
            "report_text": "Fehler: BitwigAgentBridge nicht erreichbar",
        }

    client = _bound_osc_client(timeout=2.5)

    # ── 1. Status via OSC abfragen ────────────────────────────────────────────
    status = {}
    try:
        client.send_message("/agent/track/count", 1)
        data, _ = client._sock.recvfrom(4096)
        raw = data.decode("latin-1")
        tag_idx = raw.find(",i")
        if tag_idx >= 0:
            padded = (tag_idx + 4) & ~3
            if padded + 4 <= len(data):
                count = struct.unpack(">i", data[padded:padded+4])[0]
                if 0 <= count <= 64:
                    status["track_count"] = count
        str_parts = [p.strip() for p in raw.split("\x00") if len(p.strip()) > 2 and "=" in p]
        if str_parts:
            status["tracks"] = str_parts[0]
    except OSError:
        pass

    # ── 2. Scene abspielen ────────────────────────────────────────────────────
    client.send_message(f"/scene/{slot + 1}/launch", 1)
    client.send_message("/transport/play", 1)
    time.sleep(0.5)

    # ── 3. Screenshot (Bitwig in Vordergrund) ─────────────────────────────────
    screenshot_path = "/mnt/c/Users/Admin/AppData/Local/Temp/bitwig_verify.png"
    screenshot_ok = False
    try:
        # Bitwig-Fenster in den Vordergrund bringen
        subprocess.run(["powershell.exe", "-Command",
            "Add-Type -TypeDefinition '"
            "using System;using System.Runtime.InteropServices;"
            "public class Win32{[DllImport(\"user32.dll\")]"
            "public static extern bool SetForegroundWindow(IntPtr h);"
            "[DllImport(\"user32.dll\")]"
            "public static extern IntPtr FindWindow(string c,string t);}' ;"
            "$h=[Win32]::FindWindow($null,'Bitwig Studio');"
            "if($h -ne 0){[Win32]::SetForegroundWindow($h)};"
            "Start-Sleep -Milliseconds 500;"],
            capture_output=True, timeout=5)
        subprocess.run(["powershell.exe", "-Command",
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
            "$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);"
            "$g=[System.Drawing.Graphics]::FromImage($b);"
            "$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);"
            "$b.Save('C:\\Users\\Admin\\AppData\\Local\\Temp\\bitwig_verify.png');"],
            capture_output=True, timeout=8)
        screenshot_ok = Path(screenshot_path).exists()
    except:
        pass

    # ── 4. Warten und stoppen ────────────────────────────────────────────────
    time.sleep(max(0, play_seconds - 0.5))
    client.send_message("/transport/play", 0)  # stop

    # ── 5. Verifikations-Bericht ──────────────────────────────────────────────
    import json as _json

    track_count = status.get("track_count")   # int oder None
    tracks_info = status.get("tracks", "nicht lesbar")
    warnings: list[str] = []

    if track_count == 0:
        warnings.append("Keine Tracks erkannt — create_song_from_genre nochmal ausführen!")
    elif isinstance(track_count, int) and track_count < expected_tracks:
        warnings.append(f"Nur {track_count} Tracks erkannt (erwartet {expected_tracks}) — möglicherweise fehlende Instruments")

    ok = isinstance(track_count, int) and track_count >= expected_tracks

    # Menschenlesbarer Text für Logs / Agent-Display (abwärtskompatibel)
    report_text = (
        f"VERIFIKATION:\n"
        f"  Tracks in Bitwig: {track_count if track_count is not None else '?'}\n"
        f"  Track-Details: {tracks_info}\n"
        f"  Wiedergabe: {play_seconds:.0f}s abgespielt ✓\n"
        f"  Screenshot: {'gespeichert (' + screenshot_path + ')' if screenshot_ok else 'nicht verfügbar'}\n"
    )
    if warnings:
        report_text += "\n" + "\n".join(f"⚠ {w}" for w in warnings)
    else:
        report_text += f"\n✓ Song korrekt erstellt mit {track_count} Tracks"

    return {
        "ok": ok,
        "track_count": track_count,
        "tracks_info": tracks_info,
        "playback_seconds": play_seconds,
        "screenshot_path": screenshot_path if screenshot_ok else None,
        "warnings": warnings,
        "report_text": report_text,
    }


@tool
def build_song(project_json: str) -> str:
    """Erstellt einen vollständigen Bitwig-Song aus einem einzigen Projekt-Objekt.

    Nutze dieses Tool statt einzelner setup_instrument_track / write_notes_to_clip
    Aufrufe — es spart Kontext-Tokens durch einen einzigen Tool-Call.

    project_json Schema:
    {
      "bpm": 120,
      "tracks": [
        {
          "index": 1,
          "instrument": "Phase-4",
          "fx": ["Distortion", "Amp"],
          "clip": {
            "slot": 0,
            "length_beats": 40,
            "notes": [
              {"step": 0, "pitch": 40, "vel": 0.8, "dur": 1.0},
              ...
            ]
          }
        }
      ]
    }

    Felder:
      bpm            — Tempo in BPM (z.B. 120)
      tracks         — Liste von Track-Objekten:
        index        — Track-Nummer 1-basiert
        instrument   — Bitwig-Device z.B. "Phase-4", "FM-4", "Polysynth"
        fx           — optionale FX-Geräte z.B. ["Distortion", "Amp", "EQ-5"]
        clip.slot    — Clip-Slot (0=Scene 1)
        clip.length_beats — Clip-Länge in Beats
        clip.notes   — MIDI-Noten: step=Beat-Position, pitch=MIDI 0-127,
                       vel=0.0-1.0, dur=Länge in Beats

    MIDI-Referenz Rock/Blues (tief):
      E2=40  G2=43  A2=45  B2=47  D3=50  E3=52

    Returns: Kompakter Status-String (Track-Count, Noten-Count, Fehler)
    """
    import json as _json
    from src.agent.osc.circuit_breaker import get_circuit, CircuitOpenError

    # ── 0. Circuit Breaker prüfen ─────────────────────────────────────────────
    circuit = get_circuit()
    if circuit.is_open():
        return "ERROR: Bitwig nicht erreichbar (Circuit offen). Bitte Verbindung prüfen."

    # ── 1. JSON parsen ────────────────────────────────────────────────────────
    try:
        project = _json.loads(project_json)
    except _json.JSONDecodeError as e:
        return f"Fehler: Ungültiges project_json — {e}"

    bpm    = float(project.get("bpm", 120))
    tracks = project.get("tracks", [])
    if not tracks:
        return "Fehler: project_json enthält keine 'tracks'"

    # ── 2. Bridge prüfen ──────────────────────────────────────────────────────
    if not _check_bridge():
        return "Fehler: BitwigAgentBridge nicht erreichbar — Bitwig starten"

    client = _osc_client()
    NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

    def midi_to_name(midi: int) -> str:
        return f"{NOTE_NAMES[midi % 12]}{(midi // 12) - 1}"

    results = []

    # ── 3. Tempo setzen ───────────────────────────────────────────────────────
    client.send_message("/transport/tempo", bpm)
    time.sleep(0.1)

    # ── 4. Track-Anzahl angleichen (überschüssige löschen, fehlende hinzufügen) ──
    needed_count = max(int(t.get("index", 1)) for t in tracks)
    current_count = _get_current_track_count()

    # Überschüssige Tracks von oben nach unten löschen
    while current_count > needed_count:
        client.send_message(f"/track/{current_count}/select", 1)
        time.sleep(0.2)
        client.send_message("/track/delete/last", 1)
        time.sleep(0.35)
        current_count -= 1

    # ── 5. Tracks anlegen und Noten schreiben (via Saga) ─────────────────────
    from src.agent.osc.saga import BitwigSaga, OscCommand, SagaStepError

    for track in tracks:
        idx        = int(track.get("index", 1))
        instrument = track.get("instrument", "")
        preset     = track.get("preset", "")
        fx_preset  = track.get("fx_preset", "")
        fx_list    = track.get("fx", [])
        clip       = track.get("clip", {})
        slot       = int(clip.get("slot", 0))
        length     = float(clip.get("length_beats", 16.0))
        notes      = clip.get("notes", [])

        saga = BitwigSaga(client)

        # Track hinzufügen wenn noch nicht vorhanden
        if current_count < idx:
            ok = saga.step(OscCommand(
                "/track/add/instrument", [1],
                compensate=OscCommand("/track/delete/last", [1]),
            ))
            if not ok:
                results.append(f"Track {idx}: Fehler beim Anlegen (Rollback)")
                continue
            time.sleep(0.3)
            current_count += 1

        client.send_message(f"/track/{idx}/select", 1)
        time.sleep(0.2)

        # Instrument laden
        if instrument:
            saga.step(OscCommand("/browser/device/load", [instrument]))
            time.sleep(1.5)

        # Optionaler Preset
        if preset:
            saga.step(OscCommand("/browser/preset/load", [preset]))
            time.sleep(2.5)

        # FX
        if fx_preset:
            saga.step(OscCommand("/browser/fx/load", [fx_preset]))
            time.sleep(3.0)
        elif fx_list:
            for fx in fx_list:
                saga.step(OscCommand("/browser/device/load", [fx]))
                time.sleep(1.0)

        # Clip erstellen und Noten schreiben
        if notes:
            client.send_message(f"/track/{idx}/select", 1); time.sleep(0.15)
            ok = saga.step(OscCommand(
                "/clip/create", [float(slot), float(length)],
                compensate=OscCommand("/clip/delete", [float(slot)]),
            ))
            if not ok:
                results.append(f"Track {idx}: Fehler beim Clip-Erstellen (Rollback)")
                continue
            time.sleep(0.4)
            client.send_message("/clip/step_size", 0.25); time.sleep(0.05)

            valid = 0
            for n in notes:
                pitch = int(n.get("pitch", -1))
                step  = float(n.get("step", 0))
                vel   = float(n.get("vel", 0.8))
                dur   = float(n.get("dur", 1.0))
                if not (0 <= pitch <= 127) or dur <= 0 or step < 0 or step >= length:
                    continue
                vel = max(0.01, min(1.0, vel))
                client.send_message("/clip/note/beat", [step, float(pitch), vel, dur])
                time.sleep(0.02)
                valid += 1

            saga.commit()
            results.append(f"Track {idx} ({instrument}): {valid}/{len(notes)} Noten")
        else:
            saga.commit()
            results.append(f"Track {idx} ({instrument}): kein Clip")

    summary = f"build_song OK — BPM={bpm:.0f} | " + " | ".join(results)
    return summary


@tool
def get_pattern_context(genre: str, instrument: str) -> str:
    """Holt Beschreibungen aus der KB wie ein Instrument in einem Genre typischerweise klingt.

    Der Agent soll diese Beschreibungen analysieren und daraus konkrete
    MIDI-Patterns ableiten — statt hardcodierter Regeln.

    Workflow:
        1. get_pattern_context("pop", "bass")   → KB-Beschreibung
        2. Agent analysiert: "root notes staccato eighth note patterns"
        3. Agent schreibt: write_notes_to_clip mit abgeleiteten Noten

    Args:
        genre:      Genre ("pop", "rock", "jazz" ...)
        instrument: Instrument ("bass", "drums", "chords", "melody", "groove")

    Returns:
        Beschreibungen aus MusicCaps + CoT_DAW + MusicTheoryBench
    """
    import os
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
        results = []
        with driver.session() as s:
            # MusicCaps: echte Musik-Beschreibungen mit konkreten Klang-Details
            rows = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source = 'MusicCaps'
                  AND toLower(k.text) CONTAINS $genre
                  AND (toLower(k.text) CONTAINS $instr
                       OR toLower(k.text) CONTAINS 'rhythm'
                       OR toLower(k.text) CONTAINS 'beat'
                       OR toLower(k.text) CONTAINS 'groove')
                RETURN k.text AS t
                LIMIT 3
            """, genre=genre.lower(), instr=instrument.lower()).data()

            for r in rows:
                text = r["t"]
                # Nur Musik-Beschreibungszeile extrahieren
                if "Music Description:" in text:
                    desc = text.split("Music Description:")[-1].split("\n")[0].strip()
                    if len(desc) > 20:
                        results.append(f"[MusicCaps] {desc[:300]}")

            # CoT_DAW: Produktionstechniken
            rows2 = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source = 'CoT_Music_Production_DAW'
                  AND (toLower(k.text) CONTAINS $instr
                       OR toLower(k.text) CONTAINS 'pattern'
                       OR toLower(k.text) CONTAINS 'rhythm')
                RETURN k.text AS t
                LIMIT 2
            """, instr=instrument.lower()).data()

            for r in rows2:
                text = r["t"][:400]
                results.append(f"[CoT_DAW] {text}")

        driver.close()

        if not results:
            return (
                f"Keine spezifischen {genre}/{instrument} Beschreibungen in KB. "
                f"Verwende allgemeine Musiktheorie: "
                f"Bass=Grundtöne auf betonten Beats, "
                f"Chords=Upbeats/Antizipationen, "
                f"Drums=Kick 1&3 Snare 2&4 HiHat 8tel."
            )

        header = (
            f"KB-Kontext für {genre.upper()} / {instrument.upper()}:\n"
            f"Analysiere diese Beschreibungen und leite konkrete MIDI-Noten ab.\n\n"
        )
        return header + "\n\n".join(results)

    except Exception as e:
        return f"KB nicht verfügbar ({e}) — verwende Musiktheorie-Defaults."


@tool
def compose_arrangement(
    genre: str,
    chord_progression: str,
    bpm: float = 100.0,
    style_notes: str = "",
) -> str:
    """Analysiert alle KB-Quellen und leitet eine stimmige Arrangement-Empfehlung ab.

    Das Tool aggregiert Wissen aus MusicCaps, CoT_DAW, MusicTheoryBench und
    Chordonomicon — der Agent zieht daraus Schlussfolgerungen für ein kohärentes
    Arrangement und schreibt die Noten mit write_notes_to_clip.

    WORKFLOW nach diesem Tool:
      1. Lies die Empfehlungen für jedes Instrument
      2. Leite konkrete MIDI-Noten ab (Timing, Pitch, Velocity, Dauer)
      3. Schreibe jeden Track mit write_notes_to_clip
      4. Überprüfe mit verify_song

    Args:
        genre:             "pop", "rock", "jazz" ...
        chord_progression: z.B. "Am F G Am" (Leerzeichen-getrennt)
        bpm:               Tempo in BPM
        style_notes:       Optionale Hinweise ("dunkel", "energetisch", "ruhig")
    """
    import os
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    chords = chord_progression.split()
    beats_per_bar = 4.0
    bar_count = max(len(chords), 2)
    clip_beats = bar_count * 2.0  # 2 Beats pro Akkord

    try:
        from neo4j import GraphDatabase
        from src.audio.chord_to_bitwig import detect_key, NOTE_NAMES, ROOT

        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )

        def query_kb(aspect: str, limit: int = 3) -> list[str]:
            results = []
            with driver.session() as s:
                # MusicCaps
                rows = s.run("""
                    MATCH (k:KnowledgeQA)
                    WHERE k.source = 'MusicCaps'
                      AND toLower(k.text) CONTAINS $genre
                      AND toLower(k.text) CONTAINS $aspect
                    RETURN k.text AS t LIMIT $lim
                """, genre=genre.lower(), aspect=aspect.lower(), lim=limit).data()
                for r in rows:
                    if "Music Description:" in r["t"]:
                        desc = r["t"].split("Music Description:")[-1].split("\n")[0].strip()
                        if len(desc) > 30:
                            results.append(desc[:250])

                # CoT_DAW
                rows2 = s.run("""
                    MATCH (k:KnowledgeQA)
                    WHERE k.source = 'CoT_Music_Production_DAW'
                      AND toLower(k.text) CONTAINS $aspect
                    RETURN k.text AS t LIMIT 1
                """, aspect=aspect.lower()).data()
                for r in rows2:
                    results.append("[DAW-Technik] " + r["t"][:200])
            return results

        # ── Tonart bestimmen ───────────────────────────────────────────────────
        from src.audio.chord_to_bitwig import parse_chord
        parsed_chords = [c for c in chords if parse_chord(c)]
        key_root, key_mode = detect_key(parsed_chords) if parsed_chords else (ROOT["C"], "major")
        key_name = f"{NOTE_NAMES[key_root % 12]} {key_mode}"

        # ── KB-Abfragen für alle Aspekte ───────────────────────────────────────
        aspects = {
            "drums":   query_kb("drum kick snare", 2),
            "bass":    query_kb("bass line", 2),
            "chords":  query_kb("chord", 2),
            "melody":  query_kb("melody lead", 2),
            "groove":  query_kb("groove rhythm tempo", 2),
        }
        driver.close()

        # ── Arrangement-Analyse zusammenstellen ───────────────────────────────
        # Kompakte Ausgabe — KB-Text auf 120 Zeichen kürzen um Token-Limit zu respektieren
        kb_lines = []
        for aspect, examples in aspects.items():
            if examples:
                best = examples[0][:120].replace("\n", " ")
                kb_lines.append(f"{aspect.upper()}: {best}")

        return (
            f"ARRANGEMENT {genre.upper()} | {chord_progression} | {key_name} | {bpm}BPM | {clip_beats}Beats\n"
            f"Stil: {style_notes or 'standard'}\n\n"
            f"KB-ERKENNTNISSE:\n" + "\n".join(f"• {l}" for l in kb_lines) + "\n\n"
            f"SCHLUSSFOLGERUNGEN — beantworte für jeden Track:\n"
            f"DRUMS: Kick welche Beats? Snare welche Beats? HiHat-Dichte?\n"
            f"BASS: Staccato oder gebunden? Grundton + Bewegung wo?\n"
            f"CHORDS: Downbeat oder Upbeat? Kurz oder gehalten?\n"
            f"MELODY: Pitch-Bereich? Rhythmisch dicht oder sparsam?\n"
            f"TIMING: Wo spielen alle zusammen? Wo Lücken für Luft?\n\n"
            f"WICHTIG: Erst setup_instrument_track für jeden Track, dann write_notes_to_clip.\n"
            f"pitch=float!, step=Beat-Position, dur=Beats, Clip={clip_beats}Beats"
        )

    except Exception as e:
        return (
            f"KB nicht verfügbar ({e}).\n"
            f"Akkordfolge: {chord_progression} | Tonart: {genre} | BPM: {bpm}\n"
            f"Verwende Musiktheorie: Kick 0+2, Snare 1+3, Bass Grundtöne, "
            f"Chords Upbeats, Melodie pentatonisch."
        )


@tool
def create_song_structure(
    genre: str = "pop",
    start_track_index: int = 1,
    verse_beats: float = 8.0,
    chorus_beats: float = 8.0,
    arrangement_seconds: float = 60.0,
) -> str:
    """Erstellt einen vollständigen Song mit Verse (Scene 1) und Chorus (Scene 2).

    Workflow:
      1. 6 Tracks erstellen (v9 Kick, Snare, Hat, Polysynth, Phase-4, FM-4)
      2. Verse-Patterns in Slot 0 (leichter, aufbauend)
      3. Chorus-Patterns in Slot 1 (dichter, energetischer)
      4. In Arranger aufnehmen: Verse 30s → Chorus 30s

    Unterschied Verse vs Chorus:
      Verse:  Kick 1&3, 8tel-Hat, Chords gehalten, Melodie sparsam
      Chorus: Kick 4-on-the-floor, 16tel-Hat, Chords staccato, Melodie dicht

    Args:
        genre:                 "pop", "rock" ...
        start_track_index:     aus get_bitwig_track_state()
        verse_beats:           Clip-Länge Verse in Beats (Standard: 8)
        chorus_beats:          Clip-Länge Chorus in Beats (Standard: 8)
        arrangement_seconds:   Gesamtlänge in Sekunden (Standard: 60)
    """
    import os, sys
    sys.path.insert(0, str(__file__).split("/src/")[0])
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    from src.audio.chord_to_bitwig import (
        query_chordonomicon, progression_to_pattern,
        generate_melody, detect_key,
    )
    from pythonosc import udp_client

    if not _check_bridge():
        return "Fehler: BitwigAgentBridge nicht erreichbar"

    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    step_size = 0.25

    # ── BPM aus KB ───────────────────────────────────────────────────────────
    bpm = 100.0
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
        with driver.session() as s:
            row = s.run("MATCH (g:Genre) WHERE toLower(g.name) CONTAINS $g "
                        "RETURN g.bpm_min AS mn, g.bpm_max AS mx LIMIT 1",
                        g=genre.lower()).single()
        driver.close()
        if row:
            bpm = (row["mn"] + row["mx"]) / 2
    except Exception:
        pass

    client.send_message("/transport/tempo", float(bpm))
    time.sleep(0.1)

    # ── Akkordprogressionen aus Chordonomicon ─────────────────────────────────
    GENRE_MAP = {"hard rock":"rock","heavy metal":"metal","electro pop":"pop"}
    genre_q = GENRE_MAP.get(genre.lower(), genre)
    results = query_chordonomicon(genre=genre_q, n=1)
    if not results:
        results = query_chordonomicon(genre="rock", n=1)

    parsed = results[0]
    sections = parsed["sections"]
    all_sections = list(sections.values())
    verse_chords  = all_sections[0][:4] if all_sections else ["Am","F","G","Am"]
    chorus_chords = all_sections[1][:4] if len(all_sections) > 1 else ["G","F","G","Am"]

    # ── Fix 1: Tracks nur anlegen wenn sie noch nicht existieren ─────────────
    instruments = [
        ("v9 Kick","kick"), ("v9 Snare","snare"), ("v9 Hat Closed","hihat"),
        ("Polysynth","bass"), ("Phase-4","chords"), ("FM-4","lead"),
    ]
    track_indices = list(range(start_track_index, start_track_index + 6))

    # Vorhandene Tracks via OSC prüfen
    import struct as _struct
    current_count = 0
    count_client = _bound_osc_client(timeout=2.0)
    try:
        count_client.send_message("/agent/track/count", 1)
        data, _ = count_client._sock.recvfrom(512)
        raw = data.decode("latin-1")
        idx = raw.find(",i")
        if idx >= 0:
            padded = (idx + 4) & ~3
            if padded + 4 <= len(data):
                current_count = _struct.unpack(">i", data[padded:padded+4])[0]
    except OSError:
        pass
    finally:
        try:
            count_client._sock.close()
        except Exception:
            pass

    needed_tracks = start_track_index + 5  # Tracks 1–6 bei start=1
    if current_count >= needed_tracks:
        # Tracks existieren bereits — nur Instrumente reloaden
        for idx, (instr, _) in zip(track_indices, instruments):
            client.send_message(f"/track/{idx}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", instr); time.sleep(0.5)
    else:
        # Neue Tracks anlegen
        tracks_to_add = needed_tracks - current_count
        for _ in range(min(tracks_to_add, 6)):
            client.send_message("/track/add/instrument", 1); time.sleep(0.3)
        for idx, (instr, _) in zip(track_indices, instruments):
            client.send_message(f"/track/{idx}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", instr); time.sleep(0.5)

    # ── Fix 2: Beat-genaue Aufnahmezeit berechnen ────────────────────────────
    seconds_per_verse  = verse_beats  * 60.0 / bpm
    seconds_per_chorus = chorus_beats * 60.0 / bpm
    # Loops auf ganze Zahl runden → kein Abschnitt mitten im Loop
    verse_loops  = max(1, round(arrangement_seconds / 2 / seconds_per_verse))
    chorus_loops = max(1, round(arrangement_seconds / 2 / seconds_per_chorus))
    actual_verse_sec  = verse_loops  * seconds_per_verse
    actual_chorus_sec = chorus_loops * seconds_per_chorus

    def write_clip(track_idx, notes, slot, length):
        client.send_message(f"/track/{track_idx}/select", 1); time.sleep(0.5)
        client.send_message("/clip/create", [float(slot), float(length)]); time.sleep(0.6)
        client.send_message("/clip/step_size", step_size); time.sleep(0.05)
        client.send_message("/clip/clear", 1); time.sleep(0.15)
        for n in notes:
            client.send_message("/clip/note/beat",
                [float(n["step"]), float(n["pitch"]), float(n.get("vel",0.8)), float(n.get("dur",0.5))])
            time.sleep(0.02)

    # ════════════════════════════════════════════════════════════════════════
    # VERSE (Slot 0) — leicht, aufbauend
    # ════════════════════════════════════════════════════════════════════════
    pv = progression_to_pattern(verse_chords, beats_per_chord=2.0)
    kick_v = [{"step":b,"pitch":36,"vel":0.88,"dur":0.25} for b in [0,2,4,6]]
    snare_v = [{"step":b,"pitch":38,"vel":0.82,"dur":0.25} for b in [1,3,5,7]]
    hat_v   = [{"step":b*0.5,"pitch":42,"vel":0.52 if b%2==0 else 0.38,"dur":0.1}
               for b in range(16)]

    write_clip(track_indices[0], kick_v,   0, verse_beats)
    write_clip(track_indices[1], snare_v,  0, verse_beats)
    write_clip(track_indices[2], hat_v,    0, verse_beats)
    write_clip(track_indices[3], pv["bass"],   0, verse_beats)
    write_clip(track_indices[4], pv["chords"], 0, verse_beats)
    melody_v = generate_melody(verse_chords, length_beats=verse_beats, seed=42)
    write_clip(track_indices[5], melody_v, 0, verse_beats)

    # ════════════════════════════════════════════════════════════════════════
    # CHORUS (Slot 1) — dichter, energetischer
    # ════════════════════════════════════════════════════════════════════════
    pc = progression_to_pattern(chorus_chords, beats_per_chord=2.0)

    # Kick: 4-on-the-floor + off-beat Kicks
    kick_c = [{"step":b,"pitch":36,"vel":0.95,"dur":0.25} for b in [0,1,2,3,4,5,6,7]]
    kick_c += [{"step":b,"pitch":36,"vel":0.78,"dur":0.25} for b in [0.5,2.5,4.5,6.5]]

    # Snare: lauter, mit Ghost-Notes
    snare_c  = [{"step":b,"pitch":38,"vel":0.92,"dur":0.25} for b in [1,3,5,7]]
    snare_c += [{"step":b,"pitch":38,"vel":0.45,"dur":0.1}  for b in [0.5,1.5,2.5,3.5,4.5,5.5,6.5,7.5]]

    # Hat: 16tel (doppelte Dichte)
    hat_c = [{"step":b*0.25,"pitch":42,"vel":0.62 if b%4==0 else 0.42,"dur":0.1}
             for b in range(32)]
    # Open-Hat auf Beat 3.5 und 7.5 für Energie
    hat_c += [{"step":3.5,"pitch":46,"vel":0.70,"dur":0.25},
              {"step":7.5,"pitch":46,"vel":0.70,"dur":0.25}]

    # Bass: aktiver mit Oktavsprüngen
    bass_c = pc["bass"].copy()
    for n in bass_c:
        if n["step"] % 2 == 1.0:  # Off-Beat: Oktave hoch
            n["pitch"] = int(n["pitch"]) + 12

    # Chords: staccato (kurze Noten), Upbeats
    chords_c = []
    for n in pc["chords"]:
        chords_c.append({**n, "dur": 0.45})   # staccato

    # Melodie: höher, dichter
    melody_c = generate_melody(chorus_chords, length_beats=chorus_beats,
                               melody_octave=2, seed=99)

    write_clip(track_indices[0], kick_c,   1, chorus_beats)
    write_clip(track_indices[1], snare_c,  1, chorus_beats)
    write_clip(track_indices[2], hat_c,    1, chorus_beats)
    write_clip(track_indices[3], bass_c,   1, chorus_beats)
    write_clip(track_indices[4], chords_c, 1, chorus_beats)
    write_clip(track_indices[5], melody_c, 1, chorus_beats)

    # ── Volumes: Drums lauter im Chorus ──────────────────────────────────────
    for t, vol in zip(track_indices, [0.85, 0.80, 0.65, 0.75, 0.60, 0.82]):
        client.send_message(f"/track/{t}/volume", vol); time.sleep(0.03)

    # ── In Arranger aufnehmen — beat-genau ───────────────────────────────────
    client.send_message("/arrange/view", 1); time.sleep(0.5)
    client.send_message("/arrange/record/start", 1); time.sleep(0.3)

    client.send_message("/scene/1/launch", 1)
    time.sleep(actual_verse_sec)   # Exakt N vollständige Verse-Loops

    client.send_message("/scene/2/launch", 1)
    time.sleep(actual_chorus_sec)  # Exakt M vollständige Chorus-Loops

    client.send_message("/arrange/record/stop", 1)

    v_str = " → ".join(verse_chords)
    c_str = " → ".join(chorus_chords)
    total = actual_verse_sec + actual_chorus_sec
    return (
        f"SONG-STRUKTUR FERTIG ({total:.1f}s @ {bpm:.0f}BPM)\n"
        f"Scene 1 (Verse,  Slot 0): {v_str} — leicht, 8tel-Hat\n"
        f"  {verse_loops} Loops × {seconds_per_verse:.2f}s = {actual_verse_sec:.1f}s\n"
        f"Scene 2 (Chorus, Slot 1): {c_str} — 4-on-floor, 16tel-Hat, staccato\n"
        f"  {chorus_loops} Loops × {seconds_per_chorus:.2f}s = {actual_chorus_sec:.1f}s\n"
        f"Tracks {track_indices[0]}–{track_indices[-1]}: v9 Kick|Snare|Hat|Polysynth|Phase-4|FM-4"
    )



# ── Drum-Profile pro Genre und Section-Typ ────────────────────────────────────
# Jeder Eintrag: kick_beats, snare_beats, hat_step (Abstände in Beats),
# hat_vel_on/off, open_hat_beats, kick_vel, snare_vel

DRUM_PROFILES: dict[str, dict[str, dict]] = {
    "pop": {
        "intro":  {"kick": [0, 4],    "snare": [4],     "hat_step": 1.0,  "hat_vel_on": 0.40, "hat_vel_off": 0.30, "kick_vel": 0.70, "snare_vel": 0.65},
        "verse":  {"kick": [0,2,4,6], "snare": [2,6],   "hat_step": 0.5,  "hat_vel_on": 0.52, "hat_vel_off": 0.38, "kick_vel": 0.88, "snare_vel": 0.82},
        "chorus": {"kick": "4floor",  "snare": [2,6],   "hat_step": 0.25, "hat_vel_on": 0.62, "hat_vel_off": 0.42, "open_hat": [3.5,7.5], "kick_vel": 0.95, "snare_vel": 0.92},
        "solo":   {"kick": [0,2,4,6], "snare": [2,6],   "hat_step": 1.0,  "hat_vel_on": 0.40, "hat_vel_off": 0.30, "kick_vel": 0.82, "snare_vel": 0.78},
        "outro":  {"kick": [0,4],     "snare": [2],     "hat_step": 1.0,  "hat_vel_on": 0.35, "hat_vel_off": 0.25, "kick_vel": 0.72, "snare_vel": 0.68},
    },
    "jazz": {
        "intro":  {"kick": [0],         "snare": [],    "hat_step": 0.67, "hat_vel_on": 0.35, "hat_vel_off": 0.22, "kick_vel": 0.60, "snare_vel": 0.50},
        "verse":  {"kick": [0, 3],      "snare": [2,6], "hat_step": 0.67, "hat_vel_on": 0.45, "hat_vel_off": 0.28, "kick_vel": 0.72, "snare_vel": 0.68},
        "chorus": {"kick": [0,2,4,6],   "snare": [2,6], "hat_step": 0.5,  "hat_vel_on": 0.52, "hat_vel_off": 0.35, "open_hat": [5.67], "kick_vel": 0.82, "snare_vel": 0.78},
        "solo":   {"kick": [0, 2.5],    "snare": [2,6], "hat_step": 0.67, "hat_vel_on": 0.42, "hat_vel_off": 0.28, "kick_vel": 0.75, "snare_vel": 0.70},
        "outro":  {"kick": [0],         "snare": [2],   "hat_step": 1.0,  "hat_vel_on": 0.30, "hat_vel_off": 0.22, "kick_vel": 0.55, "snare_vel": 0.50},
    },
    "metal": {
        "intro":  {"kick": [0,0.5,1,1.5,2,2.5,3,3.5], "snare": [2,6],   "hat_step": 0.25, "hat_vel_on": 0.55, "hat_vel_off": 0.40, "kick_vel": 0.88, "snare_vel": 0.85},
        "verse":  {"kick": "double",                    "snare": [2,6],   "hat_step": 0.25, "hat_vel_on": 0.65, "hat_vel_off": 0.45, "kick_vel": 0.95, "snare_vel": 0.90},
        "chorus": {"kick": "double",                    "snare": [2,4,6], "hat_step": 0.25, "hat_vel_on": 0.68, "hat_vel_off": 0.48, "open_hat": [3.75,7.75], "kick_vel": 0.98, "snare_vel": 0.95},
        "solo":   {"kick": "double",                    "snare": [2,6],   "hat_step": 0.5,  "hat_vel_on": 0.55, "hat_vel_off": 0.38, "kick_vel": 0.92, "snare_vel": 0.82},
        "outro":  {"kick": [0,2],                       "snare": [2],     "hat_step": 0.5,  "hat_vel_on": 0.45, "hat_vel_off": 0.32, "kick_vel": 0.75, "snare_vel": 0.65},
    },
    "trap": {
        "intro":  {"kick": [0,1.5,3],       "snare": [],    "hat_step": 0.125, "hat_vel_on": 0.35, "hat_vel_off": 0.20, "kick_vel": 0.72, "snare_vel": 0.65},
        "verse":  {"kick": [0,1.5,3,4.5],   "snare": [2,6], "hat_step": 0.125, "hat_vel_on": 0.55, "hat_vel_off": 0.28, "kick_vel": 0.85, "snare_vel": 0.80},
        "chorus": {"kick": [0,1,2.5,4,5.5], "snare": [2,6], "hat_step": 0.125, "hat_vel_on": 0.60, "hat_vel_off": 0.32, "open_hat": [3.875,7.875], "kick_vel": 0.90, "snare_vel": 0.85},
        "solo":   {"kick": [0,2,3.5],        "snare": [2,6], "hat_step": 0.125, "hat_vel_on": 0.50, "hat_vel_off": 0.25, "kick_vel": 0.80, "snare_vel": 0.75},
        "outro":  {"kick": [0,3],            "snare": [4],   "hat_step": 0.25,  "hat_vel_on": 0.35, "hat_vel_off": 0.22, "kick_vel": 0.65, "snare_vel": 0.55},
    },
    "bossa nova": {
        "intro":  {"kick": [0,1.5,2.5],           "snare": [],    "hat_step": 0.5, "hat_vel_on": 0.30, "hat_vel_off": 0.20, "kick_vel": 0.60, "snare_vel": 0.50},
        "verse":  {"kick": [0,1.5,2.5,4,5.5,6.5], "snare": [2,6], "hat_step": 0.5, "hat_vel_on": 0.40, "hat_vel_off": 0.28, "kick_vel": 0.72, "snare_vel": 0.65},
        "chorus": {"kick": [0,1.5,2.5,4,5.5,6.5], "snare": [2,6], "hat_step": 0.5, "hat_vel_on": 0.45, "hat_vel_off": 0.32, "open_hat": [], "kick_vel": 0.78, "snare_vel": 0.72},
        "solo":   {"kick": [0,1.5,2.5,4],          "snare": [2,6], "hat_step": 0.5, "hat_vel_on": 0.38, "hat_vel_off": 0.25, "kick_vel": 0.70, "snare_vel": 0.65},
        "outro":  {"kick": [0,2.5],                 "snare": [2],   "hat_step": 1.0, "hat_vel_on": 0.28, "hat_vel_off": 0.18, "kick_vel": 0.55, "snare_vel": 0.48},
    },
}
DRUM_PROFILES["rock"]       = DRUM_PROFILES["pop"]
DRUM_PROFILES["hard rock"]  = DRUM_PROFILES["metal"]
DRUM_PROFILES["heavy metal"] = DRUM_PROFILES["metal"]
DRUM_PROFILES["default"]    = DRUM_PROFILES["pop"]


def _build_drum_track(profile: dict, sec_type: str, length: float) -> tuple[list, list, list]:
    """Generiert Kick/Snare/Hat aus einem DRUM_PROFILES-Eintrag."""
    from src.audio.chord_to_bitwig import humanize_velocity
    p = profile.get(sec_type, profile.get("verse", {}))

    # Kick
    kick_beats = p.get("kick", [0, 2, 4, 6])
    kv = p.get("kick_vel", 0.88)
    if kick_beats == "4floor":
        kick_beats = [b for b in range(int(length))]
        kick_beats += [b + 0.5 for b in [0, 2, 4, 6] if b + 0.5 < length]
    elif kick_beats == "double":
        kick_beats = [b * 0.5 for b in range(int(length * 2))]
    kick = [{"step": b, "pitch": 36, "vel": kv * (0.78 if b != int(b) else 1.0), "dur": 0.25}
            for b in kick_beats if b < length]

    # Snare
    sv = p.get("snare_vel", 0.82)
    snare_beats = p.get("snare", [2, 6])
    snare = [{"step": b, "pitch": 38, "vel": sv, "dur": 0.25} for b in snare_beats if b < length]
    # Ghost Notes für energetische Sections
    if sec_type == "chorus":
        ghost_beats = [b + 0.5 for b in snare_beats if b + 0.5 < length]
        snare += [{"step": b, "pitch": 38, "vel": sv * 0.48, "dur": 0.1} for b in ghost_beats]

    # HiHat
    hat_step = p.get("hat_step", 0.5)
    hv_on  = p.get("hat_vel_on",  0.52)
    hv_off = p.get("hat_vel_off", 0.38)
    n_hats = int(length / hat_step)
    hat = [{"step": round(i * hat_step, 4), "pitch": 42,
            "vel": hv_on if i % 2 == 0 else hv_off, "dur": 0.1}
           for i in range(n_hats) if i * hat_step < length]
    # Open Hi-Hat
    for s in p.get("open_hat", []):
        if s < length:
            hat.append({"step": s, "pitch": 46, "vel": hv_on * 1.1, "dur": 0.25})

    # Velocity humanisieren
    kick  = humanize_velocity(kick,  variance=0.04, seed=1)
    snare = humanize_velocity(snare, variance=0.03, seed=2)
    hat   = humanize_velocity(hat,   variance=0.05, seed=3)

    return kick, snare, hat


# ── Section-Pattern-Definitionen ──────────────────────────────────────────────

def _make_intro_patterns(chords, length, bpm, genre="default"):
    """Intro: sparse, aufbauend — nur Kick + Bass + leise Chords."""
    from src.audio.chord_to_bitwig import progression_to_pattern, humanize_velocity
    pat = progression_to_pattern(chords, beats_per_chord=length/4)
    drum_profile = DRUM_PROFILES.get(genre, DRUM_PROFILES["default"])
    kick, snare, hat = _build_drum_track(drum_profile, "intro", length)
    bass  = [{"step": 0, "pitch": float(pat["bass"][0]["pitch"]), "vel": 0.65, "dur": length - 0.5}]
    bass  = humanize_velocity(bass, variance=0.03, seed=10)
    chords_notes = []
    melody = []
    return kick, snare, hat, bass, chords_notes, melody


def _make_verse_patterns(chords, length, bpm, seed=42, genre="default"):
    """Verse: klassisch, leicht."""
    from src.audio.chord_to_bitwig import progression_to_pattern, generate_melody, humanize_velocity
    pat = progression_to_pattern(chords, beats_per_chord=length/len(chords))
    drum_profile = DRUM_PROFILES.get(genre, DRUM_PROFILES["default"])
    kick, snare, hat = _build_drum_track(drum_profile, "verse", length)
    bass   = humanize_velocity(pat["bass"],   variance=0.05, seed=seed)
    chords_h = humanize_velocity(pat["chords"], variance=0.04, seed=seed+1)
    melody = generate_melody(chords, length_beats=length, seed=seed, genre=genre)
    melody = humanize_velocity(melody, variance=0.05, seed=seed+2)
    return kick, snare, hat, bass, chords_h, melody


def _make_chorus_patterns(chords, length, bpm, seed=99, genre="default"):
    """Chorus: 4-on-floor, energetisch."""
    from src.audio.chord_to_bitwig import progression_to_pattern, generate_melody, humanize_velocity
    pat = progression_to_pattern(chords, beats_per_chord=length/len(chords))
    drum_profile = DRUM_PROFILES.get(genre, DRUM_PROFILES["default"])
    kick, snare, hat = _build_drum_track(drum_profile, "chorus", length)
    # Bass: Oktavsprünge auf Off-Beats
    bass_c = []
    for n in pat["bass"]:
        note = dict(n)
        if n["step"] % 2 == 1.0:
            note["pitch"] = int(note["pitch"]) + 12
        bass_c.append(note)
    bass_c = humanize_velocity(bass_c, variance=0.05, seed=seed)
    chords_s = humanize_velocity(
        [{**n, "dur": 0.45} for n in pat["chords"]],
        variance=0.04, seed=seed+1,
    )
    melody = generate_melody(chords, length_beats=length, melody_octave=2, seed=seed, genre=genre)
    melody = humanize_velocity(melody, variance=0.05, seed=seed+2)
    return kick, snare, hat, bass_c, chords_s, melody


def _make_solo_patterns(chords, length, bpm, seed=77, genre="default"):
    """Solo: Melodie im Vordergrund, Drums minimal, Chords gedämpft."""
    from src.audio.chord_to_bitwig import (
        progression_to_pattern, PENTATONIC, detect_key, humanize_velocity
    )
    import random
    rng = random.Random(seed)
    pat = progression_to_pattern(chords, beats_per_chord=length/len(chords))
    drum_profile = DRUM_PROFILES.get(genre, DRUM_PROFILES["default"])
    kick, snare, hat = _build_drum_track(drum_profile, "solo", length)
    chords_s = humanize_velocity(
        [{**n, "vel": n["vel"] * 0.55} for n in pat["chords"]],
        variance=0.04, seed=seed,
    )
    # Solo-Melodie: schnell, volle Pentatonik, random walk
    root, mode = detect_key(chords)
    scale_ivs = PENTATONIC[mode]
    scale = sorted({root + ov * 12 + iv for ov in range(2, 4) for iv in scale_ivs
                    if 72 <= root + ov * 12 + iv <= 96})
    solo_notes = []
    beat = 0.0
    while beat < length - 0.1:
        pitch = rng.choice(scale) if scale else 72
        dur = rng.choice([0.25, 0.25, 0.5, 0.5, 0.25])
        dur = min(dur, length - beat)
        solo_notes.append({"step": round(beat, 4), "pitch": float(pitch),
                            "vel": rng.uniform(0.72, 0.92), "dur": dur})
        beat += dur
    solo_notes = humanize_velocity(solo_notes, variance=0.05, seed=seed+1)
    return kick, snare, hat, pat["bass"], chords_s, solo_notes


def _make_outro_patterns(chords, length, bpm, seed=12, genre="default"):
    """Outro: ausdünnend, letzter Akkord hält."""
    from src.audio.chord_to_bitwig import progression_to_pattern, generate_melody, parse_chord, humanize_velocity
    pat = progression_to_pattern(chords, beats_per_chord=length/len(chords))
    drum_profile = DRUM_PROFILES.get(genre, DRUM_PROFILES["default"])
    kick, snare, hat = _build_drum_track(drum_profile, "outro", length)
    last_chord_start = (len(chords) - 1) * (length / len(chords))
    outro_chords = [n for n in pat["chords"] if n["step"] < last_chord_start]
    last_r = parse_chord(chords[-1])
    if last_r:
        root, ivs = last_r
        for iv in ivs:
            outro_chords.append({
                "step": last_chord_start,
                "pitch": float(root + iv + 12),
                "vel": 0.60,
                "dur": length - last_chord_start - 0.1,
            })
    outro_chords = humanize_velocity(outro_chords, variance=0.03, seed=seed,
                                     curve=[1.0, 0.65])  # Decrescendo
    melody = generate_melody([chords[-1]], length_beats=length, seed=seed, genre=genre,
                             end_on_tonic=True)
    melody = humanize_velocity(melody, variance=0.04, seed=seed+1, curve=[1.0, 0.55])
    bass = pat["bass"][:2] + [{
        "step": last_chord_start,
        "pitch": float(pat["bass"][0]["pitch"]),
        "vel": 0.55,
        "dur": length - last_chord_start - 0.1,
    }]
    return kick, snare, hat, bass, outro_chords, melody


SECTION_BUILDERS = {
    "intro":  _make_intro_patterns,
    "verse":  _make_verse_patterns,
    "chorus": _make_chorus_patterns,
    "solo":   _make_solo_patterns,
    "outro":  _make_outro_patterns,
}


def _make_fill_pattern(from_sec: str, to_sec: str, bpm: float, genre: str = "default") -> list[dict]:
    """Erzeugt einen 1-Bar Drum-Fill als Übergangselement zwischen zwei Sections.

    Typen:
      → chorus: Snare-Roll (16tel letzte 2 Beats) + Crash
      → verse:  einfache Snare-Variante + Crash
      → solo:   Wirbel (32tel letzte 2 Beats)
      → outro:  ausdünnend — Crash + Kick

    Returns:
        Liste von Note-Dicts für 2 Beats (relativ zu Beat 0 des Fill-Bars)
    """
    notes = []
    if to_sec == "chorus":
        # Snare-Roll crescendo: 16tel × 8
        for k in range(8):
            vel = 0.45 + k * 0.06
            notes.append({"step": round(k * 0.25, 4), "pitch": 38, "vel": min(vel, 0.95), "dur": 0.2})
        notes.append({"step": 0.0,  "pitch": 36, "vel": 0.92, "dur": 0.25})
        notes.append({"step": 2.0,  "pitch": 36, "vel": 0.88, "dur": 0.25})
        notes.append({"step": 1.75, "pitch": 49, "vel": 0.88, "dur": 0.5})  # Crash
    elif to_sec in ("verse", "intro"):
        for k, b in enumerate([0.5, 1.0, 1.5]):
            notes.append({"step": b, "pitch": 38, "vel": 0.70 + k * 0.05, "dur": 0.25})
        notes.append({"step": 0.0,  "pitch": 36, "vel": 0.82, "dur": 0.25})
        notes.append({"step": 1.75, "pitch": 49, "vel": 0.72, "dur": 0.5})
    elif to_sec == "solo":
        for k in range(16):
            vel = 0.40 + k * 0.035
            notes.append({"step": round(k * 0.125, 4), "pitch": 38, "vel": min(vel, 0.90), "dur": 0.1})
        notes.append({"step": 1.875, "pitch": 49, "vel": 0.85, "dur": 0.5})
    elif to_sec == "outro":
        notes.append({"step": 0.0, "pitch": 49, "vel": 0.75, "dur": 1.0})
        notes.append({"step": 0.0, "pitch": 36, "vel": 0.72, "dur": 0.25})
    else:
        notes.append({"step": 0.0, "pitch": 49, "vel": 0.80, "dur": 0.5})
    return notes


@tool
def create_song_with_sections(
    genre: str = "pop",
    start_track_index: int = 1,
    clip_beats: float = 8.0,
    sections: str = "intro,verse,chorus,solo,chorus,outro",
    section_loops: str = "3,7,7,4,7,3",
) -> str:
    """Erstellt einen Song mit mehreren Sections und Tempo-Variationen.

    Jede Section hat eigene Patterns:
      intro  — sparse, aufbauend (nur Kick+Bass)
      verse  — klassisch, leicht
      chorus — 4-on-floor, energetisch, staccato Chords
      solo   — Lead-Solo im Vordergrund, Drums minimal
      outro  — ausdünnend, letzter Akkord hält

    Tempo-Wechsel: Chorus läuft 3% schneller, Solo 2% schneller.

    Args:
        genre:              "pop", "rock" ...
        start_track_index:  aus get_bitwig_track_state()
        clip_beats:         Clip-Länge in Beats (Standard: 8)
        sections:           Komma-getrennte Sections: "intro,verse,chorus,solo,chorus,outro"
        section_loops:      Loops pro Section: "3,7,7,4,7,3"
    """
    import os, sys
    sys.path.insert(0, str(__file__).split("/src/")[0])
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    from src.audio.chord_to_bitwig import query_chordonomicon
    from pythonosc import udp_client

    if not _check_bridge():
        return "Fehler: BitwigAgentBridge nicht erreichbar"

    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    step_size = 0.25

    section_list = [s.strip() for s in sections.split(",")]
    loop_list    = [int(x.strip()) for x in section_loops.split(",")]
    if len(loop_list) < len(section_list):
        loop_list += [4] * (len(section_list) - len(loop_list))

    # ── BPM aus KB ────────────────────────────────────────────────────────────
    from src.knowledge.neo4j_graph import get_driver as _neo4j_driver
    try:
        _neo4j_drv = _neo4j_driver()
    except ConnectionError as e:
        return f"Fehler: {e}"

    base_bpm = 100.0
    with _neo4j_drv.session() as s:
        row = s.run("MATCH (g:Genre) WHERE toLower(g.name) CONTAINS $g "
                    "RETURN g.bpm_min AS mn, g.bpm_max AS mx LIMIT 1", g=genre.lower()).single()
    if row:
        base_bpm = (row["mn"] + row["mx"]) / 2

    # Tempo-Faktoren pro Section-Typ
    BPM_FACTORS = {"intro":0.97,"verse":1.0,"chorus":1.03,"solo":1.02,"outro":0.96}

    # ── Akkordprogressionen ───────────────────────────────────────────────────
    GENRE_MAP = {"hard rock":"rock","heavy metal":"metal","electro pop":"pop"}
    genre_q = GENRE_MAP.get(genre.lower(), genre)
    results = query_chordonomicon(genre=genre_q, n=1)
    if not results:
        return (f"Fehler: Keine Akkordprogression für Genre '{genre}' in der KB. "
                f"KB befüllen: `make ingest`")
    parsed = results[0]
    all_secs = list(parsed["sections"].values())
    verse_chords  = all_secs[0][:4]
    chorus_chords = all_secs[1][:4] if len(all_secs) > 1 else verse_chords
    CHORDS_BY_TYPE = {"intro":verse_chords,"verse":verse_chords,"chorus":chorus_chords,
                      "solo":chorus_chords,"outro":verse_chords}

    # ── Dynamische Track-Konfiguration basierend auf verfügbaren Loops ───────
    from src.audio.loop_catalog import find_loops_for_genre as _find_loops

    # Tonart aus erster Akkordprogression ableiten
    from src.audio.chord_to_bitwig import detect_key
    try:
        _key_root, _key_mode = detect_key(verse_chords)
        from src.audio.chord_to_bitwig import NOTE_NAMES as _NN
        _key = f"{_NN[_key_root % 12]}{'m' if _key_mode=='minor' else ''}"
        if _key_mode == 'minor' and not _key.endswith('m'):
            _key += 'm'
    except Exception:
        _key = "Am"

    genre_loops = _find_loops(genre, _key, base_bpm)
    has_loops = any(genre_loops.values())

    if has_loops:
        # ── Loop-basierte Tracks: Drums + echte Gitarren/Bass ────────────────
        drum_instruments = [("v9 Kick","kick"),("v9 Snare","snare"),("v9 Hat Closed","hihat")]
        track_indices = list(range(start_track_index, start_track_index + 3))

        # Drums anlegen
        for _ in drum_instruments:
            client.send_message("/track/add/instrument",1); time.sleep(0.3)
        for idx,(instr,_) in zip(track_indices, drum_instruments):
            client.send_message(f"/track/{idx}/select",1); time.sleep(0.2)
            client.send_message("/browser/device/load",instr); time.sleep(0.5)

        # Guitar/Bass-Loops anlegen — Anzahl dynamisch
        loop_track_map = {}  # role → [track_index]
        next_track = start_track_index + 3
        role_order = ["bass","rhythm_guitar","lead_guitar"]
        for role in role_order:
            role_loops = genre_loops.get(role, [])
            loop_track_map[role] = []
            for loop in role_loops:
                client.send_message("/track/add/instrument",1); time.sleep(0.3)
                client.send_message(f"/track/{next_track}/select",1); time.sleep(0.3)
                client.send_message("/browser/device/load","Sampler"); time.sleep(0.8)
                client.send_message("/sampler/load", loop.windows_path); time.sleep(1.5)
                track_indices.append(next_track)
                loop_track_map[role].append(next_track)
                next_track += 1

        # Panning: Rhythmus-Gitarren links/rechts
        rg = loop_track_map.get("rhythm_guitar", [])
        if len(rg) >= 2:
            client.send_message(f"/track/{rg[0]}/pan", 0.28)
            client.send_message(f"/track/{rg[1]}/pan", 0.72)

        # ── KB-Empfohlene Effekte laden ────────────────────────────────────
        # Gitarren-Tracks: Distortion (w=0.98) + Amp (w=0.95)
        for t in loop_track_map.get("rhythm_guitar", []):
            client.send_message(f"/track/{t}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", "Distortion"); time.sleep(0.5)
            client.send_message("/browser/device/load", "Amp"); time.sleep(0.5)
        # Lead-Gitarre: Distortion + Amp + EQ-5
        for t in loop_track_map.get("lead_guitar", []):
            client.send_message(f"/track/{t}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", "Distortion"); time.sleep(0.5)
            client.send_message("/browser/device/load", "Amp"); time.sleep(0.5)
        # Bass: Saturator (w=0.90)
        for t in loop_track_map.get("bass", []):
            client.send_message(f"/track/{t}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", "Saturator"); time.sleep(0.5)
        # Drums Track 1 (Kick): Compressor + Transient Control
        if track_indices:
            client.send_message(f"/track/{track_indices[0]}/select", 1); time.sleep(0.2)
            client.send_message("/browser/device/load", "Compressor"); time.sleep(0.5)
            client.send_message("/browser/device/load", "Transient Control"); time.sleep(0.5)

        bass_tracks  = loop_track_map.get("bass",[])
        chord_tracks = loop_track_map.get("rhythm_guitar",[])
        lead_tracks  = loop_track_map.get("lead_guitar",[])
    else:
        # ── Synth-Fallback: Layout via Registry (Genre-Overrides berücksichtigt) ─────────
        from src.audio.instrument_registry import build_track_layout
        _layout = build_track_layout(genre=genre)
        instruments = [(t["device_name"], t["role"]) for t in _layout]
        track_indices = list(range(start_track_index, start_track_index + len(instruments)))
        for _ in instruments:
            client.send_message("/track/add/instrument",1); time.sleep(0.3)
        for idx,(instr,_) in zip(track_indices,instruments):
            client.send_message(f"/track/{idx}/select",1); time.sleep(0.2)
            client.send_message("/browser/device/load",instr); time.sleep(0.5)
        bass_tracks  = [track_indices[3]]
        chord_tracks = [track_indices[4]]
        lead_tracks  = [track_indices[5]] if len(track_indices) > 5 else []
        loop_track_map = {}

    # ── Patterns pro Section in Slots schreiben ───────────────────────────────
    unique_sections = list(dict.fromkeys(section_list))  # eindeutig, Reihenfolge bewahren
    slot_map = {s: i for i, s in enumerate(unique_sections)}

    def write_clip(tidx, notes, slot, length):
        client.send_message(f"/track/{tidx}/select",1); time.sleep(0.5)
        client.send_message("/clip/create",[float(slot),float(length)]); time.sleep(0.6)
        client.send_message("/clip/step_size",step_size); time.sleep(0.05)
        client.send_message("/clip/clear",1); time.sleep(0.15)
        for n in notes:
            client.send_message("/clip/note/beat",
                [float(n["step"]),float(n["pitch"]),float(n.get("vel",0.8)),float(n.get("dur",0.5))])
            time.sleep(0.02)

    from src.agent.events import get_event_bus as _get_bus
    _bus = _get_bus()

    for sec_type in unique_sections:
        slot = slot_map[sec_type]
        chords = CHORDS_BY_TYPE.get(sec_type, verse_chords)
        bpm_s = base_bpm * BPM_FACTORS.get(sec_type, 1.0)
        builder = SECTION_BUILDERS.get(sec_type, _make_verse_patterns)
        kick, snare, hat, bass, chords_n, melody = builder(chords, clip_beats, bpm_s, genre=genre)
        _bus.emit("section_start", {"section": sec_type, "bpm": bpm_s, "slot": slot})
        write_clip(track_indices[0], kick,     slot, clip_beats)
        write_clip(track_indices[1], snare,    slot, clip_beats)
        write_clip(track_indices[2], hat,      slot, clip_beats)
        write_clip(track_indices[3], bass,     slot, clip_beats)
        write_clip(track_indices[4], chords_n, slot, clip_beats)
        write_clip(track_indices[5], melody,   slot, clip_beats)
        note_total = sum(len(x) for x in [kick, snare, hat, bass, chords_n, melody])
        _bus.emit("section_done", {"section": sec_type, "note_count": note_total})

    # ── Fill-Clips: je ein 2-Beat-Fill-Slot pro Section-Übergang ─────────────
    # Fill wird im letzten Slot (unique+1) abgelegt und beim Arrangement-Record
    # als letzter Takt vor jedem Section-Wechsel eingefügt.
    fill_slot_base = len(unique_sections)
    for i in range(len(section_list) - 1):
        from_s = section_list[i]
        to_s   = section_list[i + 1]
        if from_s == to_s:
            continue
        fill_notes = _make_fill_pattern(from_s, to_s, base_bpm, genre)
        fill_slot  = fill_slot_base + i
        # Fill nur auf Kick + Snare (Track 0 + 1)
        write_clip(track_indices[0], [n for n in fill_notes if n["pitch"] in (36,49)], fill_slot, 2.0)
        write_clip(track_indices[1], [n for n in fill_notes if n["pitch"] == 38],       fill_slot, 2.0)


    # Lautstärken
    if has_loops:
        # Drum-Tracks
        for t,vol in zip(track_indices[:3], [0.88, 0.82, 0.68]):
            client.send_message(f"/track/{t}/volume", vol); time.sleep(0.03)
        # Loop-Tracks: Bass, Rhythmus-Git, Lead
        for t in loop_track_map.get("bass",[]): client.send_message(f"/track/{t}/volume",0.80); time.sleep(0.03)
        for t in loop_track_map.get("rhythm_guitar",[]): client.send_message(f"/track/{t}/volume",0.75); time.sleep(0.03)
        for t in loop_track_map.get("lead_guitar",[]): client.send_message(f"/track/{t}/volume",0.85); time.sleep(0.03)
    else:
        for t,vol in zip(track_indices,[0.85,0.80,0.65,0.75,0.60,0.82]):
            client.send_message(f"/track/{t}/volume",vol); time.sleep(0.03)

    # ── Arrangement aufnehmen mit Tempo-Wechseln ──────────────────────────────
    client.send_message("/arrange/view",1); time.sleep(0.5)
    client.send_message("/arrange/record/start",1); time.sleep(0.3)

    total_sec = 0.0
    summary = []
    for sec_type, loops in zip(section_list, loop_list):
        bpm_s = base_bpm * BPM_FACTORS.get(sec_type, 1.0)
        client.send_message("/transport/tempo", float(bpm_s))
        time.sleep(0.1)
        slot = slot_map[sec_type]
        client.send_message(f"/scene/{slot+1}/launch",1)
        sec_dur = loops * clip_beats * 60.0 / bpm_s
        time.sleep(sec_dur)
        total_sec += sec_dur
        summary.append(f"  [{sec_type:7s}] Scene {slot+1} | {loops}× | {bpm_s:.0f}BPM | {sec_dur:.1f}s")

    client.send_message("/transport/tempo", float(base_bpm))  # BPM zurücksetzen
    client.send_message("/arrange/record/stop",1)

    v_str = " → ".join(verse_chords)
    if has_loops:
        rg_count = len(loop_track_map.get("rhythm_guitar", []))
        lg_count = len(loop_track_map.get("lead_guitar", []))
        track_info = (f"Drums(3) + Bass-Loop + {rg_count}×Rhythm-Guitar-Loop"
                      f"{' + Lead-Guitar-Loop' if lg_count else ''}"
                      f" + KB-Effekte (Distortion, Amp, Saturator, Compressor)")
    else:
        track_info = "v9 Kick|Snare|Hat|Polysynth|Phase-4|FM-4 (Synth-Fallback)"
    return (
        f"SONG FERTIG ERSTELLT. KEINE weiteren create_song Aufrufe nötig.\n"
        f"{len(section_list)} Sections | {total_sec:.1f}s | {base_bpm:.0f}BPM\n"
        + "\n".join(summary) + "\n"
        f"Akkorde: {v_str}\n"
        f"Instrumente: {track_info}"
    )


@tool
def get_song_form(genre: str = "pop") -> str:
    """Holt Songform-Kompositionsregeln aus der KB für ein Genre.

    Gibt empfohlene Reihenfolge, Loop-Counts und Kompositionsregeln zurück.
    Verwende diese Infos BEVOR du create_song_with_sections aufrufst.

    Beispiel:
        get_song_form("pop")
        → "Sequenz: intro,verse,chorus,verse,chorus,solo,chorus,outro"
        → "Loops:    2,4,4,4,4,4,4,2"
        → Regel: Intro/Outro nur einmal!

    Args:
        genre: "pop", "rock", "jazz", "metal" ...
    """
    import os
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    try:
        from neo4j import GraphDatabase
        from src.knowledge.store import get_embeddings

        emb_model = get_embeddings()
        query = f"song structure form {genre} verse chorus intro outro loops"
        emb = emb_model.embed_query(query)

        driver = GraphDatabase.driver(
            os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
        )
        results = []
        with driver.session() as s:
            # Direkte Songform-Einträge (höchste Priorität)
            rows = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source STARTS WITH 'SongForm'
                  AND (toLower(k.source) CONTAINS $genre
                       OR k.source = 'SongForm_Allgemein')
                  AND k.embedding IS NOT NULL
                WITH k, vector.similarity.cosine(k.embedding, $emb) AS score
                ORDER BY score DESC LIMIT 2
                RETURN k.text AS t, k.source AS src, score
            """, genre=genre.lower(), emb=emb).data()

            for r in rows:
                results.append(f"[{r['src']}]\n{r['t'][:600]}")

        driver.close()

        if results:
            return (
                f"SONGFORM-REGELN FÜR {genre.upper()} aus KB:\n\n"
                + "\n\n".join(results)
                + f"\n\nVERWENDE: create_song_with_sections(genre='{genre}', "
                  f"sections='...', section_loops='...')"
            )
    except Exception as e:
        pass

    # Fallback: eingebaute Regeln
    DEFAULTS = {
        "pop":  ("intro,verse,chorus,verse,chorus,solo,chorus,outro", "2,4,4,4,4,4,4,2"),
        "rock": ("intro,verse,chorus,verse,chorus,solo,chorus,outro", "2,4,4,4,4,4,4,2"),
        "jazz": ("intro,verse,solo,verse,outro",                      "2,8,8,8,2"),
        "metal":("intro,verse,chorus,verse,chorus,solo,chorus,outro", "2,4,4,4,4,4,4,2"),
    }
    sec, loops = DEFAULTS.get(genre.lower(), DEFAULTS["pop"])
    return (
        f"SONGFORM {genre.upper()} (Fallback — KB nicht verfügbar):\n"
        f"Sequenz: {sec}\n"
        f"Loops:   {loops}\n"
        f"Regel: Intro/Outro NUR EINMAL (loops=2 = ~9s). "
        f"Verse/Chorus 4 Loops (~17s). Solo 4 Loops."
    )


@tool
def find_guitar_loops(
    key: str = "Am",
    bpm: float = 100.0,
    loop_type: str = "all",
) -> str:
    """Findet passende E-Gitarren und Bass-Loops aus installierten Paketen.

    Sucht nach Loops die zur Tonart und BPM des Songs passen.
    Gibt Dateipfade zurück die mit /arrange/insert/file oder /sampler/load
    direkt in Bitwig geladen werden können.

    Args:
        key:       Ziel-Tonart ("Am", "Em", "Dm", "C", "G" ...)
        bpm:       Ziel-BPM (Loops innerhalb ±20 BPM werden gefunden)
        loop_type: "GuitarRiff","GuitarLead","GuitarChords","BassGuitar","all"
    """
    import sys; sys.path.insert(0, str(__file__).split("/src/")[0])
    from src.audio.loop_catalog import scan_loops, find_best_loops, PACKAGES_BASE

    loops = scan_loops(PACKAGES_BASE)
    if not loops:
        return "Keine Loops gefunden. Pakete installiert?"

    needed = {}
    if loop_type == "all":
        needed = {"GuitarRiff":2,"GuitarLead":1,"GuitarChords":1,"BassGuitar":2}
    else:
        needed = {loop_type: 3}

    matches = find_best_loops(loops, key, bpm, needed)

    lines = [f"LOOPS für {key} @ {bpm}BPM:\n"]
    for typ, found in matches.items():
        if found:
            lines.append(f"[{typ}]")
            for l in found:
                lines.append(
                    f"  BPM:{l.bpm:.0f} Key:{l.key:4} {l.name[:45]}"
                    f"\n  → {l.windows_path}"
                )
    lines.append(
        f"\nLaden via:\n"
        f"  1. Track auswählen: /track/N/select\n"
        f"  2. Loop laden:      /sampler/load <windows_path>"
    )
    return "\n".join(lines)


@tool
def load_guitar_loop(
    track_index: int,
    windows_path: str,
) -> str:
    """Lädt einen Guitar/Bass-Loop auf einen Track in Bitwig.

    Verwendet /sampler/load um den Loop als Device auf den Track zu laden.
    Der Loop wird über den Bitwig Sampler mit Timestretching abgespielt.

    Workflow:
        1. find_guitar_loops(key, bpm) → findet passende Loop-Pfade
        2. load_guitar_loop(track, path) → lädt Loop auf Track

    Args:
        track_index:  Track-Nummer (1-basiert)
        windows_path: Windows-Pfad zur WAV-Datei (aus find_guitar_loops)
    """
    from pythonosc import udp_client
    if not _check_bridge():
        return "Fehler: BitwigAgentBridge nicht erreichbar"

    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_PORT)
    client.send_message(f"/track/{track_index}/select", 1)
    time.sleep(0.3)
    client.send_message("/sampler/load", windows_path)
    time.sleep(1.5)  # Sampler laden braucht Zeit

    loop_name = windows_path.split("\\")[-1].replace(".wav", "")
    return f"✓ Loop geladen auf Track {track_index}: {loop_name}"


@tool
def get_genre_overview(genre: str) -> str:
    """Schritt 1: Genre-Überblick aus KB. DANACH STOPPEN und User fragen ob er weitermachen will.

    Args:
        genre: "metal", "rock", "pop", "jazz" ...
    """
    import os
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    try:
        from neo4j import GraphDatabase
        from src.knowledge.store import get_embeddings

        emb_model = get_embeddings()
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))

        results = []
        with driver.session() as s:
            # 1. Genre-Node aus DB
            g_row = s.run("""
                MATCH (g:Genre)
                WHERE toLower(g.name) CONTAINS $genre
                RETURN g.name AS name, g.bpm_min AS bmin, g.bpm_max AS bmax,
                       g.description AS desc, g.key_mode AS mode
                LIMIT 1
            """, genre=genre.lower()).single()

            if g_row:
                results.append(
                    f"GENRE: {g_row['name']}\n"
                    f"BPM: {g_row['bmin']}–{g_row['bmax']} (Mitte: {(g_row['bmin']+g_row['bmax'])//2})\n"
                    f"Tonart-Modus: {g_row.get('mode','?')}\n"
                    f"Beschreibung: {g_row.get('desc','')}"
                )

            # 2. Typische Devices aus DB
            dev_rows = s.run("""
                MATCH (g:Genre)-[r:USES]->(d:Device)
                WHERE toLower(g.name) CONTAINS $genre
                RETURN d.name AS name, r.role AS role, r.weight AS w
                ORDER BY r.weight DESC LIMIT 8
            """, genre=genre.lower()).data()

            if dev_rows:
                dev_str = "\n".join(f"  • {r['name']:20} [{r['role']}]" for r in dev_rows)
                results.append(f"TYPISCHE INSTRUMENTE/DEVICES:\n{dev_str}")

            # 3. MusicCaps-Beschreibungen
            emb = emb_model.embed_query(f"{genre} music characteristics instruments mood production")
            mc_rows = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source = 'MusicCaps' AND k.embedding IS NOT NULL
                  AND toLower(k.text) CONTAINS $genre
                WITH k, vector.similarity.cosine(k.embedding, $emb) AS score
                ORDER BY score DESC LIMIT 3
                RETURN k.text AS t
            """, genre=genre.lower(), emb=emb).data()

            if mc_rows:
                results.append("ECHTE BEISPIELE AUS DER DATENBANK (MusicCaps):")
                for r in mc_rows:
                    if "Music Description:" in r["t"]:
                        desc = r["t"].split("Music Description:")[-1].split("\n")[0].strip()
                        results.append(f"  → {desc[:180]}")

            # 4. Sound-Definitionen
            sound_rows = s.run("""
                MATCH (s:Sound)
                WHERE toLower(s.name) CONTAINS $genre OR toLower(s.category) CONTAINS $genre
                   OR ANY(w IN [$genre] WHERE toLower(s.description) CONTAINS w)
                RETURN s.name AS name, s.description AS desc, s.settings AS settings
                LIMIT 4
            """, genre=genre.lower()).data()

            if sound_rows:
                results.append("SOUND-DEFINITIONEN AUS DER KB:")
                for r in sound_rows:
                    results.append(f"  {r['name']}: {r.get('desc','')}\n    Settings: {r.get('settings','')[:80]}")

        driver.close()

        if not results:
            return f"Keine spezifischen Daten für '{genre}' in der KB. Verwende allgemeine Musiktheorie."

        output = f"GENRE {genre.upper()}:\n" + "\n".join(r[:200] for r in results)
        return output[:1000] + "\n\n→ Soll ich mit dem Intro beginnen? (ja/nein oder eigene Idee)"

    except Exception as e:
        return f"KB-Fehler: {e}"


@tool
def get_section_proposal(
    genre: str,
    section: str,
    context: str = "",
) -> str:
    """Schritt 2+: Akkord-Optionen für eine Section. NACH Ausgabe STOPPEN und User wählen lassen.

    Zeigt 3 Optionen mit Akkordfolgen, Tempo, DB-Beispiele und warum es passt.
    WARTEN auf User-Wahl bevor nächste Section vorgeschlagen wird.

    Args:
        genre:   "metal", "rock", "pop" ...
        section: "intro", "verse", "chorus", "bridge", "solo", "outro"
        context: Optionaler Kontext (z.B. "nach einem schweren Verse, Chorus soll melodischer sein")
    """
    import os
    os.environ.setdefault("NEO4J_URI",      "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER",     "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")

    try:
        from neo4j import GraphDatabase
        from src.knowledge.store import get_embeddings
        from src.audio.chord_to_bitwig import query_chordonomicon

        emb_model = get_embeddings()
        driver = GraphDatabase.driver(os.environ["NEO4J_URI"],
            auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))

        results = [f"=== {section.upper()} VORSCHLÄGE FÜR {genre.upper()} ===\n"]

        # 1. BPM aus KB
        bpm_base = 120.0
        with driver.session() as s:
            g = s.run("MATCH (g:Genre) WHERE toLower(g.name) CONTAINS $g "
                      "RETURN g.bpm_min AS mn, g.bpm_max AS mx LIMIT 1",
                      g=genre.lower()).single()
            if g:
                bpm_base = (g["mn"] + g["mx"]) / 2

        # 2. Section-spezifische Tempo-Empfehlung
        BPM_ADJUSTMENTS = {
            "intro":  -0.03,
            "verse":   0.00,
            "chorus": +0.04,
            "bridge": -0.02,
            "solo":   +0.02,
            "outro":  -0.05,
        }
        bpm_section = bpm_base * (1 + BPM_ADJUSTMENTS.get(section, 0))
        results.append(f"TEMPO-EMPFEHLUNG: {bpm_section:.0f} BPM "
                       f"({'+' if bpm_section > bpm_base else ''}{bpm_section-bpm_base:.0f} vs. Basis {bpm_base:.0f})")

        # 3. Chordonomicon-Progressionen für dieses Genre
        chords = query_chordonomicon(genre, n=3)
        if chords:
            results.append(f"\nAKKORDPROGRESSIONEN AUS DATENBANK ({len(chords)} Beispiele):")
            for i, c in enumerate(chords):
                for sec_name, sec_chords in list(c["sections"].items())[:1]:
                    if section in sec_name or True:
                        prog = " → ".join(sec_chords[:4])
                        results.append(f"  Option {i+1}: {prog}  [{sec_name}]")

        # 4. Section-spezifische Empfehlungen
        SECTION_RULES = {
            "intro":  "Kurz (1-2 Loops), instrumental, baut Spannung auf. Riff-basiert für Metal/Rock.",
            "verse":  "Erzählt die Geschichte. Mittlere Energie. Gleiche Progression wie Outro.",
            "chorus": "HÖCHSTE ENERGIE. Anderen Akkord als Verse — z.B. relativer Dur statt Moll. "
                      "Melodischer, eingängig. Oft +3-5 BPM schneller.",
            "bridge": "KONTRAST zu Verse+Chorus. Andere Tonart oder Modus. Einmal im Song.",
            "solo":   "Instrument im Vordergrund. Gleiche Harmonie wie Chorus oder modaler Austausch.",
            "outro":  "Auflösung. Wie Intro aber ruhiger. Letzter Akkord als Tonika-Halt.",
        }
        results.append(f"\nKOMPOSITIONS-REGEL:\n  {SECTION_RULES.get(section, '')}")

        # 5. Ähnliche Beispiele aus MusicCaps
        query = f"{genre} {section} {context}"
        emb = emb_model.embed_query(query)
        with driver.session() as s:
            mc = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source = 'MusicCaps' AND k.embedding IS NOT NULL
                WITH k, vector.similarity.cosine(k.embedding, $emb) AS score
                ORDER BY score DESC LIMIT 2
                RETURN k.text AS t, score
            """, emb=emb).data()

        if mc:
            results.append("\nÄHNLICHE BEISPIELE IN DER DB (erkläre warum es passt):")
            for r in mc:
                if "Music Description:" in r["t"]:
                    desc = r["t"].split("Music Description:")[-1].split("\n")[0].strip()
                    score = r["score"]
                    results.append(f"  [{score:.0%} Ähnlichkeit] {desc[:160]}")

        # 6. Clip-Länge für einmalige Wiedergabe (kein Loop)
        SECTION_BARS = {"intro":4,"verse":8,"chorus":8,"bridge":4,"solo":8,"outro":4}
        bars = SECTION_BARS.get(section, 8)
        beats = bars * 4  # 4/4 Takt
        duration_s = beats * 60 / bpm_section
        results.append(f"\nSCENE-TIMING (einmalige Wiedergabe, kein Loop):\n"
                       f"  {bars} Bars × 4 Beats = {beats} Beats bei {bpm_section:.0f}BPM = {duration_s:.1f}s\n"
                       f"  → clip_beats={beats}, section_loops=1 (kein Wiederholen!)")

        driver.close()
        output = "\n".join(results)
        return (output[:1300] +
                f"\n\n→ AUSWAHL für {section.upper()}: Welche Option (1/2/3) oder eigene Akkorde?"
                f" Oder: 'weiter' für nächste Section.")

    except Exception as e:
        return f"KB-Fehler: {e}"

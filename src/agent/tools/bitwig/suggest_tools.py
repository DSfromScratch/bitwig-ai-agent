from __future__ import annotations
import os
import time
from langchain_core.tools import tool

from src.agent.tools.bitwig import launchpad_state

_INST_ROOT = 48                        # C3
_INST_SCALE = [0, 2, 4, 5, 7, 9, 11]  # Major-Skala-Intervalle
_INST_ROW_INTERVAL = 5                 # Perfect Fourth pro Zeile

OSC_HOST         = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_LED_PORT     = int(os.getenv("LAUNCHPAD_LED_PORT", "8003"))
MODE_REPLY_PORT  = int(os.getenv("LAUNCHPAD_REPLY_PORT", "9005"))

_prev_pads: list[int] = []


_DRUM_NAMES = {
    36: "Kick", 37: "Rimshot", 38: "Snare", 39: "Clap",
    40: "E-Snare", 41: "Low Tom", 42: "HH closed", 43: "High Tom",
    44: "Pedal HH", 45: "Low-Mid Tom", 46: "Open HH", 47: "Mid Tom",
    48: "Hi-Mid Tom", 49: "Crash", 50: "High Tom", 51: "Ride",
}

# MIDI note → Launchpad pad note (DRUM mode 4×4 grid)
_DRUM_NOTE_TO_PAD = {
    36: 11, 37: 12, 38: 13, 39: 14,
    40: 21, 41: 22, 42: 23, 43: 24,
    44: 31, 45: 32, 46: 33, 47: 34,
    48: 41, 49: 42, 50: 43, 51: 44,
}

# Drum pad colors matching the Java extension
_DRUM_PAD_COLORS = {
    36: (63, 10,  0), 40: (63, 10,  0),              # Kick / E-Snare — orange-rot
    37: (63, 40,  0), 38: (63, 40,  0), 39: (63, 40, 0),  # Snare-Familie — orange
    42: (63, 63,  0), 44: (63, 63,  0), 46: (63, 63, 0),  # HiHat-Familie — gelb
    49: (40,  0, 63), 51: (40,  0, 63), 48: (40,  0, 63), 50: (40,  0, 63),  # Cymbals — lila
}
_DRUM_PAD_COLOR_DEFAULT = (0, 40, 63)  # Toms — blau


def listen_played_notes(duration: float = 3.0) -> str:
    """Lauscht auf gespielte Noten am Launchpad für `duration` Sekunden.

    Gibt eine Liste der gespielten MIDI-Noten mit Namen zurück.
    Funktioniert im DRUM- und INSTRUMENT-Modus.

    Args:
        duration: Lausch-Dauer in Sekunden (Standard 3.0, max 10.0)
    """
    duration = min(max(duration, 0.5), 10.0)
    played_events = launchpad_state.listen_played_notes(duration)
    played: list[tuple[int, int]] = []
    for event in played_events:
        note_vel = (event.note, event.velocity)
        if note_vel not in played:
            played.append(note_vel)

    if not played:
        return f"[listen_played_notes] Keine Noten in {duration}s gespielt."

    lines = []
    for note, vel in played:
        name = _DRUM_NAMES.get(note, f"Note {note}")
        lines.append(f"  MIDI {note} — {name} (vel={vel})")
    return f"[listen_played_notes] {len(played)} Noten gespielt:\n" + "\n".join(lines)


def get_launchpad_mode() -> str:
    """Gibt den aktuellen Launchpad-Modus zurück: SESSION, DRUM oder INSTRUMENT.

    Fragt die LaunchpadControllerExtension via OSC ab (Port 8003 → Reply auf 9005).
    """
    try:
        mode = launchpad_state.get_mode(force_query=True)
        if mode in launchpad_state.VALID_MODES:
            return f"[get_launchpad_mode] Aktueller Modus: {mode}"
        status = launchpad_state.observer_status()
        if status.startswith("ERROR:"):
            return f"[get_launchpad_mode] Observer-Fehler auf Port {MODE_REPLY_PORT}: {status[7:].strip()}"
        return "[get_launchpad_mode] Timeout — Launchpad Controller nicht aktiv?"
    except Exception as e:
        return f"[get_launchpad_mode] Fehler: {e}"


def midi_to_pads(midi_note: int) -> list[int]:
    """Liefert alle Pad-Noten (11–88) die im INSTRUMENT-Modus die gegebene MIDI-Note erzeugen."""
    pads = []
    for row in range(1, 9):
        base = _INST_ROOT + (row - 1) * _INST_ROW_INTERVAL
        for col in range(1, 9):
            note = base + _INST_SCALE[(col - 1) % 7] + ((col - 1) // 7) * 12
            if note == midi_note:
                pads.append(row * 10 + col)
    return pads


def set_launchpad_mode(mode: str) -> str:
    """Wechselt den Launchpad-Modus per OSC: SESSION, DRUM oder INSTRUMENT.

    Args:
        mode: "SESSION", "DRUM" oder "INSTRUMENT". "CONTROL" wird als Legacy-Alias akzeptiert.
    """
    mode = launchpad_state.normalize_mode(mode)
    if mode not in launchpad_state.VALID_MODES:
        return f"[set_launchpad_mode] Ungültiger Modus: {mode}"
    try:
        current = launchpad_state.set_mode(mode)
        if current == mode:
            return f"[set_launchpad_mode] Aktueller Modus: {current}"
        return f"[set_launchpad_mode] Moduswechsel gesendet, aktueller Modus unbekannt: {current}"
    except Exception as exc:
        return f"[set_launchpad_mode] Fehler: {exc}"


def set_drum_profile(plugin_name: str) -> str:
    """Setzt das Drum-Note-Mapping auf dem Launchpad passend zum geladenen Instrument.

    Profile:
      gm           — GM Standard (36-51): VD-HEAVY, MT-PowerDrumKit, Drum Machine
      v9           — Chromatisch C3 (48-63): v9/v8/v1/v0 Einzel-Synthesizer
    Wird automatisch nach load_instrument für Drum-Instrumente aufgerufen.
    """
    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
        client.send_message("/launchpad/drum/profile", plugin_name)
        return f"[set_drum_profile] Profil für '{plugin_name}' gesetzt."
    except Exception as exc:
        return f"[set_drum_profile] Fehler: {exc}"


def arm_track(arm: int = 1) -> str:
    """Armt (1) oder disarmt (0) den aktuell ausgewählten Bitwig-Track für die Aufnahme.

    Muss vor transport.record() aufgerufen werden damit Noten in den Clip landen.

    Args:
        arm: 1 = arm (Aufnahme aktivieren), 0 = disarm
    """
    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
        client.send_message("/launchpad/track/arm", int(arm))
        return f"[arm_track] Track {'gearmt' if arm else 'disarmt'}."
    except Exception as exc:
        return f"[arm_track] Fehler: {exc}"


def play_notes(notes: list[dict], bpm: float = 120.0) -> str:
    """Spielt eine Notensequenz über das Launchpad in Bitwig.

    Schickt Note-On/Off via OSC an die LaunchpadControllerExtension (Port 8003).
    Funktioniert im DRUM- und INSTRUMENT-Modus des Launchpads.

    Args:
        notes: Liste von Noten-Dicts mit keys:
               - note (int): MIDI-Notennummer (z.B. 36=Kick, 48=C3)
               - vel (int, optional): Velocity 1–127, Standard 100
               - dur (float, optional): Dauer in Beats (Standard 0.5 = halbe Note bei 120 BPM)
               - gap (float, optional): Pause nach der Note in Beats (Standard 0.0)
        bpm: Tempo in BPM für Zeitberechnung (Standard 120)

    Beispiel Drum-Pattern:
        play_notes([
            {"note": 36, "vel": 127, "dur": 0.5},  # Kick
            {"note": 38, "vel": 100, "dur": 0.5},  # Snare
            {"note": 42, "vel": 80,  "dur": 0.25}, # HH
        ], bpm=120)
    """
    if not notes:
        return "[play_notes] Keine Noten angegeben."

    beat_sec = 60.0 / max(bpm, 20.0)

    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)

        current_mode = launchpad_state.get_mode()
        if current_mode not in {"DRUM", "INSTRUMENT"}:
            return f"[play_notes] Übersprungen: Launchpad ist im {current_mode}-Modus; Playback nur in DRUM oder INSTRUMENT."

        played = []
        for n in notes:
            note = int(n.get("note", 60))
            vel  = int(n.get("vel", 100))
            dur  = float(n.get("dur", 0.5)) * beat_sec
            gap  = float(n.get("gap", 0.0)) * beat_sec

            pad = _DRUM_NOTE_TO_PAD.get(note)
            if pad:
                client.send_message("/launchpad/led", [pad, 63, 63, 63])  # weiß

            client.send_message("/launchpad/note/on",  [note, vel])
            time.sleep(max(dur, 0.05))
            client.send_message("/launchpad/note/off", [note])

            if pad:
                r, g, b = _DRUM_PAD_COLORS.get(note, _DRUM_PAD_COLOR_DEFAULT)
                client.send_message("/launchpad/led", [pad, r, g, b])

            if gap > 0:
                time.sleep(gap)
            played.append(note)

        names = [_DRUM_NAMES.get(n, f"Note {n}") for n in played]
        return f"[play_notes] {len(played)} Noten gespielt: {', '.join(names)}"
    except Exception as exc:
        return f"[play_notes] Fehler: {exc}"


def suggest_notes(notes: list[int], r: int = 0, g: int = 50, b: int = 63) -> str:
    """Hebt MIDI-Noten auf dem Launchpad INSTRUMENT-Modus farblich hervor.

    Leuchtet alle Pads auf die die angegebenen Noten im Scale-Layout erzeugen.
    Löscht vorherige Vorschläge automatisch. Max 16 Noten pro Call.

    Args:
        notes: MIDI-Noten (z.B. [48, 52, 55] für C3-Dur-Dreiklang)
        r: Rot-Anteil 0–63 (Standard 0)
        g: Grün-Anteil 0–63 (Standard 50)
        b: Blau-Anteil 0–63 (Standard 63)
    """
    global _prev_pads
    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)

        current_mode = launchpad_state.get_mode()
        if current_mode != "INSTRUMENT":
            return f"[suggest_notes] Übersprungen: Launchpad ist im {current_mode}-Modus; Suggestions nur im INSTRUMENT-Modus."

        for pad in _prev_pads:
            client.send_message("/launchpad/led", [pad, 0, 0, 0])

        new_pads: list[int] = []
        for note in notes[:16]:
            for pad in midi_to_pads(note):
                if pad not in new_pads:
                    new_pads.append(pad)
                    client.send_message("/launchpad/led", [pad, r, g, b])

        _prev_pads = new_pads[:]

        if new_pads:
            return (
                f"[suggest_notes] {len(new_pads)} Pads leuchten für "
                f"{len(notes)} Noten (Pads: {sorted(new_pads)})"
            )
        return "[suggest_notes] Keine Pads — Noten außerhalb INSTRUMENT-Bereich (C3–G8)"
    except Exception as exc:
        return f"[suggest_notes] OSC-Fehler: {exc}"


_NOTE_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _note_name_to_midi(s: str) -> int:
    """Konvertiert Note-Namen zu MIDI-Nummer: 'E2'→40, 'C3'→48, 'A#1'→34."""
    s = s.strip()
    if not s or not s[0].isalpha():
        return 48
    note = _NOTE_OFFSETS.get(s[0].upper(), 0)
    idx = 1
    sharp = 0
    if idx < len(s) and s[idx] in "#b+":
        sharp = 1 if s[idx] in "#+" else -1
        idx += 1
    octave = int(s[idx]) if idx < len(s) and s[idx].isdigit() else 3
    return max(0, min(127, (octave + 1) * 12 + note + sharp))


def _detect_launchpad_layout(instrument_name: str) -> dict | None:
    """Auto-detectiert das passende Instrument-Layout basierend auf dem Plugin-Namen.

    Gibt None zurück für Drum-Instrumente (DRUM mode, gehandelt via set_drum_profile).
    Gibt {root: int, scale: str} zurück für melodische Instrumente.
    """
    n = instrument_name.lower()
    if any(k in n for k in ["drum", "beat", "808", "909", "kit", "schlagzeug", "clap", "kick"]):
        return None  # DRUM mode — set_drum_profile() übernimmt
    if any(k in n for k in ["bass", "vb-", "sub "]):
        return {"root": 40, "scale": "minor"}       # E2 minor
    if any(k in n for k in ["guitar", "gitarre"]):
        return {"root": 40, "scale": "pentatonic"}  # E2 pentatonisch
    if any(k in n for k in ["piano", "keys", "klavier", "ep "]):
        return {"root": 48, "scale": "major"}       # C3 major
    return {"root": 48, "scale": "major"}           # Default: C3 major


def set_instrument_layout(root: int = 48, scale: str = "major") -> str:
    """Setzt das Instrument-Grid-Layout auf dem Launchpad (Root-Note + Skala).

    Ändert das 8×8-Pad-Grid dynamisch — LEDs werden sofort neu gezeichnet.

    Args:
        root:  MIDI-Root-Note (z.B. 48=C3, 40=E2 für Bass, 60=C4 für Keys)
        scale: Skalentyp: "major", "minor", "pentatonic", "blues", "chromatic"
    """
    global _INST_ROOT, _INST_SCALE
    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
        client.send_message("/launchpad/layout", [root, scale])
        _INST_ROOT = root
        _INST_SCALE = {
            "minor": [0, 2, 3, 5, 7, 8, 10],
            "pentatonic": [0, 2, 4, 7, 9],
            "blues": [0, 3, 5, 6, 7, 10],
            "chromatic": list(range(12)),
        }.get(scale.lower(), [0, 2, 4, 5, 7, 9, 11])
        return f"[set_instrument_layout] root={root}, scale={scale}"
    except Exception as exc:
        return f"[set_instrument_layout] Fehler: {exc}"


@tool
def launchpad(
    action: str,
    mode: str = "session",
    notes: list[int] | None = None,
    note_data: list[dict] | None = None,
    bpm: float = 120.0,
    arm: int = 1,
    duration: float = 3.0,
    r: int = 0,
    g: int = 50,
    b: int = 63,
    root: int | str = 48,
    scale: str = "major",
) -> str:
    """Launchpad-Steuerung: Modus abfragen, Noten hervorheben, Aufnahme armen, lauschen, live spielen.

    action:
            mode     → Aktuellen Launchpad-Modus abfragen (SESSION/DRUM/INSTRUMENT)
        set_mode → Launchpad-Modus wechseln (mode="session"|"drum"|"instrument")
      suggest  → MIDI-Noten auf dem Launchpad hervorheben (notes = MIDI-Noten, z.B. [48,52,55])
      arm      → Track für Aufnahme armen/disarmen (arm=1 armt, arm=0 disarmt)
      listen   → Auf gespielte Noten lauschen (duration = Sekunden, Standard 3.0)
      play     → Notensequenz über das Launchpad in Bitwig spielen
                 (note_data = [{note, vel, dur, gap}...], bpm = Tempo)
      layout   → Instrument-Grid dynamisch konfigurieren (root=MIDI-Note, scale=Skalentyp)
                 root: int (MIDI) oder str ("E2", "C3") — scale: "major","minor","pentatonic","blues","chromatic"

    Args:
        mode:      Zielmodus für action=set_mode: session, drum oder instrument
        notes:     MIDI-Notennummern für action=suggest (z.B. [48, 52, 55])
        note_data: Notenliste für action=play, jede Note als Dict mit note/vel/dur/gap
        bpm:       Tempo für action=play (Standard 120)
        arm:       0 oder 1 für action=arm
        duration:  Lausch-Dauer in Sekunden für action=listen (Standard 3.0)
        r,g,b:     LED-Farbe 0-63 für action=suggest (Standard cyan)
        root:      Root-Note für action=layout (MIDI int oder Name "E2")
        scale:     Skalentyp für action=layout
    """
    act = (action or "").lower().strip()
    if act == "mode":
        return get_launchpad_mode()
    if act in {"set_mode", "switch_mode"}:
        return set_launchpad_mode(mode)
    if act == "suggest":
        return suggest_notes(notes or [], r=r, g=g, b=b)
    if act == "arm":
        return arm_track(arm)
    if act == "listen":
        return listen_played_notes(duration)
    if act == "play":
        return play_notes(note_data or [], bpm=bpm)
    if act == "layout":
        root_midi = _note_name_to_midi(root) if isinstance(root, str) else int(root)
        return set_instrument_layout(root_midi, scale)
    return (
        f"[launchpad] Unbekannte Aktion: '{action}'. "
        "Gültig: mode, set_mode, suggest, arm, listen, play, layout"
    )

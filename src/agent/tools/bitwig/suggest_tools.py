from __future__ import annotations
import os
import socket
import time
from langchain_core.tools import tool

_INST_ROOT = 48                        # C3
_INST_SCALE = [0, 2, 4, 5, 7, 9, 11]  # Major-Skala-Intervalle
_INST_ROW_INTERVAL = 5                 # Perfect Fourth pro Zeile

OSC_HOST         = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_LED_PORT     = int(os.getenv("LAUNCHPAD_LED_PORT", "8003"))
MODE_REPLY_PORT  = int(os.getenv("LAUNCHPAD_REPLY_PORT", "9005"))

_prev_pads: list[int] = []
_current_mode: str = "UNKNOWN"


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
    from src.agent.osc.client import configure_dgram_socket
    sock = configure_dgram_socket(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    try:
        sock.bind(("", MODE_REPLY_PORT))
    except OSError as e:
        return f"[listen_played_notes] Port {MODE_REPLY_PORT} belegt: {e}"

    from pythonosc.osc_message import OscMessage
    import time

    played: list[tuple[int, int]] = []  # (midi_note, velocity)
    sock.settimeout(0.2)
    end = time.monotonic() + duration
    try:
        while time.monotonic() < end:
            try:
                data, _ = sock.recvfrom(512)
                if b"/launchpad/note/played" not in data:
                    continue
                msg = OscMessage(data)
                if len(msg.params) >= 1:
                    note = int(msg.params[0])
                    vel  = int(msg.params[1]) if len(msg.params) >= 2 else 100
                    if (note, vel) not in played:
                        played.append((note, vel))
            except socket.timeout:
                pass
            except Exception:
                pass
    finally:
        sock.close()

    if not played:
        return f"[listen_played_notes] Keine Noten in {duration}s gespielt."

    lines = []
    for note, vel in played:
        name = _DRUM_NAMES.get(note, f"Note {note}")
        lines.append(f"  MIDI {note} — {name} (vel={vel})")
    return f"[listen_played_notes] {len(played)} Noten gespielt:\n" + "\n".join(lines)


def get_launchpad_mode() -> str:
    """Gibt den aktuellen Launchpad-Modus zurück: CONTROL, DRUM oder INSTRUMENT.

    Fragt die LaunchpadControllerExtension via OSC ab (Port 8003 → Reply auf 9005).
    """
    global _current_mode
    from src.agent.osc.client import configure_dgram_socket
    sock = configure_dgram_socket(socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    try:
        sock.bind(("", MODE_REPLY_PORT))
        sock.settimeout(2.0)
    except OSError as e:
        return f"[get_launchpad_mode] Port {MODE_REPLY_PORT} belegt: {e}"

    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
        client.send_message("/launchpad/mode/get", 1)
        data, _ = sock.recvfrom(512)
        for mode in ("CONTROL", "DRUM", "INSTRUMENT"):
            if mode.encode() in data:
                _current_mode = mode
                return f"[get_launchpad_mode] Aktueller Modus: {mode}"
        return "[get_launchpad_mode] UNKNOWN (unbekannte Antwort)"
    except socket.timeout:
        return "[get_launchpad_mode] Timeout — Launchpad Controller nicht aktiv?"
    except Exception as e:
        return f"[get_launchpad_mode] Fehler: {e}"
    finally:
        sock.close()


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
    """Wechselt den Launchpad-Modus per OSC: CONTROL, DRUM oder INSTRUMENT.

    Args:
        mode: "CONTROL", "DRUM" oder "INSTRUMENT"
    """
    mode = mode.upper().strip()
    if mode not in ("CONTROL", "DRUM", "INSTRUMENT"):
        return f"[set_launchpad_mode] Ungültiger Modus: {mode}"
    try:
        from pythonosc import udp_client
        client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
        client.send_message(f"/launchpad/mode/{mode.lower()}", 1)
        time.sleep(0.3)
        return get_launchpad_mode()
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


@tool
def launchpad(
    action: str,
    notes: list[int] | None = None,
    note_data: list[dict] | None = None,
    bpm: float = 120.0,
    arm: int = 1,
    duration: float = 3.0,
    r: int = 0,
    g: int = 50,
    b: int = 63,
) -> str:
    """Launchpad-Steuerung: Modus abfragen, Noten hervorheben, Aufnahme armen, lauschen, live spielen.

    action:
      mode     → Aktuellen Launchpad-Modus abfragen (CONTROL/DRUM/INSTRUMENT)
      suggest  → MIDI-Noten auf dem Launchpad hervorheben (notes = MIDI-Noten, z.B. [48,52,55])
      arm      → Track für Aufnahme armen/disarmen (arm=1 armt, arm=0 disarmt)
      listen   → Auf gespielte Noten lauschen (duration = Sekunden, Standard 3.0)
      play     → Notensequenz über das Launchpad in Bitwig spielen
                 (note_data = [{note, vel, dur, gap}...], bpm = Tempo)

    Args:
        notes:     MIDI-Notennummern für action=suggest (z.B. [48, 52, 55])
        note_data: Notenliste für action=play, jede Note als Dict mit note/vel/dur/gap
        bpm:       Tempo für action=play (Standard 120)
        arm:       0 oder 1 für action=arm
        duration:  Lausch-Dauer in Sekunden für action=listen (Standard 3.0)
        r,g,b:     LED-Farbe 0-63 für action=suggest (Standard cyan)
    """
    act = (action or "").lower().strip()
    if act == "mode":
        return get_launchpad_mode()
    if act == "suggest":
        return suggest_notes(notes or [], r=r, g=g, b=b)
    if act == "arm":
        return arm_track(arm)
    if act == "listen":
        return listen_played_notes(duration)
    if act == "play":
        return play_notes(note_data or [], bpm=bpm)
    return (
        f"[launchpad] Unbekannte Aktion: '{action}'. "
        "Gültig: mode, suggest, arm, listen, play"
    )

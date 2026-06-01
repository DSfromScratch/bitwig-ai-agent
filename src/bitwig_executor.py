"""
Bitwig Step-Executor — direkte Python-Funktionen, kein MCP-Overhead.

Zwei-Phasen-Workflow:
  Phase 1: execute_setup()  — Tracks, Instrumente, FX, Tempo
  Phase 2: compose_notes()  — Noten für EINEN Track pro Call

execute_result() bleibt für Rückwärtskompatibilität.
"""
import json as _json
import os
import time

from dotenv import load_dotenv
load_dotenv()

OSC_HOST            = os.getenv("BITWIG_HOST",            "127.0.0.1")
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))

_SETUP_TYPES = {"set_tempo", "add_track", "load_instrument", "append_effect",
                "set_param", "set_param_named", "set_send", "select_track", "clear_tracks"}
_NOTE_TYPES  = {"write_notes", "write_drum_pattern"}


def _check_connection(timeout: float = 1.5) -> bool:
    """Prüft BitwigAgentBridge (8001) oder BitwigStepPlugin (8002) — reicht einer."""
    try:
        from src.agent.tools.song_tools import _check_bridge
        if _check_bridge(timeout=timeout):
            return True
    except Exception:
        pass
    # Fallback: direkt BitwigStepPlugin auf Port 8002 anpingen
    try:
        import socket as _socket
        from pythonosc import udp_client as _udp
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        try:
            sock.bind(("", OSC_STEP_REPLY_PORT))
        except OSError:
            pass
        _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT).send_message("/ping", 1)
        try:
            sock.recvfrom(128)
            return True
        except _socket.timeout:
            return False
        finally:
            sock.close()
    except Exception:
        return False


def _exec_step_and_wait(client, step_json: str, timeout: float = 12.0) -> str:
    """Bindet Reply-Socket VOR dem Senden, wartet auf /step/done."""
    import socket as _socket
    import threading

    received = threading.Event()
    reply    = ["error:timeout"]

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("", OSC_STEP_REPLY_PORT))
    except OSError:
        sock.close()
        client.send_message("/step/exec", step_json)
        time.sleep(min(timeout, 0.5))
        return "ok:fallback"

    def _listen():
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _ = sock.recvfrom(4096)
                addr_end = data.find(b"\x00")
                if addr_end < 0:
                    continue
                osc_addr = data[:addr_end].decode("ascii", errors="ignore")
                if osc_addr == "/step/done":
                    tag_start = (addr_end + 4) & ~3
                    if tag_start + 2 < len(data) and data[tag_start:tag_start+2] == b",s":
                        str_start = (tag_start + 4) & ~3
                        null_pos  = data.find(b"\x00", str_start)
                        if null_pos > str_start:
                            reply[0] = data[str_start:null_pos].decode("utf-8", errors="ignore")
                        else:
                            reply[0] = "ok"
                    else:
                        reply[0] = "ok"
                    received.set()
                    return
            except (_socket.timeout, OSError):
                break

    threading.Thread(target=_listen, daemon=True).start()
    client.send_message("/step/exec", step_json)
    received.wait(timeout)
    try:
        sock.close()
    except Exception:
        pass
    return reply[0]


def _resolve_drum_pattern(step: dict) -> dict:
    """Konvertiert write_drum_pattern → write_notes via Neo4j-Lookup."""
    args    = step.get("args", {}) or {}
    track   = int(args["track_index"])
    genre   = str(args.get("genre",   "rock")).lower()
    section = str(args.get("section", "verse")).lower()
    role    = str(args.get("role",    "kick")).lower()
    pitch   = int(args.get("pitch",   36))
    slot    = int(args.get("slot",    0))
    length  = float(args.get("length_beats", 8.0))

    try:
        from src.knowledge.repositories import DrumPatternRepository
        pattern = DrumPatternRepository().find(genre=genre, section=section, energy_max=1.0)
    except Exception:
        pattern = None

    vel_on = vel_off = 0.55
    if pattern is None:
        beats = {"kick": [0.0, 2.0, 4.0, 6.0], "snare": [2.0, 6.0]}.get(
            role, [round(b * 0.5, 3) for b in range(int(length * 2))]
        )
        vel = 0.88 if role == "kick" else 0.80 if role == "snare" else 0.55
    else:
        if role == "kick":
            raw = pattern.kick_beats
            beats, vel = (raw if not isinstance(raw, str) else [0.0, 2.0, 4.0, 6.0]), pattern.kick_vel
        elif role == "snare":
            raw = pattern.snare_beats
            beats, vel = (raw if not isinstance(raw, str) else [2.0, 6.0]), pattern.snare_vel
        else:
            hat_step   = pattern.hat_step
            beats      = [round(b * hat_step, 3) for b in range(int(length / hat_step))]
            vel_on, vel_off = pattern.hat_vel_on, pattern.hat_vel_off
            vel        = vel_on

    notes = [
        {"step": float(b), "pitch": float(pitch),
         "vel": round(float(vel if role != "hihat" else (vel_on if i % 2 == 0 else vel_off)), 4),
         "dur": 0.5}
        for i, b in enumerate(beats)
    ]
    return {**step, "type": "write_notes", "args": {
        "track_index": track, "slot": slot, "length_beats": length, "notes": notes,
    }}


def _execute_steps(result: dict, label: str = "execute_result") -> str:
    """Führt alle Steps eines Result-Objekts aus. Reihenfolge: setup → notes → andere."""
    from pythonosc import udp_client as _udp
    from src.agent.events import get_event_bus

    if hasattr(result, "to_dict"):
        result = result.to_dict()
    elif hasattr(result, "model_dump") and not isinstance(result, dict):
        result = result.model_dump()

    if not _check_connection():
        return f"[{label}] BitwigStepPlugin nicht erreichbar — Bitwig starten und Extension aktivieren"

    try:
        from src.agent.tools.song_tools import _SYNCED_FROM_EXTENSION, _sync_device_uuids_from_extension
        if not _SYNCED_FROM_EXTENSION:
            _sync_device_uuids_from_extension()
    except Exception:
        pass

    steps = result.get("steps", [])
    bus   = get_event_bus()

    setup_steps, note_steps, other_steps = [], [], []
    seen_instruments: set[int] = set()

    for s in steps:
        if s.get("status") == "done":
            continue
        stype = s.get("type", "")
        args  = s.get("args", {}) or {}
        if stype in _NOTE_TYPES and args.get("instrument"):
            track = int(args.get("track_index", 0))
            if track not in seen_instruments:
                setup_steps.append({"type": "load_instrument",
                                    "args": {"track_index": track, "name": args["instrument"]}})
                seen_instruments.add(track)
            note_steps.append({**s, "args": {k: v for k, v in args.items() if k != "instrument"}})
        elif stype in _SETUP_TYPES:
            setup_steps.append(s)
        elif stype in _NOTE_TYPES:
            note_steps.append(s)
        else:
            other_steps.append(s)

    ordered = setup_steps + note_steps + other_steps
    client  = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT)
    done_log: list[str] = []
    errors:   list[str] = []

    try:
        from src.agent.project_state import BitwigProjectState
        state = BitwigProjectState.from_bitwig()
    except Exception:
        state = None

    for i, step in enumerate(ordered):
        stype = step.get("type", "")
        args  = step.get("args", {}) or {}

        if stype == "write_drum_pattern":
            try:
                step  = _resolve_drum_pattern(step)
                stype = "write_notes"
                args  = step.get("args", {})
            except Exception as e:
                errors.append(f"write_drum_pattern resolve: {e}")
                bus.emit("result_step_error", {"index": i, "type": stype, "error": str(e)})
                continue

        if stype in ("load_instrument", "append_effect") and "uuid" not in args:
            device_name = args.get("name", "")
            if device_name:
                try:
                    from src.agent.tools.song_tools import _lookup_device_uuid
                    resolved_uuid = _lookup_device_uuid(device_name)
                    if resolved_uuid:
                        args = {**args, "uuid": resolved_uuid}
                except Exception:
                    pass

        step_json = _json.dumps({"type": stype, "args": args})
        # VST-Laden braucht längere Browser-Navigation (bis zu 15s in Java)
        step_timeout = 20.0 if stype in ("load_instrument", "append_effect") and not args.get("uuid") else 12.0
        reply     = _exec_step_and_wait(client, step_json, timeout=step_timeout)

        if reply.startswith("error:precondition:track_not_found:"):
            try:
                missing_idx = int(reply.split(":")[-1])
                missing     = (state.missing_tracks_for(missing_idx) if state else missing_idx)
                for _ in range(max(1, missing)):
                    inj      = {"type": "add_track", "args": {"track_type": "instrument"}}
                    inj_json = _json.dumps(inj)
                    inj_reply = _exec_step_and_wait(client, inj_json, timeout=8.0)
                    if not inj_reply.startswith("error:"):
                        done_log.append("add_track✓(auto)")
                        if state:
                            state.apply_step(inj)
                reply = _exec_step_and_wait(client, step_json, timeout=12.0)
            except Exception as e:
                errors.append(f"{stype}✗(auto-inject failed:{e})")
                continue

        ok  = not reply.startswith("error:")
        tag = f"{stype}✓" if ok else f"{stype}✗({reply})"
        (done_log if ok else errors).append(tag)
        bus.emit("result_step_done" if ok else "result_step_error",
                 {"index": i, "type": stype, "args": args, "error": reply if not ok else ""})
        if ok and state:
            state.apply_step({**step, "type": stype, "args": args})

    context_type = result.get("context_type", "?")
    target       = result.get("target", {})
    bus.emit("result_done", {
        "context_type": context_type, "target": target,
        "summary": result.get("summary", ""),
        "steps_total": len(ordered), "done": len(done_log), "errors": errors,
    })

    try:
        from src.agent.tools.song_tools import _get_current_track_count
        track_count = _get_current_track_count()
        status_line = f"Bitwig-Status: {track_count} Track(s)" if track_count > 0 else ""
    except Exception:
        status_line = ""

    parts = [
        f"[{label}] context={context_type} target={target}",
        f"✓ {len(done_log)} Steps: {', '.join(done_log)}" if done_log else "Keine Steps",
    ]
    if errors:
        parts.append(f"✗ Fehler: {', '.join(errors)}")
    if status_line:
        parts.append(status_line)
    return "\n".join(parts)


def execute_setup(result: dict) -> str:
    """Phase 1: Tracks, Instrumente, FX, Tempo anlegen. Keine Noten.

    Lehnt write_notes / write_drum_pattern ab — dafür compose_notes verwenden.
    """
    steps = result.get("steps", []) if isinstance(result, dict) else []
    note_steps = [s for s in steps if s.get("type", "") in _NOTE_TYPES]
    if note_steps:
        types = ", ".join(s["type"] for s in note_steps)
        return (f"[execute_setup] Noten-Steps nicht erlaubt: {types} — "
                f"execute_setup nur für Setup, dann compose_notes für Noten.")
    return _execute_steps(result, label="execute_setup")


def compose_notes(result: dict) -> str:
    """Phase 2: Noten für EINEN Track schreiben.

    Pro Instrument ein separater Call. Das result-Objekt enthält:
    - track:      {index, name, instrument}  — aktueller Track
    - all_tracks: [{index, instrument}, ...]  — Gesamtkontext aus get_bitwig_track_state
    - target:     {bpm, genre, key, scale, chord_progression, section}
    - steps:      nur write_notes / write_drum_pattern / play / stop

    Beispiel Ablauf:
      compose_notes(track=Kick)   → write_drum_pattern
      compose_notes(track=Snare)  → write_drum_pattern
      compose_notes(track=Bass)   → write_notes
      compose_notes(track=Lead)   → write_notes + play
    """
    steps = result.get("steps", []) if isinstance(result, dict) else []

    track_indices = {
        int(s.get("args", {}).get("track_index", 0))
        for s in steps if s.get("type", "") in _NOTE_TYPES
    }
    if len(track_indices) > 1:
        return (f"[compose_notes] Mehrere Tracks ({sorted(track_indices)}) — "
                f"pro Instrument einen separaten compose_notes-Call verwenden.")

    setup_in = [s for s in steps if s.get("type", "") in _SETUP_TYPES]
    if setup_in:
        types = ", ".join(s["type"] for s in setup_in)
        return (f"[compose_notes] Setup-Steps nicht erlaubt: {types} — "
                f"execute_setup wurde bereits aufgerufen.")

    return _execute_steps(result, label="compose_notes")


def execute_result(result: dict) -> str:
    """Rückwärtskompatibel: Setup + Noten in einem Call.

    Für neuen Code execute_setup() + compose_notes() verwenden.
    """
    return _execute_steps(result, label="execute_result")

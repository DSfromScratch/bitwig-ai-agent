"""BitwigProjectState — Snapshot des laufenden Bitwig-Projekts.

Wird einmal zu Beginn von execute_result geladen (via OSC → Step Plugin Port 8002),
dann nach jedem erfolgreichen Step lokal aktualisiert. Kein OSC-Roundtrip pro Step.

Zweck:
  - Precondition-Feedback von Java auswerten (error:precondition:*)
  - Fehlende Prerequisite-Steps auto-injizieren (z.B. add_track wenn Track fehlt)
  - Postconditions nach Step prüfen (notes tatsächlich geschrieben?)
  - LLM-unabhängige Verifikation des Projektzustands
"""
from __future__ import annotations

import os
import socket
import struct
import time
from dataclasses import dataclass, field

OSC_HOST            = os.getenv("BITWIG_HOST",            "127.0.0.1")
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",       "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))


# ── Datenklassen ──────────────────────────────────────────────────────────────

@dataclass
class ClipState:
    slot:       int
    note_count: int = 0


@dataclass
class TrackState:
    index:      int
    name:       str
    instrument: str | None               = None
    fx:         list[str]                = field(default_factory=list)
    clips:      dict[int, ClipState]     = field(default_factory=dict)

    def has_instrument(self) -> bool:
        return self.instrument is not None

    def note_count(self, slot: int = 0) -> int:
        return self.clips.get(slot, ClipState(slot)).note_count


@dataclass
class BitwigProjectState:
    tracks:    list[TrackState]
    tempo:     float
    loaded_at: float = field(default_factory=time.time)

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_bitwig(cls) -> "BitwigProjectState":
        """Lädt Zustand aus Bitwig — fragt Step Plugin (Port 8002) via OSC."""
        tracks   = cls._load_tracks()
        note_map = cls._load_note_counts()
        for ts in tracks:
            count = note_map.get(ts.name, note_map.get(ts.name.lower(), 0))
            if count > 0:
                ts.clips[0] = ClipState(slot=0, note_count=count)
        return cls(tracks=tracks, tempo=120.0)

    @classmethod
    def empty(cls) -> "BitwigProjectState":
        return cls(tracks=[], tempo=120.0)

    # ── Lesende Abfragen ──────────────────────────────────────────────────────

    def track_count(self) -> int:
        return len(self.tracks)

    def track_exists(self, index: int) -> bool:
        return any(t.index == index for t in self.tracks)

    def get_track(self, index: int) -> TrackState | None:
        return next((t for t in self.tracks if t.index == index), None)

    def total_notes(self) -> int:
        return sum(c.note_count for t in self.tracks for c in t.clips.values())

    def missing_tracks_for(self, target_index: int) -> int:
        """Wie viele add_track-Steps fehlen damit track_index existiert."""
        return max(0, target_index - self.track_count())

    # ── Mutation nach jedem Step ──────────────────────────────────────────────

    def apply_step(self, step: dict) -> None:
        """Aktualisiert lokales Modell nach erfolgreichem Step."""
        stype = step.get("type", "")
        args  = step.get("args", {}) or {}
        track = int(args.get("track_index", 0))

        if stype == "add_track":
            new_idx = self.track_count() + 1
            self.tracks.append(TrackState(index=new_idx, name=f"Inst {new_idx}"))

        elif stype == "load_instrument":
            name = args.get("name", "")
            ts = self.get_track(track)
            if ts:
                ts.instrument = name.lower().strip()
                ts.name = name
            else:
                self.tracks.append(
                    TrackState(index=track, name=name, instrument=name.lower().strip())
                )

        elif stype == "append_effect":
            ts = self.get_track(track)
            if ts:
                ts.fx.append(args.get("name", "").lower())

        elif stype == "write_notes":
            ts    = self.get_track(track)
            slot  = int(args.get("slot", 0))
            notes = args.get("notes", [])
            count = len(notes) if isinstance(notes, list) else 0
            if ts:
                ts.clips[slot] = ClipState(slot=slot, note_count=count)

        elif stype == "set_tempo":
            self.tempo = float(args.get("bpm", self.tempo))

    # ── OSC-Loader (Step Plugin) ──────────────────────────────────────────────

    @staticmethod
    def _query(address: str, value, timeout: float = 2.0) -> bytes | None:
        from pythonosc import udp_client as _udp
        client = _udp.SimpleUDPClient(OSC_HOST, OSC_STEP_PORT, allow_broadcast=False)
        sock   = client._sock
        sock.settimeout(timeout)
        try:
            sock.bind(("", OSC_STEP_REPLY_PORT))
        except OSError:
            return None
        try:
            client.send_message(address, value)
            data, _ = sock.recvfrom(4096)
            return data
        except (socket.timeout, OSError):
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @classmethod
    def _load_tracks(cls) -> list[TrackState]:
        data = cls._query("/agent/track/count", 1)
        if not data:
            return []
        raw = data.decode("latin-1")
        idx = raw.find(",is")
        if idx < 0:
            return []
        count_start = idx + 4
        if count_start + 4 > len(data):
            return []
        count = struct.unpack(">i", data[count_start : count_start + 4])[0]
        str_start = count_start + 4
        null_pos  = data.find(b"\x00", str_start)
        names: list[str] = []
        if null_pos > str_start:
            raw_str = data[str_start:null_pos].decode("utf-8", errors="ignore")
            names   = [n for n in raw_str.split(",") if n]
        return [
            TrackState(index=i + 1, name=names[i] if i < len(names) else f"Inst {i + 1}")
            for i in range(count)
        ]

    @classmethod
    def _load_note_counts(cls) -> dict[str, int]:
        try:
            from src.agent.tools.song_tools import _get_note_counts
            return _get_note_counts()
        except Exception:
            return {}

    def __repr__(self) -> str:
        parts = ", ".join(
            f"{t.index}:{t.name}({'✓' if t.has_instrument() else '—'})"
            for t in self.tracks
        )
        return (
            f"BitwigProjectState(tracks=[{parts}], "
            f"tempo={self.tempo}, notes={self.total_notes()})"
        )

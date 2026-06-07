"""
Typisierte Pydantic-Klassen für jeden BitwigResult-Step-Typ.

Ersetzt die rohen dicts {"type": "...", "args": {...}} durch validierte Modelle.
Rückwärtskompatibel: model_dump() erzeugt exakt das dict-Format das execute_result erwartet.
"""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class _BaseStep(BaseModel):
    status: str = "pending"
    note: str = ""

    def model_dump(self, **kwargs) -> dict:
        d = super().model_dump(**kwargs)
        # args-Feld für execute_result kompatibles Format aufbauen
        args = {k: v for k, v in d.items() if k not in ("type", "status", "note")}
        return {"type": d["type"], "args": args, "status": d["status"], "note": d["note"]}


class SetTempoStep(_BaseStep):
    type: Literal["set_tempo"] = "set_tempo"
    bpm: int = Field(ge=60, le=300)


class AddTrackStep(_BaseStep):
    type: Literal["add_track"] = "add_track"
    track_type: Literal["instrument", "audio", "return"] = "instrument"


class SelectTrackStep(_BaseStep):
    type: Literal["select_track"] = "select_track"
    track_index: int


class LoadInstrumentStep(_BaseStep):
    type: Literal["load_instrument"] = "load_instrument"
    track_index: int
    name: str


class AppendEffectStep(_BaseStep):
    type: Literal["append_effect"] = "append_effect"
    track_index: int
    name: str


class SetParamStep(_BaseStep):
    type: Literal["set_param"] = "set_param"
    track_index: int | None = None
    index: int
    value: float = Field(ge=0.0, le=1.0)


class SetParamNamedStep(_BaseStep):
    type: Literal["set_param_named"] = "set_param_named"
    track_index: int | None = None
    param_name: str
    value: float


class SetSendStep(_BaseStep):
    type: Literal["set_send"] = "set_send"
    track_index: int
    send_index: int
    level: float = Field(ge=0.0, le=1.0)


class SetupDrumMachineStep(_BaseStep):
    """Lädt eine Drum Machine auf den Track und belegt Pads mit Built-in-Devices.

    pads: Liste von {pad|note, name, uuid?}. `pad` = Index 0..15 (alternativ
    `note` = 36+pad). `name`/`uuid` identifiziert das Built-in-Instrument je Pad;
    Pads ohne UUID-Treffer werden Bitwig-seitig übersprungen.
    """
    type: Literal["setup_drum_machine"] = "setup_drum_machine"
    track_index: int
    pads: list[dict] = Field(default_factory=list)


class WriteNotesStep(_BaseStep):
    type: Literal["write_notes"] = "write_notes"
    track_index: int
    notes: list[dict]       # [{step, pitch, vel, dur}]
    slot: int = 0
    length_beats: float = 8.0
    instrument: str | None = None


class WriteDrumPatternStep(_BaseStep):
    type: Literal["write_drum_pattern"] = "write_drum_pattern"
    track_index: int
    genre: str
    section: str
    role: str               # "kick" | "snare" | "hihat" | "bass"
    pitch: int = Field(ge=0, le=127)
    slot: int = 0
    length_beats: float = 8.0
    instrument: str | None = None


class PlayStep(_BaseStep):
    type: Literal["play"] = "play"


class StopStep(_BaseStep):
    type: Literal["stop"] = "stop"


# Discriminated Union — alle Step-Typen
BitwigStep = Union[
    SetTempoStep,
    AddTrackStep,
    SelectTrackStep,
    LoadInstrumentStep,
    AppendEffectStep,
    SetParamStep,
    SetParamNamedStep,
    SetSendStep,
    SetupDrumMachineStep,
    WriteNotesStep,
    WriteDrumPatternStep,
    PlayStep,
    StopStep,
]

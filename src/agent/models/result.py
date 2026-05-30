"""
BitwigResult als Pydantic-Modell + Builder-Pattern.

Löst das JSON-Truncation-Problem: Statt einem riesigen JSON-String
kann der Agent per Builder einzelne Steps hinzufügen oder execute_result
mit dem typisierten Objekt aufrufen.

Rückwärtskompatibel: BitwigResult.to_dict() erzeugt exakt das Format
das execute_result(result: dict) erwartet.
"""
from __future__ import annotations

from pydantic import BaseModel

from .steps import (
    AddTrackStep,
    AppendEffectStep,
    BitwigStep,
    LoadInstrumentStep,
    PlayStep,
    SelectTrackStep,
    SetParamNamedStep,
    SetParamStep,
    SetSendStep,
    SetTempoStep,
    StopStep,
    WriteDrumPatternStep,
    WriteNotesStep,
)


class BitwigResult(BaseModel):
    """Typisierter Ausführungsplan für execute_result.

    Ersetzt das rohe dict — validiert Steps, gibt Properties für Tempo/Track-Count.
    """
    context_type: str = "song"
    target: dict = {}
    summary: str = ""
    steps: list[BitwigStep] = []

    @property
    def tempo(self) -> int | None:
        for s in self.steps:
            if s.type == "set_tempo":
                return s.bpm  # type: ignore[attr-defined]
        return None

    @property
    def track_count(self) -> int:
        return sum(1 for s in self.steps if s.type == "add_track")

    def to_dict(self) -> dict:
        """Konvertiert zu execute_result-kompatiblem dict."""
        return {
            "context_type": self.context_type,
            "target": self.target,
            "summary": self.summary,
            "steps": [s.model_dump() for s in self.steps],
        }


class BitwigResultBuilder:
    """Builder-Pattern für BitwigResult — fluent API.

    Der Agent (oder Test-Code) baut das Result schrittweise auf.
    Core.py führt es danach via execute_plan() aus.

    Beispiel:
        result = (
            BitwigResultBuilder(bpm=120, genre="rock")
            .set_tempo(120)
            .add_track().load_instrument(1, "v9 Kick")
            .write_drum_pattern(1, genre="rock", section="intro",
                                role="kick", pitch=36)
            .play()
            .build()
        )
    """

    def __init__(self, context_type: str = "song", **target):
        self._steps: list[BitwigStep] = []
        self._context_type = context_type
        self._target: dict = target
        self._summary: str = ""

    # ── Fluent setters ────────────────────────────────────────────────────────

    def summary(self, text: str) -> "BitwigResultBuilder":
        self._summary = text
        return self

    # ── Step-Methoden ─────────────────────────────────────────────────────────

    def set_tempo(self, bpm: int) -> "BitwigResultBuilder":
        self._steps.append(SetTempoStep(bpm=bpm))
        return self

    def add_track(self, track_type: str = "instrument") -> "BitwigResultBuilder":
        self._steps.append(AddTrackStep(track_type=track_type))  # type: ignore[arg-type]
        return self

    def select_track(self, track_index: int) -> "BitwigResultBuilder":
        self._steps.append(SelectTrackStep(track_index=track_index))
        return self

    def load_instrument(self, track_index: int, name: str) -> "BitwigResultBuilder":
        self._steps.append(LoadInstrumentStep(track_index=track_index, name=name))
        return self

    def append_effect(self, track_index: int, name: str) -> "BitwigResultBuilder":
        self._steps.append(AppendEffectStep(track_index=track_index, name=name))
        return self

    def set_param(self, track_index: int | None, index: int, value: float) -> "BitwigResultBuilder":
        self._steps.append(SetParamStep(track_index=track_index, index=index, value=value))
        return self

    def set_param_named(self, param_name: str, value: float,
                        track_index: int | None = None) -> "BitwigResultBuilder":
        self._steps.append(SetParamNamedStep(track_index=track_index,
                                              param_name=param_name, value=value))
        return self

    def set_send(self, track_index: int, send_index: int, level: float) -> "BitwigResultBuilder":
        self._steps.append(SetSendStep(track_index=track_index,
                                        send_index=send_index, level=level))
        return self

    def write_notes(self, track_index: int, notes: list[dict],
                    length_beats: float = 8.0,
                    instrument: str | None = None) -> "BitwigResultBuilder":
        self._steps.append(WriteNotesStep(track_index=track_index, notes=notes,
                                           length_beats=length_beats, instrument=instrument))
        return self

    def write_drum_pattern(self, track_index: int, genre: str, section: str,
                            role: str, pitch: int,
                            length_beats: float = 8.0,
                            instrument: str | None = None) -> "BitwigResultBuilder":
        self._steps.append(WriteDrumPatternStep(
            track_index=track_index, genre=genre, section=section,
            role=role, pitch=pitch, length_beats=length_beats, instrument=instrument,
        ))
        return self

    def play(self) -> "BitwigResultBuilder":
        self._steps.append(PlayStep())
        return self

    def stop(self) -> "BitwigResultBuilder":
        self._steps.append(StopStep())
        return self

    # ── Terminal ──────────────────────────────────────────────────────────────

    def build(self) -> BitwigResult:
        return BitwigResult(
            context_type=self._context_type,
            target=self._target,
            summary=self._summary,
            steps=list(self._steps),
        )

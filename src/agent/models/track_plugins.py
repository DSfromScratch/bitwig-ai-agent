"""
Track-Plugin-System — Plugin Pattern für Step-Generierung pro Track-Typ.

Jede Subklasse von TrackPlugin ist für EINEN Track-Typ verantwortlich
und erzeugt die BitwigStep-Liste ohne I/O (pure function).

Verwendung:
  from src.agent.models.track_plugins import TRACK_PLUGINS
  steps = TRACK_PLUGINS["instrument"].build_steps(template_track, track_idx=3)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.models.project_template import TemplateTrack
    from src.agent.models.steps import BitwigStep


class TrackPlugin(ABC):
    """Basis-Plugin: erzeugt Steps für einen bestimmten Track-Typ."""

    @abstractmethod
    def build_steps(self, track: "TemplateTrack", track_idx: int) -> list["BitwigStep"]:
        ...


class InstrumentTrackPlugin(TrackPlugin):
    """
    Instrument-Track: add_track → load_instrument → append_effect(s).
    Entspricht dem häufigsten Fall in Bitwig-Projekten.
    """

    def build_steps(self, track: "TemplateTrack", track_idx: int) -> list["BitwigStep"]:
        from src.agent.models.steps import (
            AddTrackStep,
            LoadInstrumentStep,
            AppendEffectStep,
        )

        steps: list["BitwigStep"] = [AddTrackStep(track_type="instrument")]

        if track.instrument:
            steps.append(LoadInstrumentStep(
                track_index=track_idx,
                name=track.instrument,
            ))

        for fx_name in track.fx:
            steps.append(AppendEffectStep(
                track_index=track_idx,
                name=fx_name,
            ))

        return steps


class AudioTrackPlugin(TrackPlugin):
    """
    Audio-Track: add_track (type=audio).
    Audio-Tracks haben kein Instrument, aber FX-Kette.
    """

    def build_steps(self, track: "TemplateTrack", track_idx: int) -> list["BitwigStep"]:
        from src.agent.models.steps import AddTrackStep, AppendEffectStep

        steps: list["BitwigStep"] = [AddTrackStep(track_type="audio")]

        for fx_name in track.fx:
            steps.append(AppendEffectStep(
                track_index=track_idx,
                name=fx_name,
            ))

        return steps


class ReturnTrackPlugin(TrackPlugin):
    """
    Return/Send-Track: add_track (type=return) + FX.
    Typisch für Reverb/Delay Send-Busse.
    """

    def build_steps(self, track: "TemplateTrack", track_idx: int) -> list["BitwigStep"]:
        from src.agent.models.steps import AddTrackStep, AppendEffectStep

        steps: list["BitwigStep"] = [AddTrackStep(track_type="return")]

        for fx_name in track.fx:
            steps.append(AppendEffectStep(
                track_index=track_idx,
                name=fx_name,
            ))

        return steps


class GroupTrackPlugin(TrackPlugin):
    """
    Group-Track: add_track (type=group) via Bitwig-Action `create_group_track`.
    Gruppen bündeln zusammengehörige Tracks (z. B. „Drums", „Vocals"); sie tragen
    selbst kein Instrument, können aber Bus-FX (z. B. Glue-Compressor) erhalten.
    """

    def build_steps(self, track: "TemplateTrack", track_idx: int) -> list["BitwigStep"]:
        from src.agent.models.steps import AddTrackStep, AppendEffectStep

        steps: list["BitwigStep"] = [AddTrackStep(track_type="group")]

        for fx_name in track.fx:
            steps.append(AppendEffectStep(
                track_index=track_idx,
                name=fx_name,
            ))

        return steps


# ── Registry ──────────────────────────────────────────────────────────────────

TRACK_PLUGINS: dict[str, TrackPlugin] = {
    "instrument": InstrumentTrackPlugin(),
    "audio": AudioTrackPlugin(),
    "return": ReturnTrackPlugin(),
    "group": GroupTrackPlugin(),
}

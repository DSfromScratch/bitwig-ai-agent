"""
Instrument Registry — Template-System für Bitwig-Instrumente.

Instrumente werden als `InstrumentTemplate` definiert und können
genre-spezifisch überschrieben werden. `build_track_layout()` liefert
die vollständige Track-Liste für eine Session.

Verwendung:
    from src.audio.instrument_registry import build_track_layout, get_instrument

    tracks = build_track_layout("jazz")          # Jazz-Overrides aktiv
    kick   = get_instrument("kick", genre="pop") # Pop-Default-Kick
"""
from __future__ import annotations

from typing import Optional
from typing_extensions import TypedDict


class InstrumentTemplate(TypedDict):
    """Beschreibt ein einzelnes Bitwig-Instrument vollständig."""
    role:             str                   # "kick"|"snare"|"hihat"|"bass"|"chords"|"lead"|"pad"|...
    device_name:      str                   # OSC-Name für /browser/device/load
    uuid:             Optional[str]         # Bitwig Built-in UUID (sofortiges Laden ~5ms)
    midi_low:         int                   # Untergrenze des MIDI-Pitch-Bereichs
    midi_high:        int                   # Obergrenze des MIDI-Pitch-Bereichs
    default_velocity: float                 # Basis-Velocity (0.0–1.0)
    osc_track_index:  Optional[int]         # Wird zur Laufzeit gesetzt; None = automatisch


# ── Default-Registry (6 Standard-Tracks) ─────────────────────────────────────

DEFAULT_REGISTRY: dict[str, InstrumentTemplate] = {
    "kick": {
        "role": "kick",
        "device_name": "v9 Kick",
        "uuid": "32a4c607-039a-4998-be9c-578468f25454",
        "midi_low": 36,
        "midi_high": 36,
        "default_velocity": 0.88,
        "osc_track_index": None,
    },
    "snare": {
        "role": "snare",
        "device_name": "v9 Snare",
        "uuid": "90600c24-04c5-412e-b978-6d3cef1522da",
        "midi_low": 38,
        "midi_high": 38,
        "default_velocity": 0.82,
        "osc_track_index": None,
    },
    "hihat": {
        "role": "hihat",
        "device_name": "v9 Hat Closed",
        "uuid": "5c147bc8-7b62-408b-b057-c4023c4e1adb",
        "midi_low": 42,
        "midi_high": 42,
        "default_velocity": 0.55,
        "osc_track_index": None,
    },
    "bass": {
        "role": "bass",
        "device_name": "Polysynth",
        "uuid": "a9ffacb5-33e9-4fc7-8621-b1af31e410ef",
        "midi_low": 36,
        "midi_high": 60,
        "default_velocity": 0.85,
        "osc_track_index": None,
    },
    "chords": {
        "role": "chords",
        "device_name": "Phase-4",
        "uuid": "252723bf-68a6-4ee6-81f8-95ba4d0fb467",
        "midi_low": 48,
        "midi_high": 84,
        "default_velocity": 0.65,
        "osc_track_index": None,
    },
    "lead": {
        "role": "lead",
        "device_name": "FM-4",
        "uuid": "7a0a94df-3aa4-4bb5-8e24-2511999871ad",
        "midi_low": 55,
        "midi_high": 88,
        "default_velocity": 0.72,
        "osc_track_index": None,
    },
}

# Standard-Reihenfolge der Tracks im Projekt
DEFAULT_ROLE_ORDER: list[str] = ["kick", "snare", "hihat", "bass", "chords", "lead"]


# ── Genre-Overrides ───────────────────────────────────────────────────────────
# Nur abweichende Felder werden hier angegeben; der Rest kommt aus DEFAULT_REGISTRY.

_GENRE_OVERRIDES: dict[str, dict[str, dict]] = {
    "jazz": {
        "kick": {
            "device_name": "v9 Kick",
            "midi_low": 36,
            "midi_high": 36,
            "default_velocity": 0.65,   # Jazz: leichterer Kick
        },
        "snare": {
            "device_name": "v9 Snare",
            "default_velocity": 0.58,   # Brushed feel
        },
        "hihat": {
            "device_name": "v9 Hat Closed",
            "default_velocity": 0.45,   # Swing Hats leiser
        },
        "chords": {
            "device_name": "Piano",
            "uuid": None,               # Über Browser laden
            "default_velocity": 0.60,
        },
        "lead": {
            "device_name": "FM-4",
            "midi_low": 55,
            "midi_high": 84,
            "default_velocity": 0.68,
        },
    },
    "metal": {
        "kick": {
            "default_velocity": 0.98,   # Full-power Double-Kick
            "device_name": "v9 Kick",
        },
        "snare": {
            "default_velocity": 0.95,
        },
        "hihat": {
            "device_name": "v9 Hat Closed",
            "default_velocity": 0.70,   # Harder hitting
        },
        "bass": {
            "device_name": "Polysynth",
            "midi_low": 28,
            "midi_high": 48,            # Tiefer Drop-Tuning
            "default_velocity": 0.92,
        },
        "lead": {
            "device_name": "FM-4",
            "midi_low": 48,
            "midi_high": 80,
            "default_velocity": 0.88,
        },
    },
    "trap": {
        "hihat": {
            "device_name": "v9 Hat Closed",
            "default_velocity": 0.40,   # Trap-Hats sehr leise, aber dicht
        },
        "kick": {
            "device_name": "v9 Kick",
            "default_velocity": 0.92,
            "midi_low": 36,
            "midi_high": 36,
        },
        "snare": {
            "default_velocity": 0.88,
        },
        "bass": {
            "midi_low": 24,
            "midi_high": 48,            # 808-Style Subbass
            "default_velocity": 0.95,
        },
    },
    "bossa nova": {
        "kick": {
            "default_velocity": 0.60,
        },
        "snare": {
            "device_name": "v9 Rim",
            "uuid": None,               # Über Browser
            "default_velocity": 0.55,
        },
        "chords": {
            "device_name": "Piano",
            "uuid": None,
            "default_velocity": 0.58,
        },
    },
}

# Aliase für Genre-Overrides
_GENRE_OVERRIDES["hard rock"]   = _GENRE_OVERRIDES["metal"]
_GENRE_OVERRIDES["heavy metal"] = _GENRE_OVERRIDES["metal"]


# ── Öffentliche API ───────────────────────────────────────────────────────────

def get_instrument(role: str, genre: str | None = None) -> InstrumentTemplate:
    """
    Gibt das InstrumentTemplate für eine Rolle zurück.
    Genre-Override hat Vorrang über Default.

    Args:
        role:  Instrument-Rolle (z.B. "kick", "bass", "lead")
        genre: Optionaler Genre-Name für Overrides

    Returns:
        InstrumentTemplate (immer vollständig, mit Default-Fallback)

    Raises:
        KeyError: Wenn `role` weder in DEFAULT_REGISTRY noch in Overrides existiert
    """
    base = dict(DEFAULT_REGISTRY[role])  # Kopie, nicht Referenz

    if genre:
        genre_key = genre.lower().strip()
        overrides = _GENRE_OVERRIDES.get(genre_key, {}).get(role, {})
        base.update(overrides)

    return base  # type: ignore[return-value]


def build_track_layout(
    genre: str | None = None,
    roles: list[str] | None = None,
) -> list[InstrumentTemplate]:
    """
    Erstellt die vollständige Track-Liste für eine Session.

    Args:
        genre: Genre-Name für Overrides (None = alle Defaults)
        roles: Gewünschte Rollen in Reihenfolge; None = DEFAULT_ROLE_ORDER

    Returns:
        Liste von InstrumentTemplates mit befülltem `osc_track_index` (1-basiert)
    """
    role_order = roles if roles is not None else DEFAULT_ROLE_ORDER
    result: list[InstrumentTemplate] = []

    for idx, role in enumerate(role_order, start=1):
        tmpl = get_instrument(role, genre=genre)
        tmpl["osc_track_index"] = idx
        result.append(tmpl)

    return result


def registry_to_osc_list(
    layout: list[InstrumentTemplate],
) -> list[tuple[str, str]]:
    """
    Konvertiert ein Layout in die alte (device_name, role)-Tupel-Liste,
    kompatibel mit dem bisherigen `all_instruments`-Format in song_tools.py.
    """
    return [(t["device_name"], t["role"]) for t in layout]

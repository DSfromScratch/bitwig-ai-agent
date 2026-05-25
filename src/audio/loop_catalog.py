"""
Loop-Katalog: Scannt installierte Audio-Loops und indiziert sie nach
Tonart, BPM, Typ und Genre für automatische Auswahl.
"""
from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass, field

PACKAGES_BASE = Path.home() / ".BitwigStudio/installed-packages/5.0"

# Tonart-Ähnlichkeit (parallele + relative Moll-/Dur-Töne)
KEY_RELATIVES = {
    "Am": ["Am","Em","Dm","C","G","F"],
    "Em": ["Em","Am","Bm","G","D","A"],
    "Dm": ["Dm","Am","Gm","F","C","Bb"],
    "Gm": ["Gm","Dm","Cm","Bb","F","Eb"],
    "C":  ["C","Am","F","G","Dm","Em"],
    "G":  ["G","Em","D","C","Am","Bm"],
    "D":  ["D","Bm","G","A","Em","F#m"],
    "A":  ["A","F#m","E","D","Bm","C#m"],
    "E":  ["E","C#m","B","A","F#m","G#m"],
    "F":  ["F","Dm","C","Bb","Am","Gm"],
}

@dataclass
class AudioLoop:
    path:    Path
    name:    str
    bpm:     float
    key:     str
    loop_type: str  # "GuitarRiff","GuitarChords","GuitarLead","BassGuitar","GuitarStrums"
    package: str
    linux_path: str = field(default="")

    def __post_init__(self):
        self.linux_path = str(self.path)

    def key_distance(self, target_key: str) -> int:
        relatives = KEY_RELATIVES.get(target_key, [target_key])
        if self.key == target_key:
            return 0
        if self.key in relatives[:3]:
            return 1
        if self.key in relatives:
            return 2
        return 10

    def bpm_distance(self, target_bpm: float) -> float:
        return abs(self.bpm - target_bpm)

    def score(self, target_key: str, target_bpm: float) -> float:
        return self.key_distance(target_key) * 10 + self.bpm_distance(target_bpm) * 0.1


def _parse_filename(name: str) -> tuple[float, str, str]:
    """Extrahiert BPM, Tonart und Typ aus Dateinamen."""
    # Format: "Name 100bpm Am GuitarRiff.wav"
    bpm_m = re.search(r'(\d+)bpm', name, re.IGNORECASE)
    bpm = float(bpm_m.group(1)) if bpm_m else 0.0

    # Tonart (Am, Em, C, G#m etc.)
    key_m = re.search(r'\b([A-G][#b]?m?)\b', name.replace(bpm_m.group(0) if bpm_m else '', ''))
    key = key_m.group(1) if key_m else "?"

    # Typ
    types = ["GuitarLead","GuitarRiff","GuitarChords","GuitarStrums",
             "GuitarHarmonics","BassGuitar","GuitarArp"]
    loop_type = "Unknown"
    for t in types:
        if t.lower() in name.lower().replace(" ", ""):
            loop_type = t
            break

    return bpm, key, loop_type


def _classify_loop(name: str, parent_dirs: list[str]) -> str | None:
    """Bestimmt Loop-Typ — Bass und Drums ZUERST prüfen."""
    name_l = name.lower()
    dirs_l = " ".join(parent_dirs).lower()

    # 1. BASS zuerst (vor Guitar, da "Bass Guitar" Ordner "Guitar" enthält)
    if ("bassguitar" in name_l.replace(" ","") or
            "bass" in name_l or
            ("bass" in dirs_l and "guitar" not in name_l)):
        return "BassGuitar"

    # 2. DRUMS (kein Tonart-Bezug)
    if ("drum" in dirs_l or
            any(x in name_l for x in ["beat","fill","grv","groove","bd sn","hh","melodic"])):
        return "DrumLoop"

    # 3. GITARREN-TYPEN (nach Priorität)
    if "guitarlead" in name_l.replace(" ","") or (
            "lead" in name_l and "guitar" in dirs_l):
        return "GuitarLead"
    if "guitarriff" in name_l.replace(" ","") or "riff" in name_l:
        return "GuitarRiff"
    if "guitarstrums" in name_l.replace(" ","") or "strum" in name_l:
        return "GuitarStrums"
    if "guitarchords" in name_l.replace(" ","") or (
            "chord" in name_l and "guitar" in dirs_l):
        return "GuitarChords"
    if "guitar" in name_l or "guitar" in dirs_l:
        return "GuitarRiff"

    return None


def scan_loops(packages_base: Path = PACKAGES_BASE) -> list[AudioLoop]:
    """Scannt alle WAV-Loop-Dateien — Gitarren, Bass UND Drums."""
    loops = []
    for wav in packages_base.rglob("*.wav"):
        name = wav.stem
        parts = wav.relative_to(packages_base).parts
        parent_dirs = list(parts[:-1])  # alle Ordner ohne Dateinamen

        loop_type = _classify_loop(name, parent_dirs)
        if loop_type is None:
            continue

        bpm, key, _ = _parse_filename(name)
        if bpm == 0.0:
            continue

        package = parts[1] if len(parts) > 1 else "Unknown"
        loops.append(AudioLoop(
            path=wav, name=name, bpm=bpm, key=key,
            loop_type=loop_type, package=package,
        ))
    return loops


GENRE_LOOP_CONFIG = {
    "rock": {
        "drums":         1,   # Ein kompletter Drum-Loop
        "rhythm_guitar": 2,   # Wall of Sound: 2 Rhythmus-Gitarren (links/rechts)
        "lead_guitar":   1,   # Solo-Gitarre
        "bass":          1,
    },
    "metal": {
        "drums":         1,
        "rhythm_guitar": 2,
        "lead_guitar":   1,
        "bass":          1,
    },
    "pop": {
        "drums":         1,
        "rhythm_guitar": 1,
        "lead_guitar":   0,
        "bass":          1,
    },
    "jazz": {
        "drums":         1,
        "rhythm_guitar": 1,
        "lead_guitar":   1,
        "bass":          1,
    },
}

LOOP_TYPE_MAP = {
    "drums":         ["DrumLoop"],
    "rhythm_guitar": ["GuitarRiff", "GuitarChords", "GuitarStrums"],
    "lead_guitar":   ["GuitarLead"],
    "bass":          ["BassGuitar"],
}


def find_best_loops(
    loops: list[AudioLoop],
    target_key: str,
    target_bpm: float,
    needed: dict[str, int] = None,
) -> dict[str, list[AudioLoop]]:
    """
    Findet die besten Loops für jeden benötigten Typ.

    Args:
        loops:      Vollständiger Loop-Katalog
        target_key: Ziel-Tonart (z.B. "Am")
        target_bpm: Ziel-BPM
        needed:     {typ: anzahl} z.B. {"GuitarRiff":1, "BassGuitar":1, "GuitarLead":1}

    Returns:
        {typ: [AudioLoop, ...]}
    """
    if needed is None:
        needed = {"GuitarRiff": 1, "GuitarChords": 1, "BassGuitar": 1, "GuitarLead": 1}

    result = {}
    for loop_type, count in needed.items():
        candidates = [l for l in loops if l.loop_type == loop_type]
        # Tail-Dateien ausschließen
        candidates = [l for l in candidates if "Tail" not in l.name]
        if not candidates:
            # Fallback: ähnlicher Typ
            if "Guitar" in loop_type:
                candidates = [l for l in loops if "Guitar" in l.loop_type and "Tail" not in l.name]
        candidates.sort(key=lambda l: l.score(target_key, target_bpm))
        result[loop_type] = candidates[:count]

    return result


def get_linux_path(loop: AudioLoop) -> str:
    """Gibt den nativen Linux-Pfad zurück (für Bitwig)."""
    return loop.linux_path


def find_loops_for_genre(
    genre: str,
    target_key: str,
    target_bpm: float,
) -> dict[str, list["AudioLoop"]]:
    """
    Findet Loops basierend auf Genre-Regeln.
    Rock/Metal → 2 Rhythmus-Gitarren + 1 Lead + 1 Bass.
    Pop → 1 Rhythmus + 1 Bass.

    Returns: {"rhythm_guitar": [...], "lead_guitar": [...], "bass": [...]}
    """
    genre_key = genre.lower()
    for g in ["metal", "rock", "pop", "jazz"]:
        if g in genre_key:
            genre_key = g
            break
    else:
        genre_key = "pop"

    config = GENRE_LOOP_CONFIG.get(genre_key, GENRE_LOOP_CONFIG["pop"])
    loops = scan_loops()
    result = {}

    for role, count in config.items():
        if count == 0:
            continue
        allowed_types = LOOP_TYPE_MAP.get(role, [])
        candidates = [l for l in loops
                      if l.loop_type in allowed_types and "Tail" not in l.name]
        candidates.sort(key=lambda l: l.score(target_key, target_bpm))

        # Für 2 Rhythmus-Gitarren: verschiedene Loops wählen (anderes Set)
        selected = []
        used_names = set()
        for l in candidates:
            base = l.name.split("01")[0].split("02")[0].split("03")[0]
            if base not in used_names or len(selected) == 0:
                selected.append(l)
                used_names.add(base)
            if len(selected) >= count:
                break

        result[role] = selected

    return result

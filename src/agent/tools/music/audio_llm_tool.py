"""
Song-Analyse via Mac-LLM (Ollama/Qwen3-4B) oder Music Flamingo.

Implementiert `analyze_genre_structured()` das von song_memory.py importiert wird.
Analysiert Audio/MIDI-Dateien auf Genre, Tonart, Struktur, Tempo, Stimmung.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

log = logging.getLogger("bitwig-agent")

MAC_LLM_URL   = os.getenv("MAC_LLM_URL",   "http://192.168.0.4:11434")
MAC_LLM_MODEL = os.getenv("MAC_LLM_MODEL", "qwen3:4b")


def _mac_llm_available() -> bool:
    try:
        import httpx
        return httpx.get(f"{MAC_LLM_URL}/api/tags", timeout=2.0).status_code == 200
    except Exception:
        return False


def _extract_audio_features(file_path: str) -> dict:
    """Extrahiert grundlegende Audio-Features via librosa/basic-pitch."""
    features: dict[str, Any] = {"file": os.path.basename(file_path)}
    try:
        import librosa
        y, sr = librosa.load(file_path, duration=60.0)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        chroma   = librosa.feature.chroma_cqt(y=y, sr=sr)
        key_idx  = int(chroma.mean(axis=1).argmax())
        key_names = ["C","C#","D","Eb","E","F","F#","G","Ab","A","Bb","B"]
        features["bpm"]        = round(float(tempo), 1)
        features["key_index"]  = key_idx
        features["key_name"]   = key_names[key_idx]
        features["duration_s"] = round(len(y) / sr, 1)
        features["rms_energy"] = float(librosa.feature.rms(y=y).mean())
    except ImportError:
        log.debug("librosa nicht verfügbar — überspringe Feature-Extraktion")
    except Exception as exc:
        log.debug("Audio-Feature-Extraktion fehlgeschlagen: %s", exc)
    return features


def _query_mac_llm_for_analysis(features: dict, file_name: str) -> dict | None:
    """Fragt Mac-LLM nach Musik-Analyse basierend auf extrahierten Features."""
    if not _mac_llm_available():
        return None

    prompt = f"""Du bist ein Musikanalytiker. Analysiere diesen Song anhand der Audio-Features:

Datei: {file_name}
BPM: {features.get('bpm', 'unbekannt')}
Tonart: {features.get('key_name', 'unbekannt')} (Index {features.get('key_index', '?')})
Energie: {features.get('rms_energy', 'unbekannt'):.4f}
Dauer: {features.get('duration_s', '?')}s

Antworte NUR als JSON:
{{
  "genre": "<Haupt-Genre>",
  "subgenre": "<Sub-Genre>",
  "confidence": <0.0-1.0>,
  "key": "<Tonart z.B. A minor>",
  "scale": "<major/minor/pentatonic>",
  "mood": ["<Stimmung1>", "<Stimmung2>"],
  "energy_level": "<low/medium/high>",
  "tempo_feel": "<slow/medium/fast>",
  "structure_guess": "<intro/verse/chorus/bridge>",
  "recommended_devices": ["<Device1>", "<Device2>"],
  "notes": "<1-2 Sätze Beschreibung>"
}}"""

    try:
        import httpx
        response = httpx.post(
            f"{MAC_LLM_URL}/api/chat",
            json={
                "model": MAC_LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "think": False,
                "options": {"temperature": 0.2, "num_predict": 512},
            },
            timeout=30.0,
        )
        msg     = response.json().get("message", {})
        content = msg.get("content") or msg.get("thinking", "{}")
        return json.loads(content)
    except Exception as exc:
        log.warning("Mac-LLM Song-Analyse fehlgeschlagen: %s", exc)
        return None


def analyze_genre_structured(file_path: str) -> dict | None:
    """Analysiert eine Audio-Datei und gibt strukturierte Genre/Key/Mood-Daten zurück.

    Wird von song_memory.py importiert. Nutzt Mac-LLM wenn verfügbar,
    sonst rule-based Fallback.

    Returns None wenn keine Analyse möglich.
    """
    if not file_path or not Path(file_path).exists():
        log.debug("Datei nicht gefunden: %s", file_path)
        return None

    features = _extract_audio_features(file_path)
    result   = _query_mac_llm_for_analysis(features, os.path.basename(file_path))

    if result:
        result["source"]        = "mac_llm"
        result["audio_features"] = features
        log.info("[AudioLLM] %s: genre=%s confidence=%.2f",
                 os.path.basename(file_path), result.get("genre","?"),
                 result.get("confidence", 0))
        return result

    # Fallback: rule-based aus Features
    if features.get("bpm"):
        bpm = features["bpm"]
        genre = "Techno" if bpm > 130 else "Rock" if bpm > 100 else "Hip-Hop"
        return {
            "genre":      genre,
            "subgenre":   "Unknown",
            "confidence": 0.4,
            "key":        features.get("key_name", "C") + " major",
            "source":     "rule_based",
            "audio_features": features,
        }
    return None


@tool
def analyze_song(file_path: str) -> str:
    """Analysiert eine Audio-Datei (MP3/WAV/FLAC) auf Genre, Tonart, Tempo und Stimmung.

    Nutzt Mac-LLM (Qwen3-4B via Ollama) für musikalische Interpretation.
    Erfordert: Ollama auf Mac (192.168.0.4:11434) mit qwen3:4b Modell.

    Args:
        file_path: Pfad zur Audio-Datei
    """
    result = analyze_genre_structured(file_path)
    if not result:
        return f"[analyze_song] Konnte '{file_path}' nicht analysieren."

    lines = [
        f"[analyze_song] {os.path.basename(file_path)}",
        f"Genre: {result.get('genre','?')} / {result.get('subgenre','?')} "
        f"(Konfidenz: {result.get('confidence',0):.0%})",
        f"Tonart: {result.get('key','?')} | Energie: {result.get('energy_level','?')}",
        f"Stimmung: {', '.join(result.get('mood',[]))}",
    ]
    if result.get("recommended_devices"):
        lines.append(f"Empfohlene Geräte: {', '.join(result['recommended_devices'])}")
    if result.get("notes"):
        lines.append(result["notes"])
    return "\n".join(lines)

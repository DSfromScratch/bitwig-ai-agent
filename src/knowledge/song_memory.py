"""
Song-Memory: Speichert Analyse-Ergebnisse in der Vektor-DB.
Ermöglicht zukünftige Ähnlichkeits-Suchen und Genre-Vergleiche.

Collections:
  song_memory  — eine Analyse pro Song, mit allen Metriken als Metadaten
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.knowledge.neo4j_graph import session as neo4j_session


# ── Genre-Erkennung aus Metriken ─────────────────────────────────────────────

def detect_genre(
    bpm: float,
    key: str,
    present_stems: list[str],
    detected_instruments: dict[str, Any],
    midi_insights: dict | None = None,
    quality_results: list[dict] | None = None,
) -> dict:
    """
    Regelbasierte Genre-Erkennung aus Analyse-Metriken.
    Gibt Genre, Subgenre und Konfidenz zurück.
    """
    stems = set(present_stems)
    has_vocals  = "vocals" in stems
    has_guitar  = "guitar" in stems
    has_bass    = "bass"   in stems
    has_drums   = "drums"  in stems

    drums_info = detected_instruments.get("drums", {})
    other_info = detected_instruments.get("other", {})

    # Voiced ratio: niedrig = kein Melodie-Instrument
    voiced = (midi_insights or {}).get("voiced_ratio", 0.5)

    genre      = "Electronic"
    subgenre   = "Unbekannt"
    confidence = 0.4
    notes: list[str] = []

    # ── Vocals-Präsenz: Stem-Stille als besserer Indikator ───────────────────
    # voiced_ratio kommt vom vollen Mix (Synths klingen auch "voiced")
    # → Silence-Rate des Vocals-Stems ist zuverlässiger
    vocals_silence = 100.0
    if quality_results:
        for r in quality_results:
            if r["stem"] == "vocals":
                vocals_silence = r.get("silence_pct", 100.0)
    # Echte Vocals: Stem präsent UND < 60% Stille
    vocals_real = has_vocals and vocals_silence < 60.0

    # ── Dubstep / Bass Music ──────────────────────────────────────────────────
    if 135 <= bpm <= 150 and has_bass and has_drums and not vocals_real:
        genre, subgenre, confidence = "Electronic", "Dubstep", 0.75
        notes.append("BPM 135-150, Bass+Drums ohne Vocals → Dubstep-Bereich")
        if voiced < 0.15:
            subgenre = "Dark Dubstep / Experimental Bass"
            notes.append("Kaum stimmhafte Frames → stark elektronischer Charakter")

    # ── Techno ───────────────────────────────────────────────────────────────
    elif 128 <= bpm <= 145 and has_drums and not has_vocals and not has_guitar:
        genre, subgenre, confidence = "Electronic", "Techno", 0.70
        notes.append("BPM 128-145, Drums ohne Vocals/Guitar → Techno")
        if "Reverb (viel)" in str(drums_info.get("effects", "")):
            subgenre = "Industrial Techno"
            confidence = 0.75

    # ── House ─────────────────────────────────────────────────────────────────
    elif 118 <= bpm <= 132 and has_bass and has_drums:
        genre, subgenre, confidence = "Electronic", "House", 0.65
        notes.append("BPM 118-132 → House-Bereich")
        if has_vocals:
            subgenre = "Deep House / Vocal House"
            confidence = 0.70

    # ── Drum & Bass ───────────────────────────────────────────────────────────
    elif 160 <= bpm <= 185 and has_drums and has_bass:
        genre, subgenre, confidence = "Electronic", "Drum & Bass", 0.80
        notes.append("BPM 160-185 → Drum & Bass")
        if not has_vocals:
            subgenre = "Neurofunk / Dark DnB"

    # ── Hip-Hop / Trap ───────────────────────────────────────────────────────
    elif 60 <= bpm <= 100 and has_drums and has_bass:
        genre, subgenre, confidence = "Hip-Hop", "Trap / Hip-Hop", 0.65
        notes.append("BPM 60-100, Bass+Drums → Hip-Hop/Trap")
        if has_vocals:
            confidence = 0.75

    # ── Ambient ───────────────────────────────────────────────────────────────
    elif bpm < 90 and not has_drums and "Reverb" in str(other_info.get("effects", "")):
        genre, subgenre, confidence = "Ambient", "Dark Ambient", 0.60
        notes.append("Langsam, keine Drums, viel Reverb → Ambient")

    # ── Pop / Electronic Pop ──────────────────────────────────────────────────
    elif has_vocals and 95 <= bpm <= 128:
        genre, subgenre, confidence = "Pop", "Electronic Pop", 0.60
        notes.append("Vocals + moderates BPM → Pop")
        if has_guitar:
            subgenre = "Indie Pop / Alternative"

    return {
        "genre":      genre,
        "subgenre":   subgenre,
        "confidence": confidence,
        "notes":      notes,
    }


def detect_genre_semantic(
    file_path: str,
    rule_based: dict,
) -> dict:
    """
    Kombiniert Music Flamingo (semantisch) mit Regelwerk.

    Strategie:
    - MF-Konfidenz > 0.6  → MF-Ergebnis übernehmen, Regelwerk als Fallback
    - MF-Konfidenz ≤ 0.6  → Regelwerk bevorzugen, MF-Daten als Ergänzung
    - MF nicht verfügbar  → nur Regelwerk
    """
    from src.agent.tools.music.audio_llm_tool import analyze_genre_structured

    print("   → Music Flamingo Genre-Analyse...")
    mf_result = analyze_genre_structured(file_path)

    if mf_result is None:
        print("   ⚠  Music Flamingo nicht verfügbar — Regelwerk wird genutzt")
        return rule_based

    mf_conf = mf_result.get("confidence", 0.0)
    rb_conf = rule_based.get("confidence", 0.0)

    if mf_conf >= 0.6:
        # MF ist zuversichtlich — MF-Ergebnis primär
        merged = {
            "genre":      mf_result.get("genre",    rule_based["genre"]),
            "subgenre":   mf_result.get("subgenre",  rule_based["subgenre"]),
            "confidence": mf_conf,
            "source":     "music_flamingo",
            "notes":      rule_based.get("notes", []),
            # Zusatzinfos aus MF
            "mood":               mf_result.get("mood", []),
            "energy":             mf_result.get("energy", ""),
            "key_characteristics":mf_result.get("key_characteristics", []),
            "heard_instruments":  mf_result.get("heard_instruments", []),
            "production_style":   mf_result.get("production_style", ""),
            "typical_bpm_range":  mf_result.get("typical_bpm_range", ""),
            "bitwig_devices":     mf_result.get("bitwig_devices", []),
            "bitwig_tips":        mf_result.get("bitwig_tips", []),
        }
        print(f"   MF: {merged['genre']} / {merged['subgenre']} ({mf_conf:.0%})")
    else:
        # Regelwerk bleibt primär, MF-Daten als Anreicherung
        merged = {**rule_based}
        merged["source"] = "rule_based+mf"
        merged["mood"]               = mf_result.get("mood", [])
        merged["energy"]             = mf_result.get("energy", "")
        merged["key_characteristics"]= mf_result.get("key_characteristics", [])
        merged["heard_instruments"]  = mf_result.get("heard_instruments", [])
        merged["production_style"]   = mf_result.get("production_style", "")
        merged["bitwig_devices"]     = mf_result.get("bitwig_devices", [])
        merged["bitwig_tips"]        = mf_result.get("bitwig_tips", [])
        if mf_result.get("subgenre") and mf_conf > rb_conf * 0.8:
            merged["mf_suggestion"] = (
                f"{mf_result['genre']} / {mf_result['subgenre']} "
                f"({mf_conf:.0%} MF)"
            )
        print(f"   Regelwerk: {merged['genre']} / {merged['subgenre']} "
              f"({rb_conf:.0%}), MF: {mf_conf:.0%}")

    return merged


def query_genre_settings(genre: str, subgenre: str) -> str:
    """Genre-spezifische Einstellungen aus Neo4j."""
    try:
        from src.knowledge.neo4j_graph import query_for_genre
        result = query_for_genre(subgenre or genre)

        parts = []
        if result.get("devices"):
            devs = ", ".join(
                f"{d['device']} ({d['role']})"
                for d in result["devices"][:6]
            )
            parts.append(f"Devices für {subgenre}: {devs}")

        for wf in result.get("workflows", []):
            steps = (wf.get("steps") or "").split("\n")[:5]
            parts.append(
                f"Workflow '{wf['name']}':\n" +
                "\n".join(f"  {s}" for s in steps if s.strip())
            )

        return "\n\n".join(parts) if parts else f"Keine Einstellungen für {genre}/{subgenre}."
    except Exception as e:
        return f"Neo4j-Abfrage fehlgeschlagen: {e}"


# ── Song-Memory Speichern ─────────────────────────────────────────────────────

def store_song_analysis(
    file_path: str,
    analysis:  dict,
    pipeline:  dict,
    genre:     dict,
    midi_insights: dict,
) -> str:
    """Speichert Song-Analyse in Neo4j (Song-Node + Beziehungen)."""
    from src.knowledge.neo4j_graph import store_song_analysis_neo4j
    name = Path(file_path).name
    stem_analyses = {
        k: {"has_content": True, "character": v.get("detected",[""])[0] if v.get("detected") else "",
            "confidence": v.get("confidence", 0.0)}
        for k, v in pipeline.get("detected_instruments", {}).items()
    }
    store_song_analysis_neo4j(
        filename=name,
        bpm=float(analysis.get("bpm", 0)),
        key=str(analysis.get("key", "")),
        genre=genre.get("genre", ""),
        subgenre=genre.get("subgenre", ""),
        confidence=float(genre.get("confidence", 0)),
        present_stems=pipeline.get("present_stems", []),
        stem_analyses=stem_analyses,
    )
    return name


def query_song_memory(query: str, n: int = 5) -> list[dict]:
    """Sucht in vergangenen Song-Analysen in Neo4j."""
    try:
        with neo4j_session() as s:
            results = s.run("""
                MATCH (song:Song)
                WHERE toLower(song.filename) CONTAINS toLower($q)
                   OR toLower(song.key) CONTAINS toLower($q)
                RETURN song.filename AS filename, song.bpm AS bpm,
                       song.key AS key, song.confidence AS confidence
                LIMIT $n
            """, q=query, n=n).data()
            return [{"content": str(r), "metadata": r} for r in results]
    except Exception:
        return []

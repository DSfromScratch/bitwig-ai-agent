"""
Tool: create_track_from_recipe

Fügt einen einzelnen Track aus einem gelernten Projekt als neuen Track
in das aktuell geöffnete Bitwig-Projekt ein.

Nutzt SoundRecipe (Instrument, FX-Kette, Parameter) und optional
MidiClip-Noten aus einer bestimmten Szene.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def create_track_from_recipe(
    track_name: str,
    project_name: str = "Chee - Hey Now",
    scene_name: str = "",
    include_notes: bool = True,
    include_params: bool = True,
) -> str:
    """Fügt einen gelernten Track als neuen Track ins aktuelle Bitwig-Projekt ein.

    Lädt Instrument, Effekte, Parameter und MIDI-Noten aus der Wissensdatenbank
    und erstellt den Track mit einem einzigen Befehl.

    Args:
        track_name:     Name des Tracks, z.B. "Dissonant Pad", "Sharp Arp", "Sine Pluck 1"
        project_name:   Aus welchem Projekt (default: "Chee - Hey Now")
        scene_name:     Welche Szene für die Noten, z.B. "Break", "Peak"
                        Leer = erste Szene mit Noten wird genommen
        include_notes:  MIDI-Noten einfügen (default: True)
        include_params: Geräteparameter setzen (default: True)

    Returns:
        Status-Text mit den ausgeführten Steps.
    """
    import json
    from collections import Counter
    from src.knowledge.neo4j_graph import is_available, session as neo4j_session
    from src.agent.models.steps import (
        AddTrackStep, LoadInstrumentStep, AppendEffectStep,
        SetParamNamedStep, WriteNotesStep,
    )
    from src.agent.models.result import BitwigResult

    if not is_available():
        return "❌ Neo4j nicht erreichbar."

    # ── 1. SoundRecipe laden ──────────────────────────────────────────────
    with neo4j_session() as s:
        recipe = s.run("""
            MATCH (sr:SoundRecipe {project: $proj})
            WHERE toLower(sr.track_name) CONTAINS toLower($name)
            RETURN sr.track_name AS name, sr.primary_device AS inst,
                   sr.device_chain AS chain, sr.track_index AS idx,
                   sr.params_json AS pj
            ORDER BY sr.track_index LIMIT 1
        """, proj=project_name, name=track_name).single()

        if not recipe:
            # Fuzzy-Suche über alle Projekte
            recipe = s.run("""
                MATCH (sr:SoundRecipe)
                WHERE toLower(sr.track_name) CONTAINS toLower($name)
                RETURN sr.track_name AS name, sr.primary_device AS inst,
                       sr.device_chain AS chain, sr.track_index AS idx,
                       sr.params_json AS pj, sr.project AS project
                ORDER BY sr.track_index LIMIT 1
            """, name=track_name).single()
            if recipe:
                project_name = recipe.get("project", project_name)

        if not recipe:
            return (f"❌ Kein Track '{track_name}' in '{project_name}' gefunden.\n"
                    "   Verfügbare Tracks: query_knowledge verwenden.")

        # MIDI-Noten laden
        notes_data = None
        loop_beats = 8.0
        found_scene = ""
        if include_notes:
            notes_q = """
                MATCH (mc:MidiClip {project: $proj})
                WHERE toLower(mc.track_name) CONTAINS toLower($name)
                  AND mc.notes_json IS NOT NULL
            """
            params = {"proj": project_name, "name": track_name}
            if scene_name:
                notes_q += " AND toLower(mc.scene_name) CONTAINS toLower($scene)"
                params["scene"] = scene_name
            notes_q += " RETURN mc.notes_json AS nj, mc.loop_beats AS lb, mc.scene_name AS scene ORDER BY mc.scene_idx LIMIT 1"

            notes_row = s.run(notes_q, **params).single()
            if notes_row and notes_row["nj"]:
                notes_data = json.loads(notes_row["nj"])
                loop_beats = float(notes_row["lb"] or 8.0)
                found_scene = notes_row["scene"] or ""

    actual_name = recipe["name"]
    instrument  = recipe["inst"] or ""
    chain       = recipe["chain"] or ""
    params_json = recipe["pj"]

    # device_chain parsen: "Instrument: Phase-4 | FX-Kette: Chorus+ → Delay+"
    fx_list: list[str] = []
    if chain:
        if "Instrument:" in chain:
            # Neues Format: "Instrument: X | FX-Kette: A → B → C"
            instr_part = chain.split("|")[0].replace("Instrument:", "").strip()
            if not instrument:
                instrument = instr_part
            fx_part = ""
            for seg in chain.split("|"):
                if "FX-Kette:" in seg:
                    fx_part = seg.replace("FX-Kette:", "").strip()
            fx_list = [f.strip() for f in fx_part.split("→") if f.strip()] if fx_part else []
        else:
            # Altes Format: "Phase-4 → Chorus+ → Delay+"
            parts = [p.strip() for p in chain.split("→")]
            if not instrument and parts:
                instrument = parts[0]
            fx_list = parts[1:] if len(parts) > 1 else []

    lines = [f"🎛️  Track aus Wissensdatenbank: **{actual_name}** [{project_name}]"]
    if found_scene:
        lines.append(f"   Noten aus Szene: {found_scene} ({len(notes_data or [])} Noten)")
    elif include_notes and not notes_data:
        lines.append("   ℹ️  Keine MIDI-Noten gespeichert für diesen Track")

    # ── 2. Aktuellen Track-Count abfragen (für track_idx) ─────────────────
    try:
        from src.agent.osc.project_scan import _send, _osc_str_reply
        _send("/agent/track/count", 1)
        raw = _osc_str_reply("/agent/track/count/response", timeout=3.0)
        current_count = int(raw.split(",")[0]) if raw else 0
    except Exception:
        current_count = 0
    track_idx = current_count + 1

    # ── 3. Steps bauen ────────────────────────────────────────────────────
    steps = [AddTrackStep(track_type="instrument")]

    if instrument:
        steps.append(LoadInstrumentStep(track_index=track_idx, name=instrument))

    for fx in fx_list:
        if fx:
            steps.append(AppendEffectStep(track_index=track_idx, name=fx))

    if include_params and params_json:
        try:
            pages = json.loads(params_json)
            first_page = pages[0] if isinstance(pages, list) and pages else {}
            params_list = first_page.get("params", []) if isinstance(first_page, dict) else []
            for p in params_list[:8]:
                if isinstance(p, dict) and p.get("name") and p.get("value") is not None:
                    steps.append(SetParamNamedStep(
                        track_index=track_idx,
                        param_name=p["name"],
                        value=float(p["value"]),
                    ))
        except Exception:
            pass

    if include_notes and notes_data:
        steps.append(WriteNotesStep(
            track_index=track_idx,
            notes=notes_data,
            length_beats=loop_beats,
            instrument=None,
        ))

    # ── 4. Ausführen ──────────────────────────────────────────────────────
    counts = Counter(s.type for s in steps)
    lines.append(f"\n🔧 {len(steps)} Steps:")
    for typ, n in counts.most_common():
        lines.append(f"   • {typ:<25} {n}x")

    # Steps aufteilen: Phase 1 (Struktur) + Phase 2 (Noten)
    setup_steps = [s for s in steps if s.type != "write_notes"]

    result_setup = BitwigResult(
        context_type="song",
        target={"project": project_name, "track": actual_name},
        summary=f"Track aus Recipe: {actual_name}",
        steps=setup_steps,
    )

    try:
        from src.bitwig_executor import execute_setup
        status = execute_setup(result_setup.to_dict())
        lines.append(f"\n✅ Track {actual_name!r} als Track {track_idx} eingefügt")
        lines.append(f"   {status}")
        lines.append("ℹ️  Noten über Launchpad einspielen")

    except Exception as e:
        lines.append(f"\n❌ Ausführung fehlgeschlagen: {e}")

    return "\n".join(lines)

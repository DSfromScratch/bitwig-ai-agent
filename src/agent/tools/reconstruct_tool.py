"""
Tool: reconstruct_project

Rekonstruiert ein gelerntes Bitwig-Projekt vollständig aus der Wissensdatenbank:
  1. Lädt ProjectTemplate aus Neo4j (oder baut es aus SoundRecipes)
  2. Generiert WorkflowPlan: set_tempo + add_track + load_instrument +
     append_effect + set_param_named + write_notes
  3. Führt den Plan via execute_setup aus

Voraussetzung: scan_and_learn_project wurde vorher ausgeführt.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def reconstruct_project(
    project_name: str,
    include_notes: bool = True,
    include_params: bool = True,
    dry_run: bool = False,
) -> str:
    """Rekonstruiert ein Bitwig-Projekt aus der Wissensdatenbank.

    Lädt alle gelernten Informationen (Tracks, Instrumente, Effekte,
    Geräteparameter, MIDI-Noten) und erstellt das Projekt neu in Bitwig.

    Args:
        project_name:    Name des Projekts, z.B. "Chee - Hey Now"
        include_notes:   MIDI-Noten aus MidiClip-Nodes einbauen (default: True)
        include_params:  Geräteparameter aus SoundRecipe-Nodes setzen (default: True)
        dry_run:         Nur Plan anzeigen, nicht ausführen (default: False)

    Returns:
        Status-Text mit Zusammenfassung der ausgeführten Steps.
    """
    from src.knowledge.neo4j_graph import is_available, session as neo4j_session
    from src.agent.models.project_template import (
        ProjectTemplate, TemplateTrack, TemplateScene, TemplateTimelineSection,
    )
    from src.agent.models.workflow_plan import WorkflowPlan
    from src.knowledge.repositories import (
        ProjectTemplateRepository, WorkflowRepository,
    )

    if not is_available():
        return "❌ Neo4j nicht erreichbar — kann Template nicht laden."

    # ── 1. Template laden (aus Neo4j oder aus SoundRecipes aufbauen) ──────
    tmpl = ProjectTemplateRepository().load(project_name)

    if tmpl is None:
        # Fallback: Template direkt aus SoundRecipes + TimelineSections bauen
        with neo4j_session() as s:
            recipes = s.run("""
                MATCH (sr:SoundRecipe {project: $p})
                RETURN sr.track_name AS name, sr.primary_device AS inst,
                       sr.device_chain AS chain, sr.role AS role,
                       sr.track_index AS idx
                ORDER BY sr.track_index
            """, p=project_name).data()

            timeline_rows = s.run("""
                MATCH (:BitwigProject {name: $p})-[:HAS_TIMELINE]->(ts:TimelineSection)
                RETURN ts.name AS name, ts.bar AS bar, ts.beat AS beat,
                       ts.length_beats AS len
                ORDER BY ts.bar
            """, p=project_name).data()

            tempo_row = s.run(
                "MATCH (p:BitwigProject {name: $p}) RETURN p.tempo AS t",
                p=project_name,
            ).single()

        if not recipes:
            return (f"❌ Keine SoundRecipes für '{project_name}' in Neo4j.\n"
                    "   Führe zuerst scan_and_learn_project aus.")

        tempo = float(tempo_row["t"]) if tempo_row and tempo_row["t"] else 120.0
        if tempo < 20:
            tempo = 120.0  # Fallback bei 0.2 BPM Bug

        tracks = []
        for r in recipes:
            parts = [p.strip() for p in (r["chain"] or "").split("→")]
            tracks.append(TemplateTrack(
                name=r["name"], track_type="instrument",
                role=r["role"] or r["name"],
                instrument=parts[0] if parts else (r["inst"] or ""),
                fx=parts[1:] if len(parts) > 1 else [],
            ))

        tmpl = ProjectTemplate(
            name=project_name,
            tempo=tempo,
            genre="unknown",
            standalone_tracks=tracks,
            scenes=[TemplateScene(name=r["name"], position=int(r["bar"]))
                    for r in timeline_rows],
            timeline=[TemplateTimelineSection(
                name=r["name"], bar=r["bar"], beat=r["beat"],
                length_beats=r["len"] or 0,
            ) for r in timeline_rows],
        )

    lines = [f"📋 Template: **{tmpl.name}** | {len(tmpl.all_tracks())} Tracks | "
             f"{tmpl.tempo:.0f} BPM | {len(tmpl.scenes)} Szenen"]

    if tmpl.timeline:
        tl_str = ", ".join(f"{s.name}(T{int(s.bar)})" for s in tmpl.timeline[:4])
        lines.append(f"   Timeline: {tl_str}…")

    # ── 2. WorkflowPlan generieren ────────────────────────────────────────
    steps = tmpl.to_steps(
        include_notes=include_notes,
        include_params=include_params,
        project=project_name,
    )

    from collections import Counter
    counts = Counter(s.type for s in steps)
    lines.append(f"\n🔧 Plan: **{len(steps)} Steps**")
    for typ, n in counts.most_common():
        lines.append(f"   • {typ:<25} {n}x")

    if dry_run:
        lines.append("\n⚠️  dry_run=True — Plan wird nicht ausgeführt.")
        return "\n".join(lines)

    # ── 3. Plan in Neo4j speichern ────────────────────────────────────────
    plan = WorkflowPlan.from_steps(steps, context=f"Rekonstruktion {project_name}")
    plan.project_name = project_name
    plan.template_name = project_name
    wf_id = WorkflowRepository().save(plan)

    # ── 4. Altes Projekt leeren + ausführen ───────────────────────────────
    from src.agent.osc.project_scan import new_project, save_project
    import time as _time

    # Neues leeres Projekt anlegen
    lines.append("\n📄 Öffne neues Bitwig-Projekt …")
    new_project(timeout=2.0)
    _time.sleep(1.5)  # Bitwig braucht einen Moment

    lines.append(f"\n🚀 Führe Plan aus (Workflow: {wf_id}) …")
    try:
        from src.bitwig_executor import execute_setup
        status = execute_setup(plan.to_result())
        lines.append(f"✅ Ausgeführt: {status}")
        WorkflowRepository().mark_completed(wf_id)

        # Projekt speichern — Reply kommt sofort, Save-Dialog öffnet sich in Bitwig
        _time.sleep(0.5)
        save_project(timeout=2.0)
        lines.append("💾 Speicher-Dialog geöffnet in Bitwig")
        lines.append(f"   → Projektname eingeben (z.B. '{project_name} - Rekonstruiert')")
        lines.append("   → Danach unter Datei → Zuletzt geöffnet auffindbar")
    except Exception as e:
        lines.append(f"❌ Ausführung fehlgeschlagen: {e}")

    return "\n".join(lines)

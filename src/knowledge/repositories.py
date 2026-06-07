"""Repository Pattern für KB-Zugriff.

DrumPatternRepository      — liest DrumPattern-Nodes (ersetzt DRUM_PROFILES-Dict)
DrumSoundRepository        — liest GM-Pitch-Mapping aus DrumSound-Nodes
InstrumentRepository       — liest InstrumentTemplate-Nodes für Instrument-Auswahl
ProjectSnapshotRepository  — liest/schreibt BitwigProject + Scene + TrackGroup
ProjectTemplateRepository  — liest/schreibt ProjectTemplate + HNSW-Suche
WorkflowRepository         — liest/schreibt Workflow + WorkflowStep
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.knowledge.neo4j_graph import is_available, session

log = logging.getLogger("bitwig-agent.repositories")


# ── DrumPattern ───────────────────────────────────────────────────────────────

@dataclass
class DrumPatternRecord:
    kick_beats:  list[float] | str
    snare_beats: list[float]
    hat_step:    float
    hat_vel_on:  float
    hat_vel_off: float
    kick_vel:    float
    snare_vel:   float
    energy:      float
    description: str


class DrumPatternRepository:
    def find(
        self,
        genre: str,
        section: str,
        energy_max: float = 1.0,
        mood: str = "",
    ) -> DrumPatternRecord | None:
        """Gibt das passendste DrumPattern für genre + section zurück, oder None."""
        if not is_available():
            log.debug("Neo4j nicht verfügbar — DrumPatternRepository gibt None zurück")
            return None
        try:
            with session() as s:
                result = s.run(
                    """
                    MATCH (p:DrumPattern)
                    WHERE toLower(p.genre)   = toLower($genre)
                      AND toLower(p.section) = toLower($section)
                      AND p.energy           <= $energy_max
                      AND ($mood = '' OR toLower(p.mood) CONTAINS toLower($mood))
                    RETURN p
                    ORDER BY abs(p.energy - $energy_max)
                    LIMIT 1
                    """,
                    genre=genre,
                    section=section,
                    energy_max=energy_max,
                    mood=mood,
                )
                row = result.single()
                if row is None:
                    return None
                p = row["p"]
                return DrumPatternRecord(
                    kick_beats=list(p["kick_beats"]) if isinstance(p["kick_beats"], list) else p["kick_beats"],
                    snare_beats=list(p["snare_beats"]),
                    hat_step=float(p["hat_step"]),
                    hat_vel_on=float(p["hat_vel_on"]),
                    hat_vel_off=float(p["hat_vel_off"]),
                    kick_vel=float(p["kick_vel"]),
                    snare_vel=float(p["snare_vel"]),
                    energy=float(p["energy"]),
                    description=str(p.get("description", "")),
                )
        except Exception as exc:
            log.warning("DrumPatternRepository.find fehlgeschlagen: %s", exc)
            return None


# ── DrumSound ─────────────────────────────────────────────────────────────────

_GM_FALLBACK: dict[str, int] = {
    "kick": 36, "snare": 38, "closed_hat": 42,
    "open_hat": 46, "crash": 49,
}


class DrumSoundRepository:
    _cache: dict[str, int] = {}

    def pitch(self, sound_name: str) -> int:
        """Gibt den GM-MIDI-Pitch für sound_name zurück. Fällt auf Tabelle zurück."""
        if sound_name in self._cache:
            return self._cache[sound_name]

        if is_available():
            try:
                with session() as s:
                    row = s.run(
                        "MATCH (d:DrumSound {name: $n}) RETURN d.gm_pitch AS p",
                        n=sound_name,
                    ).single()
                    if row:
                        self._cache[sound_name] = int(row["p"])
                        return self._cache[sound_name]
            except Exception as exc:
                log.warning("DrumSoundRepository.pitch fehlgeschlagen: %s", exc)

        return _GM_FALLBACK.get(sound_name, 38)


# ── InstrumentTemplate ────────────────────────────────────────────────────────

@dataclass
class InstrumentRecord:
    role:             str
    device_name:      str
    uuid:             Optional[str]
    midi_low:         int
    midi_high:        int
    default_velocity: float
    description:      str


class InstrumentRepository:
    def find(
        self,
        role: str,
        genre: str,
        mood: str = "",
        limit: int = 3,
    ) -> list[InstrumentRecord]:
        """Gibt bis zu `limit` passende Devices für Rolle + Genre zurück."""
        if not is_available():
            log.debug("Neo4j nicht verfügbar — InstrumentRepository gibt [] zurück")
            return []
        try:
            with session() as s:
                result = s.run(
                    """
                    MATCH (t:InstrumentTemplate {role: $role})
                    WHERE ($genre = '' OR $genre IN t.genres)
                      AND NOT ($genre IN coalesce(t.not_for, []))
                      AND ($mood = '' OR $mood IN coalesce(t.moods, []))
                    RETURN t
                    ORDER BY
                        CASE WHEN $genre IN t.genres THEN 0 ELSE 1 END,
                        t.default_velocity DESC
                    LIMIT $limit
                    """,
                    role=role,
                    genre=genre.lower(),
                    mood=mood.lower(),
                    limit=limit,
                )
                return [
                    InstrumentRecord(
                        role=str(row["t"]["role"]),
                        device_name=str(row["t"]["device_name"]),
                        uuid=row["t"].get("uuid"),
                        midi_low=int(row["t"]["midi_low"]),
                        midi_high=int(row["t"]["midi_high"]),
                        default_velocity=float(row["t"]["default_velocity"]),
                        description=str(row["t"].get("description", "")),
                    )
                    for row in result
                ]
        except Exception as exc:
            log.warning("InstrumentRepository.find fehlgeschlagen: %s", exc)
            return []

    def find_best(self, role: str, genre: str, mood: str = "") -> InstrumentRecord | None:
        results = self.find(role, genre, mood, limit=1)
        return results[0] if results else None


# ── ProjectSnapshotRepository ─────────────────────────────────────────────────

class ProjectSnapshotRepository:
    """Persistiert BitwigProjectSnapshot als BitwigProject + Scene + TrackGroup Nodes."""

    def save(self, snap: "BitwigProjectSnapshot") -> None:  # noqa: F821
        if not is_available():
            return
        try:
            with session() as s:
                # BitwigProject-Node
                s.run("""
                    MERGE (p:BitwigProject {name: $name})
                    SET p.tempo = $tempo, p.updated_at = $ts
                """, name=snap.project_name, tempo=snap.tempo, ts=snap.loaded_at)

                # Scene-Nodes
                for sc in snap.scenes:
                    s.run("""
                        MATCH (p:BitwigProject {name: $proj})
                        MERGE (sc:Scene {idx: $idx, project: $proj})
                        SET sc.name = $name, sc.clip_count = $clip_count
                        MERGE (p)-[:HAS_SCENE]->(sc)
                    """, proj=snap.project_name, idx=sc.idx,
                         name=sc.name, clip_count=sc.clip_count)

                # TrackGroup-Nodes
                for t in snap.group_tracks():
                    s.run("""
                        MATCH (p:BitwigProject {name: $proj})
                        MERGE (g:TrackGroup {name: $name, project: $proj})
                        SET g.track_idx = $idx
                        MERGE (p)-[:HAS_GROUP]->(g)
                    """, proj=snap.project_name, name=t.name, idx=t.idx)

                # Energie-Level pro Szene berechnen + speichern
                total_tracks = len(snap.instrument_tracks())
                if total_tracks > 0:
                    for sc in snap.scenes:
                        active = sum(
                            1 for t in snap.instrument_tracks()
                            if t.clips.get(sc.idx) and t.clips[sc.idx].has_content
                        )
                        s.run("""
                            MATCH (sc:Scene {idx: $idx, project: $proj})
                            SET sc.active_tracks  = $active,
                                sc.total_tracks   = $total,
                                sc.energy_level   = $energy
                        """, idx=sc.idx, proj=snap.project_name,
                             active=active, total=total_tracks,
                             energy=round(active / total_tracks, 2))

                # SoundRecipe → alle aktiven Szenen verknüpfen
                for t in snap.instrument_tracks():
                    for sc_idx, clip in t.clips.items():
                        if not clip.has_content:
                            continue
                        s.run("""
                            MATCH (sr:SoundRecipe {track_index: $ti, project: $proj})
                            MATCH (sc:Scene {idx: $scene_idx, project: $proj})
                            MERGE (sr)-[:HAS_CLIP_IN_SCENE]->(sc)
                        """, ti=t.idx, proj=snap.project_name, scene_idx=sc_idx)
                    # Legacy: HAS_CLIP_AT (erste Szene) behalten
                    first_scene = t.first_clip_with_notes()
                    if first_scene is not None:
                        s.run("""
                            MATCH (sr:SoundRecipe {track_index: $ti, project: $proj})
                            MATCH (sc:Scene {idx: $scene_idx, project: $proj})
                            MERGE (sr)-[:HAS_CLIP_AT]->(sc)
                        """, ti=t.idx, proj=snap.project_name, scene_idx=first_scene)

                # TimelineSection-Nodes (Cue Markers)
                for sec in snap.timeline:
                    s.run("""
                        MATCH (p:BitwigProject {name: $proj})
                        MERGE (ts:TimelineSection {name: $name, project: $proj})
                        SET ts.beat         = $beat,
                            ts.bar          = $bar,
                            ts.length_beats = $length_beats,
                            ts.length_bars  = $length_bars
                        MERGE (p)-[:HAS_TIMELINE]->(ts)
                    """, proj=snap.project_name,
                         name=sec.name,
                         beat=sec.beat,
                         bar=sec.bar,
                         length_beats=sec.length_beats,
                         length_bars=round(sec.length_beats / 4.0, 1) if sec.length_beats else 0.0)

                    # TimelineSection → Scene verknüpfen (wenn Namen übereinstimmen)
                    s.run("""
                        MATCH (ts:TimelineSection {name: $name, project: $proj})
                        MATCH (sc:Scene {project: $proj})
                        WHERE toLower(sc.name) = toLower($name)
                        MERGE (ts)-[:CORRESPONDS_TO]->(sc)
                    """, proj=snap.project_name, name=sec.name)

            log.info("ProjectSnapshotRepository.save: %s gespeichert (%d Timeline-Sections)",
                     snap.project_name, len(snap.timeline))
        except Exception as exc:
            log.warning("ProjectSnapshotRepository.save fehlgeschlagen: %s", exc)

    def exists(self, name: str) -> bool:
        if not is_available():
            return False
        try:
            with session() as s:
                row = s.run(
                    "MATCH (p:BitwigProject {name: $n}) RETURN count(p) AS c",
                    n=name,
                ).single()
                return bool(row and row["c"] > 0)
        except Exception:
            return False


# ── ProjectTemplateRepository ─────────────────────────────────────────────────

class ProjectTemplateRepository:
    """Persistiert ProjectTemplate in Neo4j; unterstützt HNSW-Vektorsuche."""

    def save(self, tmpl: "ProjectTemplate") -> None:  # noqa: F821
        if not is_available():
            return
        try:
            from src.knowledge.store import get_embeddings
            content = f"ProjectTemplate: {tmpl.name} | Genre: {tmpl.genre} | " \
                      f"Tempo: {tmpl.tempo} | Szenen: {', '.join(tmpl.scene_names())} | " \
                      f"Tracks: {', '.join(t.name for t in tmpl.all_tracks())}"
            emb = get_embeddings().embed_documents([content])[0]
            with session() as s:
                s.run("""
                    MERGE (pt:ProjectTemplate {name: $name})
                    SET pt.genre       = $genre,
                        pt.tempo       = $tempo,
                        pt.key         = $key,
                        pt.mode        = $mode,
                        pt.description = $desc,
                        pt.scene_names = $scenes,
                        pt.track_names = $tracks,
                        pt.data_json   = $json,
                        pt.content     = $content,
                        pt.embedding   = $emb
                """, name=tmpl.name, genre=tmpl.genre, tempo=tmpl.tempo,
                     key=tmpl.key, mode=tmpl.mode, desc=tmpl.description,
                     scenes=tmpl.scene_names(),
                     tracks=[t.name for t in tmpl.all_tracks()],
                     json=tmpl.to_json(), content=content, emb=emb)

                # HNSW-Index
                try:
                    s.run("""
                        CREATE VECTOR INDEX project_template_embedding IF NOT EXISTS
                        FOR (n:ProjectTemplate) ON n.embedding
                        OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                               `vector.similarity_function`: 'cosine'}}
                    """)
                except Exception:
                    pass
            log.info("ProjectTemplateRepository.save: %s gespeichert", tmpl.name)
        except Exception as exc:
            log.warning("ProjectTemplateRepository.save fehlgeschlagen: %s", exc)

    def find_best_match(self, context_text: str, genre: str = "",
                        limit: int = 1) -> Optional["ProjectTemplate"]:  # noqa: F821
        """Findet passendstes Template per HNSW + Genre-Filter."""
        if not is_available():
            return None
        try:
            import json as _json
            from src.knowledge.store import get_embeddings
            from src.agent.models.project_template import ProjectTemplate
            emb = get_embeddings().embed_documents([context_text])[0]
            with session() as s:
                query = """
                    CALL db.index.vector.queryNodes('project_template_embedding', $k, $emb)
                    YIELD node, score
                """
                if genre:
                    query += " WHERE toLower(node.genre) = toLower($genre)"
                query += " RETURN node ORDER BY score DESC LIMIT 1"
                row = s.run(query, k=limit * 3, emb=emb, genre=genre).single()
                if row:
                    return ProjectTemplate.from_dict(
                        _json.loads(row["node"]["data_json"])
                    )
        except Exception as exc:
            log.warning("ProjectTemplateRepository.find_best_match: %s", exc)
        return None

    def load(self, name: str) -> Optional["ProjectTemplate"]:  # noqa: F821
        if not is_available():
            return None
        try:
            import json as _json
            from src.agent.models.project_template import ProjectTemplate
            with session() as s:
                row = s.run(
                    "MATCH (pt:ProjectTemplate {name: $n}) RETURN pt.data_json AS j",
                    n=name,
                ).single()
                if row and row["j"]:
                    return ProjectTemplate.from_dict(_json.loads(row["j"]))
        except Exception as exc:
            log.warning("ProjectTemplateRepository.load: %s", exc)
        return None


# ── WorkflowRepository ────────────────────────────────────────────────────────

class WorkflowRepository:
    """Persistiert WorkflowPlan als Workflow + WorkflowStep Nodes in Neo4j."""

    def save(self, plan: "WorkflowPlan") -> str:  # noqa: F821
        """Speichert Plan, gibt workflow_id zurück."""
        if not is_available():
            return plan.workflow_id
        try:
            import json as _json
            with session() as s:
                s.run("""
                    MERGE (w:Workflow {workflow_id: $wid})
                    SET w.context      = $ctx,
                        w.project      = $proj,
                        w.template     = $tmpl,
                        w.status       = 'pending',
                        w.created_at   = $ts,
                        w.step_count   = $n
                """, wid=plan.workflow_id, ctx=plan.context,
                     proj=plan.project_name, tmpl=plan.template_name,
                     ts=plan.created_at, n=len(plan.steps))

                for i, step in enumerate(plan.steps):
                    d = step.model_dump() if hasattr(step, "model_dump") else vars(step)
                    s.run("""
                        MATCH (w:Workflow {workflow_id: $wid})
                        MERGE (ws:WorkflowStep {workflow_id: $wid, step_order: $order})
                        SET ws.step_type = $typ,
                            ws.args_json = $args,
                            ws.status    = 'pending'
                        MERGE (w)-[:STEP {order: $order}]->(ws)
                    """, wid=plan.workflow_id, order=i,
                         typ=d.get("type", ""),
                         args=_json.dumps(d.get("args", {}), ensure_ascii=False))

                # Template verknüpfen (falls vorhanden)
                if plan.template_name:
                    s.run("""
                        MATCH (w:Workflow {workflow_id: $wid})
                        MATCH (pt:ProjectTemplate {name: $tmpl})
                        MERGE (w)-[:BASED_ON]->(pt)
                    """, wid=plan.workflow_id, tmpl=plan.template_name)

            log.info("WorkflowRepository.save: %s (%d steps)", plan.workflow_id, len(plan.steps))
        except Exception as exc:
            log.warning("WorkflowRepository.save fehlgeschlagen: %s", exc)
        return plan.workflow_id

    def update_step(self, workflow_id: str, step_order: int, status: str) -> None:
        """Aktualisiert Status eines einzelnen Steps (z.B. nach Ausführung)."""
        if not is_available():
            return
        try:
            with session() as s:
                s.run("""
                    MATCH (ws:WorkflowStep {workflow_id: $wid, step_order: $order})
                    SET ws.status = $status
                """, wid=workflow_id, order=step_order, status=status)
                # Workflow-Status aktualisieren wenn alle Steps done
                s.run("""
                    MATCH (w:Workflow {workflow_id: $wid})
                    MATCH (w)-[:STEP]->(ws:WorkflowStep)
                    WITH w, collect(ws.status) AS statuses
                    SET w.status = CASE
                        WHEN all(s IN statuses WHERE s = 'done') THEN 'completed'
                        WHEN any(s IN statuses WHERE s = 'error') THEN 'error'
                        ELSE 'running'
                    END
                """, wid=workflow_id)
        except Exception as exc:
            log.warning("WorkflowRepository.update_step: %s", exc)

    def mark_completed(self, workflow_id: str) -> None:
        if not is_available():
            return
        try:
            with session() as s:
                s.run(
                    "MATCH (w:Workflow {workflow_id: $wid}) SET w.status = 'completed'",
                    wid=workflow_id,
                )
        except Exception as exc:
            log.warning("WorkflowRepository.mark_completed: %s", exc)


# ── GenrePatternRepository ────────────────────────────────────────────────────

@dataclass
class GenrePatternRecord:
    name: str            # "Kuduro"
    bpm_avg: float
    bpm_range: list[float]   # [min, max]
    typical_keys: list[str]  # ["A minor", "E minor"]
    energy: float
    onset_steps: list[int]   # [0, 3, 7, 12]
    sources: list[str]       # YouTube-Titel
    analyzed_at: str         # ISO-Datum


class GenrePatternRepository:
    """Cached GenrePattern-Nodes: BPM, Tonart, Onset-Steps aus Audio-Analyse."""

    _INDEX_CREATED = False

    def save(self, record: GenrePatternRecord) -> None:
        if not is_available():
            return
        try:
            from src.knowledge.store import get_embeddings
            content = (
                f"Genre: {record.name} | BPM: {record.bpm_avg} | "
                f"Keys: {', '.join(record.typical_keys)} | "
                f"Energy: {record.energy} | "
                f"Onset-Steps: {record.onset_steps}"
            )
            emb = get_embeddings().embed_documents([content])[0]
            with session() as s:
                s.run("""
                    MERGE (g:GenrePattern {name: $name})
                    SET g.bpm_avg      = $bpm_avg,
                        g.bpm_min      = $bpm_min,
                        g.bpm_max      = $bpm_max,
                        g.typical_keys = $keys,
                        g.energy       = $energy,
                        g.onset_steps  = $steps,
                        g.sources      = $sources,
                        g.analyzed_at  = $ts,
                        g.content      = $content,
                        g.embedding    = $emb
                """,
                name=record.name,
                bpm_avg=record.bpm_avg,
                bpm_min=record.bpm_range[0] if record.bpm_range else record.bpm_avg,
                bpm_max=record.bpm_range[1] if len(record.bpm_range) > 1 else record.bpm_avg,
                keys=record.typical_keys,
                energy=record.energy,
                steps=record.onset_steps,
                sources=record.sources,
                ts=record.analyzed_at,
                content=content,
                emb=emb,
                )
                if not GenrePatternRepository._INDEX_CREATED:
                    try:
                        s.run("""
                            CREATE VECTOR INDEX genre_pattern_embedding IF NOT EXISTS
                            FOR (n:GenrePattern) ON n.embedding
                            OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                                   `vector.similarity_function`: 'cosine'}}
                        """)
                        GenrePatternRepository._INDEX_CREATED = True
                    except Exception:
                        pass

                # ── Relationen zu Scale-Nodes (USES_SCALE) ────────────────────
                for key_str in record.typical_keys:
                    parts = key_str.split()
                    if len(parts) >= 2:
                        root, scale_type = parts[0], parts[1]
                        s.run("""
                            MATCH (sc:Scale {root_en: $root, type: $scale_type})
                            MATCH (g:GenrePattern {name: $name})
                            MERGE (g)-[:USES_SCALE]->(sc)
                        """, root=root, scale_type=scale_type, name=record.name)

                # ── Relationen zu ähnlichen MidiClips (SIMILAR_PATTERN) ───────
                try:
                    similar_clips = s.run("""
                        CALL db.index.vector.queryNodes('midiclip_embedding', 3, $emb)
                        YIELD node AS mc, score
                        WHERE score >= 0.75
                        RETURN mc.source AS mc_source, mc.track_name AS mc_track
                    """, emb=emb).data()
                    for row in similar_clips:
                        src = row.get("mc_source") or ""
                        if src:
                            s.run("""
                                MATCH (mc:MidiClip {source: $src})
                                MATCH (g:GenrePattern {name: $name})
                                MERGE (g)-[:SIMILAR_PATTERN]->(mc)
                            """, src=src, name=record.name)
                except Exception:
                    pass

            log.info("GenrePatternRepository.save: %s gespeichert", record.name)
        except Exception as exc:
            log.warning("GenrePatternRepository.save fehlgeschlagen: %s", exc)

    def find(self, name: str) -> GenrePatternRecord | None:
        """Exakte Suche nach Genre-Name (case-insensitive)."""
        if not is_available():
            return None
        try:
            with session() as s:
                result = s.run("""
                    MATCH (g:GenrePattern)
                    WHERE toLower(g.name) = toLower($name)
                    RETURN g
                    LIMIT 1
                """, name=name).single()
            if not result:
                return None
            g = result["g"]
            return GenrePatternRecord(
                name=g["name"],
                bpm_avg=float(g.get("bpm_avg", 120)),
                bpm_range=[float(g.get("bpm_min", 0)), float(g.get("bpm_max", 0))],
                typical_keys=list(g.get("typical_keys", [])),
                energy=float(g.get("energy", 0.5)),
                onset_steps=list(g.get("onset_steps", [])),
                sources=list(g.get("sources", [])),
                analyzed_at=g.get("analyzed_at", ""),
            )
        except Exception as exc:
            log.warning("GenrePatternRepository.find: %s", exc)
            return None

    def find_similar(self, query_text: str, limit: int = 3) -> list[GenrePatternRecord]:
        """HNSW-Vektorsuche: findet ähnlichste Genre-Patterns."""
        if not is_available():
            return []
        try:
            from src.knowledge.store import get_embeddings
            emb = get_embeddings().embed_documents([query_text])[0]
            with session() as s:
                rows = s.run("""
                    CALL db.index.vector.queryNodes(
                        'genre_pattern_embedding', $k, $emb)
                    YIELD node AS g, score
                    RETURN g, score
                    ORDER BY score DESC
                """, k=limit, emb=emb).data()
            records = []
            for row in rows:
                g = row["g"]
                records.append(GenrePatternRecord(
                    name=g["name"],
                    bpm_avg=float(g.get("bpm_avg", 120)),
                    bpm_range=[float(g.get("bpm_min", 0)), float(g.get("bpm_max", 0))],
                    typical_keys=list(g.get("typical_keys", [])),
                    energy=float(g.get("energy", 0.5)),
                    onset_steps=list(g.get("onset_steps", [])),
                    sources=list(g.get("sources", [])),
                    analyzed_at=g.get("analyzed_at", ""),
                ))
            return records
        except Exception as exc:
            log.warning("GenrePatternRepository.find_similar: %s", exc)
            return []


# ── TYPE_CHECKING Imports (zirkuläre Importe vermeiden) ───────────────────────

from typing import TYPE_CHECKING  # noqa: E402
if TYPE_CHECKING:
    from src.agent.models.project_snapshot import BitwigProjectSnapshot
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.workflow_plan import WorkflowPlan

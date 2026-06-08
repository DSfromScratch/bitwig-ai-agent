"""Neo4j-Command-Klassen für strukturierte Wissensgraph-Anfragen.

Jede Klasse kapselt eine thematische Query-Gruppe (Concepts, Devices, etc.).
Commands erhalten die laufende Session von außen — eine Session wird geteilt.

Verwendung:
    with neo4j_session() as s:
        for cmd in [ConceptQuery(words), DeviceQuery(words), ...]:
            parts += cmd.execute(s)
"""
from __future__ import annotations
import json


def _fmt_params(params: list[dict], limit: int = 8) -> str:
    lines = []
    for p in params[:limit]:
        ps = f"  • {p['name']}"
        if p.get('desc'):
            ps += f": {p['desc']}"
        if p.get('low') and p.get('high'):
            ps += f" (↓{p['low']} / ↑{p['high']})"
        if p.get('tip'):
            ps += f" → {p['tip']}"
        lines.append(ps)
    return "\n".join(lines)


class ConceptQuery:
    """Bitwig-Konzepte + verwandte Devices."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        concepts = s.run("""
            MATCH (c:Concept)
            WHERE any(w IN $words WHERE toLower(c.name) CONTAINS w
                   OR toLower(coalesce(c.description,'')) CONTAINS w
                   OR toLower(coalesce(c.category,'')) CONTAINS w)
            RETURN c.name AS name, c.description AS desc,
                   c.use_case AS use_case, c.category AS category
            LIMIT 3
        """, words=self.words).data()
        if not concepts:
            return []
        lines = []
        for c in concepts:
            line = f"**{c['name']}** [{c.get('category','')}]\n  {c.get('desc','')}"
            if c.get('use_case'):
                line += f"\n  Wann: {c['use_case']}"
            related_devs = s.run("""
                MATCH (c:Concept {name: $name})-[]->(d:Device)
                RETURN d.name AS n LIMIT 5
            """, name=c['name']).data()
            if related_devs:
                line += "\n  Devices: " + ", ".join(r['n'] for r in related_devs)
            lines.append(line)
        return ["**Bitwig-Konzepte:**\n" + "\n\n".join(lines)]


class DeviceQuery:
    """Devices + Parameter + Traversal (ähnliche Devices, Workflows, Genres, Tracks)."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        devices = s.run("""
            MATCH (d:Device)
            WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w
                   OR toLower(coalesce(d.category,'')) CONTAINS w
                   OR toLower(coalesce(d.description,'')) CONTAINS w
                   OR toLower(coalesce(d.use_case,'')) CONTAINS w)
            WITH d,
                 CASE WHEN any(w IN $words WHERE toLower(d.name) CONTAINS w)
                      THEN 2 ELSE 1 END AS relevance
            ORDER BY relevance DESC
            RETURN d.name AS name, d.device_type AS type,
                   d.category AS category, d.description AS desc,
                   d.use_case AS use_case, d.tips AS tips
            LIMIT 5
        """, words=self.words).data()
        if not devices:
            return []
        dev_lines = []
        for d in devices:
            params_result = s.run("""
                MATCH (dev:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
                RETURN p.name AS name, coalesce(p.description, '') AS desc,
                       p.tip AS tip, p.low_means AS low, p.high_means AS high
                LIMIT 8
            """, name=d["name"]).data()

            similar = s.run("""
                MATCH (dev:Device {name: $name})-[:SIMILAR_TO]->(sim:Device)
                RETURN sim.name AS n, sim.description AS desc LIMIT 4
            """, name=d["name"]).data()

            wf_using = s.run("""
                MATCH (w:Workflow)-[:REQUIRES]->(dev:Device {name: $name})
                RETURN w.name AS n LIMIT 4
            """, name=d["name"]).data()

            genre_uses = s.run("""
                MATCH (g:Genre)-[r:USES]->(dev:Device {name: $name})
                RETURN g.name AS n, r.role AS role
                ORDER BY r.weight DESC LIMIT 4
            """, name=d["name"]).data()

            recipe_uses = s.run("""
                MATCH (sr:SoundRecipe)-[u:USES_DEVICE]->(dev:Device {name: $name})
                RETURN sr.project AS project, sr.track_name AS track,
                       u.is_primary AS primary
                ORDER BY u.is_primary DESC, project LIMIT 5
            """, name=d["name"]).data()

            nav = s.run("""
                MATCH (dev:Device {name: $name})
                RETURN dev.browser_tab AS tab, dev.ui_path AS path,
                       dev.ui_panel AS panel, dev.builtin_uuid AS uuid,
                       dev.load_cmd AS load_cmd
            """, name=d["name"]).single()

            line = f"**{d['name']}**"
            if d.get('desc'):
                line += f" — {d['desc']}"
            if d.get('use_case'):
                line += f"\n  Für: {d['use_case']}"
            if nav and nav.get('tab'):
                line += f"\n  📍 Wo: {nav['path'] or nav['tab']}"
                if nav.get('panel'):
                    line += f" | Panel: {nav['panel']}"
            if params_result:
                line += "\n  Parameter:\n" + _fmt_params(params_result)
            if similar:
                line += "\n  Ähnliche Devices: " + ", ".join(r['n'] for r in similar)
            if wf_using:
                line += "\n  Workflows: " + ", ".join(r['n'] for r in wf_using)
            if genre_uses:
                line += "\n  Genres: " + ", ".join(
                    f"{r['n']} ({r['role']})" for r in genre_uses)
            if recipe_uses:
                line += "\n  Benutzt in: " + ", ".join(
                    f"{r['project']}/{r['track']}"
                    + (" ★" if r.get('primary') else "")
                    for r in recipe_uses)
            if d.get('tips'):
                try:
                    tips = json.loads(d['tips']) if isinstance(d['tips'], str) else d['tips']
                    if tips:
                        line += f"\n  Tipp: {tips[0]}"
                except Exception:
                    pass
            dev_lines.append(line)
        return ["**Devices:**\n" + "\n\n".join(dev_lines)]


class GenreQuery:
    """Genre → Device-Set, Instrument-Templates + verwandte Workflows."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        genres = s.run("""
            MATCH (g:Genre)
            WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w)
            WITH g LIMIT 2
            MATCH (g)-[r:USES]->(d:Device)
            RETURN g.name AS genre, g.bpm_min AS bmin, g.bpm_max AS bmax,
                   g.description AS gdesc,
                   collect({device: d.name, role: r.role, weight: r.weight}) AS devices
        """, words=self.words).data()
        parts = []
        for g in genres:
            devs = sorted(g["devices"], key=lambda x: -(x.get("weight") or 0))
            dev_str = ", ".join(f"{d['device']} ({d['role']})" for d in devs[:8])

            templates = s.run("""
                MATCH (t:InstrumentTemplate)
                WHERE $genre IN t.genres
                RETURN t.role AS role, t.device_name AS device, t.uuid AS uuid
                ORDER BY t.role
            """, genre=g["genre"].lower()).data()

            genre_wfs = s.run("""
                MATCH (g:Genre {name: $name})-[:USED_IN|USES*1..2]-(w:Workflow)
                RETURN DISTINCT w.name AS n LIMIT 5
            """, name=g["genre"]).data()

            genre_text = (
                f"**Genre: {g['genre']}** ({g['bmin']}–{g['bmax']} BPM)\n"
                f"  Typische Devices: {dev_str}"
            )
            if templates:
                tmpl_str = ", ".join(
                    f"{t['role']}={t['device']}" + (" [builtin]" if t["uuid"] else "")
                    for t in templates
                )
                genre_text += f"\n  Empfohlene Instrumente: {tmpl_str}"
            if g.get('gdesc'):
                genre_text += f"\n  {g['gdesc']}"
            if genre_wfs:
                genre_text += "\n  Relevante Workflows: " + ", ".join(r['n'] for r in genre_wfs)
            parts.append(genre_text)
        return parts


class WorkflowQuery:
    """Recording-Workflows (priorisiert) + allgemeine Workflows mit benötigten Devices."""

    def __init__(self, words: list[str], q_lower: str):
        self.words = words
        self.q_lower = q_lower

    def execute(self, s) -> list[str]:
        parts = []
        recording_kw = {"aufnehm", "recording", "record", "arm", "clip aufnahm"}
        if any(kw in self.q_lower for kw in recording_kw):
            rec_wfs = s.run("""
                MATCH (w:Workflow)
                WHERE w.category = 'recording'
                   OR any(kw IN coalesce(w.keywords,[]) WHERE kw CONTAINS 'aufnahm' OR kw CONTAINS 'record')
                RETURN w.name AS name, w.description AS desc, w.steps AS steps
                LIMIT 3
            """).data()
            for wf in rec_wfs:
                wf_text = f"**Workflow: {wf['name']}**\n  {wf.get('desc','')}"
                steps_raw = wf.get("steps") or ""
                if steps_raw:
                    step_lines = "\n".join(
                        f"  {i+1}. {st}"
                        for i, st in enumerate(steps_raw.split("\n")[:6]) if st
                    )
                    if step_lines:
                        wf_text += "\n" + step_lines
                parts.append(wf_text)

        workflows = s.run("""
            MATCH (w:Workflow)
            WHERE any(w2 IN $words WHERE toLower(w.name) CONTAINS w2
                     OR toLower(coalesce(w.description,'')) CONTAINS w2
                     OR toLower(coalesce(w.use_case,'')) CONTAINS w2
                     OR any(kw IN coalesce(w.keywords,[]) WHERE toLower(kw) CONTAINS w2))
            RETURN w.name AS name, w.description AS desc,
                   w.steps AS steps, w.use_case AS use_case
            LIMIT 3
        """, words=self.words).data()
        for wf in workflows:
            wf_text = f"**Workflow: {wf['name']}**\n  {wf.get('desc','')}"
            if wf.get('use_case'):
                wf_text += f"\n  Wann: {wf['use_case']}"
            steps_raw = wf.get("steps") or ""
            if steps_raw:
                try:
                    steps = (json.loads(steps_raw) if steps_raw.startswith("[")
                             else steps_raw.split("\n"))
                except Exception:
                    steps = steps_raw.split("\n")
                step_lines = "\n".join(
                    f"  {i+1}. {st}" for i, st in enumerate(steps[:6]) if st
                )
                if step_lines:
                    wf_text += "\n" + step_lines

            req_devs = s.run("""
                MATCH (w:Workflow {name: $name})-[:REQUIRES]->(d:Device)
                RETURN d.name AS n LIMIT 6
            """, name=wf["name"]).data()
            if req_devs:
                wf_text += "\n  Benötigte Devices: " + ", ".join(r['n'] for r in req_devs)
            parts.append(wf_text)
        return parts


class SimilarDeviceQuery:
    """„Ähnlich wie X" — SIMILAR_TO-Traversal zwischen Devices."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        similar_query = s.run("""
            MATCH (d:Device)-[:SIMILAR_TO]->(sim:Device)
            WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w)
            RETURN d.name AS src, sim.name AS similar,
                   sim.description AS desc, sim.use_case AS use_case
            LIMIT 6
        """, words=self.words).data()
        if not similar_query:
            return []
        groups: dict[str, list] = {}
        for r in similar_query:
            groups.setdefault(r['src'], []).append(r)
        parts = []
        for src, rows in groups.items():
            sim_strs = []
            for r in rows:
                s_str = f"**{r['similar']}**"
                if r.get('desc'):
                    s_str += f": {r['desc'][:80]}"
                sim_strs.append(s_str)
            parts.append(f"**Ähnlich wie {src}:**\n" + "\n".join(f"  • {s}" for s in sim_strs))
        return parts


class ArtistQuery:
    """Gespeicherte Künstler-Profile."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        artists = s.run("""
            MATCH (a:Artist)
            WHERE any(w IN $words WHERE toLower(a.name) CONTAINS w
                   OR toLower(coalesce(a.genre,'')) CONTAINS w
                   OR toLower(coalesce(a.style,'')) CONTAINS w)
            RETURN a.name AS name, a.genre AS genre, a.bpm AS bpm,
                   a.key AS key, a.style AS style,
                   a.devices_json AS devices_json,
                   a.note_plan AS note_plan,
                   a.quality_score AS score
            ORDER BY a.quality_score DESC
            LIMIT 3
        """, words=self.words).data()
        parts = []
        for a in artists:
            try:
                devices = json.loads(a["devices_json"] or "[]")
                dev_str = ", ".join(devices[:6]) if devices else ""
            except Exception:
                dev_str = ""
            artist_text = (
                f"**Künstler: {a['name']}** [{a.get('genre','')}] "
                f"(KB-Score: {a.get('score',0):.2f})\n"
                f"  BPM: {a.get('bpm','')} | Tonart: {a.get('key','')}\n"
                f"  Stil: {a.get('style','')[:200]}"
            )
            if dev_str:
                artist_text += f"\n  Devices: {dev_str}"
            if a.get("note_plan"):
                artist_text += f"\n  Notenplan:\n    {a['note_plan'][:400]}"
            parts.append(artist_text)
        return parts


class SongQuery:
    """Gespeicherte Song-Analysen."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        songs = s.run("""
            MATCH (s:Song)
            WHERE any(w IN $words WHERE toLower(s.name) CONTAINS w
                   OR toLower(coalesce(s.artist,'')) CONTAINS w)
            RETURN s.name AS name, s.artist AS artist, s.bpm AS bpm,
                   s.key AS key, s.chord_progression AS chords,
                   s.note_plan AS note_plan,
                   s.quality_score AS score
            ORDER BY s.quality_score DESC
            LIMIT 3
        """, words=self.words).data()
        parts = []
        for sg in songs:
            song_text = (
                f"**Song: {sg['name']}** von {sg.get('artist','')} "
                f"(KB-Score: {sg.get('score',0):.2f})\n"
                f"  BPM: {sg.get('bpm','')} | Tonart: {sg.get('key','')}"
            )
            if sg.get("chords"):
                song_text += f"\n  Akkordfolge: {sg['chords']}"
            if sg.get("note_plan"):
                song_text += f"\n  Notenplan:\n    {sg['note_plan'][:400]}"
            parts.append(song_text)
        return parts


class ProductionPatternQuery:
    """ProductionPatterns + beteiligte Devices."""

    def __init__(self, words: list[str]):
        self.words = words

    def execute(self, s) -> list[str]:
        patterns = s.run("""
            MATCH (p:ProductionPattern)
            WHERE any(w IN $words WHERE toLower(p.name) CONTAINS w
                   OR toLower(coalesce(p.description,'')) CONTAINS w
                   OR toLower(coalesce(p.use_case,'')) CONTAINS w
                   OR toLower(coalesce(p.genre,'')) CONTAINS w)
            RETURN p.name AS name, p.description AS desc,
                   p.use_case AS use_case, p.approach AS approach,
                   p.difficulty AS difficulty, p.source_project AS source,
                   p.genre AS genre
            LIMIT 3
        """, words=self.words).data()
        parts = []
        for pat in patterns:
            pat_text = f"**Produktions-Muster: {pat['name']}**"
            if pat.get('genre'):
                pat_text += f" [{pat['genre']}]"
            if pat.get('source'):
                pat_text += f" — aus: {pat['source']}"
            if pat.get('desc'):
                pat_text += f"\n  {pat['desc'][:200]}"
            if pat.get('use_case'):
                pat_text += f"\n  Wann: {pat['use_case'][:150]}"
            if pat.get('approach'):
                pat_text += f"\n  Vorgehensweise: {pat['approach'][:300]}"
            if pat.get('difficulty'):
                pat_text += f"\n  Schwierigkeit: {pat['difficulty']}"

            pat_devs = s.run("""
                MATCH (p:ProductionPattern {name: $name})-[:INVOLVES]->(d:Device)
                RETURN d.name AS n LIMIT 6
            """, name=pat["name"]).data()
            if pat_devs:
                pat_text += "\n  Devices: " + ", ".join(r['n'] for r in pat_devs)
            parts.append(pat_text)
        return parts

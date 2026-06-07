from __future__ import annotations
import json
import re
from langchain_core.tools import tool


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


_STOPWORDS = {
    "was", "wie", "für", "mit", "und", "oder", "der", "die", "das",
    "for", "with", "the", "and", "how", "what", "which", "gibt", "eine",
    "einen", "einem", "welche", "welchen", "kann", "beim", "bitte",
    "machen", "mache", "sein", "sind",
}


def _extract_keywords(query: str) -> list[str]:
    """Extrahiert relevante Suchbegriffe (≥3 Zeichen, ohne Stopwörter)."""
    return [w for w in re.findall(r'\b\w{3,}\b', query.lower())
            if w not in _STOPWORDS]


def _section_concepts(s, words: list[str]) -> list[str]:
    """Bitwig-Konzepte + verwandte Devices."""
    concepts = s.run("""
        MATCH (c:Concept)
        WHERE any(w IN $words WHERE toLower(c.name) CONTAINS w
               OR toLower(coalesce(c.description,'')) CONTAINS w
               OR toLower(coalesce(c.category,'')) CONTAINS w)
        RETURN c.name AS name, c.description AS desc,
               c.use_case AS use_case, c.category AS category
        LIMIT 3
    """, words=words).data()
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


def _section_devices(s, words: list[str]) -> list[str]:
    """Devices + Parameter + Traversal (ähnliche Devices, Workflows, Genres, Tracks)."""
    # Namens-Treffer werden höher gewichtet als Beschreibungs-Treffer
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
    """, words=words).data()
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

        # Traverse: ähnliche Devices
        similar = s.run("""
            MATCH (dev:Device {name: $name})-[:SIMILAR_TO]->(sim:Device)
            RETURN sim.name AS n, sim.description AS desc LIMIT 4
        """, name=d["name"]).data()

        # Traverse: Workflows die dieses Device benötigen
        wf_using = s.run("""
            MATCH (w:Workflow)-[:REQUIRES]->(dev:Device {name: $name})
            RETURN w.name AS n LIMIT 4
        """, name=d["name"]).data()

        # Traverse: in welchen Genres verwendet
        genre_uses = s.run("""
            MATCH (g:Genre)-[r:USES]->(dev:Device {name: $name})
            RETURN g.name AS n, r.role AS role
            ORDER BY r.weight DESC LIMIT 4
        """, name=d["name"]).data()

        # Traverse: in welchen echten Projekt-Tracks verwendet (USES_DEVICE)
        recipe_uses = s.run("""
            MATCH (sr:SoundRecipe)-[u:USES_DEVICE]->(dev:Device {name: $name})
            RETURN sr.project AS project, sr.track_name AS track,
                   u.is_primary AS primary
            ORDER BY u.is_primary DESC, project LIMIT 5
        """, name=d["name"]).data()

        # Navigation / Location
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


def _section_genres(s, words: list[str]) -> list[str]:
    """Genre → Device-Set, Instrument-Templates + verwandte Workflows."""
    genres = s.run("""
        MATCH (g:Genre)
        WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w)
        WITH g LIMIT 2
        MATCH (g)-[r:USES]->(d:Device)
        RETURN g.name AS genre, g.bpm_min AS bmin, g.bpm_max AS bmax,
               g.description AS gdesc,
               collect({device: d.name, role: r.role, weight: r.weight}) AS devices
    """, words=words).data()
    parts = []
    for g in genres:
        devs = sorted(g["devices"], key=lambda x: -(x.get("weight") or 0))
        dev_str = ", ".join(f"{d['device']} ({d['role']})" for d in devs[:8])

        # InstrumentTemplates für dieses Genre
        templates = s.run("""
            MATCH (t:InstrumentTemplate)
            WHERE $genre IN t.genres
            RETURN t.role AS role, t.device_name AS device, t.uuid AS uuid
            ORDER BY t.role
        """, genre=g["genre"].lower()).data()

        # Traverse: Workflows die zu diesem Genre passen
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


def _section_workflows(s, words: list[str], q_lower: str) -> list[str]:
    """Recording-Workflows (priorisiert) + allgemeine Workflows mit benötigten Devices."""
    parts = []
    # ── 4a. Recording-Workflows priorisiert ──
    recording_kw = {"aufnehm", "recording", "record", "arm", "clip aufnahm"}
    if any(kw in q_lower for kw in recording_kw):
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
                step_lines = "\n".join(f"  {i+1}. {st}" for i, st in enumerate(steps_raw.split("\n")[:6]) if st)
                if step_lines:
                    wf_text += "\n" + step_lines
            parts.append(wf_text)

    # ── 4. Workflows + benötigte Devices ──
    workflows = s.run("""
        MATCH (w:Workflow)
        WHERE any(w2 IN $words WHERE toLower(w.name) CONTAINS w2
                 OR toLower(coalesce(w.description,'')) CONTAINS w2
                 OR toLower(coalesce(w.use_case,'')) CONTAINS w2
                 OR any(kw IN coalesce(w.keywords,[]) WHERE toLower(kw) CONTAINS w2))
        RETURN w.name AS name, w.description AS desc,
               w.steps AS steps, w.use_case AS use_case
        LIMIT 3
    """, words=words).data()
    for wf in workflows:
        wf_text = f"**Workflow: {wf['name']}**\n  {wf.get('desc','')}"
        if wf.get('use_case'):
            wf_text += f"\n  Wann: {wf['use_case']}"
        steps_raw = wf.get("steps") or ""
        if steps_raw:
            try:
                steps = json.loads(steps_raw) if steps_raw.startswith("[") else steps_raw.split("\n")
            except Exception:
                steps = steps_raw.split("\n")
            step_lines = "\n".join(f"  {i+1}. {st}" for i, st in enumerate(steps[:6]) if st)
            if step_lines:
                wf_text += "\n" + step_lines

        # Traverse: welche Devices braucht dieser Workflow?
        req_devs = s.run("""
            MATCH (w:Workflow {name: $name})-[:REQUIRES]->(d:Device)
            RETURN d.name AS n LIMIT 6
        """, name=wf["name"]).data()
        if req_devs:
            wf_text += "\n  Benötigte Devices: " + ", ".join(r['n'] for r in req_devs)
        parts.append(wf_text)
    return parts


def _section_similar_devices(s, words: list[str]) -> list[str]:
    """„Ähnlich wie X" — SIMILAR_TO-Traversal zwischen Devices."""
    similar_query = s.run("""
        MATCH (d:Device)-[:SIMILAR_TO]->(sim:Device)
        WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w)
        RETURN d.name AS src, sim.name AS similar,
               sim.description AS desc, sim.use_case AS use_case
        LIMIT 6
    """, words=words).data()
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


def _section_artists(s, words: list[str]) -> list[str]:
    """Gespeicherte Künstler-Profile."""
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
    """, words=words).data()
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


def _section_songs(s, words: list[str]) -> list[str]:
    """Gespeicherte Song-Analysen."""
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
    """, words=words).data()
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


def _section_production_patterns(s, words: list[str]) -> list[str]:
    """ProductionPatterns + beteiligte Devices."""
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
    """, words=words).data()
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

        # Traverse: welche Devices sind beteiligt?
        pat_devs = s.run("""
            MATCH (p:ProductionPattern {name: $name})-[:INVOLVES]->(d:Device)
            RETURN d.name AS n LIMIT 6
        """, name=pat["name"]).data()
        if pat_devs:
            pat_text += "\n  Devices: " + ", ".join(r['n'] for r in pat_devs)
        parts.append(pat_text)
    return parts


def _query_neo4j(query: str) -> str:
    """Sucht im Neo4j-Graph nach Devices, Parametern, Presets, Concepts und Genres."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
    except Exception:
        return ""

    words = _extract_keywords(query)
    if not words:
        return ""
    q_lower = query.lower()

    parts: list[str] = []
    try:
        with neo4j_session() as s:
            parts += _section_concepts(s, words)
            parts += _section_devices(s, words)
            parts += _section_genres(s, words)
            parts += _section_workflows(s, words, q_lower)
            parts += _section_similar_devices(s, words)
            parts += _section_artists(s, words)
            parts += _section_songs(s, words)
            parts += _section_production_patterns(s, words)
    except Exception as e:
        return f"[Neo4j Fehler: {e}]"

    return "\n\n".join(parts)


@tool
def query_bitwig_docs(query: str, n_results: int = 6) -> str:
    """Durchsucht die Bitwig-Wissensdatenbank (Neo4j Graph + Vektorsuche).

    Kombiniert strukturierten Graph-Traversal mit semantischer Suche:
    - Devices mit Parametern, ähnlichen Devices (SIMILAR_TO), relevanten Workflows
    - Genre → Device-Sets mit Rollen und verwandten Workflows
    - Workflows → benötigte Devices
    - Concepts → verknüpfte Devices
    - Semantische Vektorsuche für kontextuelle Treffer

    Nutze dieses Tool für:
    - Genre-spezifische Device-Empfehlungen ("Techno Bass", "Ambient Pad")
    - Geräteparameter und Einstellungen ("SVF Resonance", "Compressor Threshold")
    - Alternativen zu einem Device ("ähnlich wie Low-pass LD")
    - Workflows mit Schritt-für-Schritt-Anleitung ("Sidechain Kompression")
    - Kontext-übergreifende Fragen ("Kick klingt dünn", "warmer Pad-Sound")

    Args:
        query: Suchanfrage auf Deutsch oder Englisch
        n_results: Anzahl ChromaDB-Ergebnisse (Standard: 6)
    """
    results = []

    # ── Installierte VST-Plugins (InstalledPlugin Knoten) ─────────────────
    q_lower = query.lower()
    vst_keywords = {"vst", "plugin", "plug-in", "installiert", "installed",
                    "bass", "drum", "gitarre", "guitar", "synth", "surge", "dexed",
                    "ujam", "vb-", "vg-", "vd-", "welche", "which", "available"}
    if any(k in q_lower for k in vst_keywords):
        try:
            from src.knowledge.vst_scanner import query_installed_plugins
            plugins = query_installed_plugins()
            if plugins:
                by_type: dict[str, list[str]] = {}
                for p in plugins:
                    by_type.setdefault(p["type"], []).append(p["name"])
                lines = ["## Installierte VST3-Plugins\n"]
                for t, names in sorted(by_type.items()):
                    lines.append(f"**{t.capitalize()}**: {', '.join(f'`{n}`' for n in names)}")
                results.append("\n".join(lines))
        except Exception:
            pass

    # ── Neo4j Graph-Suche ──────────────────────────────────────────────────
    neo4j_result = _query_neo4j(query)
    if neo4j_result:
        results.append("## Bitwig-Graph (Devices, Parameter, Presets)\n\n" + neo4j_result)

    # ── Neo4j Vektor-Suche via HNSW-Index (Fix: kein Brute-Force-Scan) ───────
    _SCORE_MIN_DOC = 0.70   # Mindest-Score für Docs / Q&A
    _SCORE_MIN_YT  = 0.75   # Strenger für YouTube-Transkripte (mehr Rauschen)

    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
        from src.knowledge.store import get_embeddings
        emb = get_embeddings().embed_query(query)
        with neo4j_session() as s:
            # Documents: HNSW-Index statt Brute-Force-Scan
            raw_docs = s.run("""
                CALL db.index.vector.queryNodes('document_embedding', $k, $emb)
                YIELD node AS d, score
                RETURN d.content AS content, d.source AS source,
                       d.doc_type AS doc_type, d.video_url AS video_url,
                       'doc' AS kind, score
            """, k=8, emb=emb).data()

            # SoundRecipes (live aus Bitwig-Projekten): eigener Index
            sr_count = s.run("MATCH (n:SoundRecipe) RETURN count(n) AS c").single()["c"]
            raw_recipes: list[dict] = []
            if sr_count > 0:
                raw_recipes = s.run("""
                    CALL db.index.vector.queryNodes('sound_recipe_embedding', 4, $emb)
                    YIELD node AS n, score
                    OPTIONAL MATCH (a:AudioSample)-[:SAMPLED_IN]->(n)
                    WITH n, score, collect(DISTINCT a.filename)[..5] AS samples
                    RETURN n.content AS content, n.source AS source,
                           n.project AS project, n.role AS role,
                           samples AS samples,
                           null AS doc_type, null AS video_url,
                           'recipe' AS kind, score
                """, emb=emb).data()

            # AudioSamples (WAV-Analyse aus Bitwig-Projekten)
            as_count = s.run("MATCH (n:AudioSample) RETURN count(n) AS c").single()["c"]
            raw_audio: list[dict] = []
            if as_count > 0:
                raw_audio = s.run("""
                    CALL db.index.vector.queryNodes('audio_sample_embedding', 3, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.source AS source,
                           n.project AS project, n.category AS role,
                           null AS doc_type, null AS video_url,
                           'audio' AS kind, score
                """, emb=emb).data()

            # Grid-Module + Workflow-Patterns
            gm_count = s.run("MATCH (n:GridModule) RETURN count(n) AS c").single()["c"]
            raw_grid: list[dict] = []
            if gm_count > 0:
                raw_grid = s.run("""
                    CALL db.index.vector.queryNodes('gridmodule_embedding', 3, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.source AS source,
                           n.category AS role, null AS doc_type, null AS video_url,
                           'grid' AS kind, score
                """, emb=emb).data()
                gw = s.run("""
                    CALL db.index.vector.queryNodes('gridworkflow_embedding', 2, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.source AS source,
                           'workflow' AS role, null AS doc_type, null AS video_url,
                           'grid' AS kind, score
                """, emb=emb).data()
                raw_grid += gw

            # GridAnalysis (Claude Vision Analysen von Grid-Patches)
            ga_count = s.run("MATCH (n:GridAnalysis) RETURN count(n) AS c").single()["c"]
            raw_ga: list[dict] = []
            if ga_count > 0:
                raw_ga = s.run("""
                    CALL db.index.vector.queryNodes('gridanalysis_embedding', 2, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.source AS source,
                           'GridAnalysis' AS role, null AS doc_type, null AS video_url,
                           'grid' AS kind, score
                """, emb=emb).data()

            # MidiClip-Nodes (MIDI-Analyse: Key, Akkorde, Rhythmus)
            mc_count = s.run("MATCH (n:MidiClip) RETURN count(n) AS c").single()["c"]
            raw_midi: list[dict] = []
            if mc_count > 0:
                raw_midi = s.run("""
                    CALL db.index.vector.queryNodes('midiclip_embedding', 3, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.source AS source,
                           n.full_key AS role, null AS doc_type, null AS video_url,
                           'midi' AS kind, score
                """, emb=emb).data()

            # Artist-Nodes (Vektorsuche)
            ar_count = s.run("MATCH (n:Artist) RETURN count(n) AS c").single()["c"]
            raw_artists: list[dict] = []
            if ar_count > 0:
                raw_artists = s.run("""
                    CALL db.index.vector.queryNodes('artist_embedding', 3, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.name AS source,
                           'artist' AS role, null AS doc_type, null AS video_url,
                           'artist' AS kind, score
                """, emb=emb).data()

            # Song-Nodes (Vektorsuche)
            so_count = s.run("MATCH (n:Song) RETURN count(n) AS c").single()["c"]
            raw_songs: list[dict] = []
            if so_count > 0:
                raw_songs = s.run("""
                    CALL db.index.vector.queryNodes('song_embedding', 3, $emb)
                    YIELD node AS n, score
                    RETURN n.content AS content, n.name AS source,
                           'song' AS role, null AS doc_type, null AS video_url,
                           'song' AS kind, score
                """, emb=emb).data()

            # GenrePattern: BPM + Tonart + Onset-Steps aus Audio-Analyse
            gp_count = s.run("MATCH (g:GenrePattern) RETURN count(g) AS c").single()["c"]
            raw_genre = []
            if gp_count > 0:
                raw_genre = s.run("""
                    CALL db.index.vector.queryNodes('genre_pattern_embedding', 3, $emb)
                    YIELD node AS g, score
                    RETURN g.content AS content,
                           g.name    AS source,
                           null AS role, null AS doc_type, null AS video_url,
                           'genre_pattern' AS kind, score
                """, emb=emb).data()

            raw_docs = raw_docs + raw_recipes + raw_audio + raw_grid + raw_ga + raw_midi + raw_genre + raw_artists + raw_songs

            # Score-Threshold: YouTube strenger als strukturierte Docs
            docs = [
                d for d in raw_docs
                if d["score"] >= (_SCORE_MIN_YT if d.get("doc_type") == "youtube_transcript"
                                  else _SCORE_MIN_DOC)
            ]

            # NEXT_CHUNK Context-Fetch: zum besten YouTube-Treffer Nachbar-Chunk laden
            yt_hit = next((d for d in docs if d.get("doc_type") == "youtube_transcript"), None)
            if yt_hit:
                neighbor = s.run("""
                    MATCH (hit:Document {source: $src})-[:NEXT_CHUNK]->(nxt:Document)
                    RETURN nxt.content AS content, nxt.source AS source,
                           nxt.doc_type AS doc_type, nxt.video_url AS video_url,
                           0.0 AS score
                    LIMIT 1
                """, src=yt_hit["source"]).single()
                if neighbor and neighbor["source"] not in {d["source"] for d in docs}:
                    docs.append({**dict(neighbor), "kind": "doc", "score": 0.0, "_context": True})

            # KnowledgeQA: HNSW-Index, nur wenn Nodes vorhanden
            qa_count = s.run("MATCH (k:KnowledgeQA) RETURN count(k) AS c").single()["c"]
            raw_qa = []
            if qa_count > 0:
                raw_qa = s.run("""
                    CALL db.index.vector.queryNodes('knowledgeqa_embedding', 6, $emb)
                    YIELD node AS k, score
                    RETURN coalesce(k.text, k.content, '') AS content, k.source AS source,
                           'qa' AS kind, score
                """, emb=emb).data()

            bw_qa = [r for r in raw_qa
                     if r["source"] == "Bitwig_Generated" and r["score"] >= _SCORE_MIN_DOC]
            qa    = [r for r in raw_qa
                     if r["source"] != "Bitwig_Generated" and r["score"] >= _SCORE_MIN_DOC]
            # Bitwig-Q&A priorisieren, allgemeines Musik-Wissen als Ergänzung
            qa_merged = (sorted(bw_qa, key=lambda x: -x["score"])[:2] +
                         sorted(qa,    key=lambda x: -x["score"])[:2])

        # Context-Chunks ans Ende — nach Score sortieren, Context-Chunk bleibt hinten
        context_chunks = [d for d in docs if d.get("_context")]
        scored_chunks   = [d for d in docs if not d.get("_context")]
        all_results = (sorted(scored_chunks + qa_merged, key=lambda x: -x["score"])[:n_results]
                       + context_chunks)
        if all_results:
            vec_parts = []
            for i, d in enumerate(all_results):
                label = "Kontext" if d.get("_context") else str(i + 1)
                header = f"**[{label}] {d['source']}** (score: {d['score']:.2f})"
                if d.get("video_url"):
                    header += f" — [Video]({d['video_url']})"
                vec_parts.append(f"{header}\n{d['content'][:400].strip()}")
                if d.get("samples"):
                    vec_parts[-1] += "\n  🎚️ Samples: " + ", ".join(d["samples"])
            results.append(
                "## Wissen (Neo4j Vektorsuche)\n\n" +
                "\n\n---\n\n".join(vec_parts)
            )
    except Exception as e:
        results.append(f"[Vektorsuche nicht verfügbar: {e}]")

    if not results:
        return "Keine Ergebnisse gefunden."

    return "\n\n" + "\n\n═══\n\n".join(results)

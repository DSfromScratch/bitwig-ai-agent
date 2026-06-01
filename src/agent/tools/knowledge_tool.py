from __future__ import annotations
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


def _query_neo4j(query: str) -> str:
    """Sucht im Neo4j-Graph nach Devices, Parametern, Presets, Concepts und Genres."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
    except Exception:
        return ""

    parts = []
    q_lower = query.lower()

    words = [w for w in re.findall(r'\b\w{3,}\b', q_lower)
             if w not in ("was","wie","für","mit","und","oder","der","die","das",
                          "for","with","the","and","how","what","which","gibt","eine",
                          "einen","einem","welche","welchen","kann","beim","bitte",
                          "machen","einen","mache","sein","sind","beim","eine")]

    if not words:
        return ""

    try:
        with neo4j_session() as s:

            # ── 1. Concepts ────────────────────────────────────────────────
            concepts = s.run("""
                MATCH (c:Concept)
                WHERE any(w IN $words WHERE toLower(c.name) CONTAINS w
                       OR toLower(coalesce(c.description,'')) CONTAINS w
                       OR toLower(coalesce(c.category,'')) CONTAINS w)
                RETURN c.name AS name, c.description AS desc,
                       c.use_case AS use_case, c.category AS category
                LIMIT 3
            """, words=words).data()

            if concepts:
                lines = []
                for c in concepts:
                    line = f"**{c['name']}** [{c.get('category','')}]\n  {c.get('desc','')}"
                    if c.get('use_case'):
                        line += f"\n  Wann: {c['use_case']}"
                    # Traverse: Concept → related Devices
                    related_devs = s.run("""
                        MATCH (c:Concept {name: $name})-[]->(d:Device)
                        RETURN d.name AS n LIMIT 5
                    """, name=c['name']).data()
                    if related_devs:
                        line += "\n  Devices: " + ", ".join(r['n'] for r in related_devs)
                    lines.append(line)
                parts.append("**Bitwig-Konzepte:**\n" + "\n\n".join(lines))

            # ── 2. Devices + Parameter + Traversal ────────────────────────
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

            if devices:
                dev_lines = []
                for d in devices:
                    params_result = s.run("""
                        MATCH (dev:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
                        RETURN p.name AS name, coalesce(p.description, p.key, '') AS desc,
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
                    if d.get('tips'):
                        import json
                        try:
                            tips = json.loads(d['tips']) if isinstance(d['tips'], str) else d['tips']
                            if tips:
                                line += f"\n  Tipp: {tips[0]}"
                        except Exception:
                            pass
                    dev_lines.append(line)

                parts.append("**Devices:**\n" + "\n\n".join(dev_lines))

            # ── 3. Genre → Device-Set + verwandte Workflows ───────────────
            genres = s.run("""
                MATCH (g:Genre)
                WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w)
                WITH g LIMIT 2
                MATCH (g)-[r:USES]->(d:Device)
                RETURN g.name AS genre, g.bpm_min AS bmin, g.bpm_max AS bmax,
                       g.description AS gdesc,
                       collect({device: d.name, role: r.role, weight: r.weight}) AS devices
            """, words=words).data()

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

            # ── 4a. Recording-Workflows priorisiert ──────────────────────
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

            # ── 4. Workflows + benötigte Devices ─────────────────────────
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
                    import json
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

            # ── 5. Presets ────────────────────────────────────────────────
            presets = s.run("""
                MATCH (p:Preset)-[:BELONGS_TO]->(d:Device)
                WHERE any(w IN $words WHERE toLower(p.name) CONTAINS w)
                RETURN p.name AS preset, d.name AS device,
                       p.category AS category, p.package AS package
                LIMIT 8
            """, words=words).data()

            if presets:
                preset_lines = [
                    f"  • {p['preset']} → {p['device']} [{p.get('package','?')}]"
                    for p in presets
                ]
                parts.append("**Presets:**\n" + "\n".join(preset_lines))

            # ── 6. "Ähnlich wie X" — SIMILAR_TO Traversal ────────────────
            similar_query = s.run("""
                MATCH (d:Device)-[:SIMILAR_TO]->(sim:Device)
                WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w)
                RETURN d.name AS src, sim.name AS similar,
                       sim.description AS desc, sim.use_case AS use_case
                LIMIT 6
            """, words=words).data()

            if similar_query:
                groups: dict[str, list] = {}
                for r in similar_query:
                    groups.setdefault(r['src'], []).append(r)
                for src, rows in groups.items():
                    sim_strs = []
                    for r in rows:
                        s_str = f"**{r['similar']}**"
                        if r.get('desc'):
                            s_str += f": {r['desc'][:80]}"
                        sim_strs.append(s_str)
                    parts.append(f"**Ähnlich wie {src}:**\n" + "\n".join(f"  • {s}" for s in sim_strs))

            # ── 7. ProductionPatterns ─────────────────────────────────────
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

    # ── Neo4j Vektor-Suche (Documents + KnowledgeQA) ──────────────────────
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
        from src.knowledge.store import get_embeddings
        emb = get_embeddings().embed_query(query)
        with neo4j_session() as s:
            # Bitwig-Dokumentation
            docs = s.run("""
                MATCH (d:Document) WHERE d.embedding IS NOT NULL
                WITH d, vector.similarity.cosine(d.embedding, $emb) AS score
                ORDER BY score DESC LIMIT $k
                RETURN d.content AS content, d.source AS source,
                       'doc' AS kind, score
            """, k=3, emb=emb).data()

            # Bitwig-spezifische Q&A zuerst
            bw_qa = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source = 'Bitwig_Generated' AND k.embedding IS NOT NULL
                WITH k, vector.similarity.cosine(k.embedding, $emb) AS score
                ORDER BY score DESC LIMIT 2
                RETURN k.text AS content, k.source AS source,
                       'qa' AS kind, score
            """, emb=emb).data()

            # Allgemeines Musik-Wissen als Ergänzung
            qa = s.run("""
                MATCH (k:KnowledgeQA)
                WHERE k.source <> 'Bitwig_Generated' AND k.embedding IS NOT NULL
                WITH k, vector.similarity.cosine(k.embedding, $emb) AS score
                ORDER BY score DESC LIMIT 2
                RETURN k.text AS content, k.source AS source,
                       'qa' AS kind, score
            """, emb=emb).data()
            qa = bw_qa + qa

        all_results = sorted(docs + qa, key=lambda x: -x["score"])[:n_results]
        if all_results:
            vec_parts = [
                f"**[{i+1}] {d['source']}** (score: {d['score']:.2f})\n"
                f"{d['content'][:400].strip()}"
                for i, d in enumerate(all_results)
            ]
            results.append(
                "## Wissen (Neo4j Vektorsuche)\n\n" +
                "\n\n---\n\n".join(vec_parts)
            )
    except Exception as e:
        results.append(f"[Vektorsuche nicht verfügbar: {e}]")

    if not results:
        return "Keine Ergebnisse gefunden."

    return "\n\n" + "\n\n═══\n\n".join(results)

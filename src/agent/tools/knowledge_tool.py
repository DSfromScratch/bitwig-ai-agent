from __future__ import annotations
import re
from langchain_core.tools import tool


def _query_neo4j(query: str) -> str:
    """Sucht im Neo4j-Graph nach Devices, Parametern, Presets, Concepts und Genres."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
    except Exception:
        return ""

    parts = []
    q_lower = query.lower()

    # Schlüsselwörter extrahieren
    words = [w for w in re.findall(r'\b\w{3,}\b', q_lower)
             if w not in ("was","wie","für","mit","und","oder","der","die","das",
                          "for","with","the","and","how","what","which","gibt","eine",
                          "einen","einem","welche","welchen","kann","beim","bitte")]

    if not words:
        return ""

    try:
        with neo4j_session() as s:
            # 1. Concepts (Bitwig-Konzepte aus dem Handbuch)
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
                    lines.append(line)
                parts.append("**Bitwig-Konzepte:**\n" + "\n\n".join(lines))

            # 2. Passende Devices finden
            devices = s.run("""
                MATCH (d:Device)
                WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w
                       OR toLower(coalesce(d.category,'')) CONTAINS w
                       OR toLower(coalesce(d.description,'')) CONTAINS w
                       OR toLower(coalesce(d.use_case,'')) CONTAINS w)
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

                    chain_result = s.run("""
                        MATCH (dev:Device {name: $name})-[r:RECOMMENDED_WITH]->(fx:Device)
                        RETURN fx.name AS fx, r.reason AS reason LIMIT 3
                    """, name=d["name"]).data()

                    line = f"**{d['name']}**"
                    if d.get('desc'):
                        line += f" — {d['desc']}"
                    if d.get('use_case'):
                        line += f"\n  Für: {d['use_case']}"
                    if params_result:
                        param_strs = []
                        for p in params_result:
                            ps = f"  • {p['name']}"
                            if p.get('desc'):
                                ps += f": {p['desc']}"
                            if p.get('low') and p.get('high'):
                                ps += f" (niedrig={p['low']}, hoch={p['high']})"
                            if p.get('tip'):
                                ps += f" → {p['tip']}"
                            param_strs.append(ps)
                        line += "\n  Parameter:\n" + "\n".join(param_strs)
                    if chain_result:
                        chain_str = ", ".join(f"{r['fx']}" for r in chain_result)
                        line += f"\n  Empfohlen mit: {chain_str}"
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

            # 3. Genre-Empfehlungen
            genres = s.run("""
                MATCH (g:Genre)
                WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w)
                WITH g LIMIT 2
                MATCH (g)-[r:USES]->(d:Device)
                RETURN g.name AS genre, g.bpm_min AS bmin, g.bpm_max AS bmax,
                       collect({device: d.name, role: r.role, weight: r.weight})
                       AS devices
                LIMIT 2
            """, words=words).data()

            for g in genres:
                devs = sorted(g["devices"], key=lambda x: -x.get("weight", 0))
                dev_str = ", ".join(f"{d['device']} ({d['role']})" for d in devs[:6])
                parts.append(
                    f"**Genre: {g['genre']}** ({g['bmin']}–{g['bmax']} BPM)\n"
                    f"  Typische Devices: {dev_str}"
                )

            # 4. Workflows
            workflows = s.run("""
                MATCH (w:Workflow)
                WHERE any(w2 IN $words WHERE toLower(w.name) CONTAINS w2
                         OR toLower(coalesce(w.description,'')) CONTAINS w2
                         OR toLower(coalesce(w.use_case,'')) CONTAINS w2)
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
                    step_lines = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps[:6]) if s)
                    if step_lines:
                        wf_text += "\n" + step_lines
                parts.append(wf_text)

            # 4. Presets suchen
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

    except Exception as e:
        return f"[Neo4j Fehler: {e}]"

    return "\n\n".join(parts)


@tool
def query_bitwig_docs(query: str, n_results: int = 6) -> str:
    """Durchsucht die Bitwig-Wissensdatenbank (ChromaDB + Neo4j Graph).

    Kombiniert zwei Quellen:
    - ChromaDB: semantische Suche in Bitwig-Dokumentation und Workflows
    - Neo4j: strukturiertes Wissen über alle 151 Devices, 2.663 Presets,
             Parameter, Genre-Empfehlungen, Effektketten

    Nutze dieses Tool für:
    - Welche Devices für ein Genre? ("Dubstep Bass Setup")
    - Parameter eines Instruments ("FM-4 Operator Ratio")
    - Verfügbare Presets ("E-Kick Presets")
    - Empfohlene Effektketten ("FM-4 mit welchen Effekten?")
    - Workflows ("Reese Bass erstellen")

    Args:
        query: Suchanfrage auf Deutsch oder Englisch
        n_results: Anzahl ChromaDB-Ergebnisse (Standard: 6)
    """
    results = []

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

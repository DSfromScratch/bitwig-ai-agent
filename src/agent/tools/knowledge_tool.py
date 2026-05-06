from __future__ import annotations
import re
from langchain_core.tools import tool


def _query_neo4j(query: str) -> str:
    """Sucht im Neo4j-Graph nach Devices, Parametern, Presets und Genres."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
    except Exception:
        return ""

    parts = []
    q_lower = query.lower()

    # Schlüsselwörter extrahieren
    words = [w for w in re.findall(r'\b\w{3,}\b', q_lower)
             if w not in ("was","wie","für","mit","und","oder","der","die","das",
                          "for","with","the","and","how","what","which")]

    if not words:
        return ""

    pattern = "|".join(f"(?i).*{w}.*" for w in words[:4])

    try:
        with neo4j_session() as s:
            # 1. Passende Devices finden
            devices = s.run("""
                MATCH (d:Device)
                WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w
                       OR toLower(d.category) CONTAINS w
                       OR toLower(coalesce(d.description,'')) CONTAINS w)
                RETURN d.name AS name, d.type AS type,
                       d.category AS category, d.description AS desc,
                       d.browser_path AS path
                LIMIT 6
            """, words=words).data()

            if devices:
                dev_lines = []
                for d in devices:
                    params_result = s.run("""
                        MATCH (dev:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
                        WHERE p.source = 'bitwig_install'
                        RETURN p.key AS key LIMIT 12
                    """, name=d["name"]).data()
                    params = [r["key"] for r in params_result]

                    chain_result = s.run("""
                        MATCH (dev:Device {name: $name})-[r:RECOMMENDED_WITH]->(fx:Device)
                        RETURN fx.name AS fx, r.reason AS reason LIMIT 4
                    """, name=d["name"]).data()

                    preset_count = s.run("""
                        MATCH (p:Preset)-[:BELONGS_TO]->(d:Device {name: $name})
                        RETURN count(p) AS cnt
                    """, name=d["name"]).single()["cnt"]

                    line = f"**{d['name']}** [{d.get('category','?')}] — {d.get('desc','')}"
                    if d.get('path'):
                        line += f"\n  Browser: {d['path']}"
                    if params:
                        line += f"\n  Parameter: {', '.join(params[:10])}"
                    if chain_result:
                        chain_str = ", ".join(f"{r['fx']} ({r['reason']})" for r in chain_result)
                        line += f"\n  Empfohlen mit: {chain_str}"
                    if preset_count > 0:
                        line += f"\n  Presets: {preset_count}"
                    dev_lines.append(line)

                parts.append("**Devices aus Bitwig-Installation:**\n" + "\n\n".join(dev_lines))

            # 2. Genre-Empfehlungen
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

            # 3. Workflows
            workflows = s.run("""
                MATCH (w:Workflow)
                WHERE any(w2 IN $words WHERE toLower(w.name) CONTAINS w2
                         OR toLower(w.description) CONTAINS w2)
                RETURN w.name AS name, w.description AS desc, w.steps AS steps
                LIMIT 2
            """, words=words).data()

            for wf in workflows:
                parts.append(
                    f"**Workflow: {wf['name']}**\n{wf['desc']}\n"
                    + "\n".join(f"  {i+1}. {step}"
                                for i, step in enumerate((wf.get("steps") or "").split("\n")[:6]))
                )

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

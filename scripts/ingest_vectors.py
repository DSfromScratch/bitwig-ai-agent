"""
Generiert Document-Nodes + Embeddings in Neo4j aus vorhandenen Graphdaten.

Keine PDF-Verarbeitung nötig — nutzt Device, Concept, Workflow, Genre Nodes
die bereits im Graph sind.

Ausführen:
    python scripts/ingest_vectors.py
    python scripts/ingest_vectors.py --dry-run      # nur zählen, nicht schreiben
    python scripts/ingest_vectors.py --reset         # alle Document-Nodes vorher löschen
    python scripts/ingest_vectors.py --batch 64      # Batch-Größe für Embeddings
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _build_device_text(d: dict, params: list[dict]) -> str:
    parts = [f"**{d['name']}**"]
    if d.get("description"):
        parts.append(d["description"])
    if d.get("use_case"):
        parts.append(f"Verwendung: {d['use_case']}")
    if d.get("category"):
        parts.append(f"Kategorie: {d['category']}")
    if params:
        param_strs = []
        for p in params:
            ps = p["name"]
            if p.get("description"):
                ps += f": {p['description']}"
            if p.get("low_means") and p.get("high_means"):
                ps += f" (niedrig={p['low_means']}, hoch={p['high_means']})"
            if p.get("tip"):
                ps += f". Tipp: {p['tip']}"
            param_strs.append(ps)
        parts.append("Parameter: " + "; ".join(param_strs))
    if d.get("tips"):
        import json
        try:
            tips = json.loads(d["tips"]) if isinstance(d["tips"], str) else d["tips"]
            if tips:
                parts.append(f"Tipps: {'; '.join(str(t) for t in tips[:3])}")
        except Exception:
            pass
    return "\n".join(parts)


def _build_concept_text(c: dict) -> str:
    parts = [f"**{c['name']}**"]
    if c.get("category"):
        parts.append(f"[{c['category']}]")
    if c.get("description"):
        parts.append(c["description"])
    if c.get("use_case"):
        parts.append(f"Wann: {c['use_case']}")
    return " ".join(parts)


def _build_workflow_text(w: dict) -> str:
    parts = [f"Workflow: **{w['name']}**"]
    if w.get("description"):
        parts.append(w["description"])
    if w.get("use_case"):
        parts.append(f"Wann: {w['use_case']}")
    steps_raw = w.get("steps") or ""
    if steps_raw:
        import json
        try:
            steps = json.loads(steps_raw) if steps_raw.startswith("[") else steps_raw.split("\n")
        except Exception:
            steps = steps_raw.split("\n")
        step_lines = [f"{i+1}. {s}" for i, s in enumerate(steps[:8]) if str(s).strip()]
        if step_lines:
            parts.append("Schritte: " + " | ".join(step_lines))
    return "\n".join(parts)


def _build_genre_text(g: dict, devices: list[dict]) -> str:
    parts = [f"Genre: **{g['name']}**"]
    if g.get("bpm_min") and g.get("bpm_max"):
        parts.append(f"BPM: {g['bpm_min']}–{g['bpm_max']}")
    if g.get("description"):
        parts.append(g["description"])
    if devices:
        dev_strs = [f"{d['device']} ({d.get('role', '')})" for d in devices[:8]]
        parts.append("Typische Devices: " + ", ".join(dev_strs))
    return "\n".join(parts)


def collect_chunks(session) -> list[dict]:
    """Liest alle relevanten Nodes aus Neo4j und baut Text-Chunks daraus."""
    chunks: list[dict] = []

    # 1. Devices (mit Parametern zusammengeführt)
    devices = session.run("""
        MATCH (d:Device)
        RETURN d.name AS name, d.description AS description,
               d.use_case AS use_case, d.category AS category,
               d.device_type AS device_type, d.tips AS tips
        ORDER BY d.name
    """).data()

    for d in devices:
        params = session.run("""
            MATCH (dev:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
            RETURN p.name AS name, p.description AS description,
                   p.tip AS tip, p.low_means AS low_means, p.high_means AS high_means
            LIMIT 12
        """, name=d["name"]).data()
        text = _build_device_text(d, params)
        chunks.append({
            "source": f"Device:{d['name']}",
            "content": text,
        })

    # 2. Concepts
    concepts = session.run("""
        MATCH (c:Concept)
        RETURN c.name AS name, c.description AS description,
               c.use_case AS use_case, c.category AS category
        ORDER BY c.name
    """).data()
    for c in concepts:
        text = _build_concept_text(c)
        chunks.append({
            "source": f"Concept:{c['name']}",
            "content": text,
        })

    # 3. Workflows
    workflows = session.run("""
        MATCH (w:Workflow)
        RETURN w.name AS name, w.description AS description,
               w.use_case AS use_case, w.steps AS steps
        ORDER BY w.name
    """).data()
    for w in workflows:
        text = _build_workflow_text(w)
        chunks.append({
            "source": f"Workflow:{w['name']}",
            "content": text,
        })

    # 4. Genres
    genres = session.run("""
        MATCH (g:Genre)
        RETURN g.name AS name, g.description AS description,
               g.bpm_min AS bpm_min, g.bpm_max AS bpm_max
        ORDER BY g.name
    """).data()
    for g in genres:
        devices_for_genre = session.run("""
            MATCH (genre:Genre {name: $name})-[r:USES]->(d:Device)
            RETURN d.name AS device, r.role AS role
            ORDER BY r.weight DESC LIMIT 10
        """, name=g["name"]).data()
        text = _build_genre_text(g, devices_for_genre)
        chunks.append({
            "source": f"Genre:{g['name']}",
            "content": text,
        })

    # 5. ProductionPatterns
    patterns = session.run("""
        MATCH (p:ProductionPattern)
        RETURN p.name AS name, p.description AS description,
               p.use_case AS use_case, p.approach AS approach,
               p.genre AS genre, p.difficulty AS difficulty,
               p.source_project AS source_project
        ORDER BY p.name
    """).data()
    for pat in patterns:
        parts = [f"Produktions-Muster: **{pat['name']}**"]
        if pat.get("genre"):
            parts.append(f"[{pat['genre']}]")
        if pat.get("source_project"):
            parts.append(f"Quelle: {pat['source_project']}")
        if pat.get("description"):
            parts.append(pat["description"])
        if pat.get("use_case"):
            parts.append(f"Wann: {pat['use_case']}")
        if pat.get("approach"):
            parts.append(f"Vorgehensweise: {pat['approach']}")
        if pat.get("difficulty"):
            parts.append(f"Schwierigkeit: {pat['difficulty']}")
        # Devices die beteiligt sind
        pat_devs = session.run("""
            MATCH (p:ProductionPattern {name: $name})-[:INVOLVES]->(d:Device)
            RETURN d.name AS n LIMIT 8
        """, name=pat["name"]).data()
        if pat_devs:
            parts.append("Devices: " + ", ".join(r["n"] for r in pat_devs))
        chunks.append({
            "source": f"ProductionPattern:{pat['name']}",
            "content": "\n".join(parts),
        })

    return chunks


def embed_and_store(chunks: list[dict], batch_size: int, dry_run: bool) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    print(f"[embed] Lade Embedding-Modell …")
    emb_model = get_embeddings()

    # Kurzer Test
    test_vec = emb_model.embed_query("test")
    dim = len(test_vec)
    print(f"[embed] Modell bereit — Dimension: {dim}")

    if dry_run:
        print(f"[dry-run] {len(chunks)} Chunks würden verarbeitet — kein Schreiben")
        for c in chunks[:5]:
            print(f"  {c['source']}: {c['content'][:80]}…")
        return

    total = len(chunks)
    written = 0
    t0 = time.time()

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["content"] for c in batch]

        # Embeddings generieren
        vectors = emb_model.embed_documents(texts)

        # In Neo4j schreiben
        with neo4j_session() as s:
            for chunk, vec in zip(batch, vectors):
                s.run("""
                    MERGE (d:Document {source: $source})
                    SET d.content   = $content,
                        d.embedding = $embedding
                """, source=chunk["source"], content=chunk["content"], embedding=vec)
        written += len(batch)
        elapsed = time.time() - t0
        rate = written / elapsed if elapsed > 0 else 0
        eta = (total - written) / rate if rate > 0 else 0
        print(f"  [{written:>4}/{total}] {batch[-1]['source']:50}  "
              f"{rate:.1f}/s  ETA {eta:.0f}s")

    print(f"\n[done] {written} Document-Nodes mit Embeddings geschrieben "
          f"({time.time()-t0:.0f}s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Neo4j Vector Ingest")
    parser.add_argument("--dry-run",   action="store_true", help="Nur zählen, nicht schreiben")
    parser.add_argument("--reset",     action="store_true", help="Alle Document-Nodes vorher löschen")
    parser.add_argument("--batch",     type=int, default=32, help="Batch-Größe (Standard: 32)")
    args = parser.parse_args()

    from src.knowledge.neo4j_graph import session as neo4j_session

    if args.reset and not args.dry_run:
        print("[reset] Lösche alle Document-Nodes …")
        with neo4j_session() as s:
            result = s.run("MATCH (d:Document) DELETE d RETURN count(d) AS c").single()
            print(f"[reset] {result['c']} Nodes gelöscht")

    print("[collect] Baue Chunks aus Neo4j-Graph …")
    with neo4j_session() as s:
        chunks = collect_chunks(s)
    print(f"[collect] {len(chunks)} Chunks gesammelt "
          f"({sum(1 for c in chunks if c['source'].startswith('Device:'))} Devices, "
          f"{sum(1 for c in chunks if c['source'].startswith('Concept:'))} Concepts, "
          f"{sum(1 for c in chunks if c['source'].startswith('Workflow:'))} Workflows, "
          f"{sum(1 for c in chunks if c['source'].startswith('Genre:'))} Genres, "
          f"{sum(1 for c in chunks if c['source'].startswith('ProductionPattern:'))} Patterns)")

    embed_and_store(chunks, args.batch, args.dry_run)


if __name__ == "__main__":
    main()

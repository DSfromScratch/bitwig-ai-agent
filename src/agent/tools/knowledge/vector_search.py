"""Neo4j Vektor-Suche via HNSW-Index für query_bitwig_docs."""
from __future__ import annotations

_SCORE_MIN_DOC = 0.70   # Mindest-Score für Docs / Q&A
_SCORE_MIN_YT  = 0.75   # Strenger für YouTube-Transkripte (mehr Rauschen)


def query_vector(query: str, n_results: int = 6) -> str:
    """Semantische Suche über alle Neo4j HNSW-Indizes.

    Gibt einen formatierten Markdown-String zurück oder einen Fehler-Hinweis.
    """
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
        from src.knowledge.store import get_embeddings
        emb = get_embeddings().embed_query(query)
        with neo4j_session() as s:
            raw_docs = s.run("""
                CALL db.index.vector.queryNodes('document_embedding', $k, $emb)
                YIELD node AS d, score
                RETURN d.content AS content, d.source AS source,
                       d.doc_type AS doc_type, d.video_url AS video_url,
                       'doc' AS kind, score
            """, k=8, emb=emb).data()

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

            gp_count = s.run("MATCH (g:GenrePattern) RETURN count(g) AS c").single()["c"]
            raw_genre: list[dict] = []
            if gp_count > 0:
                raw_genre = s.run("""
                    CALL db.index.vector.queryNodes('genre_pattern_embedding', 3, $emb)
                    YIELD node AS g, score
                    RETURN g.content AS content,
                           g.name    AS source,
                           null AS role, null AS doc_type, null AS video_url,
                           'genre_pattern' AS kind, score
                """, emb=emb).data()

            all_raw = (raw_docs + raw_recipes + raw_audio + raw_grid
                       + raw_ga + raw_midi + raw_genre + raw_artists + raw_songs)

            docs = [
                d for d in all_raw
                if d["score"] >= (_SCORE_MIN_YT if d.get("doc_type") == "youtube_transcript"
                                  else _SCORE_MIN_DOC)
            ]

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

            qa_count = s.run("MATCH (k:KnowledgeQA) RETURN count(k) AS c").single()["c"]
            raw_qa: list[dict] = []
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
            qa_merged = (sorted(bw_qa, key=lambda x: -x["score"])[:2] +
                         sorted(qa,    key=lambda x: -x["score"])[:2])

        context_chunks = [d for d in docs if d.get("_context")]
        scored_chunks  = [d for d in docs if not d.get("_context")]
        all_results = (sorted(scored_chunks + qa_merged, key=lambda x: -x["score"])[:n_results]
                       + context_chunks)

        if not all_results:
            return ""

        vec_parts = []
        for i, d in enumerate(all_results):
            label  = "Kontext" if d.get("_context") else str(i + 1)
            header = f"**[{label}] {d['source']}** (score: {d['score']:.2f})"
            if d.get("video_url"):
                header += f" — [Video]({d['video_url']})"
            vec_parts.append(f"{header}\n{d['content'][:400].strip()}")
            if d.get("samples"):
                vec_parts[-1] += "\n  🎚️ Samples: " + ", ".join(d["samples"])

        return "## Wissen (Neo4j Vektorsuche)\n\n" + "\n\n---\n\n".join(vec_parts)

    except Exception as e:
        return f"[Vektorsuche nicht verfügbar: {e}]"

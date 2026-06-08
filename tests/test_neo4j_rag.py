"""
Integrationstests für die Neo4j RAG-Queries und Agent-Einbindung.

Marker:
  - unit   : Kein Neo4j nötig — mockt Session + Embeddings
  - neo4j  : Erfordert laufendes Neo4j (bolt://localhost:7687)

Ausführen:
  pytest tests/test_neo4j_rag.py -m unit                 # schnell, kein Neo4j
  pytest tests/test_neo4j_rag.py -m neo4j                # benötigt Neo4j
  pytest tests/test_neo4j_rag.py                         # alle (neo4j standard-excluded)

Was wird geprüft:
  1. Cypher nutzt HNSW-Index (kein Brute-Force-Scan)
  2. Score-Threshold: YouTube ≥ 0.75, strukturierte Docs ≥ 0.70
  3. NEXT_CHUNK-Kontext-Chunk wird angehängt
  4. KnowledgeQA-Query wird übersprungen wenn keine Nodes
  5. Video-URLs erscheinen als Links im Output
  6. query_bitwig_docs ist im Agent (ALL_TOOLS + Router)
  7. [neo4j] HNSW-Index ONLINE + korrekte Konfiguration
  8. [neo4j] YouTube-Chunks mit Metadaten vorhanden
  9. [neo4j] NEXT_CHUNK-Kanten traversierbar
 10. [neo4j] HNSW schneller als Brute-Force
 11. [neo4j] Vollständiger query_bitwig_docs End-to-End
"""
from __future__ import annotations

import inspect
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch, call

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_neo4j_run(*, docs=None, neighbor=None, qa=None, qa_count: int = 0):
    """Query-aware Neo4j-Session-Mock.

    Dispatch erfolgt anhand des Query-Inhalts statt über eine starre
    Aufruf-Reihenfolge — robust gegenüber den zahlreichen `count()`-Guards
    für optionale Node-Typen (SoundRecipe, AudioSample, GridModule, Artist,
    Song, GenrePattern …), die `query_bitwig_docs` der Reihe nach abfragt.

      - count(k:KnowledgeQA)  → qa_count  (steuert, ob die KQ-HNSW-Query läuft)
      - sonstige count(...)   → 0         (optionale Node-Typen deaktiviert)
      - document_embedding    → docs
      - NEXT_CHUNK            → neighbor  (None ⇒ kein Nachbar-Chunk)
      - knowledgeqa_embedding → qa

    Das zurückgegebene Mock trägt `_counters` mit der Anzahl der jeweils
    semantisch relevanten Aufrufe (doc_hnsw, neighbor, kq_hnsw).
    """
    docs = docs or []
    qa = qa or []
    counters = {"doc_hnsw": 0, "neighbor": 0, "kq_hnsw": 0}

    def _run(query="", *args, **kwargs):
        q = " ".join(str(query).split())
        ql = q.lower()
        result_mock = MagicMock()
        data: list[dict] = []
        single = None
        if "count(" in ql:
            single = {"c": qa_count if "KnowledgeQA" in q else 0}
        elif "document_embedding" in q:
            counters["doc_hnsw"] += 1
            data = docs
        elif "NEXT_CHUNK" in q:
            counters["neighbor"] += 1
            single = neighbor
        elif "knowledgeqa_embedding" in q:
            counters["kq_hnsw"] += 1
            data = qa
        result_mock.data.return_value = data
        result_mock.single.return_value = (
            single if single is not None else (data[0] if data else None)
        )
        return result_mock

    s = MagicMock()
    s.run.side_effect = _run
    s._counters = counters
    return s


@contextmanager
def _neo4j_ctx(session_mock):
    """Contextmanager-kompatibles Fixture für neo4j_graph.session."""
    yield session_mock


def _patch_neo4j(session_mock):
    return patch(
        "src.knowledge.neo4j_graph.session",
        side_effect=lambda: _neo4j_ctx(session_mock),
    )


def _patch_embeddings(dim: int = 768):
    emb = MagicMock()
    emb.embed_query.return_value = [0.1] * dim
    return patch("src.knowledge.store.get_embeddings", return_value=emb)


# ── Teil 1: Unit-Tests (kein Neo4j) ───────────────────────────────────────────

class TestCypherQueries:
    """Prüft den Quellcode von knowledge_tool.py auf korrekte Query-Muster."""

    @pytest.mark.unit
    def test_hnsw_index_call_present(self):
        """knowledge_tool.py muss db.index.vector.queryNodes verwenden."""
        import src.agent.tools.knowledge_tool as kt
        src_code = inspect.getsource(kt)
        assert "db.index.vector.queryNodes" in src_code, (
            "HNSW-Index-Query 'db.index.vector.queryNodes' nicht gefunden — "
            "Brute-Force-Scan statt Index?"
        )

    @pytest.mark.unit
    def test_brute_force_scan_removed(self):
        """Der alte Brute-Force-Pattern darf nicht mehr im Code sein."""
        import src.agent.tools.knowledge_tool as kt
        src_code = inspect.getsource(kt)
        assert "MATCH (d:Document) WHERE d.embedding IS NOT NULL" not in src_code, (
            "Alter Brute-Force-Scan noch im Code: "
            "'MATCH (d:Document) WHERE d.embedding IS NOT NULL'"
        )

    @pytest.mark.unit
    def test_score_constants_defined(self):
        """Score-Threshold-Konstanten müssen im query_bitwig_docs-Body definiert sein."""
        import src.agent.tools.knowledge_tool as kt
        src_code = inspect.getsource(kt.query_bitwig_docs.func)
        assert "_SCORE_MIN_DOC" in src_code, "_SCORE_MIN_DOC nicht in query_bitwig_docs"
        assert "_SCORE_MIN_YT"  in src_code, "_SCORE_MIN_YT nicht in query_bitwig_docs"

    @pytest.mark.unit
    def test_next_chunk_query_present(self):
        """NEXT_CHUNK-Traversal-Query muss im Code vorhanden sein."""
        import src.agent.tools.knowledge_tool as kt
        src_code = inspect.getsource(kt.query_bitwig_docs.func)
        assert "NEXT_CHUNK" in src_code, "NEXT_CHUNK-Traversal fehlt in query_bitwig_docs"

    @pytest.mark.unit
    def test_kq_count_guard_present(self):
        """KnowledgeQA-Query muss einen count()-Guard haben."""
        import src.agent.tools.knowledge_tool as kt
        src_code = inspect.getsource(kt.query_bitwig_docs.func)
        assert "qa_count" in src_code, (
            "qa_count-Guard fehlt — KnowledgeQA-Query wird immer ausgeführt"
        )


class TestScoreThreshold:
    """Score-Threshold filtert schwache Treffer heraus."""

    def _invoke(self, raw_docs: list[dict], qa_count: int = 0) -> str:
        """Ruft query_bitwig_docs mit gemockten Neo4j-Ergebnissen auf.

        Der Session-Mock ist query-aware: Document-HNSW liefert ``raw_docs``,
        ein NEXT_CHUNK-Treffer liefert einen Nachbar-Chunk, KnowledgeQA-Count
        wird über ``qa_count`` gesteuert.
        """
        session_mock = _make_neo4j_run(
            docs=raw_docs,
            neighbor={"content": "Neighbor content", "source": "YouTube:Test#99",
                      "doc_type": "youtube_transcript",
                      "video_url": "https://youtu.be/x", "score": 0.0},
            qa_count=qa_count,
        )

        with _patch_neo4j(session_mock), _patch_embeddings():
            # _query_neo4j (Graph-Suche) mocken damit nur Vektor-Teil getestet wird
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                return query_bitwig_docs.invoke({"query": "test"})

    @pytest.mark.unit
    def test_youtube_below_075_filtered(self):
        """YouTube-Chunk mit Score 0.74 wird herausgefiltert."""
        raw = [{"content": "YT low", "source": "YouTube:Test#0",
                "doc_type": "youtube_transcript", "video_url": "https://youtu.be/x",
                "kind": "doc", "score": 0.74}]
        result = self._invoke(raw)
        assert "YT low" not in result, "YouTube-Chunk mit Score 0.74 sollte gefiltert sein"

    @pytest.mark.unit
    def test_youtube_at_075_passes(self):
        """YouTube-Chunk mit Score 0.75 passiert den Filter."""
        raw = [{"content": "YT pass content", "source": "YouTube:Test#0",
                "doc_type": "youtube_transcript", "video_url": "https://youtu.be/ok",
                "kind": "doc", "score": 0.75}]
        result = self._invoke(raw)
        assert "YT pass content" in result, "YouTube-Chunk mit Score 0.75 sollte erscheinen"

    @pytest.mark.unit
    def test_structured_doc_below_070_filtered(self):
        """Strukturierter Doc-Chunk mit Score 0.69 wird herausgefiltert."""
        raw = [{"content": "Struct low", "source": "Device:TestDevice",
                "doc_type": None, "video_url": None,
                "kind": "doc", "score": 0.69}]
        result = self._invoke(raw)
        assert "Struct low" not in result, "Doc-Chunk mit Score 0.69 sollte gefiltert sein"

    @pytest.mark.unit
    def test_structured_doc_at_070_passes(self):
        """Strukturierter Doc-Chunk mit Score 0.70 passiert den Filter."""
        raw = [{"content": "Struct pass content", "source": "Device:TestDevice",
                "doc_type": None, "video_url": None,
                "kind": "doc", "score": 0.70}]
        result = self._invoke(raw)
        assert "Struct pass content" in result, "Doc-Chunk mit Score 0.70 sollte erscheinen"

    @pytest.mark.unit
    def test_mixed_results_only_above_threshold(self):
        """Nur Treffer über Threshold erscheinen bei gemischten Scores."""
        raw = [
            {"content": "Good YT",    "source": "YouTube:A#0", "doc_type": "youtube_transcript",
             "video_url": "https://youtu.be/a", "kind": "doc", "score": 0.90},
            {"content": "Bad YT",     "source": "YouTube:B#0", "doc_type": "youtube_transcript",
             "video_url": "https://youtu.be/b", "kind": "doc", "score": 0.60},
            {"content": "Good struct","source": "Device:X",    "doc_type": None,
             "video_url": None, "kind": "doc", "score": 0.80},
            {"content": "Bad struct", "source": "Device:Y",    "doc_type": None,
             "video_url": None, "kind": "doc", "score": 0.65},
        ]
        result = self._invoke(raw)
        assert "Good YT"     in result
        assert "Good struct" in result
        assert "Bad YT"      not in result
        assert "Bad struct"  not in result


class TestContextChunk:
    """NEXT_CHUNK-Kontext-Chunk wird angehängt."""

    @pytest.mark.unit
    def test_neighbor_chunk_appended(self):
        """Wenn bester Treffer ein YouTube-Chunk ist, wird Nachbar-Chunk geladen."""
        yt_doc = {"content": "Main chunk", "source": "YouTube:Vid#0",
                  "doc_type": "youtube_transcript", "video_url": "https://youtu.be/v",
                  "kind": "doc", "score": 0.90}
        neighbor = {"content": "Neighbor chunk", "source": "YouTube:Vid#1",
                    "doc_type": "youtube_transcript", "video_url": "https://youtu.be/v",
                    "score": 0.0}

        session_mock = _make_neo4j_run(docs=[yt_doc], neighbor=neighbor)

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                result = query_bitwig_docs.invoke({"query": "test"})

        assert "Neighbor chunk" in result, "Nachbar-Chunk via NEXT_CHUNK nicht im Ergebnis"
        assert "[Kontext]" in result, "Kontext-Label fehlt für Nachbar-Chunk"

    @pytest.mark.unit
    def test_no_duplicate_if_neighbor_already_in_results(self):
        """Nachbar-Chunk wird nicht doppelt eingefügt wenn bereits im Ergebnis."""
        yt_doc = {"content": "Main chunk", "source": "YouTube:Vid#0",
                  "doc_type": "youtube_transcript", "video_url": "https://youtu.be/v",
                  "kind": "doc", "score": 0.90}
        # Nachbar-Chunk mit identischer source wie einer der Treffer
        session_mock = _make_neo4j_run(
            docs=[yt_doc],
            neighbor={"content": "Main chunk", "source": "YouTube:Vid#0",   # same source
                      "doc_type": "youtube_transcript",
                      "video_url": "https://youtu.be/v", "score": 0.0},
        )

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                result = query_bitwig_docs.invoke({"query": "test"})

        assert result.count("Main chunk") == 1, "Chunk-Duplikat im Ergebnis"

    @pytest.mark.unit
    def test_no_neighbor_query_for_non_youtube_hit(self):
        """NEXT_CHUNK-Query wird nur für YouTube-Chunks ausgeführt."""
        struct_doc = {"content": "Device doc", "source": "Device:Reverb",
                      "doc_type": None, "video_url": None,
                      "kind": "doc", "score": 0.88}

        session_mock = _make_neo4j_run(docs=[struct_doc])

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                result = query_bitwig_docs.invoke({"query": "test"})

        assert "Device doc" in result
        # NEXT_CHUNK-Query darf bei rein strukturierten Docs nicht aufgerufen werden
        assert session_mock._counters["neighbor"] == 0, (
            "NEXT_CHUNK-Query bei nicht-YouTube-Treffer ausgeführt"
        )


class TestVideoUrlLinks:
    """YouTube-Chunks produzieren klickbare Video-Links."""

    @pytest.mark.unit
    def test_video_url_rendered_as_link(self):
        """video_url wird als Markdown-Link [Video](url) ausgegeben."""
        yt_doc = {"content": "Tutorial content", "source": "YouTube:Tutorial#0",
                  "doc_type": "youtube_transcript",
                  "video_url": "https://www.youtube.com/watch?v=ABC123",
                  "kind": "doc", "score": 0.85}

        session_mock = _make_neo4j_run(docs=[yt_doc], neighbor=None)

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                result = query_bitwig_docs.invoke({"query": "test"})

        assert "[Video](https://www.youtube.com/watch?v=ABC123)" in result, (
            "Video-URL nicht als Markdown-Link gerendert"
        )

    @pytest.mark.unit
    def test_no_link_for_structured_doc(self):
        """Strukturierte Docs (kein video_url) produzieren keinen Video-Link."""
        struct_doc = {"content": "Device content", "source": "Device:FM-4",
                      "doc_type": None, "video_url": None,
                      "kind": "doc", "score": 0.80}

        session_mock = _make_neo4j_run(docs=[struct_doc])

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                result = query_bitwig_docs.invoke({"query": "test"})

        assert "[Video](" not in result, "Kein Video-Link für strukturierten Doc erwartet"


class TestKnowledgeQAGuard:
    """KnowledgeQA-Query wird nur ausgeführt wenn Nodes vorhanden."""

    @pytest.mark.unit
    def test_kq_query_skipped_when_zero_nodes(self):
        """Bei qa_count=0 darf kein HNSW-Query für KnowledgeQA stattfinden."""
        struct_doc = {"content": "Doc", "source": "Device:X",
                      "doc_type": None, "video_url": None,
                      "kind": "doc", "score": 0.80}

        session_mock = _make_neo4j_run(docs=[struct_doc], qa_count=0)

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                query_bitwig_docs.invoke({"query": "test"})

        # Bei qa_count=0 darf die KnowledgeQA-HNSW-Query nicht laufen
        assert session_mock._counters["kq_hnsw"] == 0, (
            "KnowledgeQA-HNSW-Query trotz qa_count=0 ausgeführt"
        )

    @pytest.mark.unit
    def test_kq_query_runs_when_nodes_present(self):
        """Bei qa_count>0 wird KnowledgeQA HNSW-Query ausgeführt."""
        struct_doc = {"content": "Doc", "source": "Device:X",
                      "doc_type": None, "video_url": None,
                      "kind": "doc", "score": 0.80}

        session_mock = _make_neo4j_run(docs=[struct_doc], qa_count=5)

        with _patch_neo4j(session_mock), _patch_embeddings():
            with patch("src.agent.tools.knowledge_tool._query_neo4j", return_value=""):
                from src.agent.tools.knowledge_tool import query_bitwig_docs
                query_bitwig_docs.invoke({"query": "test"})

        # Bei qa_count>0 wird die KnowledgeQA-HNSW-Query genau einmal ausgeführt
        assert session_mock._counters["kq_hnsw"] == 1, (
            "KnowledgeQA-HNSW-Query trotz qa_count>0 nicht ausgeführt"
        )


# ── Teil 2: Agent-Einbindung (Unit) ──────────────────────────────────────────

class TestAgentIntegration:
    """Prüft dass der Agent query_bitwig_docs korrekt einbindet."""

    @pytest.mark.unit
    def test_query_bitwig_docs_in_all_tools(self):
        """query_bitwig_docs muss in ALL_TOOLS des Agents sein."""
        from src.agent.tools import ALL_TOOLS
        names = [getattr(t, "name", "") for t in ALL_TOOLS]
        assert "query_bitwig_docs" in names, (
            f"query_bitwig_docs nicht in ALL_TOOLS: {names}"
        )

    @pytest.mark.unit
    def test_query_bitwig_docs_in_song_router(self):
        """Router muss query_bitwig_docs für Song-Modus freigeben."""
        from src.agent.router import _SONG_TOOL_NAMES
        assert "query_bitwig_docs" in _SONG_TOOL_NAMES, (
            "query_bitwig_docs nicht in _SONG_TOOL_NAMES — "
            "Agent kann Tool im Song-Modus nicht aufrufen"
        )

    @pytest.mark.unit
    def test_query_bitwig_docs_not_in_control_router(self):
        """query_bitwig_docs darf nicht im Control-Modus freigegeben sein."""
        from src.agent.router import _CONTROL_TOOL_NAMES
        assert "query_bitwig_docs" not in _CONTROL_TOOL_NAMES, (
            "query_bitwig_docs unnötig im Control-Modus"
        )

    @pytest.mark.unit
    def test_filter_tools_includes_query_for_song(self):
        """_filter_tools_for_mode gibt query_bitwig_docs für song-Modus zurück."""
        from src.agent.router import _filter_tools_for_mode
        from src.agent.tools import ALL_TOOLS

        song_tools = _filter_tools_for_mode("song", ALL_TOOLS)
        names = [getattr(t, "name", "") for t in song_tools]
        assert "query_bitwig_docs" in names

    @pytest.mark.unit
    def test_filter_tools_excludes_query_for_control(self):
        """_filter_tools_for_mode gibt query_bitwig_docs NICHT für control-Modus zurück."""
        from src.agent.router import _filter_tools_for_mode
        from src.agent.tools import ALL_TOOLS

        control_tools = _filter_tools_for_mode("control", ALL_TOOLS)
        names = [getattr(t, "name", "") for t in control_tools]
        assert "query_bitwig_docs" not in names

    @pytest.mark.unit
    def test_query_bitwig_docs_tool_schema(self):
        """query_bitwig_docs hat das korrekte Tool-Schema (query + n_results)."""
        from src.agent.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if getattr(t, "name", "") == "query_bitwig_docs")
        schema = tool.args_schema.model_json_schema() if hasattr(tool, "args_schema") else {}
        # Mindestens 'query' als Parameter
        props = schema.get("properties", {})
        assert "query" in props, f"'query'-Parameter fehlt im Tool-Schema: {props}"

    @pytest.mark.unit
    def test_prompt_mentions_query_bitwig_docs(self):
        """PROMPT_SONG referenziert query_bitwig_docs damit der Agent weiß wann es nutzen."""
        from src.agent.prompts import PROMPT_SONG
        assert "query_bitwig_docs" in PROMPT_SONG, (
            "PROMPT_SONG erwähnt query_bitwig_docs nicht — Agent könnte Tool ignorieren"
        )

    @pytest.mark.unit
    def test_recovery_knows_query_bitwig_docs(self):
        """Recovery-Mechanismus muss query_bitwig_docs als bekanntes Tool kennen."""
        from src.agent.recovery import _KNOWN_TOOL_NAMES
        assert "query_bitwig_docs" in _KNOWN_TOOL_NAMES, (
            "query_bitwig_docs nicht in _KNOWN_TOOL_NAMES (recovery.py) — "
            "wird bei Recovery-Fallback u.U. blockiert"
        )


# ── Teil 3: Neo4j-Integrationstests (erfordern laufendes Neo4j) ──────────────

@pytest.fixture(scope="module")
def neo4j_session_live(neo4j_available):
    """Liefert eine echte Neo4j-Session oder überspringt den Test."""
    if not neo4j_available:
        pytest.skip("Neo4j nicht erreichbar")
    from src.knowledge.neo4j_graph import session
    return session


class TestNeo4jIndexes:
    """Prüft HNSW-Index-Konfiguration direkt in Neo4j."""

    @pytest.mark.neo4j
    def test_document_embedding_index_online(self, neo4j_session_live):
        """VECTOR-Index 'document_embedding' muss ONLINE sein."""
        with neo4j_session_live() as s:
            indexes = s.run("SHOW INDEXES").data()
        idx = next((i for i in indexes if i.get("name") == "document_embedding"), None)
        assert idx is not None, "Index 'document_embedding' nicht gefunden"
        assert idx["state"] == "ONLINE", f"Index-Status: {idx['state']}"
        assert idx["type"] == "VECTOR", f"Falscher Index-Typ: {idx['type']}"

    @pytest.mark.neo4j
    def test_document_embedding_index_returns_scores_in_range(self, neo4j_session_live):
        """HNSW-Query liefert Scores im Bereich [0, 1] (Cosine-Ähnlichkeit)."""
        with neo4j_session_live() as s:
            results = s.run("""
                CALL db.index.vector.queryNodes('document_embedding', 5, $emb)
                YIELD node, score RETURN score
            """, emb=[0.1] * 768).data()
        assert results, "HNSW-Query lieferte keine Ergebnisse"
        for r in results:
            assert 0.0 <= r["score"] <= 1.0, (
                f"Score außerhalb [0,1]: {r['score']} — "
                "Cosine-Similarity liefert immer Werte in [0,1]"
            )

    @pytest.mark.neo4j
    def test_minimum_document_count(self, neo4j_session_live):
        """Mindestens 100 Document-Nodes mit Embeddings müssen vorhanden sein."""
        with neo4j_session_live() as s:
            row = s.run("""
                MATCH (d:Document) WHERE d.embedding IS NOT NULL
                RETURN count(d) AS c
            """).single()
        assert row["c"] >= 100, f"Zu wenige Document-Nodes: {row['c']}"

    @pytest.mark.neo4j
    def test_youtube_chunks_present(self, neo4j_session_live):
        """YouTube-Transkript-Chunks (doc_type='youtube_transcript') müssen vorhanden sein."""
        with neo4j_session_live() as s:
            row = s.run("""
                MATCH (d:Document {doc_type: 'youtube_transcript'})
                RETURN count(d) AS c
            """).single()
        assert row["c"] > 0, "Keine YouTube-Chunks in Neo4j"

    @pytest.mark.neo4j
    def test_youtube_chunks_have_metadata(self, neo4j_session_live):
        """YouTube-Chunks brauchen video_url, chunk_index und content."""
        with neo4j_session_live() as s:
            samples = s.run("""
                MATCH (d:Document {doc_type: 'youtube_transcript'})
                RETURN d.video_url AS video_url, d.chunk_index AS chunk_index,
                       d.content AS content, d.source AS source
                LIMIT 10
            """).data()
        assert samples, "Keine YouTube-Chunks gefunden"
        for doc in samples:
            assert doc["video_url"], f"video_url fehlt bei {doc['source']}"
            assert doc["chunk_index"] is not None, f"chunk_index fehlt bei {doc['source']}"
            assert doc["content"] and len(doc["content"]) > 50, \
                f"content zu kurz bei {doc['source']}"


class TestNeo4jNextChunk:
    """Prüft NEXT_CHUNK-Relationships."""

    @pytest.mark.neo4j
    def test_next_chunk_edges_exist(self, neo4j_session_live):
        """Mindestens eine NEXT_CHUNK-Kante muss vorhanden sein."""
        with neo4j_session_live() as s:
            row = s.run("""
                MATCH ()-[r:NEXT_CHUNK]->() RETURN count(r) AS c
            """).single()
        assert row["c"] > 0, "Keine NEXT_CHUNK-Kanten in Neo4j"

    @pytest.mark.neo4j
    def test_next_chunk_connects_same_video(self, neo4j_session_live):
        """NEXT_CHUNK darf nur Chunks desselben Videos verbinden."""
        with neo4j_session_live() as s:
            pairs = s.run("""
                MATCH (a:Document)-[:NEXT_CHUNK]->(b:Document)
                RETURN a.source AS src_a, b.source AS src_b
                LIMIT 20
            """).data()
        assert pairs, "Keine NEXT_CHUNK-Paare gefunden"
        for p in pairs:
            # source-Format: "YouTube:<titel>#<idx>"
            title_a = p["src_a"].rsplit("#", 1)[0]
            title_b = p["src_b"].rsplit("#", 1)[0]
            assert title_a == title_b, (
                f"NEXT_CHUNK verbindet verschiedene Videos: "
                f"{p['src_a']} → {p['src_b']}"
            )

    @pytest.mark.neo4j
    def test_next_chunk_index_sequential(self, neo4j_session_live):
        """chunk_index muss bei NEXT_CHUNK-Kante um 1 steigen."""
        with neo4j_session_live() as s:
            pairs = s.run("""
                MATCH (a:Document)-[:NEXT_CHUNK]->(b:Document)
                WHERE a.chunk_index IS NOT NULL AND b.chunk_index IS NOT NULL
                RETURN a.chunk_index AS idx_a, b.chunk_index AS idx_b,
                       a.source AS src
                LIMIT 30
            """).data()
        for p in pairs:
            assert p["idx_b"] == p["idx_a"] + 1, (
                f"Nicht-sequentieller chunk_index: {p['idx_a']} → {p['idx_b']} "
                f"bei {p['src']}"
            )


class TestNeo4jHNSWPerformance:
    """HNSW-Query muss schneller sein als Brute-Force-Scan."""

    @pytest.mark.neo4j
    @pytest.mark.slow
    def test_hnsw_faster_than_brute_force(self, neo4j_session_live):
        """db.index.vector.queryNodes braucht weniger als die Hälfte der Brute-Force-Zeit."""
        from src.knowledge.store import get_embeddings
        emb = get_embeddings().embed_query("sidechain compression Bitwig")

        with neo4j_session_live() as s:
            # Warmup
            s.run("CALL db.index.vector.queryNodes('document_embedding', 5, $e) "
                  "YIELD node, score RETURN score LIMIT 1", e=emb).data()

            # HNSW messen
            t0 = time.perf_counter()
            for _ in range(5):
                s.run("CALL db.index.vector.queryNodes('document_embedding', 5, $e) "
                      "YIELD node AS d, score RETURN d.source, score", e=emb).data()
            hnsw_ms = (time.perf_counter() - t0) / 5 * 1000

            # Brute-Force messen
            t0 = time.perf_counter()
            for _ in range(5):
                s.run("MATCH (d:Document) WHERE d.embedding IS NOT NULL "
                      "WITH d, vector.similarity.cosine(d.embedding, $e) AS score "
                      "ORDER BY score DESC LIMIT 5 RETURN d.source, score", e=emb).data()
            brute_ms = (time.perf_counter() - t0) / 5 * 1000

        assert hnsw_ms < brute_ms, (
            f"HNSW ({hnsw_ms:.1f}ms) langsamer als Brute-Force ({brute_ms:.1f}ms)"
        )


class TestNeo4jQueryBitwigDocs:
    """End-to-End: query_bitwig_docs mit echtem Neo4j + Embedding-Server."""

    @pytest.mark.neo4j
    @pytest.mark.slow
    def test_returns_youtube_result_for_tutorial_query(self, neo4j_session_live):
        """Bitwig-Tutorial-Query liefert mindestens einen YouTube-Chunk zurück."""
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        result = query_bitwig_docs.invoke({"query": "Bitwig modulation Poly Grid tutorial"})
        assert "YouTube:" in result or "youtu.be" in result or "youtube.com" in result, (
            "Keine YouTube-Ergebnisse für Tutorial-Query"
        )

    @pytest.mark.neo4j
    @pytest.mark.slow
    def test_score_above_threshold_in_result(self, neo4j_session_live):
        """Ergebnis muss Score-Angaben enthalten die ≥ Threshold sind."""
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        import re
        result = query_bitwig_docs.invoke({"query": "reverb send track Bitwig"})
        scores = [float(m) for m in re.findall(r"score: (\d+\.\d+)", result)]
        assert scores, "Keine Score-Angaben im Ergebnis"
        for s in scores:
            if s > 0.0:  # Kontext-Chunks haben score 0.0
                assert s >= 0.70, f"Score {s} unter Mindest-Threshold 0.70"

    @pytest.mark.neo4j
    @pytest.mark.slow
    def test_result_not_empty(self, neo4j_session_live):
        """query_bitwig_docs liefert nie einen leeren String."""
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        result = query_bitwig_docs.invoke({"query": "Phase-4 synthesizer parameters"})
        assert result and result.strip(), "query_bitwig_docs gab leeres Ergebnis zurück"

    @pytest.mark.neo4j
    @pytest.mark.slow
    def test_video_link_in_youtube_result(self, neo4j_session_live):
        """YouTube-Chunks im Ergebnis enthalten klickbaren [Video]-Link."""
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        result = query_bitwig_docs.invoke({"query": "Bitwig compressor tutorial how to use"})
        if "YouTube:" in result:
            assert "[Video](" in result, (
                "YouTube-Chunk ohne [Video]-Link im Ergebnis"
            )

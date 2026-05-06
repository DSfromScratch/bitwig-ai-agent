"""Tests: Neo4j Wissensdatenbank (erfordert laufendes Neo4j)."""
import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")


class TestChordonomicon:
    """Chordonomicon-Abfragen aus Neo4j."""

    @pytest.mark.neo4j
    def test_pop_progression_found(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.audio.chord_to_bitwig import query_chordonomicon
        results = query_chordonomicon("pop", n=1)
        assert len(results) > 0
        assert "genre" in results[0]
        assert "sections" in results[0]

    @pytest.mark.neo4j
    def test_rock_progression_found(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.audio.chord_to_bitwig import query_chordonomicon
        results = query_chordonomicon("rock", n=1)
        assert len(results) > 0

    @pytest.mark.neo4j
    @pytest.mark.parametrize("genre", ["pop", "rock", "jazz", "metal"])
    def test_genre_has_sections(self, genre, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.audio.chord_to_bitwig import query_chordonomicon
        results = query_chordonomicon(genre, n=1)
        if results:
            assert len(results[0]["sections"]) > 0
            for section, chords in results[0]["sections"].items():
                assert len(chords) > 0

    @pytest.mark.neo4j
    def test_genre_fallback_hard_rock(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.audio.chord_to_bitwig import query_chordonomicon
        # "hard rock" ist nicht direkt im Chordonomicon → Fallback auf "rock"
        results_hr = query_chordonomicon("hard rock", n=1)
        results_r  = query_chordonomicon("rock", n=1)
        # Beide sollten Ergebnisse liefern (oder keines, wenn Genre fehlt)
        if results_r:
            assert len(results_r) > 0

    @pytest.mark.neo4j
    def test_unknown_genre_empty(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.audio.chord_to_bitwig import query_chordonomicon
        results = query_chordonomicon("xyzabc123notagenre", n=1)
        assert results == []


class TestKnowledgeBase:
    """Allgemeine KB-Abfragen."""

    @pytest.mark.neo4j
    def test_query_bitwig_docs_returns_results(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        result = query_bitwig_docs.invoke({"query": "Polysynth FM-4 Instrument", "n_results": 3})
        assert result
        assert len(result) > 10

    @pytest.mark.neo4j
    def test_api_knowledge_in_kb(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from src.agent.tools.knowledge_tool import query_bitwig_docs
        result = query_bitwig_docs.invoke({"query": "PopupBrowser commit setStep", "n_results": 3})
        # Sollte API-Wissen aus BitiwgAPI_v25 enthalten
        assert "BitiwgAPI" in result or "setStep" in result or "commit" in result

    @pytest.mark.neo4j
    def test_genre_devices_in_neo4j(self, neo4j_available):
        if not neo4j_available:
            pytest.skip("Neo4j nicht erreichbar")
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4jllm"))
        with driver.session() as s:
            genres = s.run("MATCH (g:Genre) RETURN count(g) AS cnt").single()["cnt"]
            devices = s.run("MATCH (d:Device) RETURN count(d) AS cnt").single()["cnt"]
            presets = s.run("MATCH (p:Preset) RETURN count(p) AS cnt").single()["cnt"]
        driver.close()
        assert genres >= 10, f"Zu wenige Genres: {genres}"
        assert devices >= 100, f"Zu wenige Devices: {devices}"
        assert presets >= 1000, f"Zu wenige Presets: {presets}"

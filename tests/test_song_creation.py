"""Unit + Integration Tests: Song-Erstellungs-Pipeline."""
import pytest
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")


class TestGenreMapping:
    """Genre-Fallback-Mapping."""

    GENRE_MAP = {
        "hard rock": "rock", "hardrock": "rock", "heavy metal": "metal",
        "progressive rock": "rock", "indie rock": "rock",
        "electro pop": "pop", "synth pop": "pop", "dance pop": "pop",
        "hip hop": "hip-hop", "r&b": "hip-hop", "edm": "house",
        "jazz rock": "rock", "jazz fusion": "jazz",
    }

    @pytest.mark.unit
    @pytest.mark.parametrize("input_genre,expected", [
        ("hard rock", "rock"),
        ("heavy metal", "metal"),
        ("electro pop", "pop"),
        ("hip hop", "hip-hop"),
        ("jazz fusion", "jazz"),
        ("pop", "pop"),      # kein Mapping nötig
        ("rock", "rock"),    # kein Mapping nötig
    ])
    def test_genre_fallback(self, input_genre, expected):
        result = self.GENRE_MAP.get(input_genre.lower().strip(), input_genre)
        assert result == expected

    @pytest.mark.unit
    def test_unknown_genre_passthrough(self):
        result = self.GENRE_MAP.get("unknowngenre", "unknowngenre")
        assert result == "unknowngenre"


class TestVerifySong:
    """verify_song Tests."""

    @pytest.mark.unit
    def test_verify_song_exists(self):
        from src.agent.tools.song_tools import verify_song
        assert callable(verify_song.invoke)

    @pytest.mark.unit
    def test_verify_song_returns_string(self):
        """Mock: verify_song ohne echte Bridge gibt dict mit report_text zurück."""
        with patch("src.agent.tools.song_tools._check_bridge", return_value=False):
            from src.agent.tools.song_tools import verify_song
            result = verify_song.invoke({"play_seconds": 1.0})
            assert isinstance(result, dict)
            assert result["ok"] is False
            assert "Bridge" in result["error"]


class TestAgentState:
    """AgentState Struktur."""

    @pytest.mark.unit
    def test_state_has_required_fields(self):
        from src.agent.state import AgentState
        import typing
        hints = typing.get_type_hints(AgentState)
        assert "messages" in hints
        assert "track_count" in hints
        assert "tracks" in hints
        assert "tempo" in hints
        assert "bridge_ok" in hints

    @pytest.mark.unit
    def test_default_state_values(self):
        from src.agent.core import _default_state
        state = _default_state()
        assert state["track_count"] == 0
        assert state["tracks"] == []
        assert state["tempo"] == 120.0
        assert state["bridge_ok"] is False
        assert state["messages"] == []

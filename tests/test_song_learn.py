"""Unit-Tests für song_metadata_tool und song_learn_tool — alles gemockt."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── song_metadata_tool ──────────────────────────────────────────────────────

@patch("src.agent.tools.song_metadata_tool.httpx.get")
def test_musicbrainz_lookup_parses_response(mock_get):
    from src.agent.tools.song_metadata_tool import _musicbrainz_lookup
    mock_get.return_value = MagicMock(
        status_code=200,
        raise_for_status=lambda: None,
        json=lambda: {"recordings": [{
            "id": "abc-mbid",
            "title": "Idioteque",
            "artist-credit": [{"name": "Radiohead"}],
            "length": 335000,
            "releases": [{"title": "Kid A", "date": "2000-10-02"}],
            "tags": [{"name": "electronic"}, {"name": "idm"}],
            "score": 100,
        }]},
    )
    r = _musicbrainz_lookup("Radiohead", "Idioteque")
    assert r["mbid"] == "abc-mbid"
    assert r["tags"] == ["electronic", "idm"]
    assert r["score"] == 100


@patch("src.agent.tools.song_metadata_tool.httpx.get")
def test_musicbrainz_lookup_returns_none_on_empty(mock_get):
    from src.agent.tools.song_metadata_tool import _musicbrainz_lookup
    mock_get.return_value = MagicMock(
        status_code=200, raise_for_status=lambda: None,
        json=lambda: {"recordings": []},
    )
    assert _musicbrainz_lookup("X", "Y") is None


@patch("src.agent.tools.song_metadata_tool._lastfm_info", return_value=None)
@patch("src.agent.tools.song_metadata_tool._acousticbrainz_features",
       return_value={"bpm": 137.5, "key": "A#", "scale": "major",
                     "genre_dortmund": "electronic"})
@patch("src.agent.tools.song_metadata_tool._musicbrainz_lookup",
       return_value={"mbid": "x", "title": "T", "artist": "A",
                     "tags": ["rock"], "releases": [], "score": 100})
def test_search_artist_song_formats(mock_mb, mock_ab, mock_lf):
    from src.agent.tools.song_metadata_tool import search_artist_song
    out = search_artist_song.invoke({"artist": "A", "title": "T"})
    assert "MBID" in out
    assert "BPM (AB): 137.5" in out
    assert "rock" in out
    assert "electronic" in out


# ── song_learn_tool ─────────────────────────────────────────────────────────

def test_build_content_text_includes_all_fields():
    from src.agent.tools.song_learn_tool import _build_content_text
    meta = {
        "musicbrainz": {"tags": ["rock"]},
        "acousticbrainz": {"scale": "major", "danceability": "danceable"},
        "lastfm": {"tags": ["alternative"]},
    }
    features = {"bpm": 120.0, "key": "D", "duration_s": 180.0,
                "spectral_centroid_mean": 2000, "rms_mean": 0.1}
    text = _build_content_text("Test Artist", "Test Title", meta, features)
    assert "Test Artist" in text and "Test Title" in text
    assert "BPM: 120.0" in text
    assert "Tonart: D major" in text
    assert "rock" in text and "alternative" in text
    assert "danceability: danceable" in text


def test_learn_song_rejects_invalid_url():
    from src.agent.tools.song_learn_tool import learn_song_from_youtube
    r = learn_song_from_youtube.invoke({
        "artist": "X", "title": "Y", "youtube_url": "not-a-url",
    })
    assert "Ungültige URL" in r


@patch("src.agent.tools.song_learn_tool._persist_to_neo4j",
       return_value={"persisted": True, "node_key": "A / T"})
@patch("src.agent.tools.song_learn_tool._extract_features",
       return_value={"bpm": 120.0, "key": "C", "duration_s": 180.0,
                     "spectral_centroid_mean": 1500.0, "rms_mean": 0.1,
                     "section_times_s": [0.0, 60.0, 120.0]})
@patch("src.agent.tools.song_learn_tool._download_youtube_audio")
@patch("src.agent.tools.song_metadata_tool.search_artist_song_dict",
       return_value={"musicbrainz": None, "acousticbrainz": None, "lastfm": None})
def test_learn_song_pipeline_orchestration(mock_meta, mock_dl, mock_feat,
                                            mock_persist, tmp_path):
    from src.agent.tools.song_learn_tool import learn_song_from_youtube
    fake_audio = tmp_path / "x.wav"
    fake_audio.write_bytes(b"RIFF")
    mock_dl.return_value = fake_audio

    r = learn_song_from_youtube.invoke({
        "artist": "A", "title": "T",
        "youtube_url": "https://www.youtube.com/watch?v=abc",
    })
    assert "✓ Song gelernt" in r
    assert "BPM=120.0" in r
    assert "Key=C" in r
    mock_meta.assert_called_once()
    mock_dl.assert_called_once()
    mock_feat.assert_called_once()
    mock_persist.assert_called_once()


@patch("src.agent.tools.song_learn_tool._download_youtube_audio", return_value=None)
@patch("src.agent.tools.song_metadata_tool.search_artist_song_dict",
       return_value={"musicbrainz": None, "acousticbrainz": None, "lastfm": None})
def test_learn_song_returns_error_on_download_fail(mock_meta, mock_dl):
    from src.agent.tools.song_learn_tool import learn_song_from_youtube
    r = learn_song_from_youtube.invoke({
        "artist": "A", "title": "T",
        "youtube_url": "https://example.com/x",
    })
    assert "Download fehlgeschlagen" in r

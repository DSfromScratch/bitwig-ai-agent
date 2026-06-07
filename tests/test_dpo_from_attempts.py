"""Tests für PatternAttempt-Storage und DPO-Extraction."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_context_signature_is_stable():
    from src.agent.tools.knowledge.music_learning import _context_signature
    s1 = _context_signature("Synth", "rock", "C", "minor", 120, 2)
    s2 = _context_signature("Synth", "rock", "C", "minor", 120, 2)
    s3 = _context_signature("Synth", "rock", "C", "major", 120, 2)
    assert s1 == s2
    assert s1 != s3
    assert "bpm=120" in s1 and "bars=2" in s1


def test_store_learning_feedback_writes_attempt_node():
    """Verifiziert, dass _store_learning_feedback einen PatternAttempt-MERGE
    mit notes_json, score, attempt_id und context_signature ausführt."""
    import src.agent.tools.knowledge.music_learning as ml

    driver = MagicMock()
    session_ctx = MagicMock()
    session_obj = MagicMock()
    session_ctx.__enter__.return_value = session_obj
    driver.session.return_value = session_ctx

    with patch("neo4j.GraphDatabase.driver", return_value=driver):
        ml._store_learning_feedback(
            instrument="Synth", genre="rock", key="C", scale="minor",
            score=0.42, issues=["zu wenig kick"], suggestions=["mehr kick"],
            notes=[{"step": 0, "pitch": 36, "velocity": 100, "duration": 0.5}],
            bpm=120, bars=2,
        )

    cypher_calls = [call.args[0] for call in session_obj.run.call_args_list]
    assert any("MERGE (p:ProductionPattern" in c for c in cypher_calls)
    assert any("MERGE (a:PatternAttempt" in c for c in cypher_calls)
    attempt_call = next(c for c in session_obj.run.call_args_list
                        if "PatternAttempt" in c.args[0])
    kwargs = attempt_call.kwargs
    assert kwargs["score"] == 0.42
    assert len(kwargs["attempt_id"]) == 16
    assert "Synth" in kwargs["ctx_sig"]


# ── DPO-Extractor ──────────────────────────────────────────────────────────

def test_user_prompt_includes_all_fields():
    from scripts.extract_dpo_from_attempts import _user_prompt
    p = _user_prompt("Synth", "techno", "F", "minor", 130, 4)
    assert "Synth" in p and "techno" in p and "F minor" in p
    assert "4 Takte" in p and "130 BPM" in p


def test_completion_for_wraps_notes_as_tool_call():
    from scripts.extract_dpo_from_attempts import _completion_for
    notes_json = '[{"step":0,"pitch":60,"velocity":80,"duration":0.4}]'
    c = _completion_for(notes_json, "Synth", "C minor", 2)
    obj = json.loads(c)
    assert obj["tool"] == "write_pattern"
    assert obj["args"]["track_name"] == "Synth"
    assert obj["args"]["length_beats"] == 8.0
    assert obj["args"]["key"] == "C minor"
    assert obj["args"]["notes"][0]["pitch"] == 60


def test_pair_hash_deduplicates_identical_pairs():
    from scripts.extract_dpo_from_attempts import _pair_hash
    h1 = _pair_hash("p", "c", "r")
    h2 = _pair_hash("p", "c", "r")
    h3 = _pair_hash("p", "c", "r2")
    assert h1 == h2
    assert h1 != h3


@patch("scripts.extract_dpo_from_attempts.session")
def test_extract_pairs_skips_below_min_contrast(mock_session):
    from scripts.extract_dpo_from_attempts import extract_pairs
    sess = MagicMock()
    mock_session.return_value.__enter__.return_value = sess
    # Beide Scores zu nah beieinander → kein Paar
    sess.run.return_value.data.return_value = [{
        "sig": "Synth|rock|C|minor",
        "attempts": [
            {"attempt_id": "a1", "score": 0.65, "instrument": "Synth",
             "genre": "rock", "key": "C", "scale": "minor", "bpm": 120, "bars": 2,
             "notes_json": '[{"step":0,"pitch":60}]', "issues": [], "suggestions": []},
            {"attempt_id": "a2", "score": 0.70, "instrument": "Synth",
             "genre": "rock", "key": "C", "scale": "minor", "bpm": 120, "bars": 2,
             "notes_json": '[{"step":0,"pitch":61}]', "issues": [], "suggestions": []},
        ],
    }]
    pairs, ids = extract_pairs(min_contrast=0.20, max_per_context=3)
    assert pairs == [] and ids == []


@patch("scripts.extract_dpo_from_attempts.session")
def test_extract_pairs_produces_valid_dpo(mock_session):
    from scripts.extract_dpo_from_attempts import extract_pairs
    sess = MagicMock()
    mock_session.return_value.__enter__.return_value = sess
    sess.run.return_value.data.return_value = [{
        "sig": "Synth|rock|C|minor",
        "attempts": [
            {"attempt_id": "bad", "score": 0.35, "instrument": "Synth",
             "genre": "rock", "key": "C", "scale": "minor", "bpm": 120, "bars": 2,
             "notes_json": '[{"step":0,"pitch":60,"velocity":80,"duration":0.4}]',
             "issues": ["sparse"], "suggestions": []},
            {"attempt_id": "good", "score": 0.85, "instrument": "Synth",
             "genre": "rock", "key": "C", "scale": "minor", "bpm": 120, "bars": 2,
             "notes_json": ('[{"step":0,"pitch":60,"velocity":80,"duration":0.4},'
                            '{"step":2,"pitch":63,"velocity":80,"duration":0.4}]'),
             "issues": [], "suggestions": ["solider Lauf"]},
        ],
    }]
    pairs, ids = extract_pairs(min_contrast=0.20, max_per_context=3)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["metadata"]["chosen_score"] == 0.85
    assert pair["metadata"]["rejected_score"] == 0.35
    assert pair["metadata"]["score_delta"] == 0.5
    assert "Synth" in pair["user_message"]
    assert json.loads(pair["chosen"])["tool"] == "write_pattern"
    assert set(ids) == {"good", "bad"}

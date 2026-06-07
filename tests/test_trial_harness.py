"""Tests für den Trial-Harness (trial_compose_validate) + Auswertung (analyze_trials)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── trial_compose_validate ───────────────────────────────────────────────────

def test_build_prompt_with_kb_includes_constraints():
    from scripts.trial_compose_validate import build_prompt

    ref = {"name": "Techno", "bpm": 130, "energy": 0.8,
           "onset_steps": [0, 4, 8, 12], "ref": "GenrePattern"}
    p = build_prompt(ref, with_kb=True)
    assert "Techno" in p and "130" in p
    assert "Energie" in p
    assert "[0, 4, 8, 12]" in p


def test_build_prompt_no_kb_is_generic():
    from scripts.trial_compose_validate import build_prompt

    ref = {"name": "House", "bpm": 124, "energy": 0.7, "ref": None}
    p = build_prompt(ref, with_kb=False)
    assert "House" in p and "124" in p
    assert "Energie" not in p   # keine KB-Constraints


def test_fetch_references_no_kb_returns_generic():
    from scripts.trial_compose_validate import fetch_references

    refs = fetch_references(with_kb=False, n=5)
    assert len(refs) == 5
    assert all(r["ref"] is None for r in refs)


def test_feedback_flags_invalid_json():
    from scripts.trial_compose_validate import _feedback

    fb = _feedback(0.0, {"json": False})
    assert "JSON" in fb
    assert "0.00" in fb


def test_feedback_low_density_hint():
    from scripts.trial_compose_validate import _feedback

    fb = _feedback(0.5, {"json": True, "notes_ok": True, "rhythm_density": 0.1})
    assert "dichte" in fb.lower() or "onsets" in fb.lower()


def test_run_trial_stops_at_threshold(monkeypatch):
    """Trial bricht ab, sobald Score >= Threshold (keine weiteren Iterationen)."""
    import scripts.trial_compose_validate as mod

    calls = {"n": 0}

    def fake_compose(messages, **kw):
        calls["n"] += 1
        return '{"tool":"write_pattern_raw","args":{}}', 1.0

    monkeypatch.setattr(mod, "compose", fake_compose)
    monkeypatch.setattr(mod, "score_completion",
                        lambda p, o: (0.95, {"json": True}))

    ref = {"name": "Techno", "bpm": 130, "energy": 0.8, "ref": "GenrePattern"}
    rows = mod.run_trial(1, ref, with_kb=True, max_iterations=3, threshold=0.8)
    assert len(rows) == 1            # sofort gelöst
    assert calls["n"] == 1
    assert rows[0]["score"] == 0.95


def test_run_trial_iterates_until_max(monkeypatch):
    """Bei dauerhaft niedrigem Score wird bis max_iterations iteriert."""
    import scripts.trial_compose_validate as mod

    monkeypatch.setattr(mod, "compose", lambda m, **k: ("garbage", 1.0))
    monkeypatch.setattr(mod, "score_completion",
                        lambda p, o: (0.0, {"json": False}))

    ref = {"name": "House", "bpm": 124, "energy": 0.6, "ref": "GenrePattern"}
    rows = mod.run_trial(2, ref, with_kb=True, max_iterations=3, threshold=0.8)
    assert len(rows) == 3
    assert all(r["score"] == 0.0 for r in rows)
    assert rows[-1]["iteration"] == 3


# ── analyze_trials ───────────────────────────────────────────────────────────

def test_summarize_computes_best_and_solverate():
    from scripts.analyze_trials import summarize

    rows = [
        {"_tag": "with_kb", "trial_id": 1, "iteration": 1, "score": 0.4, "latency_s": 10.0},
        {"_tag": "with_kb", "trial_id": 1, "iteration": 2, "score": 0.9, "latency_s": 11.0},
        {"_tag": "with_kb", "trial_id": 2, "iteration": 1, "score": 0.3, "latency_s": 9.0},
    ]
    s = summarize(rows, threshold=0.8)["with_kb"]
    assert s["n_trials"] == 2
    assert s["mean_best"] == pytest.approx((0.9 + 0.3) / 2)
    assert s["solve_rate"] == 0.5
    assert s["mean_iter_to_solve"] == 2


def test_per_iteration_means():
    from scripts.analyze_trials import per_iteration_means

    rows = [
        {"_tag": "a", "iteration": 1, "score": 0.2},
        {"_tag": "a", "iteration": 1, "score": 0.4},
        {"_tag": "a", "iteration": 2, "score": 0.8},
    ]
    curves = per_iteration_means(rows)
    assert curves["a"][1] == pytest.approx(0.3)
    assert curves["a"][2] == pytest.approx(0.8)


def test_ascii_plot_renders_bars():
    from scripts.analyze_trials import ascii_plot

    out = ascii_plot({"with_kb": {1: 0.5, 2: 0.9}})
    assert "with_kb" in out
    assert "it1" in out and "it2" in out

"""Unit-Tests für BaseRepository._query_one / _query_many.

Verifiziert das zentralisierte Boilerplate (is_available-Guard, Session-Kontext,
Fehler-Logging) verhaltensgleich zum vorherigen Inline-Code in jeder Read-Methode.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import src.knowledge.repositories as repos
from src.knowledge.repositories import BaseRepository

pytestmark = pytest.mark.unit


@contextmanager
def _fake_session(run_result):
    s = MagicMock()
    s.run.return_value = run_result
    yield s


def test_query_one_returns_default_when_unavailable(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: False)
    repo = BaseRepository()
    assert repo._query_one("MATCH ...", lambda row: row, default="X") == "X"


def test_query_one_returns_default_when_no_row(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: True)
    result = MagicMock()
    result.single.return_value = None
    monkeypatch.setattr(repos, "session", lambda: _fake_session(result))
    repo = BaseRepository()
    assert repo._query_one("MATCH ...", lambda row: row, default=42) == 42


def test_query_one_maps_single_row(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: True)
    result = MagicMock()
    result.single.return_value = {"c": 3}
    monkeypatch.setattr(repos, "session", lambda: _fake_session(result))
    repo = BaseRepository()
    assert repo._query_one("MATCH ...", lambda row: row["c"] * 2) == 6


def test_query_one_swallows_exception_returns_default(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: True)

    @contextmanager
    def _boom():
        s = MagicMock()
        s.run.side_effect = RuntimeError("neo4j down")
        yield s

    monkeypatch.setattr(repos, "session", _boom)
    repo = BaseRepository()
    assert repo._query_one("MATCH ...", lambda row: row, default=None) is None


def test_query_many_returns_empty_list_default(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: False)
    repo = BaseRepository()
    assert repo._query_many("MATCH ...", lambda row: row) == []


def test_query_many_maps_each_row(monkeypatch):
    monkeypatch.setattr(repos, "is_available", lambda: True)
    rows = [{"n": 1}, {"n": 2}, {"n": 3}]
    monkeypatch.setattr(repos, "session", lambda: _fake_session(iter(rows)))
    repo = BaseRepository()
    assert repo._query_many("MATCH ...", lambda row: row["n"]) == [1, 2, 3]

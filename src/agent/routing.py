"""Router Chain für Anfrage-Klassifizierung (F4).

Chain of Responsibility: jeder Klassifizierer gibt eine Route zurück oder
reicht None weiter. Keyword-Check ist schnell und kostenlos; der LLM-
Fallback wird nur bei echter Unklarheit aufgerufen.
Neuer Anwendungsfall = neuer Classifier, keine Änderung am RouterChain.
"""
from __future__ import annotations

import re
from typing import Protocol


class TaskClassifier(Protocol):
    def classify(self, text: str) -> str | None: ...


class KeywordClassifier:
    """Zwei-Stufen-Check: Musik-Produktions-Terme + Verb-Intention."""

    _DIRECT = frozenset({
        "beat", "drum", "drums", "hip hop", "hip-hop", "trap", "techno",
        "house", "genre", "riff", "loop", "melodie", "melody", "bassline",
        "lead", "song", "track",
    })

    _MASTER_VERBS = frozenset({
        "erstell", "bau", "mach", "komponier", "schreib", "erzeug",
        "leg an", "füge hinzu",
    })

    _INSTRUMENT_TERMS = frozenset({
        "phase-4", "fm-4", "polysynth", "instrument", "gitarre", "guitar",
    })
    _FX_TERMS = frozenset({
        "distortion", "amp", "fx", "effekt", "chain",
    })
    _THEORY_TERMS = frozenset({
        "e-moll", "minor", "pentatonik", "midi", "tonart", "scale",
    })
    _TIME_TERMS = frozenset({
        "bpm", "sek", "sekunden", "seconds", "takt",
    })

    _QUERY = frozenset({
        "erkläre", "was ist", "zeig mir", "liste", "wie funktioniert",
        "welche", "gibt es", "beschreib",
    })

    def classify(self, text: str) -> str | None:
        lower = text.lower()

        if any(k in lower for k in self._QUERY):
            return "standard_agent"

        if any(k in lower for k in self._DIRECT):
            return "master_graph"

        if any(k in lower for k in self._MASTER_VERBS):
            return "master_graph"

        # Multi-group heuristic: ≥2 different domains → concrete track task
        groups = [
            self._INSTRUMENT_TERMS,
            self._FX_TERMS,
            self._TIME_TERMS,
            self._THEORY_TERMS,
        ]
        hits = sum(1 for g in groups if any(t in lower for t in g))
        if hits >= 2:
            return "master_graph"

        return None


class StructureClassifier:
    """Strukturelle Hinweise: Zahlen + Einheiten → konkreter Task."""

    _BPM  = re.compile(r"\d+\s*bpm", re.I)
    _BEAT = re.compile(r"\d+\s*(takte?|bars?|beats?)", re.I)

    def classify(self, text: str) -> str | None:
        if self._BPM.search(text) or self._BEAT.search(text):
            return "master_graph"
        return None


class LLMFallbackClassifier:
    """Letztes Mittel: ein schneller LLM-Aufruf mit 1-Token-Antwort."""

    def __init__(self, llm) -> None:
        self._llm = llm

    def classify(self, text: str) -> str | None:
        prompt = (
            "Classify the following user request.\n"
            "Reply with exactly one word: master_graph or standard_agent.\n\n"
            f"Request: {text}"
        )
        result = self._llm.invoke(prompt).content.strip().lower()
        return result if result in ("master_graph", "standard_agent") else "standard_agent"


class RouterChain:
    """Probiert jeden Klassifizierer der Reihe nach; gibt das erste Nicht-None-Ergebnis zurück."""

    def __init__(self, classifiers: list[TaskClassifier]) -> None:
        self._chain = classifiers

    def route(self, text: str) -> str:
        for clf in self._chain:
            if route := clf.classify(text):
                return route
        return "standard_agent"


# Default-Instanz ohne LLM — LLMFallbackClassifier kann in core.py ergänzt werden.
DEFAULT_ROUTER: RouterChain = RouterChain([
    KeywordClassifier(),
    StructureClassifier(),
])

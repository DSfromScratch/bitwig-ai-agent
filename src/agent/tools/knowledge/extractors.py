"""Keyword-Extraktion für Neo4j-Suchbegriffe."""
from __future__ import annotations
import re

_STOPWORDS = {
    "was", "wie", "für", "mit", "und", "oder", "der", "die", "das",
    "for", "with", "the", "and", "how", "what", "which", "gibt", "eine",
    "einen", "einem", "welche", "welchen", "kann", "beim", "bitte",
    "machen", "mache", "sein", "sind",
}


def _extract_keywords(query: str) -> list[str]:
    """Extrahiert relevante Suchbegriffe (≥3 Zeichen, ohne Stopwörter)."""
    return [w for w in re.findall(r'\b\w{3,}\b', query.lower())
            if w not in _STOPWORDS]

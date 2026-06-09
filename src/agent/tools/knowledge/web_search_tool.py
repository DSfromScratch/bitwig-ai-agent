"""
Web-Suche für den Bitwig-Agenten — Ökosystem-Ebene.

Liefert stilistisches/kulturelles Wissen das nicht in Neo4j oder Modell-Gewichten steht:
- Genre-Charakteristika (Akkordprogressionen, Rhythmus, Struktur)
- Künstler-Referenzen und Sound-Beschreibungen
- Spieltechniken und Produktions-Stile

NICHT für: diatonische Akkorde, Bitwig-Device-Parameter, Projektdaten
→ dafür query_knowledge() nutzen.
"""
from __future__ import annotations
import os
import re
import logging
from langchain_core.tools import tool

log = logging.getLogger(__name__)

# Maximal zurückgegebene Zeichen pro Suchergebnis
_MAX_RESULT_CHARS = 600
_MAX_RESULTS = 5


def _clean(text: str) -> str:
    """Entfernt HTML-Artefakte und kürzt auf lesbare Länge."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text[:_MAX_RESULT_CHARS]


def _search_duckduckgo(query: str, max_results: int = _MAX_RESULTS) -> list[dict]:
    """DuckDuckGo via langchain_community (kein API-Key nötig)."""
    try:
        from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
        ddg = DuckDuckGoSearchAPIWrapper(max_results=max_results)
        raw = ddg.results(query, max_results)
        return [
            {
                "title": r.get("title", ""),
                "snippet": _clean(r.get("snippet", "")),
                "url": r.get("link", ""),
            }
            for r in raw
            if r.get("snippet")
        ]
    except Exception as e:
        log.warning("DuckDuckGo Fehler: %s", e)
        return []


def _search_brave(query: str, max_results: int = _MAX_RESULTS) -> list[dict]:
    """Brave Search API (BRAVE_SEARCH_API_KEY in .env nötig, schneller/zuverlässiger)."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    if not api_key:
        return []
    try:
        import httpx
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key,
        }
        params = {"q": query, "count": max_results, "search_lang": "de"}
        resp = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers, params=params, timeout=8.0
        )
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "snippet": _clean(r.get("description", "")),
                "url": r.get("url", ""),
            }
            for r in results
            if r.get("description")
        ]
    except Exception as e:
        log.warning("Brave Search Fehler: %s", e)
        return []


def _format_results(results: list[dict], query: str) -> str:
    """Formatiert Suchergebnisse als lesbaren Kontext-Block."""
    if not results:
        return f"Keine Web-Ergebnisse für: {query}"

    lines = [f"**Web-Suche: {query}**\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] **{r['title']}**")
        if r.get("snippet"):
            lines.append(f"    {r['snippet']}")
        if r.get("url"):
            lines.append(f"    Quelle: {r['url']}")
        lines.append("")

    return "\n".join(lines)


@tool
def web_search(query: str) -> str:
    """Sucht im Web nach stilistischen und kulturellen Musikinformationen.

    Nutze dieses Tool wenn du Wissen brauchst das nicht in Neo4j oder deinen Gewichten ist:
    - Genre-Charakteristika: "typische Akkordprogressionen UK Garage"
    - Künstler-Stil: "was charakterisiert Burial's Sound"
    - Produktionstechniken: "Sub-Bass Technik Trap Genre"
    - Aktuelle Trends: "2024 melodic techno Strukturen"

    NICHT für:
    - Diatonische Akkorde einer Tonart → query_knowledge()
    - Bitwig Device-Parameter → query_knowledge()
    - Projektdaten → query_knowledge(type="song")

    Tipps für bessere Ergebnisse:
    - Auf Englisch suchen für internationale Musikproduktion
    - Konkret: "F# minor chord progression dark techno" statt "dunkle Musik"
    - Stil + Anwendung: "how to write UK Garage chords tutorial"

    Args:
        query: Suchanfrage — Englisch bevorzugt für Musikproduktions-Themen
    """
    # Brave bevorzugen falls API-Key vorhanden, sonst DuckDuckGo
    results = _search_brave(query) or _search_duckduckgo(query)

    formatted = _format_results(results, query)
    log.info("web_search('%s') → %d Ergebnisse", query, len(results))
    return formatted

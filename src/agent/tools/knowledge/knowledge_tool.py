from __future__ import annotations
from langchain_core.tools import tool

from src.agent.error_handler import log_error, ErrorDomain
from src.agent.tools.knowledge.extractors import _extract_keywords
from src.agent.tools.knowledge.neo4j_commands import (
    ConceptQuery, DeviceQuery, GenreQuery, WorkflowQuery,
    SimilarDeviceQuery, ArtistQuery, SongQuery, ProductionPatternQuery,
)
from src.agent.tools.knowledge.vector_search import query_vector


def _query_neo4j(query: str) -> str:
    """Strukturierte Graph-Traversal-Suche über alle Neo4j-Sectionen."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session
    except Exception:
        return ""

    words = _extract_keywords(query)
    if not words:
        return ""
    q_lower = query.lower()

    commands = [
        ConceptQuery(words),
        DeviceQuery(words),
        GenreQuery(words),
        WorkflowQuery(words, q_lower),
        SimilarDeviceQuery(words),
        ArtistQuery(words),
        SongQuery(words),
        ProductionPatternQuery(words),
    ]

    parts: list[str] = []
    try:
        with neo4j_session() as s:
            for cmd in commands:
                try:
                    parts += cmd.execute(s)
                except Exception as _e:
                    log_error(ErrorDomain.NEO4J, _e,
                              f"knowledge_tool.{cmd.__class__.__name__}")
    except Exception as e:
        return f"[Neo4j Fehler: {e}]"

    return "\n\n".join(parts)


@tool
def query_bitwig_docs(query: str, n_results: int = 6) -> str:
    """Durchsucht die Bitwig-Wissensdatenbank (Neo4j Graph + Vektorsuche).

    Kombiniert strukturierten Graph-Traversal mit semantischer Suche:
    - Devices mit Parametern, ähnlichen Devices (SIMILAR_TO), relevanten Workflows
    - Genre → Device-Sets mit Rollen und verwandten Workflows
    - Workflows → benötigte Devices
    - Concepts → verknüpfte Devices
    - Semantische Vektorsuche für kontextuelle Treffer

    Nutze dieses Tool für:
    - Genre-spezifische Device-Empfehlungen ("Techno Bass", "Ambient Pad")
    - Geräteparameter und Einstellungen ("SVF Resonanz", "Compressor Threshold")
    - Alternativen zu einem Device ("ähnlich wie Low-pass LD")
    - Workflows mit Schritt-für-Schritt-Anleitung ("Sidechain Kompression")
    - Kontext-übergreifende Fragen ("Kick klingt dünn", "warmer Pad-Sound")

    Args:
        query: Suchanfrage auf Deutsch oder Englisch
        n_results: Anzahl Vektor-Ergebnisse (Standard: 6)
    """
    results = []

    # ── Installierte VST-Plugins (InstalledPlugin Knoten) ─────────────────
    q_lower = query.lower()
    vst_keywords = {"vst", "plugin", "plug-in", "installiert", "installed",
                    "bass", "drum", "gitarre", "guitar", "synth", "surge", "dexed",
                    "ujam", "vb-", "vg-", "vd-", "welche", "which", "available"}
    if any(k in q_lower for k in vst_keywords):
        try:
            from src.knowledge.vst_scanner import query_installed_plugins
            plugins = query_installed_plugins()
            if plugins:
                by_type: dict[str, list[str]] = {}
                for p in plugins:
                    by_type.setdefault(p["type"], []).append(p["name"])
                lines = ["## Installierte VST3-Plugins\n"]
                for t, names in sorted(by_type.items()):
                    lines.append(f"**{t.capitalize()}**: {', '.join(f'`{n}`' for n in names)}")
                results.append("\n".join(lines))
        except Exception as _e:
            log_error(ErrorDomain.TOOL, _e, "knowledge_tool.vst_scanner")

    # ── Neo4j Graph-Suche ──────────────────────────────────────────────────
    neo4j_result = _query_neo4j(query)
    if neo4j_result:
        results.append("## Bitwig-Graph (Devices, Parameter, Presets)\n\n" + neo4j_result)

    # ── Neo4j Vektor-Suche ─────────────────────────────────────────────────
    vec_result = query_vector(query, n_results)
    if vec_result:
        results.append(vec_result)

    if not results:
        return "Keine Ergebnisse gefunden."

    return "\n\n" + "\n\n═══\n\n".join(results)

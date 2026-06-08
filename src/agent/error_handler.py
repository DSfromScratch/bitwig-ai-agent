"""Zentrales Error-Reporting — loggt Domain-Fehler und emittiert an EventBus.

Verwendung in except-Blöcken:
    from src.agent.error_handler import log_error, ErrorDomain

    try:
        driver.session().run(...)
    except Exception as _e:
        log_error(ErrorDomain.NEO4J, _e, "mein_modul.meine_funktion")
"""
from __future__ import annotations

from enum import Enum


class ErrorDomain(str, Enum):
    NEO4J   = "neo4j"
    OSC     = "osc"
    LLM     = "llm"
    TOOL    = "tool"
    NETWORK = "network"


def log_error(
    domain: ErrorDomain,
    error: Exception,
    source: str,
    context: dict | None = None,
) -> None:
    """Loggt Fehler auf WARNING-Level und emittiert Domain-Event an EventBus.

    Wirft selbst nie eine Exception — sicher in except-Blöcken verwendbar.

    Args:
        domain:  Fehler-Domäne (NEO4J, OSC, LLM, TOOL, NETWORK)
        error:   Die aufgefangene Exception
        source:  Lesbarer Kontext-String, z.B. "modul.funktion"
        context: Optionale Zusatzdaten für EventBus-Payload
    """
    import logging
    logging.getLogger("bitwig-agent").warning(
        "[%s] %s: %s", domain.value, source, error
    )
    try:
        from src.agent.events import get_event_bus
        get_event_bus().emit(f"{domain.value}_error", {
            "source":  source,
            "error":   str(error),
            "context": context or {},
        })
    except Exception:
        pass

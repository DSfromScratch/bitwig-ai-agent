"""Zentrale Tool-Registry.

Ersetzt die manuell gepflegte ``ALL_TOOLS``-Liste durch ein Registry-Objekt,
das Tools beim Import einsammelt und mit einem Domänen-Tag versieht
(``bitwig`` / ``music`` / ``knowledge`` / ``meta``).

Vorteile gegenüber der nackten Liste:

* **Eine Registrierungsstelle** statt Import + Listeneintrag an zwei Orten.
* **Domänen-Filterung** (``by_domain``) für Router-Phasen und Context-Limit.
* **Doppel-Registrierungs-Schutz** — gleicher Tool-Name kann nicht zweimal rein.

Der öffentliche Name ``ALL_TOOLS`` (in ``__init__.py``) bleibt erhalten und wird
aus ``registry.all()`` gespeist, damit ``core.py`` und Tests unverändert laufen.
"""
from __future__ import annotations

from typing import Any

VALID_DOMAINS = {"bitwig", "music", "knowledge", "meta"}


def _tool_name(tool: Any) -> str | None:
    """Ermittelt den Tool-Namen (LangChain-``name`` oder Fallback ``__name__``)."""
    return getattr(tool, "name", None) or getattr(tool, "__name__", None)


class ToolRegistry:
    """Sammelt Tools in Registrierungs-Reihenfolge inklusive Domänen-Tag."""

    def __init__(self) -> None:
        self._tools: list[Any] = []
        self._domain_by_name: dict[str, str] = {}

    def register(self, tool: Any, *, domain: str = "meta") -> Any:
        """Registriert ``tool`` unter ``domain`` und gibt es zurück.

        Rückgabe des Tools erlaubt Nutzung als Dekorator:
        ``my_tool = registry.register(my_tool, domain="music")``.
        """
        if domain not in VALID_DOMAINS:
            raise ValueError(
                f"Unbekannte Domäne '{domain}', erlaubt: {sorted(VALID_DOMAINS)}"
            )
        name = _tool_name(tool)
        if not name:
            raise ValueError(f"Tool ohne Namen kann nicht registriert werden: {tool!r}")
        if name in self._domain_by_name:
            raise ValueError(f"Tool '{name}' ist bereits registriert")
        self._tools.append(tool)
        self._domain_by_name[name] = domain
        return tool

    def all(self) -> list:
        """Alle registrierten Tools in Registrierungs-Reihenfolge."""
        return list(self._tools)

    def by_domain(self, domain: str) -> list:
        """Tools einer einzelnen Domäne."""
        if domain not in VALID_DOMAINS:
            raise ValueError(
                f"Unbekannte Domäne '{domain}', erlaubt: {sorted(VALID_DOMAINS)}"
            )
        return [
            t for t in self._tools
            if self._domain_by_name.get(_tool_name(t) or "") == domain
        ]

    def domain_of(self, name: str) -> str | None:
        """Domäne eines Tool-Namens oder ``None``."""
        return self._domain_by_name.get(name)

    def names(self) -> list[str]:
        """Alle registrierten Tool-Namen."""
        return [_tool_name(t) or "" for t in self._tools]

    def __len__(self) -> int:
        return len(self._tools)


registry = ToolRegistry()

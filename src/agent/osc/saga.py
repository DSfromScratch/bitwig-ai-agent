"""Saga + Command Queue für transaktionale OSC-Ausführung (F1).

Eine Song-Erstellung besteht aus ~50 OSC-Schritten. BitwigSaga koordiniert
diese Schritte: jeder Schritt kann einen Kompensations-Befehl und einen
optionalen Verify-Callback haben. Schlägt ein Schritt fehl, rollt die Saga
alle bereits ausgeführten Schritte in umgekehrter Reihenfolge zurück.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("bitwig-agent.saga")


@dataclass
class OscCommand:
    address: str
    args: list = field(default_factory=list)
    compensate: OscCommand | None = None
    verify: Callable[[], bool] | None = None


class SagaStepError(RuntimeError):
    """Ein Saga-Schritt ist fehlgeschlagen und der Rollback wurde durchgeführt."""


class BitwigSaga:
    """Führt eine Folge von OSC-Befehlen transaktional aus.

    Usage:
        saga = BitwigSaga(client)
        ok = saga.step(OscCommand("/track/add/instrument", [1],
                                   compensate=OscCommand("/track/delete/last", [1]),
                                   verify=lambda: track_count() > before))
        if not ok:
            raise SagaStepError("Track konnte nicht angelegt werden")
    """

    def __init__(self, client) -> None:
        self._client = client
        self._executed: list[OscCommand] = []

    def step(self, cmd: OscCommand, timeout: float = 2.0) -> bool:
        """Sendet cmd und prüft optional via verify(). Schlägt verify fehl → Rollback."""
        self._client.send_message(cmd.address, cmd.args if len(cmd.args) != 1 else cmd.args[0])

        if cmd.verify:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cmd.verify():
                    break
                time.sleep(0.05)
            else:
                log.warning("saga: verify fehlgeschlagen für %s — Rollback", cmd.address)
                self._rollback()
                return False

        self._executed.append(cmd)
        return True

    def commit(self) -> None:
        """Markiert alle Schritte als committed — Rollback nicht mehr möglich."""
        self._executed.clear()

    def rollback(self) -> None:
        """Expliziter Rollback von außen."""
        self._rollback()

    def _rollback(self) -> None:
        log.info("saga: Rollback von %d Schritten", len(self._executed))
        for cmd in reversed(self._executed):
            if cmd.compensate:
                try:
                    c = cmd.compensate
                    self._client.send_message(
                        c.address,
                        c.args if len(c.args) != 1 else c.args[0],
                    )
                    time.sleep(0.1)
                except Exception as exc:
                    log.warning("saga: Rollback-Schritt %s fehlgeschlagen: %s", c.address, exc)
        self._executed.clear()

"""Circuit Breaker für OSC-Kommunikation mit Bitwig.

Drei Zustände: CLOSED (normal) → OPEN (Fehler-Schwelle erreicht, Calls ablehnen)
→ HALF_OPEN (nach recovery_timeout einen Probe-Call durchlassen).
Verhindert eine Retry-Lawine wenn Bitwig nicht erreichbar ist.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from enum import Enum, auto

log = logging.getLogger("bitwig-agent.circuit-breaker")


class State(Enum):
    CLOSED    = auto()
    OPEN      = auto()
    HALF_OPEN = auto()


class CircuitOpenError(RuntimeError):
    """Bitwig nicht erreichbar — Circuit ist offen."""


@dataclass
class CircuitBreaker:
    failure_threshold: int   = 3
    recovery_timeout:  float = 30.0
    _state:    State = field(default=State.CLOSED, init=False, repr=False)
    _failures: int   = field(default=0,            init=False, repr=False)
    _opened:   float = field(default=0.0,          init=False, repr=False)

    @property
    def state(self) -> State:
        if self._state is State.OPEN:
            if time.monotonic() - self._opened >= self.recovery_timeout:
                log.info("Circuit → HALF_OPEN (recovery_timeout abgelaufen)")
                self._state = State.HALF_OPEN
        return self._state

    def call(self, fn, *args, **kwargs):
        if self.state is State.OPEN:
            raise CircuitOpenError(
                "Bitwig-Circuit offen — Verbindung prüfen. "
                f"Automatische Erholung in {self.recovery_timeout:.0f}s."
            )
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        if self._state is State.HALF_OPEN:
            log.info("Circuit → CLOSED (Probe-Call erfolgreich)")
        self._failures = 0
        self._state    = State.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            if self._state is not State.OPEN:
                log.warning(
                    "Circuit → OPEN nach %d Fehlern (threshold=%d)",
                    self._failures, self.failure_threshold,
                )
            self._state  = State.OPEN
            self._opened = time.monotonic()

    def is_open(self) -> bool:
        return self.state is State.OPEN

    def reset(self) -> None:
        self._failures = 0
        self._state    = State.CLOSED
        log.info("Circuit manuell zurückgesetzt → CLOSED")


# Globale Singleton-Instanz — geteilt von allen OSC-Tools
_bitwig_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)


def get_circuit() -> CircuitBreaker:
    return _bitwig_circuit


def send_osc_guarded(client, address: str, *args) -> None:
    """Drop-in-Ersatz für direkten client.send_message() mit Circuit-Breaker-Schutz."""
    _bitwig_circuit.call(client.send_message, address, list(args) if len(args) != 1 else args[0])

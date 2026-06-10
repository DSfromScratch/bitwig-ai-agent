"""ReasoningExtractionState — extrahiert <think>-Blöcke und leitet Phase ab."""
from __future__ import annotations
import logging
from src.agent.llm_client import _THINK_RE, _THINK_OPEN
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")

_PHASE_SIGNALS: list[tuple[list[str], str]] = [
    (["fehler aufgetreten", "nicht erreichbar", "verbindung fehlgeschlagen", "fatal error", "abbruch"], "error"),
    (["fertig", "abgeschlossen", "song ist bereit", "done", "riff wurde"], "done"),
    (["verif", "überprüf", "prüf", "playback", "abspielen"], "verifying"),
    (["noten schreib", "write_notes", "clip", "midi schreib", "riff schreib"], "generating"),
    (["instrument", "track anlegen", "setup_instrument", "fm-4", "polysynth"], "setup"),
    (["plan", "struktur", "bluep", "section", "akkord"], "planning"),
]

# Phases may only advance — never regress (except → error)
_PHASE_ORDER = {"idle": 0, "planning": 1, "setup": 2, "generating": 3, "verifying": 4, "done": 5}


class ReasoningExtractionState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        ctx.updates.update(_process_reasoning(ctx.response, ctx.agent_state, len(ctx.messages)))
        return ctx


def _extract_think(text: str) -> tuple[str, str]:
    match = _THINK_RE.search(text)
    if match:
        reasoning = match.group(1).strip()
        cleaned = _THINK_RE.sub("", text)
    else:
        open_match = _THINK_OPEN.search(text)
        reasoning = open_match.group(0).removeprefix("<think>").strip() if open_match else ""
        cleaned = _THINK_OPEN.sub("", text)
    return reasoning, cleaned.strip()


def _phase_from_reasoning(reasoning: str, current: str) -> str | None:
    if not reasoning or current in ("error", "done"):
        return None
    lower = reasoning.lower()
    current_order = _PHASE_ORDER.get(current, 0)
    for keywords, phase in _PHASE_SIGNALS:
        if any(kw in lower for kw in keywords):
            if phase == current:
                return None
            # Always allow error; only allow forward advancement otherwise
            if phase == "error" or _PHASE_ORDER.get(phase, 0) > current_order:
                return phase
    return None


def _process_reasoning(response, state: dict, msg_count: int) -> dict:
    updates: dict = {}
    if not (hasattr(response, "content") and isinstance(response.content, str)):
        return updates
    reasoning, cleaned = _extract_think(response.content)
    response.content = cleaned
    if not reasoning:
        return updates
    current_phase = state.get("generation_phase", "idle")
    new_phase = _phase_from_reasoning(reasoning, current_phase)
    from src.agent.events import get_event_bus
    bus = get_event_bus()
    bus.emit("reasoning", {"text": reasoning[:500], "current_phase": current_phase,
                            "detected_phase": new_phase, "msg_count": msg_count})
    log.info(
        "Reasoning erkannt: chars=%d phase=%s detected=%s",
        len(reasoning), current_phase, new_phase,
    )
    if new_phase is not None:
        log.info("Phase %s → %s (aus Reasoning)", current_phase, new_phase)
        bus.emit("phase_change", {"from": current_phase, "to": new_phase})
        updates["generation_phase"] = new_phase
    return updates

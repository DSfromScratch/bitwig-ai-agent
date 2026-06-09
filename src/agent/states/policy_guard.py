"""PolicyGuardState — validiert Tool-Entscheidungen, schreibt Feedback-Log."""
from __future__ import annotations
import logging
from datetime import datetime
from src.agent.policy import enforce_policy_on_response
from src.agent.router import _latest_user_text, _latest_human_is_nudge
from src.agent.states.base import AgentPhaseState, PhaseContext
from src.agent.states.shared import _append_policy_feedback

log = logging.getLogger("bitwig-agent")


class PolicyGuardState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        effective_state = {**ctx.agent_state, **ctx.updates}
        ctx.response, _ = _apply_policy(ctx.response, effective_state)
        return ctx


def _apply_policy(response, state: dict) -> tuple:
    proposed   = [dict(tc) for tc in (response.tool_calls or [])]
    response, policy_meta = enforce_policy_on_response(state, response)
    final      = [dict(tc) for tc in (response.tool_calls or [])]
    _append_policy_feedback({
        "timestamp": datetime.now().isoformat(),
        "action": policy_meta.get("action", "none"),
        "violations": policy_meta.get("violations", []),
        "concrete_track_task": policy_meta.get("concrete_track_task", False),
        "strict_fx_request": policy_meta.get("strict_fx_request", False),
        "explicit_fx": policy_meta.get("explicit_fx", []),
        "phase": state.get("generation_phase", "idle"),
        "prompt": _latest_user_text(state.get("messages", [])),
        "nudge_prompt": _latest_human_is_nudge(state.get("messages", [])),
        "proposed_tool_calls": proposed, "final_tool_calls": final,
    })
    from src.agent.events import get_event_bus
    bus = get_event_bus()
    if policy_meta.get("action") == "rewrite":
        log.info("PolicyGuard rewrite: %s", policy_meta.get("violations", []))
        bus.emit("policy_violation", {
            "violations": policy_meta.get("violations", []),
            "action": "rewrite", "phase": state.get("generation_phase", "idle"),
        })
        bus.emit("policy_rewrite_applied", {
            "before": proposed, "after": final,
            "phase": state.get("generation_phase", "idle"),
        })
    elif policy_meta.get("action") == "allow":
        bus.emit("policy_check", {"action": "allow", "phase": state.get("generation_phase", "idle")})
    return response, policy_meta

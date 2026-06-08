"""RecoveryState — korrigiert fehlerhafte Tool-Call-Formate."""
from __future__ import annotations
from src.agent.recovery import _recover_tool_calls
from src.agent.states.base import AgentPhaseState, PhaseContext


class RecoveryState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        ctx.response = _recover_tool_calls(ctx.response, ctx.agent_state)
        return ctx

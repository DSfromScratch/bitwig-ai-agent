"""LLMOrchestrator — verkettet die LLM-Phasen-States."""
from __future__ import annotations
from src.agent.states import (
    HelpState, PreparationState, InvokeState, ReasoningExtractionState,
    InvalidOutputState, PolicyGuardState, EmptyResponseState, FinalizeState,
)
from src.agent.states.base import PhaseContext


class LLMOrchestrator:
    _CHAIN = [
        HelpState(),
        PreparationState(),
        InvokeState(),
        ReasoningExtractionState(),
        PolicyGuardState(),
        InvalidOutputState(),
        EmptyResponseState(),
        FinalizeState(),
    ]

    def run(self, state: dict) -> dict:
        ctx = PhaseContext(agent_state=state)
        for phase in self._CHAIN:
            ctx = phase.execute(ctx)
            if ctx.early_return is not None:
                return ctx.early_return
        return ctx.updates

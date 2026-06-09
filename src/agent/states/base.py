"""Basisklassen für das State Pattern in call_llm()."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PhaseContext:
    """Transport-Objekt zwischen den LLM-Orchestrierungs-States."""
    agent_state: dict
    messages: list = field(default_factory=list)
    system: object = None           # SystemMessage
    selected_tools: list = field(default_factory=list)
    response: object = None         # AIMessage
    updates: dict = field(default_factory=dict)
    early_return: dict | None = None
    intent: str | None = None       # LLM-klassifizierter Intent (einmal in PreparationState gesetzt)


class AgentPhaseState(ABC):
    @abstractmethod
    def execute(self, ctx: PhaseContext) -> PhaseContext: ...

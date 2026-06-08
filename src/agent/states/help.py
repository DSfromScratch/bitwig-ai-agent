"""HelpState — antwortet sofort auf /hilfe-Kommandos."""
from __future__ import annotations
from langchain_core.messages import AIMessage
from src.agent.router import _latest_user_text
from src.agent.states.base import AgentPhaseState, PhaseContext

_HELP_COMMANDS = {"/hilfe", "/help", "/befehle", "/commands"}

_HELP_TEXT = """\
Verfügbare Befehle (mit / einleiten):

Transport
  /play              — Play/Stop umschalten
  /stop              — Transport stoppen
  /record            — Aufnahme starten
  /tempo <bpm>       — Tempo setzen  (z.B. /tempo 128)
  /loop              — Loop an/aus

Tracks
  /select <n>        — Track n auswählen
  /mute <n>          — Track n muten
  /solo <n>          — Track n solo
  /volume <n> <wert> — Lautstärke setzen  (z.B. /volume 1 0.8)

Info
  /status            — Aktuellen Bitwig-Status abfragen
  /hilfe             — Diese Übersicht

Für Erklärungen einfach normal fragen — kein /  nötig.
"""


class HelpState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        if _latest_user_text(ctx.agent_state["messages"]).lower().strip() in _HELP_COMMANDS:
            ctx.early_return = {"messages": [AIMessage(content=_HELP_TEXT)]}
        return ctx

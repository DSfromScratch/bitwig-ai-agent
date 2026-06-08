"""PreparationState — Nachrichten kürzen, Tools filtern, System-Prompt wählen."""
from __future__ import annotations
import logging
from langchain_core.messages import SystemMessage, ToolMessage
from src.agent.router import _route_request, _get_prompt_for_mode, _latest_user_text
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")

MAX_MESSAGES = 30


class PreparationState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        from src.agent.tools import ALL_TOOLS
        from src.agent.router import _select_tools_for_context as _filter

        all_messages = ctx.agent_state["messages"]
        ctx.messages  = self._prepare_messages(all_messages)
        ctx.selected_tools = _filter(all_messages, lambda: ALL_TOOLS)
        mode = _route_request(_latest_user_text(all_messages))
        ctx.system = SystemMessage(content=_get_prompt_for_mode(mode))
        log.info("LLM call — mode=%s %d Nachrichten, %d Tools",
                 mode, len(ctx.messages), len(ctx.selected_tools))
        return ctx

    @staticmethod
    def _prepare_messages(all_messages: list) -> list:
        messages = all_messages[-MAX_MESSAGES:]
        trimmed = []
        for m in messages:
            if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > 400:
                trimmed.append(ToolMessage(
                    content=m.content[:400] + " …[gekürzt]",
                    tool_call_id=m.tool_call_id,
                ))
            else:
                trimmed.append(m)
        return trimmed

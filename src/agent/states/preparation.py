"""PreparationState — History kompakt halten, Tools filtern, System-Prompt wählen."""
from __future__ import annotations
import logging
from langchain_core.messages import SystemMessage, ToolMessage
from src.agent.router import (
    _NUDGE_PREFIXES,
    _effective_generation_phase,
    _get_prompt_for_mode,
    _is_confirmation,
    _latest_user_text,
    _route_request,
    classify_intent_llm,
)
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")

RECENT_MESSAGES = 4
MAX_TOOL_RESULT_CHARS = 300
MAX_HISTORY_SUMMARY_CHARS = 1000
MAX_SUMMARY_ITEM_CHARS = 180
MAX_PHASE_SUMMARY_CHARS = 700


class PreparationState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        from src.agent.tools import ALL_TOOLS
        from src.agent.router import _select_tools_for_context as _filter

        all_messages = ctx.agent_state["messages"]
        user_text = _latest_user_text(all_messages)
        current_phase = ctx.agent_state.get("generation_phase", "idle")
        phase = _effective_generation_phase(
            all_messages,
            current_phase,
            user_text,
        )
        ctx.messages = self._prepare_messages(all_messages, current_phase, phase)
        if phase != current_phase:
            ctx.updates["generation_phase"] = phase

        # Intent einmal per LLM klassifizieren — alle nachfolgenden States lesen ctx.intent
        ctx.intent = classify_intent_llm(user_text)

        ctx.selected_tools = _filter(all_messages, lambda: ALL_TOOLS, phase, intent=ctx.intent)
        mode = _route_request(user_text)
        ctx.system = SystemMessage(content=_get_prompt_for_mode(mode))
        log.info("LLM call — mode=%s intent=%s %d→%d Nachrichten, %d Tools",
                 mode, ctx.intent, len(all_messages), len(ctx.messages), len(ctx.selected_tools))
        return ctx

    @staticmethod
    def _prepare_messages(
        all_messages: list,
        current_phase: str = "idle",
        effective_phase: str | None = None,
    ) -> list:
        effective_phase = effective_phase or current_phase
        recent = all_messages[-RECENT_MESSAGES:]
        older = all_messages[:-RECENT_MESSAGES]
        messages = []
        if effective_phase != current_phase:
            summary = _summarize_phase_transition(older, current_phase, effective_phase)
        else:
            summary = _summarize_history(older)
        if summary:
            messages.append(SystemMessage(content=summary))
        messages.extend(_trim_recent_messages(recent))
        return messages


def _trim_recent_messages(messages: list) -> list:
    trimmed = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > MAX_TOOL_RESULT_CHARS:
            trimmed.append(ToolMessage(
                content=m.content[:MAX_TOOL_RESULT_CHARS] + " …[gekürzt]",
                tool_call_id=m.tool_call_id,
            ))
        else:
            trimmed.append(m)
    return trimmed


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return " ".join(content.split())
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        return " ".join(" ".join(parts).split())
    return str(content or "").strip()


def _message_summary_line(message) -> str | None:
    cls_name = type(message).__name__
    if cls_name == "HumanMessage":
        prefix = "User"
    elif cls_name == "AIMessage":
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            names = ", ".join(str(tc.get("name", "?")) for tc in tool_calls[:5])
            return f"Assistant Tool-Calls: {names}"
        prefix = "Assistant"
    elif isinstance(message, ToolMessage):
        prefix = "Tool"
    else:
        return None

    text = _message_text(message)
    if not text:
        return None
    if cls_name == "HumanMessage" and _is_nudge_text(text):
        return None
    if len(text) > MAX_SUMMARY_ITEM_CHARS:
        text = text[:MAX_SUMMARY_ITEM_CHARS] + " …"
    return f"{prefix}: {text}"


def _is_nudge_text(text: str) -> bool:
    return text.startswith(_NUDGE_PREFIXES)


def _latest_substantial_user_line(messages: list) -> str | None:
    for message in reversed(messages):
        if type(message).__name__ != "HumanMessage":
            continue
        text = _message_text(message)
        if text and not _is_nudge_text(text) and not _is_confirmation(text):
            return _truncate_summary_text(text)
    return None


def _latest_assistant_plan_line(messages: list) -> str | None:
    for message in reversed(messages):
        if type(message).__name__ != "AIMessage":
            continue
        if getattr(message, "tool_calls", None):
            continue
        text = _message_text(message)
        if text:
            return _truncate_summary_text(text)
    return None


def _latest_tool_call_line(messages: list) -> str | None:
    for message in reversed(messages):
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            names = ", ".join(str(tc.get("name", "?")) for tc in tool_calls[:5])
            return names
    return None


def _latest_tool_result_line(messages: list) -> str | None:
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            text = _message_text(message)
            if text:
                return _truncate_summary_text(text)
    return None


def _truncate_summary_text(text: str, limit: int = MAX_SUMMARY_ITEM_CHARS) -> str:
    if len(text) > limit:
        return text[:limit] + " …"
    return text


def _summarize_phase_transition(messages: list, current_phase: str, effective_phase: str) -> str:
    """Erzeugt eine aggressive Übergabe-Notiz statt alter Detail-History."""
    lines = []
    user_line = _latest_substantial_user_line(messages)
    if user_line:
        lines.append(f"- Aktueller Auftrag: {user_line}")

    plan_line = _latest_assistant_plan_line(messages)
    if plan_line:
        lines.append(f"- Letzte Planung: {plan_line}")

    tool_line = _latest_tool_call_line(messages)
    if tool_line:
        lines.append(f"- Relevante Tool-Calls: {tool_line}")

    result_line = _latest_tool_result_line(messages)
    if result_line:
        lines.append(f"- Letztes Tool-Ergebnis: {result_line}")

    body = "\n".join(lines)
    if len(body) > MAX_PHASE_SUMMARY_CHARS:
        body = "…[Phasenübergabe gekürzt]\n" + body[-MAX_PHASE_SUMMARY_CHARS:]

    return (
        f"Workflow-Phasenwechsel {current_phase} → {effective_phase}. "
        "Überholte Detaildialoge, Nudges und fehlgeschlagene Zwischenversuche "
        "wurden aus dem LLM-Kontext entfernt.\n"
        f"{body}"
    ).rstrip()


def _summarize_history(messages: list) -> str:
    if not messages:
        return ""

    lines = []
    for message in messages:
        line = _message_summary_line(message)
        if line:
            lines.append(f"- {line}")

    if not lines:
        return ""

    body = "\n".join(lines)
    if len(body) > MAX_HISTORY_SUMMARY_CHARS:
        body = "…[älterer Verlauf gekürzt]\n" + body[-MAX_HISTORY_SUMMARY_CHARS:]

    return (
        "Kompakter Verlauf älterer Chat-Nachrichten. "
        "Nutze ihn nur als Kontext; die aktuellen Nachrichten danach haben Vorrang.\n"
        f"{body}"
    )

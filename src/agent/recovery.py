"""
Tool-Call Recovery: Erkennt und repariert ungültige LLM-Ausgaben.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage

if TYPE_CHECKING:
    from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent")

InvalidOutputCategory = str  # "xml_fragment" | "truncated_json" | "empty_args" | ...


def _get_known_tool_names() -> frozenset[str]:
    from src.agent.tools.registry import registry
    return frozenset(registry.names())


def _recover_tool_calls(response: AIMessage, state: "AgentState | None" = None) -> AIMessage:
    from src.agent.parsing.tool_call_parsers import TOOL_CALL_PARSER
    return TOOL_CALL_PARSER.patch_message(response)


def _classify_invalid_output(response: AIMessage) -> InvalidOutputCategory:
    content = response.content if isinstance(response.content, str) else ""
    if "<tool_call>" in content and "</tool_call>" not in content:
        return "xml_fragment"
    if "<tool_call>" in content and "</tool_call>" in content:
        inner = content.split("<tool_call>", 1)[-1].split("</tool_call>", 1)[0].strip()
        try:
            json.loads(inner)
            return "malformed_args"
        except json.JSONDecodeError:
            return "truncated_json"
    for tc in (response.tool_calls or []):
        if not tc.get("args"):
            return "empty_args"
        name = tc.get("name", "")
        if name and name not in _get_known_tool_names():
            return "unknown_tool_schema"
    return "unknown"


def _has_invalid_tool_output(response: AIMessage) -> bool:
    if getattr(response, "tool_calls", None):
        return False
    if not isinstance(response.content, str):
        return False
    return "<tool_call>" in response.content


def _recover_xml_fragment_once(
    system,
    messages: list,
    selected_tools: list,
    state: "AgentState",
    get_tools_fn,
    get_llm_fn,
    log_tokens_fn,
) -> AIMessage | None:
    from langchain_core.messages import HumanMessage
    from openai import BadRequestError

    fallback_tools = [
        t for t in get_tools_fn()
        if getattr(t, "name", "") in {
            "get_bitwig_state", "execute_setup", "query_knowledge",
        }
    ]
    llm = get_llm_fn(max_tokens=4000).bind_tools(fallback_tools or selected_tools)
    hard_nudge = HumanMessage(content=(
        "Deine letzte Antwort war ein XML-Fragment — der Tool-Call wurde abgeschnitten. "
        "Führe die ursprüngliche Aufgabe vollständig aus: "
        "Generiere denselben execute_setup-Call erneut, diesmal komplett und valide. "
        "Keine XML-Tags, kein Markdown, kein Freitext — nur ein ausführbarer Tool-Call."
    ))
    try:
        candidate = llm.invoke([system] + messages[-6:] + [hard_nudge])
        log_tokens_fn(candidate, label="xml-recovery")
    except BadRequestError as exc:
        log.debug("XML-Recovery fehlgeschlagen (BadRequest): %s", exc)
        return None
    except Exception as exc:
        log.debug("XML-Recovery fehlgeschlagen: %s", exc)
        return None

    candidate = _recover_tool_calls(candidate, state)
    if _has_invalid_tool_output(candidate):
        return None
    return candidate

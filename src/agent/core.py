"""
Bitwig Audio Agent — LangGraph StateGraph.
Qwen3 via vLLM + LangChain Tools für Audio-Analyse und Bitwig-Integration.
"""

from __future__ import annotations

import json
import os
import re
import logging
import threading
from datetime import datetime
from dotenv import load_dotenv
from typing import Any

# ── Persistentes Logging ──────────────────────────────────────────────────────
LOG_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, f"agent_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("bitwig-agent")
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs.chat_generation import ChatGeneration
from langchain_core.outputs.llm_result import LLMResult
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from openai import BadRequestError

from src.agent.state import AgentState, GenerationPhase
from src.agent.prompts import SYSTEM_PROMPT, PROMPT_SONG, PROMPT_CONTROL
from src.agent.tools import ALL_TOOLS
from src.agent.events import get_event_bus
from src.agent.policy import enforce_policy_on_response


# ── Re-exports für Backward-Kompatibilität ──────────────────────────────────
from src.agent.osc_listener import (  # noqa: F401
    _LATEST_UI_CONFIG, _LATEST_UI_CONFIG_LOCK,
    _set_latest_ui_config, _consume_latest_ui_config,
)
from src.agent.llm_client import (  # noqa: F401
    MockLLM, _patch_langchain_tool_call_parser, _get_llm, _log_token_usage,
)
from src.agent.router import (  # noqa: F401
    _CONTROL_COMMANDS, _SONG_TOOL_NAMES, _CONTROL_TOOL_NAMES, _CONFIRMATIONS,
    _NUDGE_PREFIXES, _route_request, _get_prompt_for_mode, _filter_tools_for_mode,
    _latest_user_text, _latest_human_is_nudge, _is_knowledge_question,
)
from src.agent.recovery import (  # noqa: F401
    _KNOWN_TOOL_NAMES, InvalidOutputCategory,
    _recover_tool_calls, _classify_invalid_output,
    _has_invalid_tool_output,
)
from src.agent.llm_client import _THINK_RE as _THINK_RE_  # to avoid duplicate import


def _extract_think(text: str) -> tuple[str, str]:
    from src.agent.llm_client import _THINK_RE, _THINK_OPEN
    match = _THINK_RE.search(text)
    reasoning = match.group(1).strip() if match else ""
    cleaned   = _THINK_RE.sub("", text)
    cleaned   = _THINK_OPEN.sub("", cleaned)
    return reasoning, cleaned.strip()


def _phase_from_reasoning(reasoning: str, current) -> str | None:
    if not reasoning:
        return None
    if current in ("error", "done"):
        return None
    lower = reasoning.lower()
    for keywords, phase in _PHASE_SIGNALS:
        if any(kw in lower for kw in keywords):
            return phase if phase != current else None
    return None




_patch_langchain_tool_call_parser()

# ── Konstanten ────────────────────────────────────────────────────────────────
from src.agent.llm_client import _THINK_RE, _THINK_OPEN  # noqa: F401

MAX_MESSAGES = 30

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

_NUDGE_PREFIXES = (
    "Deine Antwort war leer.",
    "Dein Tool-Call war ungültig",
)

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

_PHASE_SIGNALS: list[tuple[list[str], str]] = [
    (["fehler aufgetreten", "nicht erreichbar", "verbindung fehlgeschlagen", "fatal error", "abbruch"],  "error"),
    (["fertig", "abgeschlossen", "song ist bereit", "done", "riff wurde"],  "done"),
    (["verif", "überprüf", "prüf", "playback", "abspielen"],              "verifying"),
    (["noten schreib", "write_notes", "clip", "midi schreib", "riff schreib"],  "generating"),
    (["instrument", "track anlegen", "setup_instrument", "fm-4", "polysynth"],  "setup"),
    (["plan", "struktur", "bluep", "section", "akkord"],                   "planning"),
]

POLICY_LOG_DIR  = os.path.join(LOG_DIR, "policy_feedback")
POLICY_LOG_FILE = os.path.join(POLICY_LOG_DIR, "policy_feedback.jsonl")


def _append_policy_feedback(entry: dict) -> None:
    try:
        os.makedirs(POLICY_LOG_DIR, exist_ok=True)
        with open(POLICY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.debug("Policy-Feedback konnte nicht geschrieben werden: %s", exc)


def _get_tools() -> list:
    return ALL_TOOLS


def _select_tools_for_context(all_messages: list) -> list:
    from src.agent.router import _select_tools_for_context as _fn
    return _fn(all_messages, _get_tools)


def _recover_xml_fragment_once(system, messages, selected_tools, state) -> AIMessage | None:
    from src.agent.recovery import _recover_xml_fragment_once as _fn
    return _fn(system, messages, selected_tools, state, _get_tools, _get_llm, _log_token_usage)


def _prepare_messages(all_messages: list, max_messages: int) -> list:
    """Kürzt lange Tool-Antworten und begrenzt die Nachrichtenanzahl."""
    from langchain_core.messages import ToolMessage
    messages = all_messages[-max_messages:]
    trimmed = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > 400:
            trimmed.append(ToolMessage(content=m.content[:400] + " …[gekürzt]", tool_call_id=m.tool_call_id))
        else:
            trimmed.append(m)
    return trimmed


def _invoke_with_retry(system: SystemMessage, messages: list, selected_tools: list) -> AIMessage:
    """Ruft das LLM auf — mit Fallback bei Kontext-Overflow."""
    llm = _get_llm().bind_tools(selected_tools) if selected_tools else _get_llm()
    try:
        response = llm.invoke([system] + messages)
        _log_token_usage(response, label="main")
        return response
    except BadRequestError as exc:
        msg = str(exc)
        if "maximum context length" not in msg and "input_tokens" not in msg:
            raise
        fallback_tools = [t for t in _get_tools() if getattr(t, "name", "") in
                          {"check_bitwig_connection", "execute_setup"}]
        fallback_llm = _get_llm(max_tokens=700).bind_tools(fallback_tools or selected_tools)
        log.warning("LLM Kontextlimit — Fallback mit %d Tools, max_tokens=700",
                    len(fallback_tools or selected_tools))
        try:
            response = fallback_llm.invoke([SystemMessage(content=PROMPT_CONTROL)] + messages[-6:])
            _log_token_usage(response, label="fallback")
            return response
        except Exception as fallback_exc:
            log.error("LLM Fallback fehlgeschlagen: %s", fallback_exc, exc_info=True)
            get_event_bus().emit("agent_error", {"source": "llm_fallback",
                "error": type(fallback_exc).__name__, "message": str(fallback_exc)})
            raise RuntimeError(
                f"LLM nicht erreichbar — Kontext zu groß, Fallback fehlgeschlagen: {fallback_exc}"
            ) from fallback_exc


def _process_reasoning(response: AIMessage, state: AgentState, msg_count: int) -> dict:
    """Extrahiert <think>-Block, emittiert Events, leitet Phase ab."""
    updates: dict = {}
    if not (hasattr(response, "content") and isinstance(response.content, str)):
        return updates
    reasoning, cleaned = _extract_think(response.content)
    response.content = cleaned
    if not reasoning:
        return updates
    current_phase: GenerationPhase = state.get("generation_phase", "idle")
    new_phase = _phase_from_reasoning(reasoning, current_phase)
    bus = get_event_bus()
    bus.emit("reasoning", {"text": reasoning[:500], "current_phase": current_phase,
                            "detected_phase": new_phase, "msg_count": msg_count})
    if new_phase is not None:
        log.info("Phase %s → %s (aus Reasoning)", current_phase, new_phase)
        bus.emit("phase_change", {"from": current_phase, "to": new_phase})
        updates["generation_phase"] = new_phase
    return updates


def _handle_invalid_output(response: AIMessage, system: SystemMessage, messages: list,
                            selected_tools: list, state: AgentState,
                            updates: dict) -> dict | None:
    """Behandelt kaputte Tool-Ausgaben — gibt Retry-Dict oder None zurück."""
    if not _has_invalid_tool_output(response):
        return None
    retry      = state.get("retry_count", 0) + 1
    snippet    = (response.content or "")[:300]
    diagnostic = _classify_invalid_output(response)
    user_text  = _latest_user_text(state["messages"])
    outcome    = "abort" if retry >= 3 else "retry"
    log.warning("LLM: ungültiger Tool-Output (%s) — Regenerierung #%d", diagnostic, retry)
    get_event_bus().emit("invalid_tool_output", {"diagnostic": diagnostic,
        "phase": state.get("generation_phase","idle"), "retry": retry,
        "snippet": snippet, "outcome": outcome, "user_prompt": user_text[:200]})
    _append_policy_feedback({"timestamp": datetime.now().isoformat(),
        "action": "invalid_tool_output", "diagnostic": diagnostic,
        "phase": state.get("generation_phase","idle"), "retry": retry,
        "snippet": snippet, "outcome": outcome, "user_prompt": user_text[:200]})

    if diagnostic == "xml_fragment":
        recovered = _recover_xml_fragment_once(system, messages, selected_tools, state)
        if recovered is not None:
            log.info("LLM: xml_fragment auto-recovered")
            get_event_bus().emit("invalid_tool_output_recovered",
                {"diagnostic": diagnostic, "phase": state.get("generation_phase","idle"), "retry": retry})
            _append_policy_feedback({"timestamp": datetime.now().isoformat(),
                "action": "invalid_tool_output_recovered", "diagnostic": diagnostic,
                "phase": state.get("generation_phase","idle"), "retry": retry})
            return {"messages": [recovered], "retry_count": state.get("retry_count", 0), **updates}

    if retry >= 3:
        return {"messages": [AIMessage(content=(
            "Abbruch: Wiederholt ungültige Tool-Ausgaben vom Modell. "
            "Bitte Anfrage erneut senden oder Prompt vereinfachen."
        ))], "retry_count": retry, **updates}

    nudge = HumanMessage(content=(
        "Dein Tool-Call war ungültig oder abgeschnitten. "
        "Generiere denselben Schritt erneut als gültigen Tool-Call. "
        "Kein Freitext, kein XML-Fragment, nur ein ausführbarer Tool-Call "
        "mit validen JSON-Args."
    ))
    return {"messages": [response, nudge], "retry_count": retry, **updates}


def _apply_policy(response: AIMessage, state: AgentState) -> tuple[AIMessage, dict]:
    """Policy-Guard: validiert Tool-Entscheidungen, schreibt Feedback-Log."""
    proposed   = [dict(tc) for tc in (response.tool_calls or [])]
    response, policy_meta = enforce_policy_on_response(state, response)
    final      = [dict(tc) for tc in (response.tool_calls or [])]
    _append_policy_feedback({"timestamp": datetime.now().isoformat(),
        "action": policy_meta.get("action","none"),
        "violations": policy_meta.get("violations",[]),
        "concrete_track_task": policy_meta.get("concrete_track_task",False),
        "strict_fx_request": policy_meta.get("strict_fx_request",False),
        "explicit_fx": policy_meta.get("explicit_fx",[]),
        "phase": state.get("generation_phase","idle"),
        "prompt": _latest_user_text(state.get("messages",[])),
        "nudge_prompt": _latest_human_is_nudge(state.get("messages",[])),
        "proposed_tool_calls": proposed, "final_tool_calls": final})
    bus = get_event_bus()
    if policy_meta.get("action") == "rewrite":
        log.info("PolicyGuard rewrite: %s", policy_meta.get("violations",[]))
        bus.emit("policy_violation", {"violations": policy_meta.get("violations",[]),
            "action":"rewrite","phase":state.get("generation_phase","idle")})
        bus.emit("policy_rewrite_applied", {"before": proposed, "after": final,
            "phase": state.get("generation_phase","idle")})
    elif policy_meta.get("action") == "allow":
        bus.emit("policy_check", {"action":"allow","phase":state.get("generation_phase","idle")})
    return response, policy_meta


def call_llm(state: AgentState) -> dict:
    """Orchestriert LLM-Aufruf: Vorbereitung → Invoke → Reasoning → Recovery → Policy."""
    all_messages = state["messages"]

    if _latest_user_text(all_messages).lower().strip() in ("/hilfe", "/help", "/befehle", "/commands"):
        return {"messages": [AIMessage(content=_HELP_TEXT)]}

    messages       = _prepare_messages(all_messages, MAX_MESSAGES)
    selected_tools = _select_tools_for_context(all_messages)
    mode           = _route_request(_latest_user_text(all_messages))
    system         = SystemMessage(content=_get_prompt_for_mode(mode))
    log.info("LLM call — mode=%s %d Nachrichten, %d Tools", mode, len(messages), len(selected_tools))

    response = _invoke_with_retry(system, messages, selected_tools)
    updates  = _process_reasoning(response, state, len(messages))
    response = _recover_tool_calls(response, state)

    retry_result = _handle_invalid_output(response, system, messages, selected_tools, state, updates)
    if retry_result is not None:
        return retry_result

    response, _ = _apply_policy(response, state)

    has_tool_calls = bool(getattr(response, "tool_calls", None))
    if not has_tool_calls and not (response.content or "").strip():
        retry = state.get("retry_count", 0) + 1
        log.warning("LLM: leere Antwort (think-only) — Nudge #%d", retry)
        nudge = HumanMessage(content="Deine Antwort war leer. Bitte ruf jetzt direkt ein "
                             "passendes Tool auf. Kein Text, nur Tool-Call.")
        return {"messages": [response, nudge], "retry_count": retry, **updates}

    if has_tool_calls:
        for tc in response.tool_calls:
            log.info("Tool-Call: %s(%s)", tc["name"], str(tc.get("args", {}))[:120])
    else:
        log.info("Agent-Antwort: %s", response.content[:200])
    return {"messages": [response], **updates}


def should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def route_by_phase(state: AgentState) -> str:
    last = state["messages"][-1] if state.get("messages") else None

    # Explizite Tool-Calls → ausführen
    if last and hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"

    # Retry-Limit
    if state.get("retry_count", 0) >= 3:
        return END

    # Nudge-Message → Agent nochmal aufrufen
    if isinstance(last, HumanMessage):
        return "agent"

    phase = state.get("generation_phase", "idle")
    if phase in ("done", "error"):
        return END

    # Hat der Agent eine echte Textantwort gegeben (kein leerer Think-Only) → fertig
    if isinstance(last, AIMessage) and (last.content or "").strip():
        return END

    return should_continue(state)


def build_graph() -> StateGraph:
    tools = _get_tools()
    tool_node = ToolNode(tools, handle_tool_errors=True)
    graph = StateGraph(AgentState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_by_phase, {"tools": "tools", "agent": "agent", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _default_state() -> "AgentState":
    return {
        "messages":          [],
        "track_count":       0,
        "tracks":            [],
        "tempo":             120.0,
        "bridge_ok":         False,
        "bitwig_result":     None,
        # Song-Generierungs-Kontext
        "generation_phase":  "idle",
        "song_blueprint":    None,
        "section_timeline":  [],
        "quality_report":    None,
        "pending_sections":  [],
        "retry_count":       0,
        "ui_song_config":    None,
        # Multi-Agent Slave-State
        "slave_plan":        None,
        "slave_results":     [],
        "assembled_json":    None,
        "build_result":      None,
        "slave_retry_counts": {},
        # Observer / Retry-Loop
        "retry_budget":       {"instrument": 2, "harmony": 2, "note": 2},
        "phase_quality_score": 1.0,
        "quality_thresholds":  {"overall": 0.75, "notes": 0.70},
        "retry_signal":        None,
    }


GRAPH = None


def get_graph():
    global GRAPH
    if GRAPH is None:
        GRAPH = build_graph()
    return GRAPH


def chat(message: str, history: list | None = None) -> str:
    """Einfacher Chat-Einstieg für Streamlit."""
    from langchain_core.messages import HumanMessage, AIMessage as _AIMsg
    log.info("=== Neue Anfrage: %s", message[:100])
    graph = get_graph()
    state = _default_state()
    state["messages"] = history or []
    state["messages"].append(HumanMessage(content=message))
    try:
        result = graph.invoke(state)
        answer = result["messages"][-1].content

        # Token-Zusammenfassung: alle AI-Messages des Runs aufsummieren
        total_in = total_out = total_think = 0
        llm_calls = 0
        for m in result["messages"]:
            if isinstance(m, _AIMsg):
                meta = getattr(m, "usage_metadata", None) or {}
                if meta.get("total_tokens"):
                    total_in    += meta.get("input_tokens", 0)
                    total_out   += meta.get("output_tokens", 0)
                    total_think += (meta.get("output_tokens", 0) - meta.get("input_tokens", 0)) // 2
                    llm_calls   += 1
        if llm_calls:
            summary = (
                f"=== TOKEN SUMMARY ({llm_calls} LLM-Calls): "
                f"input={total_in} | output={total_out} | total={total_in + total_out}"
            )
            log.info(summary)
            print(summary, flush=True)

        log.info("=== Fertig. Antwort: %s", answer[:200])
        return answer
    except Exception as e:
        log.error("=== Fehler: %s", e, exc_info=True)
        try:
            get_event_bus().emit("agent_error", {
                "source": "chat",
                "error": type(e).__name__,
                "message": str(e),
            })
        except Exception:
            pass
        return f"[Fehler] {type(e).__name__}: {e}"


def execute_plan(result: "BitwigResult") -> str:  # type: ignore[name-defined]
    """Workflow-Orchestrator: führt ein BitwigResult aus und gibt den Status-String zurück.

    Args:
        result: BitwigResult-Objekt (Pydantic) oder kompatibles dict
    """
    from src.bitwig_executor import execute_result
    return execute_result(result)


from src.agent.osc_listener import (  # noqa: F401
    _start_agent_ui_osc_listener,
)


if __name__ == "__main__":
    history = []
    history_lock = threading.Lock()

    def _run_request(user: str) -> str:
        nonlocal_history = history
        ui_cfg = _consume_latest_ui_config()
        nonlocal_history.append(HumanMessage(content=user))
        graph = get_graph()
        state = _default_state()
        state["messages"] = nonlocal_history
        if ui_cfg:
            state["ui_song_config"] = ui_cfg
        try:
            result = graph.invoke(state)
            nonlocal_history[:] = result["messages"]
            reply_local = nonlocal_history[-1].content
            return reply_local
        except Exception as e:
            # History-Rollback: User-Message entfernen damit der State konsistent bleibt
            if nonlocal_history and isinstance(nonlocal_history[-1], HumanMessage):
                nonlocal_history.pop()
            log.error("graph.invoke fehlgeschlagen: %s", e, exc_info=True)
            get_event_bus().emit("agent_error", {
                "source": "_run_request",
                "error": type(e).__name__,
                "message": str(e),
            })
            raise

    import sys, signal as _signal, time as _time

    def _run_request_threadsafe(user: str) -> str:
        with history_lock:
            return _run_request(user)

    _start_agent_ui_osc_listener(_run_request_threadsafe)

    # Daemon-Modus nur wenn explizit gesetzt oder weder stdin noch stderr ein TTY ist
    _daemon = os.getenv("AGENT_DAEMON", "").lower() in ("1", "true")
    if _daemon or (not sys.stdin.isatty() and not sys.stderr.isatty()):
        # Daemon-Modus: OSC-Listener + Idle-Watchdog
        log.info("Daemon-Modus: OSC-Listener aktiv auf Port 9003. SIGTERM zum Beenden.")
        _signal.pause()
    else:
        print("Bitwig Audio Agent — interaktiv (Ctrl+C zum Beenden)\n")
        while True:
            try:
                user = input("Du: ").strip()
                if not user:
                    continue
                reply = _run_request_threadsafe(user)
                print(f"\nAgent: {reply}\n")
            except EOFError:
                print("\nEingabe beendet (EOF). Agent wird sauber beendet.")
                break
            except KeyboardInterrupt:
                print("\nTschüss!")
                break

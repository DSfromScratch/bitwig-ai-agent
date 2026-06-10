"""
Bitwig Audio Agent — LangGraph StateGraph.
Qwen3 via vLLM + LangChain Tools für Audio-Analyse und Bitwig-Integration.
"""

from __future__ import annotations

import os
import logging
import threading
from datetime import datetime

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

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.agent.tools import ALL_TOOLS
from src.agent.events import get_event_bus
from src.agent.llm_client import _patch_langchain_tool_call_parser
from src.agent.orchestrator import LLMOrchestrator
from src.agent.router import _NUDGE_PREFIXES

_patch_langchain_tool_call_parser()


def call_llm(state: AgentState) -> dict:
    """LLM-Aufruf: delegiert an LLMOrchestrator (9-stufige State-Kette)."""
    return LLMOrchestrator().run(state)


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
    tools = ALL_TOOLS
    tool_node = ToolNode(tools, handle_tool_errors=True)
    graph = StateGraph(AgentState)
    graph.add_node("agent", call_llm)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route_by_phase, {"tools": "tools", "agent": "agent", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def _is_nudge_message(msg: "HumanMessage") -> bool:
    text = (msg.content or "").strip()
    return any(text.startswith(p) for p in _NUDGE_PREFIXES)


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
        "retry_count":       0,
        "ui_song_config":    None,
    }


def _state_for_user_turn(session_state: "AgentState", user: str, ui_cfg: dict | None = None) -> "AgentState":
    """Build the next graph input while preserving workflow state across turns."""
    state = dict(session_state)
    state["messages"] = list(session_state.get("messages", [])) + [HumanMessage(content=user)]
    state["retry_count"] = 0
    # Abgeschlossene/fehlerhafte Workflows auf idle zurücksetzen, damit neue Anfragen
    # nicht fälschlicherweise im "done"/"error" Phase-Kontext starten.
    if state.get("generation_phase") in ("done", "error"):
        state["generation_phase"] = "idle"
    if ui_cfg is not None:
        state["ui_song_config"] = ui_cfg
    return state  # type: ignore[return-value]


def _merge_session_state(previous_state: "AgentState", graph_result: dict) -> "AgentState":
    """Persist all graph-updated fields, not only messages."""
    merged = dict(previous_state)
    for key, value in graph_result.items():
        merged[key] = value
    return merged  # type: ignore[return-value]


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
        nudge_count = sum(
            1 for m in result["messages"]
            if isinstance(m, HumanMessage) and _is_nudge_message(m)
        )
        retry_count = result.get("retry_count", 0)
        if llm_calls:
            summary = (
                f"=== TOKEN SUMMARY ({llm_calls} LLM-Calls): "
                f"input={total_in} | output={total_out} | total={total_in + total_out} | "
                f"nudges={nudge_count} retries={retry_count}"
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
        except Exception as _e:
            log.debug("EventBus agent_error emit fehlgeschlagen: %s", _e)
        return f"[Fehler] {type(e).__name__}: {e}"


def execute_plan(result: "BitwigResult") -> str:  # type: ignore[name-defined]
    """Workflow-Orchestrator: führt ein BitwigResult aus und gibt den Status-String zurück.

    Args:
        result: BitwigResult-Objekt (Pydantic) oder kompatibles dict
    """
    from src.bitwig_executor import execute_result
    return execute_result(result)


if __name__ == "__main__":
    from src.agent.osc_listener import _start_agent_ui_osc_listener, _consume_latest_ui_config
    session_state_box = {"state": _default_state()}
    history_lock = threading.Lock()

    def _run_request(user: str) -> str:
        ui_cfg = _consume_latest_ui_config()
        graph = get_graph()
        state = _state_for_user_turn(session_state_box["state"], user, ui_cfg)
        try:
            result = graph.invoke(state)
            session_state_box["state"] = _merge_session_state(state, result)
            reply_local = session_state_box["state"]["messages"][-1].content
            return reply_local
        except Exception as e:
            log.error("graph.invoke fehlgeschlagen: %s", e, exc_info=True)
            get_event_bus().emit("agent_error", {
                "source": "_run_request",
                "error": type(e).__name__,
                "message": str(e),
            })
            raise

    import sys
    import signal as _signal

    def _run_request_threadsafe(user: str) -> str:
        with history_lock:
            return _run_request(user)

    _start_agent_ui_osc_listener(_run_request_threadsafe)  # type: ignore[possibly-unbound]

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

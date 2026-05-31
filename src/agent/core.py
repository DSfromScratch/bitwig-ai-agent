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
from src.agent.prompts import SYSTEM_PROMPT, PROMPT_SONG, PROMPT_CONTROL, PROMPT_LAUNCHPAD
from src.agent.tools import ALL_TOOLS
from src.agent.events import get_event_bus
from src.agent.policy import enforce_policy_on_response


_LATEST_UI_CONFIG: dict[str, Any] | None = None
_LATEST_UI_CONFIG_LOCK = threading.Lock()


def _set_latest_ui_config(cfg: dict[str, Any]) -> None:
    global _LATEST_UI_CONFIG
    with _LATEST_UI_CONFIG_LOCK:
        _LATEST_UI_CONFIG = dict(cfg)


def _consume_latest_ui_config() -> dict[str, Any] | None:
    global _LATEST_UI_CONFIG
    with _LATEST_UI_CONFIG_LOCK:
        cfg = _LATEST_UI_CONFIG
        _LATEST_UI_CONFIG = None
    return cfg


class MockLLM(BaseChatModel):
    """Mock-LLM für Tests ohne externe API-Abhängigkeiten."""
    
    @property
    def _llm_type(self) -> str:
        return "mock"
    
    def invoke(self, input, config=None, **kwargs):
        """Überschreibe invoke() direkt für einfache Mock-Responses."""
        response = "OK: Mock-Antwort im Test-Modus. Agent läuft, aber LLM-Backend nicht verfügbar."
        return AIMessage(content=response)
    
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        """Fallback für andere Methoden."""
        response = "OK: Mock-Antwort im Test-Modus. Agent läuft, aber LLM-Backend nicht verfügbar."
        message = AIMessage(content=response)
        generation = ChatGeneration(message=message)
        return LLMResult(generations=[[generation]])
    
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        """Async Version für Konsistenz."""
        return self._generate(messages, stop, run_manager, **kwargs)
    
    def bind_tools(self, tools=None, **kwargs):
        """Bindet Tools an (im Mock-Modus ein no-op)."""
        return self


def _patch_langchain_tool_call_parser() -> None:
    """Normalisiert doppelt-serialisierte Tool-Args aus manchen vLLM-Antworten.

    Manche OpenAI-kompatible Backends liefern `function.arguments` als JSON-String,
    der wiederum nur ein weiterer String ist (z. B. '"{...}"').
    LangChain erwartet am Ende ein dict in `tool_calls[].args`.
    """
    try:
        import langchain_openai.chat_models.base as lc_openai_base

        original_parse_tool_call = lc_openai_base.parse_tool_call

        def _safe_parse_tool_call(raw_tool_call: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
            parsed = original_parse_tool_call(raw_tool_call, **kwargs)
            if not parsed:
                return parsed

            args = parsed.get("args")
            if isinstance(args, str):
                try:
                    reparsed = json.loads(args)
                    if isinstance(reparsed, dict):
                        parsed["args"] = reparsed
                        return parsed
                except Exception:
                    pass
                # Letzter Fallback: leeres Dict statt Pydantic-Crash
                parsed["args"] = {}
            return parsed

        lc_openai_base.parse_tool_call = _safe_parse_tool_call
    except Exception as exc:
        log.debug("LangChain Tool-Parser Patch nicht angewendet: %s", exc)


_patch_langchain_tool_call_parser()

POLICY_LOG_DIR = os.path.join(LOG_DIR, "policy_feedback")
POLICY_LOG_FILE = os.path.join(POLICY_LOG_DIR, "policy_feedback.jsonl")


def _append_policy_feedback(entry: dict) -> None:
    """Persistiert Policy-Entscheidungen für spätere Analyse/Training."""
    try:
        os.makedirs(POLICY_LOG_DIR, exist_ok=True)
        with open(POLICY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.debug("Policy-Feedback konnte nicht geschrieben werden: %s", exc)

def _get_tools() -> list:
    return ALL_TOOLS

load_dotenv()

_THINK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*", re.DOTALL)
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
MAX_MESSAGES = 30  # Kontext-Budget für mehrstufige Setups (Phase-4 + FX = ~15 Schritte)
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
  /add track         — Instrument-Track hinzufügen
  /add effect        — Effect/Return-Track hinzufügen
  /add group         — Group-Track hinzufügen
  /select <n>        — Track n auswählen
  /mute <n>          — Track n muten
  /solo <n>          — Track n solo
  /volume <n> <wert> — Lautstärke setzen  (z.B. /volume 1 0.8)

Devices
  /load <name>       — Instrument laden  (z.B. /load Phase-4)
  /param <n> <wert>  — Parameter n setzen  (0.0–1.0)
  /undo              — Letzten Schritt rückgängig

Launchpad MK2
  /map pad <n> <aktion>  — Pad belegen  (z.B. /map pad 1 play_stop)
  /clear pads            — Alle Pad-Mappings löschen

  Aktionen: play_stop  stop  record  undo
            loop_toggle  mute_toggle  next_track  prev_track
  Pad-Noten: Pad 1=11, Pad 2=12, … Pad 8=18

Info
  /status            — Aktuellen Bitwig-Status abfragen
  /hilfe             — Diese Übersicht

Für Erklärungen einfach normal fragen — kein /  nötig:
  "Wie funktioniert FM-4?"
  "Was ist ein Sidechain-Kompressor?"
"""

# Schlüsselwörter im Reasoning → GenerationPhase-Mapping (Reihenfolge: spezifisch zuerst)
_PHASE_SIGNALS: list[tuple[list[str], GenerationPhase]] = [
    (["fehler", "error", "nicht erreichbar", "verbindung", "failed"],  "error"),
    (["fertig", "abgeschlossen", "song ist bereit", "done", "riff wurde"],  "done"),
    (["verif", "überprüf", "prüf", "playback", "abspielen"],              "verifying"),
    (["noten schreib", "write_notes", "clip", "midi schreib", "riff schreib"],  "generating"),
    (["instrument", "track anlegen", "setup_instrument", "fm-4", "polysynth"],  "setup"),
    (["plan", "struktur", "bluep", "section", "akkord"],                   "planning"),
]


def _log_token_usage(response: AIMessage, label: str = "") -> dict:
    """Loggt Token-Nutzung mit Thinking- vs. Rest-Aufschlüsselung."""
    meta = getattr(response, "usage_metadata", None) or {}
    input_tok  = meta.get("input_tokens", 0)
    output_tok = meta.get("output_tokens", 0)
    total_tok  = meta.get("total_tokens", input_tok + output_tok)

    # Thinking-Tokens: vLLM liefert ggf. completion_tokens_details.reasoning_tokens
    think_tok = 0
    resp_meta = getattr(response, "response_metadata", None) or {}
    usage_raw = resp_meta.get("usage", resp_meta.get("token_usage", {})) or {}
    details   = usage_raw.get("completion_tokens_details") or {}
    think_tok = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0

    # Fallback: Schätzung aus <think>-Block-Länge (~4 Zeichen pro Token)
    think_estimated = False
    if think_tok == 0:
        raw_content = getattr(response, "content", "") or ""
        m = _THINK_RE.search(raw_content)
        if m:
            think_tok = len(m.group(1)) // 4
            think_estimated = True

    non_think = max(0, output_tok - think_tok)
    prefix = f" [{label}]" if label else ""
    est_mark = "≈" if think_estimated else ""
    line = (
        f"TOKENS{prefix}  "
        f"input={input_tok} | "
        f"output={output_tok}  "
        f"(thinking{est_mark}={think_tok} [{(think_tok/output_tok*100):.0f}%]  "
        f"rest={non_think} [{(non_think/output_tok*100):.0f}%])  "
        f"| total={total_tok}"
        if output_tok else
        f"TOKENS{prefix}  input={input_tok} | output={output_tok} | total={total_tok}  [keine Usage-Daten]"
    )
    log.info(line)
    print(line, flush=True)

    usage = {
        "input_tokens":    input_tok,
        "output_tokens":   output_tok,
        "thinking_tokens": think_tok,
        "rest_tokens":     non_think,
        "total_tokens":    total_tok,
        "label":           label,
    }
    try:
        get_event_bus().emit("token_usage", usage)
    except Exception:
        pass
    return usage


def _get_llm(max_tokens: int = 3000) -> BaseChatModel:
    test_mode = os.getenv("BITWIG_TEST_MODE", "").lower() == "mock"
    
    if test_mode:
        log.info("TEST_MODE: Verwende Mock-LLM statt vLLM-Backend")
        return MockLLM()
    else:
        base = os.getenv("VLLM_BASE_URL", "http://192.168.0.3:8100") + "/v1"
        model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
        return ChatOpenAI(
            base_url=base,
            api_key="vllm",
            model=model,
            temperature=0.6,
            max_tokens=max_tokens,
            timeout=120,
        )


def _latest_user_text(messages: list) -> str:
    """Liefert die letzte echte User-Nachricht (ohne interne Nudge-Nachrichten)."""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = (m.content or "").strip()
            if text and not any(text.startswith(p) for p in _NUDGE_PREFIXES):
                return text
    return ""


def _latest_human_is_nudge(messages: list) -> bool:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            text = (m.content or "").strip()
            return bool(text and any(text.startswith(p) for p in _NUDGE_PREFIXES))
    return False


# Kurze Zustimmungen die vorherigen Vorschlag bestätigen → ausführen
_CONFIRMATIONS = frozenset([
    "ja", "ja bitte", "ja!", "ok", "klar", "gut", "los",
    "mach das", "mach es", "alles klar", "bitte", "mach",
])

def _is_knowledge_question(text: str) -> bool:
    """Alles ist Wissensfrage AUSSER: Slash-Commands oder kurze Zustimmungen."""
    lower = text.lower().strip()
    if lower.startswith("/"):
        return False
    if lower in _CONFIRMATIONS or any(
        lower == c or lower.startswith(c + " ") or lower.startswith(c + ",")
        for c in _CONFIRMATIONS
    ):
        return False
    return True


# ── Master Router ─────────────────────────────────────────────────────────────
# Bestimmt aus dem User-Prompt welche Phase (und damit welche Tools + Prompt)
# benötigt werden. Kein LLM-Call — reines Keyword-Routing.

_CONTROL_COMMANDS = frozenset(["/play", "/stop", "/tempo", "/select", "/mute", "/solo", "/volume", "/status", "/record", "/loop", "/undo"])
_LAUNCHPAD_KEYWORDS = frozenset(["launchpad", "/map pad", "/clear pads", "pad belegen", "pad zuweisen"])

# Tool-Namen pro Modus (aus dem kombinierten MCP+Agent-Pool filtern)
_SONG_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "execute_setup",
    "get_bitwig_track_state", "query_bitwig_docs",
])
_CONTROL_TOOL_NAMES = frozenset([
    "check_bitwig_connection", "control_bitwig",
    "bitwig_play", "bitwig_stop", "bitwig_set_tempo",
    "bitwig_select_track", "bitwig_set_track_volume",
    "bitwig_pan_track", "bitwig_solo_track", "bitwig_mute_track",
    "bitwig_eq_band",
])
_LAUNCHPAD_TOOL_NAMES = frozenset([
    "check_bitwig_connection",
    "bitwig_launchpad_map", "bitwig_launchpad_led", "bitwig_launchpad_clear",
])


def _route_request(text: str) -> str:
    """Gibt 'song' | 'control' | 'launchpad' zurück."""
    lower = text.lower().strip()
    if any(kw in lower for kw in _LAUNCHPAD_KEYWORDS):
        return "launchpad"
    if lower.startswith("/"):
        cmd = lower.split()[0]
        if cmd in _CONTROL_COMMANDS:
            return "control"
    return "song"


def _get_prompt_for_mode(mode: str) -> str:
    if mode == "control":
        return PROMPT_CONTROL
    if mode == "launchpad":
        return PROMPT_LAUNCHPAD
    return PROMPT_SONG


def _filter_tools_for_mode(mode: str, all_tools: list) -> list:
    """Gibt nur die für den Modus relevanten Tools zurück."""
    allowed = {"song": _SONG_TOOL_NAMES, "control": _CONTROL_TOOL_NAMES,
               "launchpad": _LAUNCHPAD_TOOL_NAMES}.get(mode, _SONG_TOOL_NAMES)
    filtered = [t for t in all_tools if getattr(t, "name", "") in allowed]
    # Fallback: mind. check_bitwig_connection immer dabei
    if not filtered:
        return [t for t in all_tools if getattr(t, "name", "") == "check_bitwig_connection"] or all_tools
    return filtered


def _select_tools_for_context(all_messages: list) -> list:
    """Gibt Tool-Set basierend auf der letzten User-Nachricht zurück."""
    user_text = _latest_user_text(all_messages)
    mode = _route_request(user_text)
    all_tools = _get_tools()
    tools = _filter_tools_for_mode(mode, all_tools)
    log.info("Router: mode=%s → %d Tools: %s", mode, len(tools),
             [getattr(t, "name", "?") for t in tools])
    return tools


def _extract_think(text: str) -> tuple[str, str]:
    """Gibt (reasoning, cleaned_text) zurück — reasoning ist der <think>-Inhalt."""
    match = _THINK_RE.search(text)
    reasoning = match.group(1).strip() if match else ""
    cleaned = _THINK_RE.sub("", text)
    cleaned = _THINK_OPEN.sub("", cleaned)
    return reasoning, cleaned.strip()


def _phase_from_reasoning(reasoning: str, current: GenerationPhase) -> GenerationPhase | None:
    """Leitet die neue generation_phase aus dem LLM-Reasoning ab.

    Gibt None zurück wenn keine passende Phase erkannt wurde.
    Terminale Phasen ("error", "done") werden nie durch Reasoning überschrieben.
    """
    if not reasoning:
        return None
    # Terminale Phasen sind unveränderlich — nur Tool-Ergebnisse dürfen sie setzen
    if current in ("error", "done"):
        return None
    lower = reasoning.lower()
    for keywords, phase in _PHASE_SIGNALS:
        if any(kw in lower for kw in keywords):
            if phase != current:
                return phase
            return None  # Keine Änderung nötig
    return None


def _recover_tool_calls(response: AIMessage, state: AgentState | None = None) -> AIMessage:
    """Fallback-Parser via CompositeToolCallParser (F7 — Parser-Chain)."""
    from src.agent.parsing.tool_call_parsers import TOOL_CALL_PARSER
    return TOOL_CALL_PARSER.patch_message(response)


_KNOWN_TOOL_NAMES: frozenset[str] = frozenset([
    "query_bitwig_docs", "control_bitwig",
    "check_bitwig_connection", "bitwig_check_connection", "get_bitwig_track_state",
    "execute_setup",
    "bitwig_launchpad_map", "bitwig_launchpad_led", "bitwig_launchpad_clear",
])

# Diagnostic categories for invalid tool outputs
InvalidOutputCategory = str  # "xml_fragment" | "truncated_json" | "empty_args" | "unknown_tool_schema" | "unknown"


def _classify_invalid_output(response: AIMessage) -> InvalidOutputCategory:
    """Klassifiziert die Art des ungültigen Tool-Outputs für strukturiertes Logging."""
    content = response.content if isinstance(response.content, str) else ""

    # Offenes <tool_call> ohne schließendes Tag
    if "<tool_call>" in content and "</tool_call>" not in content:
        return "xml_fragment"

    # <tool_call> mit schließendem Tag — JSON-Inhalt prüfen
    if "<tool_call>" in content and "</tool_call>" in content:
        inner = content.split("<tool_call>", 1)[-1].split("</tool_call>", 1)[0].strip()
        try:
            json.loads(inner)
            return "malformed_args"  # valides JSON, aber falsches Schema
        except json.JSONDecodeError:
            return "truncated_json"  # unvollständiges / kaputtes JSON

    # tool_calls-Objekte prüfen (falls vorhanden aber leer/unbekannt)
    for tc in (response.tool_calls or []):
        if not tc.get("args"):
            return "empty_args"
        name = tc.get("name", "")
        if name and name not in _KNOWN_TOOL_NAMES:
            return "unknown_tool_schema"

    return "unknown"


def _has_invalid_tool_output(response: AIMessage) -> bool:
    """Erkennt kaputte Tool-Ausgaben (z. B. abgeschnittenes <tool_call>)."""
    if getattr(response, "tool_calls", None):
        return False
    if not isinstance(response.content, str):
        return False
    content = response.content
    return "<tool_call>" in content


def _recover_xml_fragment_once(
    system: SystemMessage,
    messages: list,
    selected_tools: list,
    state: AgentState,
) -> AIMessage | None:
    """Einmaliger Hard-Reask für XML-Fragment-Antworten.

    Nutzt minimales Toolset und kurze Message-Historie, um valide Tool-Calls zu erzwingen.
    """
    fallback_tools = [
        t for t in _get_tools()
        if getattr(t, "name", "") in {
            "check_bitwig_connection",
            "execute_setup",
            "query_bitwig_docs",
        }
    ]
    llm = _get_llm(max_tokens=4000).bind_tools(fallback_tools or selected_tools)
    hard_nudge = HumanMessage(
        content=(
            "Deine letzte Antwort war ein XML-Fragment — der Tool-Call wurde abgeschnitten. "
            "Führe die ursprüngliche Aufgabe vollständig aus: "
            "Generiere denselben execute_setup-Call erneut, diesmal komplett und valide. "
            "Keine XML-Tags, kein Markdown, kein Freitext — nur ein ausführbarer Tool-Call."
        )
    )
    try:
        candidate = llm.invoke([system] + messages[-6:] + [hard_nudge])
        _log_token_usage(candidate, label="xml-recovery")
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


def call_llm(state: AgentState) -> dict:
    all_messages = state["messages"]

    # /hilfe — statische Antwort ohne LLM-Call
    user_text = _latest_user_text(all_messages)
    if user_text.lower().strip() in ("/hilfe", "/help", "/befehle", "/commands"):
        return {"messages": [AIMessage(content=_HELP_TEXT)]}

    messages = all_messages[-MAX_MESSAGES:]
    # Tool-Results kürzen: notes_json-Antworten können Hunderte Tokens sein
    from langchain_core.messages import ToolMessage
    trimmed = []
    for m in messages:
        if isinstance(m, ToolMessage) and isinstance(m.content, str) and len(m.content) > 400:
            trimmed.append(ToolMessage(content=m.content[:400] + " …[gekürzt]", tool_call_id=m.tool_call_id))
        else:
            trimmed.append(m)
    messages = trimmed
    selected_tools = _select_tools_for_context(all_messages)
    mode = _route_request(_latest_user_text(all_messages))
    prompt_text = _get_prompt_for_mode(mode)
    llm = _get_llm().bind_tools(selected_tools) if selected_tools else _get_llm()
    system = SystemMessage(content=prompt_text)
    log.info("LLM call — mode=%s %d Nachrichten, %d Tools", mode, len(messages), len(selected_tools))
    try:
        response = llm.invoke([system] + messages)
        _log_token_usage(response, label="main")
    except BadRequestError as exc:
        msg = str(exc)
        # Kontext-Overflow: mit kleinerem Toolset + weniger Output-Tokens erneut versuchen.
        if "maximum context length" in msg or "input_tokens" in msg:
            fallback_tools = [
                t for t in _get_tools()
                if getattr(t, "name", "") in {
                    "check_bitwig_connection",
                    "execute_setup",
                }
            ]
            fallback_llm = _get_llm(max_tokens=700).bind_tools(fallback_tools or selected_tools)
            fallback_messages = messages[-6:]
            log.warning(
                "LLM Kontextlimit erreicht — Fallback mit %d Tools, %d Messages, max_tokens=700",
                len(fallback_tools or selected_tools),
                len(fallback_messages),
            )
            try:
                response = fallback_llm.invoke([SystemMessage(content=PROMPT_CONTROL)] + fallback_messages)
                _log_token_usage(response, label="fallback")
            except Exception as fallback_exc:
                log.error("LLM Fallback-Invoke fehlgeschlagen: %s", fallback_exc, exc_info=True)
                get_event_bus().emit("agent_error", {
                    "source": "llm_fallback",
                    "error": type(fallback_exc).__name__,
                    "message": str(fallback_exc),
                })
                raise RuntimeError(
                    f"LLM nicht erreichbar — Kontext zu groß, Fallback ebenfalls fehlgeschlagen: {fallback_exc}"
                ) from fallback_exc
        else:
            raise

    # ── Reasoning extrahieren, emittieren, Phase ableiten ────────────────────
    updates: dict = {}
    if hasattr(response, "content") and isinstance(response.content, str):
        reasoning, cleaned = _extract_think(response.content)
        response.content = cleaned
        if reasoning:
            current_phase: GenerationPhase = state.get("generation_phase", "idle")
            new_phase = _phase_from_reasoning(reasoning, current_phase)
            bus = get_event_bus()
            bus.emit("reasoning", {
                "text":         reasoning[:500],  # max 500 Zeichen im Event
                "current_phase": current_phase,
                "detected_phase": new_phase,
                "msg_count":     len(messages),
            })
            if new_phase is not None:
                log.info("Phase %s → %s (aus Reasoning)", current_phase, new_phase)
                bus.emit("phase_change", {"from": current_phase, "to": new_phase})
                updates["generation_phase"] = new_phase

    response = _recover_tool_calls(response, state)

    # ── Kaputte Tool-Ausgaben abfangen, Observer informieren, neu generieren ─
    if _has_invalid_tool_output(response):
        retry = state.get("retry_count", 0) + 1
        snippet = (response.content or "")[:300]
        diagnostic = _classify_invalid_output(response)
        user_text = _latest_user_text(all_messages)
        log.warning(
            "LLM: ungültiger Tool-Output erkannt (%s) — Regenerierung #%d",
            diagnostic,
            retry,
        )
        outcome = "abort" if retry >= 3 else "retry"
        event_payload = {
            "diagnostic": diagnostic,
            "phase": state.get("generation_phase", "idle"),
            "retry": retry,
            "snippet": snippet,
            "outcome": outcome,
            "user_prompt": user_text[:200],
        }
        get_event_bus().emit("invalid_tool_output", event_payload)
        _append_policy_feedback({
            "timestamp": datetime.now().isoformat(),
            "action": "invalid_tool_output",
            "diagnostic": diagnostic,
            "phase": state.get("generation_phase", "idle"),
            "retry": retry,
            "snippet": snippet,
            "outcome": outcome,
            "user_prompt": user_text[:200],
        })

        # Spezieller Recovery-Pfad: XML-Fragment einmal hart regenerieren.
        if diagnostic == "xml_fragment":
            recovered = _recover_xml_fragment_once(system, messages, selected_tools, state)
            if recovered is not None:
                log.info("LLM: xml_fragment erfolgreich auto-recovered")
                get_event_bus().emit("invalid_tool_output_recovered", {
                    "diagnostic": diagnostic,
                    "phase": state.get("generation_phase", "idle"),
                    "retry": retry,
                })
                _append_policy_feedback({
                    "timestamp": datetime.now().isoformat(),
                    "action": "invalid_tool_output_recovered",
                    "diagnostic": diagnostic,
                    "phase": state.get("generation_phase", "idle"),
                    "retry": retry,
                })
                return {
                    "messages": [recovered],
                    "retry_count": state.get("retry_count", 0),
                    **updates,
                }

        # Harte Grenze: nicht endlos regenerieren
        if retry >= 3:
            msg = AIMessage(
                content=(
                    "Abbruch: Wiederholt ungültige Tool-Ausgaben vom Modell. "
                    "Bitte Anfrage erneut senden oder Prompt vereinfachen."
                )
            )
            return {"messages": [msg], "retry_count": retry, **updates}

        nudge = HumanMessage(
            content=(
                "Dein Tool-Call war ungültig oder abgeschnitten. "
                "Generiere denselben Schritt erneut als gültigen Tool-Call. "
                "Kein Freitext, kein XML-Fragment, nur ein ausführbarer Tool-Call "
                "mit validen JSON-Args."
            )
        )
        return {"messages": [response, nudge], "retry_count": retry, **updates}

    proposed_tool_calls = [dict(tc) for tc in (response.tool_calls or [])]

    # ── Policy-Guard: Tool-Entscheidungen deterministisch validieren ─────────
    response, policy_meta = enforce_policy_on_response(state, response)
    final_tool_calls = [dict(tc) for tc in (response.tool_calls or [])]

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
        "proposed_tool_calls": proposed_tool_calls,
        "final_tool_calls": final_tool_calls,
    })

    if policy_meta.get("action") == "rewrite":
        log.info("PolicyGuard rewrite angewendet: %s", policy_meta.get("violations", []))
        get_event_bus().emit("policy_violation", {
            "violations": policy_meta.get("violations", []),
            "action": "rewrite",
            "phase": state.get("generation_phase", "idle"),
        })
        get_event_bus().emit("policy_rewrite_applied", {
            "before": proposed_tool_calls,
            "after": final_tool_calls,
            "phase": state.get("generation_phase", "idle"),
        })
    elif policy_meta.get("action") == "allow":
        get_event_bus().emit("policy_check", {
            "action": "allow",
            "phase": state.get("generation_phase", "idle"),
        })

    # ── Leere Antwort (think-only) — Nudge zurück zum Agenten ────────────────
    has_tool_calls = bool(getattr(response, "tool_calls", None))
    if not has_tool_calls and not (response.content or "").strip():
        retry = state.get("retry_count", 0) + 1
        log.warning("LLM: leere Antwort (think-only) — Nudge #%d", retry)
        nudge = HumanMessage(
            content="Deine Antwort war leer. Bitte ruf jetzt direkt ein passendes Tool auf "
                    "um die Aufgabe zu erledigen. Kein Text, nur Tool-Call."
        )
        return {"messages": [response, nudge], "retry_count": retry, **updates}

    # Tool-Calls loggen
    if has_tool_calls:
        for tc in response.tool_calls:
            log.info("Tool-Call: %s(%s)", tc["name"],
                     str(tc.get("args", {}))[:120])
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


def _start_agent_ui_osc_listener(on_prompt) -> object | None:
    """Startet OSC-Listener für Bitwig-internes Agent-UI.

    Unterstützt:
      - /agent/ui/prompt <text>
      - /agent/ui/config <json>

    Antworten werden per OSC an Bitwig/Plugin zurückgesendet (/agent/ui/response).
    """
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc import osc_server, udp_client
    except Exception as exc:
        log.warning("Agent UI OSC deaktiviert (python-osc fehlt): %s", exc)
        return None

    listen_host = os.getenv("BITWIG_AGENT_UI_HOST", "127.0.0.1")
    listen_port = int(os.getenv("BITWIG_AGENT_UI_PORT", "9003"))
    bitwig_host = os.getenv("BITWIG_HOST", "127.0.0.1")
    bitwig_port = int(os.getenv("BITWIG_PORT", "8001"))
    # Port 8001 → Bitwig Controller Extension; port 9004 → CLAP plugin
    plugin_port = int(os.getenv("AGENT_PLUGIN_RESPONSE_PORT", "9004"))
    plugin_host = os.getenv("AGENT_PLUGIN_HOST", bitwig_host)
    out_clients = [
        udp_client.SimpleUDPClient(bitwig_host, bitwig_port),
        udp_client.SimpleUDPClient(plugin_host, plugin_port),
    ]

    def _send_ui_response(text: str) -> None:
        msg = (text or "")[:500]
        for client in out_clients:
            try:
                client.send_message("/agent/ui/response", msg)
            except Exception as exc:
                log.debug("Agent UI Antwort konnte nicht gesendet werden: %s", exc)

    def _process_prompt(prompt: str) -> None:
        _send_ui_response("Prompt empfangen, generiere...")
        try:
            reply = on_prompt(prompt)
            _send_ui_response(reply or "Fertig")
        except Exception as exc:
            log.exception("Agent UI Prompt-Fehler")
            _send_ui_response(f"Fehler: {exc}")

    def _handle_prompt(_address: str, *args: Any) -> None:
        prompt = str(args[0]).strip() if args else ""
        if not prompt:
            _send_ui_response("Prompt ist leer")
            return
        log.info("Agent UI Prompt empfangen: %s", prompt[:120])
        threading.Thread(target=_process_prompt, args=(prompt,), daemon=True).start()

    def _handle_config(_address: str, *args: Any) -> None:
        raw = str(args[0]).strip() if args else ""
        if not raw:
            _send_ui_response("Config ist leer")
            return
        try:
            cfg = json.loads(raw)
            if not isinstance(cfg, dict):
                raise ValueError("JSON muss ein Objekt sein")
            prompt = str(cfg.get("prompt", "")).strip()
            bpm = cfg.get("bpm")
            if not prompt:
                _send_ui_response("Prompt ist leer")
                return
            # Bitwig UI-Prompts immer ausführen (User hat explizit "Send" gedrückt)
            if not prompt.startswith("/"):
                prompt = "/ " + prompt
            _set_latest_ui_config({"bpm": bpm} if bpm else {})
            log.info("Agent UI Config empfangen: prompt=%s bpm=%s", prompt[:80], bpm)
            threading.Thread(target=_process_prompt, args=(prompt,), daemon=True).start()
        except Exception as exc:
            log.warning("Agent UI Config parse error: %s", exc)
            _send_ui_response(f"Config-Fehler: {exc}")

    dispatcher = Dispatcher()
    dispatcher.map("/agent/ui/prompt", _handle_prompt)
    dispatcher.map("/agent/ui/config", _handle_config)

    import socket as _socket
    # SO_REUSEPORT erlaubt sofortigen Neustart ohne "Address already in use"
    server = osc_server.ThreadingOSCUDPServer((listen_host, listen_port), dispatcher,
                                              bind_and_activate=False)
    server.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
    try:
        server.socket.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEPORT, 1)
    except AttributeError:
        pass  # SO_REUSEPORT nicht auf allen Plattformen verfügbar
    server.server_bind()
    server.server_activate()

    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Agent UI OSC Listener aktiv auf %s:%d", listen_host, listen_port)
    return server


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

    IDLE_TIMEOUT = int(os.getenv("AGENT_IDLE_TIMEOUT", "600"))  # Sekunden, 0 = kein Timeout
    _last_request = [_time.monotonic()]

    def _run_request_threadsafe(user: str) -> str:
        _last_request[0] = _time.monotonic()
        with history_lock:
            return _run_request(user)

    def _idle_watchdog():
        while True:
            _time.sleep(30)
            if IDLE_TIMEOUT > 0 and (_time.monotonic() - _last_request[0]) > IDLE_TIMEOUT:
                log.info("Idle-Timeout (%ds) erreicht — Agent beendet sich.", IDLE_TIMEOUT)
                os.kill(os.getpid(), _signal.SIGTERM)
                break

    if IDLE_TIMEOUT > 0:
        threading.Thread(target=_idle_watchdog, daemon=True).start()
        log.info("Idle-Timeout aktiv: %ds (AGENT_IDLE_TIMEOUT)", IDLE_TIMEOUT)

    _start_agent_ui_osc_listener(_run_request_threadsafe)

    if not sys.stdin.isatty():
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

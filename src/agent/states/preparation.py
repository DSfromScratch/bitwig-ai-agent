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
    classify_note_input_answer,
)
from src.agent.states.base import AgentPhaseState, PhaseContext

log = logging.getLogger("bitwig-agent")

RECENT_MESSAGES = 4
MAX_TOOL_RESULT_CHARS = 300
MAX_HISTORY_SUMMARY_CHARS = 1000
MAX_SUMMARY_ITEM_CHARS = 180
MAX_PHASE_SUMMARY_CHARS = 700


def _build_note_input_question(user_text: str = "") -> str:
    """Baut die Launchpad/Agent-Frage — filtert Instrumente nach Stichwort aus user_text."""
    base = (
        "Möchtest du die Noten selbst einspielen oder soll ich sie generieren?\n\n"
        "1. Launchpad — du spielst live ein (+ Instrument angeben)\n"
        "2. Agent — ich generiere die Noten automatisch\n"
    )
    instrument_block = _fetch_instrument_list(user_text)
    if instrument_block:
        base += f"\n{instrument_block}"
        base += "\nBeispiel-Antwort: \"1. Arturia Bass V3\""
    return base


_INSTRUMENT_CATEGORIES = frozenset(["synthesizer", "sampler", "oscillator"])

_INSTRUMENT_KEYWORDS = {
    "bass":      ["bass"],
    "piano":     ["piano", "keys", "keyboard", "klavier"],
    "synth":     ["synth", "lead", "pad", "arp"],
    "drums":     ["drum", "beat", "schlagzeug", "kick"],
    "guitar":    ["guitar", "gitarre"],
    "strings":   ["string", "violin", "cello", "streicher"],
    "sampler":   ["sample", "kontakt"],
}

# Compound phrases checked before individual keywords to avoid "bass drum" → "bass"
_COMPOUND_KEYWORDS: list[tuple[str, str]] = [
    ("bass drum",    "drum"),
    ("drum kit",     "drum"),
    ("drum machine", "drum"),
    ("kick drum",    "drum"),
    ("808",          "drum"),
]


def _extract_search_term(user_text: str) -> str | None:
    """Extrahiert ein Instrument-Stichwort aus dem User-Request (z.B. 'drum' aus 'Drum Kit')."""
    lower = user_text.lower()
    # Compound-Begriffe zuerst (verhindert dass "bass drum" → "bass")
    for phrase, term in _COMPOUND_KEYWORDS:
        if phrase in lower:
            return term
    for keywords in _INSTRUMENT_KEYWORDS.values():
        for kw in keywords:
            if kw in lower:
                return kw
    return None


def _fetch_instrument_list(user_text: str = "") -> str:
    """Lädt Instrumente aus Neo4j, gefiltert nach Namens-Stichwort wenn erkennbar."""
    search = _extract_search_term(user_text)
    try:
        from src.knowledge.neo4j_graph import session
        with session() as s:
            if search:
                # Gezielt nach Namen suchen (Device + InstalledPlugin)
                rows = s.run(
                    "MATCH (d:Device) "
                    "WHERE (d.category IN $cats OR d.device_type = 'instrument') "
                    "  AND toLower(d.name) CONTAINS $term "
                    "RETURN d.name AS name, coalesce(d.category,'synthesizer') AS category "
                    "ORDER BY d.name LIMIT 12",
                    cats=list(_INSTRUMENT_CATEGORIES), term=search,
                ).data()
                vst_rows = s.run(
                    "MATCH (p:InstalledPlugin {installed: true}) "
                    "WHERE toLower(p.name) CONTAINS $term "
                    "RETURN p.name AS name, p.type AS category "
                    "ORDER BY p.name LIMIT 12",
                    term=search,
                ).data()
            else:
                # Alle Kategorien, aber nur echte Plugin-Nodes (kein Name-only-Fallback)
                rows = s.run(
                    "MATCH (d:Device) "
                    "WHERE d.category IN $cats "
                    "  AND NOT d.name IN ['Drum Machine','E-Clap','E-Cowbell','E-Hat',"
                    "                     'E-Kick','E-Snare','E-Tom','Hi-hat','Kick','Tom'] "
                    "RETURN d.name AS name, d.category AS category "
                    "ORDER BY category, d.name",
                    cats=list(_INSTRUMENT_CATEGORIES),
                ).data()
                vst_rows = s.run(
                    "MATCH (p:InstalledPlugin {installed: true}) "
                    "RETURN p.name AS name, p.type AS category "
                    "ORDER BY p.type, p.name LIMIT 40"
                ).data()

            rows.extend(vst_rows)

        if not rows:
            return ""

        by_cat: dict[str, list[str]] = {}
        seen: set[str] = set()
        for r in rows:
            n = r["name"]
            if n in seen:
                continue
            seen.add(n)
            by_cat.setdefault(r.get("category", "synthesizer"), []).append(n)

        header = (f"Passende Instrumente für '{search}':"
                  if search else "Verfügbare Instrumente (oder beliebigen VST-Namen eingeben):")
        lines = [header]
        for cat, names in sorted(by_cat.items()):
            lines.append(f"  {cat}: {', '.join(names)}")
        return "\n".join(lines)
    except Exception:
        return ""


_NOTE_INPUT_HINTS = {
    "launchpad": (
        "HINWEIS: Der User möchte die Noten SELBST auf dem Launchpad einspielen.\n"
        "Das gewünschte Instrument steht in der User-Antwort (z.B. '1. Arturia Bass V3').\n"
        "Schritt 1: execute_setup aufrufen — add_track + load_instrument mit dem genannten Instrument.\n"
        "  Falls kein Instrument erkennbar: nimm ein generisches Bass-/Synth-Preset.\n"
        "Schritt 2: launchpad(action='arm', arm=1) aufrufen.\n"
        "NICHT generate_pattern, write_pattern_raw oder launchpad(action='listen') aufrufen."
    ),
    "agent": (
        "HINWEIS: Der User möchte dass der AGENT die Noten automatisch generiert.\n"
        "→ Ruf execute_setup auf, danach generate_pattern mit den gewünschten Parametern.\n"
        "NICHT launchpad(action='listen') aufrufen."
    ),
}


class PreparationState(AgentPhaseState):
    def execute(self, ctx: PhaseContext) -> PhaseContext:
        from langchain_core.messages import AIMessage
        from src.agent.tools import ALL_TOOLS
        from src.agent.router import _select_tools_for_context as _filter

        all_messages = ctx.agent_state["messages"]
        user_text = _latest_user_text(all_messages)
        current_phase = ctx.agent_state.get("generation_phase", "idle")
        note_input_mode = ctx.agent_state.get("note_input_mode")

        phase = _effective_generation_phase(all_messages, current_phase, user_text)

        # Intent einmal per LLM klassifizieren — alle nachfolgenden States lesen ctx.intent
        ctx.intent = classify_intent_llm(user_text)

        # ── Noten-Eingabe-Abfrage ────────────────────────────────────────────
        if ctx.intent == "song_creation" and note_input_mode is None:
            # Frage stellen — kein LLM-Call nötig
            ctx.early_return = {
                "messages": [AIMessage(content=_build_note_input_question(user_text))],
                "generation_phase": phase,
                "note_input_mode": "pending",
            }
            log.info("note_input_mode: Frage gestellt")
            return ctx

        if note_input_mode == "pending":
            # Antwort klassifizieren — auch wenn intent=launchpad (User hat "Launchpad" geantwortet)
            note_input_mode = classify_note_input_answer(user_text)
            ctx.updates["note_input_mode"] = note_input_mode
            log.info("note_input_mode: %s (aus '%s')", note_input_mode, user_text[:40])

        # ── Phase done → kein Tool-Call, nur Zusammenfassung ─────────────────
        if phase == "done":
            ctx.updates["generation_phase"] = "done"
            ctx.intent = ctx.intent or classify_intent_llm(user_text)
            ctx.selected_tools = []
            ctx.messages = self._prepare_messages(all_messages, current_phase, phase, note_input_mode)
            mode = _route_request(user_text)
            ctx.system = SystemMessage(content=_get_prompt_for_mode(mode))
            log.info("LLM call (done summary) — intent=%s 0 Tools", ctx.intent)
            return ctx

        ctx.messages = self._prepare_messages(all_messages, current_phase, phase, note_input_mode)
        if phase != current_phase:
            ctx.updates["generation_phase"] = phase

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
        note_input_mode: str | None = None,
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
        # Modus-Hint als ersten Kontext einfügen damit das LLM weiß was zu tun ist
        if note_input_mode in _NOTE_INPUT_HINTS:
            messages.insert(0, SystemMessage(content=_NOTE_INPUT_HINTS[note_input_mode]))
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

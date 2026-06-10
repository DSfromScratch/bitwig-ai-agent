#!/usr/bin/env python3
"""Bitwig AI Agent — Console Interface"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Input, RichLog, Static, Label
from textual import work
from rich.text import Text

from dotenv import load_dotenv
load_dotenv()


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
Screen {
    background: #0d1117;
}

#status-bar {
    height: 3;
    background: #161b22;
    border-bottom: solid #21262d;
    padding: 0 2;
    content-align: left middle;
    color: #8b949e;
}

#chat {
    height: 1fr;
    background: #0d1117;
    padding: 1 2;
    scrollbar-gutter: stable;
    scrollbar-background: #0d1117;
    scrollbar-color: #21262d;
}

#thinking-bar {
    height: 1;
    background: #0d1117;
    padding: 0 2;
    color: #d29922;
    display: none;
}

#thinking-bar.visible {
    display: block;
}

#input-container {
    height: 3;
    background: #161b22;
    border-top: solid #21262d;
    padding: 0 1;
    layout: horizontal;
    content-align: left middle;
}

#prompt-label {
    width: 5;
    color: #58a6ff;
    content-align: left middle;
}

#user-input {
    background: transparent;
    border: none;
    color: #e6edf3;
    height: 1;
    width: 1fr;
}

#user-input:focus {
    border: none;
}

Footer {
    background: #161b22;
    color: #6e7681;
}
"""


# ── Chat Log ──────────────────────────────────────────────────────────────────

class ChatLog(RichLog):

    def add_user(self, text: str) -> None:
        self.write(Text(""))
        msg = Text()
        msg.append("  You  ", style="bold black on #58a6ff")
        msg.append("  " + text, style="#e6edf3")
        self.write(msg)

    def add_agent(self, text: str) -> None:
        msg = Text()
        msg.append(" Agent ", style="bold black on #3fb950")
        msg.append("  " + text, style="#e6edf3")
        self.write(msg)
        self.write(Text(""))

    def add_tool(self, name: str, args: dict) -> None:
        args_str = ", ".join(
            f"{k}={repr(v)[:40]}" for k, v in list(args.items())[:3]
        )
        msg = Text()
        msg.append("  ◆ ", style="#8b949e")
        msg.append(name, style="bold #d2a8ff")
        msg.append(f"({args_str})", style="#8b949e")
        self.write(msg)

    def add_error(self, text: str) -> None:
        msg = Text()
        msg.append("  ✗ ", style="#f85149")
        msg.append(text, style="#f85149")
        self.write(msg)
        self.write(Text(""))

    def add_system(self, text: str) -> None:
        self.write(Text("  " + text, style="italic #6e7681"))


# ── Main App ──────────────────────────────────────────────────────────────────

class BitwigCLI(App):
    TITLE = "Bitwig AI Agent"
    CSS = CSS

    BINDINGS = [
        Binding("ctrl+c", "quit",       "Beenden",  priority=True),
        Binding("ctrl+l", "clear_chat", "Löschen"),
        Binding("f1",     "show_help",  "Hilfe"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._session_state: dict | None = None
        self._history_lock = threading.Lock()
        self._pending_tools: list[dict] = []
        self._setup_event_bus()

    def compose(self) -> ComposeResult:
        yield Static(id="status-bar")
        yield ChatLog(id="chat", highlight=True, markup=True, wrap=True)
        yield Label("  ⠋ Thinking…", id="thinking-bar")
        with Horizontal(id="input-container"):
            yield Static("›", id="prompt-label")
            yield Input(placeholder="Nachricht eingeben…", id="user-input")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_status()
        self.set_interval(30, self._refresh_status)
        chat = self.query_one(ChatLog)
        chat.add_system("Bitwig AI Agent bereit.  /help für Befehle.")
        self.query_one("#user-input").focus()

    # ── Status ────────────────────────────────────────────────────────────────

    @work(thread=True)
    def _refresh_status(self) -> None:
        from src.agent.config import config
        import httpx, socket as _socket

        def _check_neo4j() -> bool:
            try:
                from src.knowledge.neo4j_graph import is_available
                return is_available()
            except Exception:
                return False

        def _check_vllm() -> bool:
            try:
                r = httpx.get(f"{config.vllm_base_url}/v1/models", timeout=2)
                return r.status_code == 200
            except Exception:
                return False

        def _check_bitwig() -> bool:
            try:
                s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                s.settimeout(1.0)
                s.connect((config.bitwig_host, config.bitwig_port))
                s.close()
                return True
            except Exception:
                return False

        neo4j_ok  = _check_neo4j()
        vllm_ok   = _check_vllm()
        bitwig_ok = _check_bitwig()

        def _icon(ok: bool) -> tuple[str, str]:
            return ("●", "#3fb950") if ok else ("●", "#f85149")

        line = Text()
        line.append("  Bitwig AI Agent   ", style="bold #e6edf3")
        line.append("│  ", style="#30363d")
        for label, ok in [("Neo4j", neo4j_ok), ("vLLM", vllm_ok), ("Bitwig", bitwig_ok)]:
            icon, color = _icon(ok)
            line.append(f"{icon} {label}  ", style=color)

        self.call_from_thread(
            self.query_one("#status-bar", Static).update, line
        )

    # ── Input ─────────────────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if text.startswith("/"):
            self._handle_command(text)
            return
        chat = self.query_one(ChatLog)
        chat.add_user(text)
        chat.scroll_end(animate=False)
        self._set_thinking(True)
        self._run_agent(text)

    def _handle_command(self, cmd: str) -> None:
        chat = self.query_one(ChatLog)
        if cmd in ("/help", "/h"):
            chat.add_system("─" * 48)
            chat.add_system("/clear  /status  /quit  /help")
            chat.add_system("Ctrl+L = löschen  ·  Ctrl+C = beenden")
            chat.add_system("─" * 48)
        elif cmd in ("/clear", "/c"):
            self.action_clear_chat()
        elif cmd in ("/status", "/s"):
            self._refresh_status()
            chat.add_system("Status wird aktualisiert…")
        elif cmd in ("/quit", "/q", "/exit"):
            self.exit()
        else:
            chat.add_system(f"Unbekannter Befehl: {cmd}")

    # ── Agent ─────────────────────────────────────────────────────────────────

    @work(thread=True)
    def _run_agent(self, user_text: str) -> None:
        from src.agent.core import (
            get_graph, _default_state, _state_for_user_turn, _merge_session_state,
        )
        try:
            with self._history_lock:
                if self._session_state is None:
                    self._session_state = _default_state()
                state = _state_for_user_turn(self._session_state, user_text)

            pending = []
            self._pending_tools = pending
            result = get_graph().invoke(state)

            with self._history_lock:
                self._session_state = _merge_session_state(state, result)
                msgs = self._session_state["messages"]
                from langchain_core.messages import AIMessage as _AI
                last_ai = next(
                    (m for m in reversed(msgs) if isinstance(m, _AI) and (m.content or "").strip()),
                    None,
                )
                reply = last_ai.content if last_ai else (msgs[-1].content if msgs else "Keine Antwort.")

            self.call_from_thread(self._on_agent_reply, reply, list(pending))
        except Exception as exc:
            import traceback as _tb
            tb = _tb.format_exc()
            import logging as _log
            _log.getLogger("bitwig-agent").error("_run_agent Fehler:\n%s", tb)
            label = f"{type(exc).__name__}: {exc}"
            self.call_from_thread(self._on_agent_error, label, tb)

    def _on_agent_reply(self, text: str, tools: list[dict]) -> None:
        self._set_thinking(False)
        chat = self.query_one(ChatLog)
        for tool in tools:
            chat.add_tool(tool.get("name") or "?", tool.get("args", {}))
        chat.add_agent(text)
        chat.scroll_end(animate=False)

    def _on_agent_error(self, error: str, traceback: str = "") -> None:
        self._set_thinking(False)
        chat = self.query_one(ChatLog)
        chat.add_error(error)
        if traceback:
            for line in traceback.strip().splitlines()[-6:]:
                chat.add_system(line)
        chat.scroll_end(animate=False)

    def _set_thinking(self, visible: bool) -> None:
        bar = self.query_one("#thinking-bar", Label)
        if visible:
            bar.add_class("visible")
        else:
            bar.remove_class("visible")

    def _setup_event_bus(self) -> None:
        from src.agent.events import get_event_bus
        get_event_bus().subscribe("tool_call", lambda e: self._pending_tools.append(e["payload"]))

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self.query_one(ChatLog).clear()
        with self._history_lock:
            self._session_state = None
        self.query_one(ChatLog).add_system("Chat geleert.")

    def action_show_help(self) -> None:
        self._handle_command("/help")


def main() -> None:
    BitwigCLI().run()


if __name__ == "__main__":
    main()

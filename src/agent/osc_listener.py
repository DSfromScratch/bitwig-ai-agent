"""
OSC-Listener für das Bitwig Agent UI (Port 9003).
Empfängt Prompts von Bitwig-Plugins und leitet sie an den Agenten weiter.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

log = logging.getLogger("bitwig-agent")

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


def _start_agent_ui_osc_listener(on_prompt) -> object | None:
    """Startet OSC-Listener für Bitwig-internes Agent-UI (Port 9003)."""
    try:
        from pythonosc.dispatcher import Dispatcher
        from pythonosc import osc_server, udp_client
    except Exception as exc:
        log.warning("Agent UI OSC deaktiviert (python-osc fehlt): %s", exc)
        return None

    listen_host  = os.getenv("BITWIG_AGENT_UI_HOST", "127.0.0.1")
    listen_port  = int(os.getenv("BITWIG_AGENT_UI_PORT", "9003"))
    bitwig_host  = os.getenv("BITWIG_HOST", "127.0.0.1")
    bitwig_port  = int(os.getenv("BITWIG_PORT", "8001"))
    plugin_port  = int(os.getenv("AGENT_PLUGIN_RESPONSE_PORT", "9004"))
    plugin_host  = os.getenv("AGENT_PLUGIN_HOST", bitwig_host)
    out_clients  = [
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
            _send_ui_response(reply or "Fertig.")
        except Exception as exc:
            log.error("Fehler beim Verarbeiten des UI-Prompts: %s", exc)
            _send_ui_response(f"Fehler: {exc}")

    def _on_prompt(address: str, *args) -> None:
        prompt = args[0] if args and isinstance(args[0], str) else ""
        if prompt:
            threading.Thread(target=_process_prompt, args=(prompt,), daemon=True).start()

    def _on_config(address: str, *args) -> None:
        import json
        config_str = args[0] if args and isinstance(args[0], str) else ""
        try:
            cfg = json.loads(config_str)
            if isinstance(cfg, dict):
                _set_latest_ui_config(cfg)
                log.info("UI-Config empfangen: %s", list(cfg.keys()))
        except (json.JSONDecodeError, ValueError):
            pass

    try:
        dispatcher = Dispatcher()
        dispatcher.map("/agent/ui/prompt", _on_prompt)
        dispatcher.map("/agent/ui/config", _on_config)
        server = osc_server.ThreadingOSCUDPServer((listen_host, listen_port), dispatcher)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        log.info("Agent UI OSC-Listener auf %s:%d", listen_host, listen_port)
        return server
    except (OSError, Exception) as exc:
        log.warning("Agent UI OSC-Listener konnte nicht gestartet werden: %s", exc)
        return None

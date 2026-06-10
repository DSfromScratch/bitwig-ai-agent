from __future__ import annotations

import os
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass

from pythonosc import udp_client
from pythonosc.osc_message import OscMessage

from src.agent.osc.client import configure_dgram_socket

OSC_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
OSC_LED_PORT = int(os.getenv("LAUNCHPAD_LED_PORT", "8003"))
MODE_REPLY_PORT = int(os.getenv("LAUNCHPAD_REPLY_PORT", "9005"))

VALID_MODES = {"SESSION", "DRUM", "INSTRUMENT"}
_MODE_ALIASES = {"CONTROL": "SESSION"}
_MODE_STALE_SECONDS = 5.0


@dataclass(frozen=True)
class PlayedNote:
    note: int
    velocity: int
    timestamp: float


_lock = threading.RLock()
_condition = threading.Condition(_lock)
_listener_thread: threading.Thread | None = None
_listener_error: str | None = None
_listener_ready = False
_current_mode = "UNKNOWN"
_mode_updated_at = 0.0
_played_notes: deque[PlayedNote] = deque(maxlen=512)


def normalize_mode(mode: str | None) -> str:
    normalized = (mode or "").upper().strip()
    return _MODE_ALIASES.get(normalized, normalized)


def current_mode() -> str:
    ensure_observer()
    with _lock:
        return _current_mode


def mode_is(*modes: str) -> bool:
    mode = get_mode()
    allowed = {normalize_mode(m) for m in modes}
    return mode in allowed


def get_mode(*, force_query: bool = False, timeout: float = 2.0) -> str:
    ensure_observer()
    with _lock:
        cached_mode = _current_mode
        cache_age = time.monotonic() - _mode_updated_at
        if not force_query and cached_mode in VALID_MODES and cache_age <= _MODE_STALE_SECONDS:
            return cached_mode

    return query_mode(timeout=timeout)


def set_mode(mode: str, *, timeout: float = 2.0) -> str:
    mode = normalize_mode(mode)
    if mode not in VALID_MODES:
        raise ValueError(f"Ungültiger Launchpad-Modus: {mode}")
    ensure_observer()
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
    client.send_message(f"/launchpad/mode/{mode.lower()}", 1)
    return wait_for_mode(mode, timeout=timeout)


def query_mode(*, timeout: float = 2.0) -> str:
    ensure_observer()
    before = time.monotonic()
    client = udp_client.SimpleUDPClient(OSC_HOST, OSC_LED_PORT)
    client.send_message("/launchpad/mode/get", 1)

    deadline = time.monotonic() + max(timeout, 0.05)
    with _condition:
        while time.monotonic() < deadline:
            if _current_mode in VALID_MODES and _mode_updated_at >= before:
                return _current_mode
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _condition.wait(timeout=remaining)
        return _current_mode


def wait_for_mode(mode: str, *, timeout: float = 2.0) -> str:
    expected = normalize_mode(mode)
    deadline = time.monotonic() + max(timeout, 0.05)
    with _condition:
        while time.monotonic() < deadline:
            if _current_mode == expected:
                return _current_mode
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _condition.wait(timeout=remaining)
        return _current_mode


def consume_played_notes_since(start_time: float) -> list[PlayedNote]:
    ensure_observer()
    with _lock:
        return [event for event in _played_notes if event.timestamp >= start_time]


def listen_played_notes(duration: float) -> list[PlayedNote]:
    ensure_observer()
    start_time = time.monotonic()
    deadline = start_time + duration
    with _condition:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _condition.wait(timeout=min(0.2, remaining))
    return consume_played_notes_since(start_time)


def observer_status() -> str:
    ensure_observer()
    with _lock:
        if _listener_error:
            return f"ERROR: {_listener_error}"
        if _listener_thread and _listener_thread.is_alive():
            return "RUNNING"
        return "STOPPED"


def ensure_observer() -> None:
    global _listener_thread
    with _condition:
        if _listener_thread and _listener_thread.is_alive():
            if not _listener_ready and _listener_error is None:
                _condition.wait(timeout=0.2)
            return
        _listener_thread = threading.Thread(
            target=_observer_loop,
            name="launchpad-mode-observer",
            daemon=True,
        )
        _listener_thread.start()
        if not _listener_ready and _listener_error is None:
            _condition.wait(timeout=0.2)


def _observer_loop() -> None:
    global _listener_error, _listener_ready
    sock = configure_dgram_socket(
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM),
        timeout=0.5,
        reuse_port=True,
    )
    try:
        sock.bind(("", MODE_REPLY_PORT))
    except OSError as exc:
        with _condition:
            _listener_error = str(exc)
            _listener_ready = False
            _condition.notify_all()
        try:
            sock.close()
        except OSError:
            pass
        return

    with _condition:
        _listener_error = None
        _listener_ready = True
        _condition.notify_all()

    while True:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError as exc:
            with _condition:
                _listener_error = str(exc)
                _listener_ready = False
                _condition.notify_all()
            return
        _handle_packet(data)


def _handle_packet(data: bytes) -> None:
    try:
        msg = OscMessage(data)
    except Exception:
        return

    address = msg.address
    if address in {"/launchpad/mode/changed", "/launchpad/mode/response"}:
        if msg.params:
            _set_cached_mode(str(msg.params[0]))
        return

    if address == "/launchpad/note/played":
        if not msg.params:
            return
        try:
            note = int(msg.params[0])
            velocity = int(msg.params[1]) if len(msg.params) >= 2 else 100
        except (TypeError, ValueError):
            return
        with _condition:
            _played_notes.append(PlayedNote(note, velocity, time.monotonic()))
            _condition.notify_all()


def _set_cached_mode(mode: str) -> None:
    global _current_mode, _mode_updated_at
    normalized = normalize_mode(mode)
    if normalized not in VALID_MODES:
        normalized = "UNKNOWN"
    with _condition:
        _current_mode = normalized
        _mode_updated_at = time.monotonic()
        _condition.notify_all()

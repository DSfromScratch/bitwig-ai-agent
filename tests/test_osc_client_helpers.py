"""Unit-Tests für den zentralisierten OSC-Socket-Helfer (Phase B)."""
from __future__ import annotations

import socket

import pytest

from src.agent.osc.client import configure_dgram_socket

pytestmark = pytest.mark.unit


def _fresh():
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def test_sets_reuseaddr():
    s = configure_dgram_socket(_fresh())
    try:
        assert s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0
    finally:
        s.close()


def test_sets_timeout_when_given():
    s = configure_dgram_socket(_fresh(), timeout=1.5)
    try:
        assert s.gettimeout() == 1.5
    finally:
        s.close()


def test_no_timeout_by_default():
    s = configure_dgram_socket(_fresh())
    try:
        assert s.gettimeout() is None
    finally:
        s.close()


def test_reuse_port_optional():
    s = configure_dgram_socket(_fresh(), reuse_port=True)
    try:
        if hasattr(socket, "SO_REUSEPORT"):
            assert s.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) != 0
    finally:
        s.close()


def test_returns_same_socket():
    raw = _fresh()
    try:
        assert configure_dgram_socket(raw) is raw
    finally:
        raw.close()


def test_does_not_bind():
    """Helfer bindet bewusst NICHT — getsockname()-Port bleibt 0 vor bind."""
    s = configure_dgram_socket(_fresh())
    try:
        assert s.getsockname()[1] == 0
    finally:
        s.close()

"""Tests für die zentrale Tool-Registry (src/agent/tools/registry.py)."""
from __future__ import annotations

import pytest

from src.agent.tools.registry import ToolRegistry, VALID_DOMAINS

pytestmark = pytest.mark.unit


class _FakeTool:
    """Minimaler Tool-Stub mit ``name`` wie LangChain-Tools."""

    def __init__(self, name: str) -> None:
        self.name = name


# ── ToolRegistry ─────────────────────────────────────────────────────────────

def test_register_returns_tool_and_keeps_order():
    reg = ToolRegistry()
    a, b = _FakeTool("a"), _FakeTool("b")
    assert reg.register(a, domain="music") is a
    reg.register(b, domain="bitwig")
    assert reg.all() == [a, b]
    assert len(reg) == 2


def test_by_domain_filters():
    reg = ToolRegistry()
    a, b, c = _FakeTool("a"), _FakeTool("b"), _FakeTool("c")
    reg.register(a, domain="music")
    reg.register(b, domain="music")
    reg.register(c, domain="bitwig")
    assert reg.by_domain("music") == [a, b]
    assert reg.by_domain("bitwig") == [c]
    assert reg.by_domain("knowledge") == []


def test_domain_of_and_names():
    reg = ToolRegistry()
    reg.register(_FakeTool("x"), domain="knowledge")
    assert reg.domain_of("x") == "knowledge"
    assert reg.domain_of("missing") is None
    assert reg.names() == ["x"]


def test_default_domain_is_meta():
    reg = ToolRegistry()
    reg.register(_FakeTool("x"))
    assert reg.domain_of("x") == "meta"


def test_invalid_domain_rejected():
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(_FakeTool("x"), domain="nope")
    with pytest.raises(ValueError):
        reg.by_domain("nope")


def test_duplicate_name_rejected():
    reg = ToolRegistry()
    reg.register(_FakeTool("dup"), domain="music")
    with pytest.raises(ValueError):
        reg.register(_FakeTool("dup"), domain="bitwig")


def test_unnamed_tool_rejected():
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register(object(), domain="music")


def test_register_function_uses_dunder_name():
    reg = ToolRegistry()

    def my_tool():
        return None

    reg.register(my_tool, domain="meta")
    assert reg.domain_of("my_tool") == "meta"


# ── Integration mit ALL_TOOLS ────────────────────────────────────────────────

def test_all_tools_registered_with_valid_domains():
    from src.agent.tools import ALL_TOOLS
    from src.agent.tools.registry import registry

    assert len(ALL_TOOLS) == len(registry)
    for tool in ALL_TOOLS:
        name = getattr(tool, "name", "")
        assert name, f"Tool ohne Namen: {tool!r}"
        assert registry.domain_of(name) in VALID_DOMAINS


def test_query_knowledge_in_knowledge_domain():
    from src.agent.tools.registry import registry

    assert registry.domain_of("query_knowledge") == "knowledge"


def test_launchpad_in_music_domain():
    from src.agent.tools.registry import registry

    assert registry.domain_of("launchpad") == "music"


def test_get_bitwig_state_in_bitwig_domain():
    from src.agent.tools.registry import registry

    assert registry.domain_of("get_bitwig_state") == "bitwig"

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from src.agent.states.reasoning import _extract_think, _process_reasoning

pytestmark = pytest.mark.unit


def test_extracts_closed_think_and_keeps_visible_content():
    reasoning, cleaned = _extract_think("<think>plan struktur akkord</think>OK")

    assert reasoning == "plan struktur akkord"
    assert cleaned == "OK"


def test_extracts_open_think_instead_of_dropping_it():
    reasoning, cleaned = _extract_think("<think>noten schreib clip")

    assert reasoning == "noten schreib clip"
    assert cleaned == ""


def test_think_only_response_can_drive_phase_update():
    response = AIMessage(content="<think>noten schreib clip")
    updates = _process_reasoning(response, {"generation_phase": "setup"}, msg_count=1)

    assert updates["generation_phase"] == "generating"
    assert response.content == ""

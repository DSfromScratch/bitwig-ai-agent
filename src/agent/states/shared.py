"""Geteilte Konstanten und Hilfsfunktionen für die LLM-States."""
from __future__ import annotations
import json
import logging
import os
from datetime import datetime

log = logging.getLogger("bitwig-agent")

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "logs",
)
POLICY_LOG_DIR  = os.path.join(LOG_DIR, "policy_feedback")
POLICY_LOG_FILE = os.path.join(POLICY_LOG_DIR, "policy_feedback.jsonl")


def _append_policy_feedback(entry: dict) -> None:
    try:
        os.makedirs(POLICY_LOG_DIR, exist_ok=True)
        with open(POLICY_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log.debug("Policy-Feedback konnte nicht geschrieben werden: %s", exc)

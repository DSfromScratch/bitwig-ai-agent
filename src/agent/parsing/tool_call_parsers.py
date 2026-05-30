"""Parser-Chain für LLM Tool-Call-Outputs (F7).

Ersetzt die verstreuten _recover_*-Funktionen in core.py.
Jeder Parser versucht es; bei Misserfolg gibt er None zurück.
Ein neues Modell erfordert nur einen neuen Parser, keine Änderung am Graphen.
"""
from __future__ import annotations

import json
import re
import logging
from typing import Protocol

from langchain_core.messages import AIMessage

log = logging.getLogger("bitwig-agent.parsers")


class ToolCallParser(Protocol):
    def parse(self, message: AIMessage) -> list[dict] | None: ...


class OpenAIFormatParser:
    """Standardfall: tool_calls direkt im AIMessage-Objekt."""

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if getattr(msg, "tool_calls", None):
            return [dict(tc) for tc in msg.tool_calls]
        return None


class QwenXMLParser:
    """Qwen3 gibt manchmal <tool_call>{...}</tool_call> als Fließtext."""

    _RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if not isinstance(msg.content, str):
            return None
        matches = self._RE.findall(msg.content)
        if not matches:
            return None
        result = []
        for raw in matches:
            try:
                data = json.loads(raw)
                name = data.get("name") or data.get("function", {}).get("name")
                args = data.get("arguments") or data.get("parameters") or data.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if name:
                    result.append({
                        "name": name,
                        "args": args,
                        "id": f"qwen_xml_{len(result)}",
                        "type": "tool_call",
                    })
            except (json.JSONDecodeError, KeyError):
                continue
        return result or None


class MarkdownCodeBlockParser:
    """Fallback: JSON-Tool-Call in ```json ... ``` Block."""

    _RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if not isinstance(msg.content, str):
            return None
        m = self._RE.search(msg.content)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            name = data.get("name") or data.get("function")
            args = data.get("arguments") or data.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name:
                return [{
                    "name": name,
                    "args": args,
                    "id": "md_block_0",
                    "type": "tool_call",
                }]
        except (json.JSONDecodeError, KeyError):
            pass
        return None


class TruncatedXMLParser:
    """Repariert abgeschnittenes <tool_call> ohne schließendes Tag."""

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if not isinstance(msg.content, str):
            return None
        content = msg.content
        if "<tool_call>" not in content or "</tool_call>" in content:
            return None
        inner = content.split("<tool_call>", 1)[-1].strip()

        # Stack-basierte Reparatur: fehlende } und ] in richtiger Reihenfolge schließen
        stack = []
        in_string = False
        escape_next = False
        for ch in inner:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack and stack[-1] == ch:
                    stack.pop()
        inner_fixed = inner + "".join(reversed(stack))

        try:
            data = json.loads(inner_fixed)
            name = data.get("name")
            args = data.get("arguments") or data.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name:
                log.info("TruncatedXMLParser repaired tool call: %s", name)
                return [{
                    "name": name,
                    "args": args,
                    "id": "truncated_xml_0",
                    "type": "tool_call",
                }]
        except (json.JSONDecodeError, KeyError):
            pass
        return None


class CompositeToolCallParser:
    """Probiert jeden Parser der Reihe nach; gibt das erste Nicht-None-Ergebnis zurück."""

    def __init__(self, parsers: list[ToolCallParser]) -> None:
        self._parsers = parsers

    def extract(self, msg: AIMessage) -> list[dict]:
        for parser in self._parsers:
            result = parser.parse(msg)
            if result:
                parser_name = type(parser).__name__
                if parser_name != "OpenAIFormatParser":
                    log.debug("Tool-Call via %s extrahiert", parser_name)
                return result
        return []

    def patch_message(self, msg: AIMessage) -> AIMessage:
        """Gibt eine neue AIMessage zurück mit tool_calls gefüllt, falls nötig."""
        if getattr(msg, "tool_calls", None):
            return msg
        tool_calls = self.extract(msg)
        if not tool_calls:
            return msg
        clean_content = msg.content
        if isinstance(clean_content, str):
            clean_content = re.sub(r"<tool_call>.*?</tool_call>", "", clean_content, flags=re.S).strip()
        return AIMessage(content=clean_content, tool_calls=tool_calls)


# Singleton-Instanz — ersetzt alle _recover_*-Funktionen in core.py
TOOL_CALL_PARSER = CompositeToolCallParser([
    OpenAIFormatParser(),
    QwenXMLParser(),
    TruncatedXMLParser(),
    MarkdownCodeBlockParser(),
])

"""
LLM-Backend: MockLLM, _get_llm, Token-Logging, LangChain-Patch.
"""
from __future__ import annotations

import json
import re
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs.chat_generation import ChatGeneration
from langchain_core.outputs.llm_result import LLMResult
from langchain_openai import ChatOpenAI

from src.agent.config import config

log = logging.getLogger("bitwig-agent")

_THINK_RE   = re.compile(r"<think>(.*?)</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*", re.DOTALL)


class MockLLM(BaseChatModel):
    """Mock-LLM für Tests ohne externe API-Abhängigkeiten."""

    @property
    def _llm_type(self) -> str:
        return "mock"

    def invoke(self, input, config=None, **kwargs):
        response = "OK: Mock-Antwort im Test-Modus. Agent läuft, aber LLM-Backend nicht verfügbar."
        return AIMessage(content=response)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        response = "OK: Mock-Antwort im Test-Modus. Agent läuft, aber LLM-Backend nicht verfügbar."
        return LLMResult(generations=[[ChatGeneration(message=AIMessage(content=response))]])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop, run_manager, **kwargs)

    def bind_tools(self, tools=None, **kwargs):
        return self


def _patch_langchain_tool_call_parser() -> None:
    """Normalisiert doppelt-serialisierte Tool-Args aus manchen vLLM-Antworten."""
    try:
        import langchain_openai.chat_models.base as lc_openai_base
        original_parse = lc_openai_base.parse_tool_call

        def _safe_parse(raw_tool_call: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
            parsed = original_parse(raw_tool_call, **kwargs)
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
                parsed["args"] = {}
            return parsed

        lc_openai_base.parse_tool_call = _safe_parse
    except Exception as exc:
        log.debug("LangChain Tool-Parser Patch nicht angewendet: %s", exc)


import os as _os
def _get_llm(
    max_tokens: int | None = None,
    backend: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    if _os.getenv("BITWIG_TEST_MODE", "").lower() == "mock":
        log.info("TEST_MODE: Verwende Mock-LLM")
        return MockLLM()

    max_tokens = max_tokens if max_tokens is not None else config.llm_max_tokens
    temp = temperature if temperature is not None else config.llm_temperature
    backend = (backend or config.llm_backend).lower()

    if backend == "mlx":
        base  = config.mac_mlx_url + "/v1"
        model = model or config.mlx_model
        log.info("MLX-Backend: %s / %s", base, model)
        return ChatOpenAI(
            base_url=base, api_key="mlx", model=model,
            temperature=temp, max_tokens=max_tokens,
            timeout=config.llm_timeout,
        )

    if backend == "vllm":
        base  = config.vllm_base_url + "/v1"
        model = model or config.vllm_model
        log.info("vLLM-Backend: %s / %s", base, model)
        return ChatOpenAI(
            base_url=base, api_key="vllm", model=model,
            temperature=temp,
            max_tokens=min(max_tokens, config.llm_vllm_token_cap),
            timeout=config.llm_timeout,
        )

    log.warning("Unbekanntes LLM_BACKEND '%s' — fallback auf mlx", backend)
    return _get_llm(max_tokens=max_tokens, backend="mlx", model=model, temperature=temperature)


def _log_token_usage(response: AIMessage, label: str = "") -> dict:
    from src.agent.events import get_event_bus
    meta       = getattr(response, "usage_metadata", None) or {}
    input_tok  = meta.get("input_tokens", 0)
    output_tok = meta.get("output_tokens", 0)
    total_tok  = meta.get("total_tokens", input_tok + output_tok)

    think_tok = 0
    resp_meta = getattr(response, "response_metadata", None) or {}
    usage_raw = resp_meta.get("usage", resp_meta.get("token_usage", {})) or {}
    details   = usage_raw.get("completion_tokens_details") or {}
    think_tok = (details.get("reasoning_tokens") or 0) if isinstance(details, dict) else 0

    think_estimated = False
    if think_tok == 0:
        raw_content = getattr(response, "content", "") or ""
        m = _THINK_RE.search(raw_content)
        if m:
            think_tok = len(m.group(1)) // 4
            think_estimated = True

    non_think = max(0, output_tok - think_tok)
    prefix    = f" [{label}]" if label else ""
    est_mark  = "≈" if think_estimated else ""
    line = (
        f"TOKENS{prefix}  input={input_tok} | output={output_tok}  "
        f"(thinking{est_mark}={think_tok} [{(think_tok/output_tok*100):.0f}%]  "
        f"rest={non_think} [{(non_think/output_tok*100):.0f}%])  | total={total_tok}"
        if output_tok else
        f"TOKENS{prefix}  input={input_tok} | output={output_tok} | total={total_tok}  [keine Usage-Daten]"
    )
    log.info(line)
    print(line, flush=True)

    usage = {
        "input_tokens": input_tok, "output_tokens": output_tok,
        "thinking_tokens": think_tok, "rest_tokens": non_think,
        "total_tokens": total_tok, "label": label,
    }
    try:
        get_event_bus().emit("token_usage", usage)
    except Exception as _e:
        log.debug("EventBus token_usage emit fehlgeschlagen: %s", _e)
    return usage

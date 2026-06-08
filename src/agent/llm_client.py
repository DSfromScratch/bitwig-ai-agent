"""
LLM-Backend: MockLLM, _get_llm, Token-Logging, LangChain-Patch.
"""
from __future__ import annotations

import json
import os
import re
import time
import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs.chat_generation import ChatGeneration
from langchain_core.outputs.llm_result import LLMResult
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
load_dotenv()

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


def _github_token() -> str | None:
    """GitHub-Token aus Env oder `gh auth token` (für GitHub-Models-Backend)."""
    tok = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if tok:
        return tok
    try:
        import subprocess
        out = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception as exc:
        log.debug("gh auth token nicht verfügbar: %s", exc)
    return None


# --- Copilot (Max) Backend -------------------------------------------------
# Im Gegensatz zu GitHub Models (Free-Tier: 8000-Token-Input-Cap) nutzt dieser
# Pfad die echte Copilot-API (api.individual.githubcopilot.com) und ist damit
# für die volle Song-Komposition (>8k Tokens) geeignet. Ablauf:
#   1. Langlebiges OAuth-Token (ghu_) aus Env oder Datei.
#   2. Eintausch gegen kurzlebiges Copilot-API-Token (~30 min), gecacht.
_COPILOT_OAUTH_PATH = Path.home() / ".config" / "bitwig-agent" / "copilot_oauth.txt"
_COPILOT_CLIENT_ID  = "Iv1.b507a08c87ecfe98"  # offizielle Copilot-Client-ID
_copilot_cache: dict[str, Any] = {"token": None, "base": None, "exp": 0.0}


def _copilot_oauth_token() -> str | None:
    """Langlebiges Copilot-OAuth-Token (ghu_) aus Env oder gespeicherter Datei."""
    tok = os.getenv("COPILOT_OAUTH_TOKEN")
    if tok:
        return tok.strip()
    try:
        if _COPILOT_OAUTH_PATH.exists():
            return _COPILOT_OAUTH_PATH.read_text().strip()
    except Exception as exc:
        log.debug("Copilot-OAuth-Datei nicht lesbar: %s", exc)
    return None


def _copilot_api_token() -> tuple[str, str]:
    """Kurzlebiges Copilot-API-Token + Base-URL (mit Auto-Refresh, gecacht)."""
    now = time.time()
    if _copilot_cache["token"] and now < _copilot_cache["exp"] - 300:
        return _copilot_cache["token"], _copilot_cache["base"]

    oauth = _copilot_oauth_token()
    if not oauth:
        raise RuntimeError(
            "LLM_BACKEND=copilot gesetzt, aber kein Copilot-OAuth-Token gefunden "
            f"(COPILOT_OAUTH_TOKEN oder {_COPILOT_OAUTH_PATH})."
        )
    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/copilot_internal/v2/token",
        headers={
            "Authorization": f"token {oauth}",
            "Editor-Version": "vscode/1.95.0",
            "Editor-Plugin-Version": "copilot-chat/0.20.0",
            "User-Agent": "GithubCopilot/1.0.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    token = data.get("token")
    if not token:
        raise RuntimeError("Copilot-Token-Exchange fehlgeschlagen (keine Copilot-Lizenz?).")
    base = (data.get("endpoints", {}) or {}).get("api", "https://api.githubcopilot.com")
    _copilot_cache.update(token=token, base=base, exp=float(data.get("expires_at", now + 1500)))
    log.info("Copilot-API-Token erneuert (sku=%s)", data.get("sku", "?"))
    return token, base


def _get_llm(max_tokens: int = 3000) -> BaseChatModel:
    if os.getenv("BITWIG_TEST_MODE", "").lower() == "mock":
        log.info("TEST_MODE: Verwende Mock-LLM statt vLLM-Backend")
        return MockLLM()

    # Copilot (Max) – echte Copilot-API ohne 8k-Token-Cap. Geeignet für die
    # volle Song-Komposition. Aktivierung via LLM_BACKEND=copilot.
    if os.getenv("LLM_BACKEND", "").lower() in ("copilot", "copilot-max"):
        token, base = _copilot_api_token()
        model = os.getenv("COPILOT_MODEL", "gpt-4o")
        log.info("LLM_BACKEND=copilot: Verwende Copilot-API (%s) @ %s", model, base)
        return ChatOpenAI(
            base_url=base.rstrip("/"),
            api_key=token, model=model,
            temperature=0.6, max_tokens=max_tokens, timeout=120,
            default_headers={
                "Editor-Version": "vscode/1.95.0",
                "Copilot-Integration-Id": "vscode-chat",
                "User-Agent": "GithubCopilot/1.0.0",
            },
        )

    # Optionaler Referenz-/Vergleichs-Backend: GitHub Models (Modelle hinter
    # Copilot, z.B. GPT-4o). OpenAI-kompatibel inkl. Tool-Calling. Aktivierung
    # via LLM_BACKEND=github. Hinweis: Free-Tier mit 8000-Token-Input-Cap.
    # Token aus GITHUB_TOKEN/GH_TOKEN oder `gh auth token`.
    if os.getenv("LLM_BACKEND", "").lower() in ("github", "github-models"):
        token = _github_token()
        if not token:
            raise RuntimeError(
                "LLM_BACKEND=github gesetzt, aber kein GitHub-Token gefunden "
                "(GITHUB_TOKEN/GH_TOKEN oder `gh auth login`)."
            )
        base  = os.getenv("GITHUB_MODELS_BASE_URL", "https://models.github.ai/inference")
        model = os.getenv("GITHUB_MODEL", "openai/gpt-4o")
        log.info("LLM_BACKEND=github: Verwende GitHub Models (%s)", model)
        return ChatOpenAI(
            base_url=base, api_key=token, model=model,
            temperature=0.6, max_tokens=max_tokens, timeout=120,
        )

    base  = os.getenv("VLLM_BASE_URL", "http://192.168.0.3:8100") + "/v1"
    model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
    return ChatOpenAI(
        base_url=base, api_key="vllm", model=model,
        temperature=0.6, max_tokens=max_tokens, timeout=120,
    )


def _log_token_usage(response: AIMessage, label: str = "") -> dict:
    from src.agent.events import get_event_bus
    meta       = getattr(response, "usage_metadata", None) or {}
    input_tok  = meta.get("input_tokens") or 0
    output_tok = meta.get("output_tokens") or 0
    total_tok  = meta.get("total_tokens") or (input_tok + output_tok)

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
    except Exception:
        pass
    return usage

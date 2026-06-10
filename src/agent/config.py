"""
Central configuration for the Bitwig AI Agent.

All settings are read from environment variables (compatible with .env).
Pydantic-Settings maps field names to env vars automatically:
  llm_backend  →  LLM_BACKEND
  neo4j_uri    →  NEO4J_URI
  ...
"""
from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM Backend ───────────────────────────────────────────────────────────
    llm_backend: str = "vllm"
    llm_temperature: float = 0.3
    llm_timeout: int = 120

    # Token budgets
    llm_max_tokens: int = 1500          # main agent call
    llm_intent_max_tokens: int = 50     # intent classification (no thinking needed)
    llm_fallback_max_tokens: int = 700  # context-overflow fallback
    llm_vllm_token_cap: int = 1500      # hard cap applied to vLLM calls

    # ── MLX (Mac local) ───────────────────────────────────────────────────────
    mac_mlx_url: str = "http://localhost:8080"
    mlx_model: str = "mlx-community/Qwen3-14B-4bit"

    # ── vLLM (Linux GPU) ──────────────────────────────────────────────────────
    vllm_base_url: str = "http://192.168.0.3:8100"
    vllm_model: str = "agent"

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4jllm"
    neo4j_database: str = "neo4j"

    # ── OSC / Bitwig ──────────────────────────────────────────────────────────
    bitwig_host: str = "127.0.0.1"
    bitwig_port: int = 8002
    bitwig_reply_port: int = 9002
    bitwig_socket_timeout: float = 2.0

    # ── Agent behaviour ───────────────────────────────────────────────────────
    agent_max_retries: int = 3
    agent_connect_retry_wait: int = 5   # seconds between LLM connect retries
    agent_tool_result_max_chars: int = 600


config = AgentConfig()

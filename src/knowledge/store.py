"""
Embedding-Modell für Neo4j Vektorsuche.

Priorität:
  1. Lokaler Embedding-Server (EMBEDDING_BASE_URL) — kein HF-Netzwerk nötig
  2. Direktes HuggingFace-Modell (lokal gecacht, kein Download)
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

# .env laden falls vorhanden — sonst greift os.getenv-Default
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

EMBED_MODEL      = os.getenv("KB_EMBED_MODEL", "intfloat/multilingual-e5-base")
EMBEDDING_SERVER = os.getenv("EMBEDDING_BASE_URL", "http://localhost:8080")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_PORT_FILE = PROJECT_ROOT / ".run" / "embedding_server.port"


def _candidate_servers() -> list[str]:
    candidates: list[str] = []
    try:
        value = ACTIVE_PORT_FILE.read_text(encoding="utf-8").strip()
        if value.isdigit():
            candidates.append(f"http://127.0.0.1:{value}")
    except Exception:
        pass

    if EMBEDDING_SERVER not in candidates:
        candidates.append(EMBEDDING_SERVER)
    return candidates


def _server_available() -> str | None:
    """Prüft ob ein lokaler Embedding-Server läuft und liefert dessen Base-URL.

    Verifiziert auch dass es WIRKLICH ein Embedding-Server ist (Qwen-LLM
    auf 8080 hat ebenfalls /health, würde aber nur 'Not Found' auf
    /v1/embeddings zurückgeben).
    """
    import json
    import urllib.request
    for server_url in _candidate_servers():
        try:
            urllib.request.urlopen(f"{server_url}/health", timeout=2.0)
        except Exception:
            continue
        # Sanity-Check: bietet der Server wirklich /v1/embeddings an?
        try:
            req = urllib.request.Request(
                f"{server_url}/v1/embeddings",
                data=json.dumps({"model": EMBED_MODEL, "input": "ping"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3.0) as r:
                if r.status == 200:
                    return server_url
        except Exception:
            continue
    return None


@lru_cache(maxsize=1)
def get_embeddings():
    server_url = _server_available()
    if server_url:
        # Lokaler Server → kein HuggingFace-Netzwerk-Zugriff
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(
            base_url=f"{server_url}/v1",
            api_key="local",
            model=EMBED_MODEL,
            check_embedding_ctx_length=False,
        )
    else:
        raise RuntimeError(
            f"Embedding-Server nicht erreichbar ({EMBEDDING_SERVER}). "
            "Starte den Server mit: python src/knowledge/embedding_server.py"
        )

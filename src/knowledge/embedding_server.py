"""
Lokaler Embedding-Server — OpenAI-kompatibler /v1/embeddings Endpoint.

Lädt das Modell einmalig beim Start und hält es im RAM.
Kein HuggingFace-Netzwerk-Zugriff nötig (nutzt lokalen Cache).

Starten:
    python src/knowledge/embedding_server.py
    → läuft auf http://localhost:8080

LangChain nutzt ihn über:
    EMBEDDING_BASE_URL=http://localhost:8080
"""

from __future__ import annotations
import json
import time
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

MODEL_NAME = os.getenv("KB_EMBED_MODEL", "intfloat/multilingual-e5-base")
PORT       = int(os.getenv("EMBEDDING_PORT", "8080"))
_fallback_raw = os.getenv("EMBEDDING_FALLBACK_PORT", "").strip()
EMBEDDING_FALLBACK_PORT = int(_fallback_raw) if _fallback_raw.isdigit() else None
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = PROJECT_ROOT / ".run"
ACTIVE_PORT_FILE = RUN_DIR / "embedding_server.port"


def _healthcheck_running_server(port: int) -> bool:
    """Prüft, ob auf dem Port bereits unser Embedding-Server läuft."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status == 200 and data.get("status") == "ok"
    except Exception:
        return False


@lru_cache(maxsize=1)
def _get_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ModuleNotFoundError as exc:
        print("[EmbeddingServer] Fehlende Abhaengigkeit: sentence_transformers")
        print("[EmbeddingServer] Installiere zuerst eine CPU- oder CUDA-passende sentence-transformers/torch Kombination.")
        raise SystemExit(2) from exc

    print(f"[EmbeddingServer] Lade Modell: {MODEL_NAME}")
    t = time.time()
    model = SentenceTransformer(MODEL_NAME)
    print(f"[EmbeddingServer] Modell geladen in {time.time()-t:.1f}s")
    return model


class EmbeddingHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # Kein Log-Spam

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, {"status": "ok", "model": MODEL_NAME})
        elif self.path == "/v1/models":
            self._respond(200, {"object":"list","data":[{"id":MODEL_NAME,"object":"model"}]})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/embeddings":
            self._respond(404, {"error": "not found"}); return

        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length))

        input_texts = body.get("input", [])
        if isinstance(input_texts, str):
            input_texts = [input_texts]

        model = _get_model()
        embeddings = model.encode(input_texts, normalize_embeddings=True).tolist()

        data = [
            {"object": "embedding", "index": i, "embedding": emb}
            for i, emb in enumerate(embeddings)
        ]
        self._respond(200, {
            "object": "list",
            "data":   data,
            "model":  MODEL_NAME,
            "usage":  {"prompt_tokens": sum(len(t.split()) for t in input_texts), "total_tokens": 0},
        })

    def _respond(self, code: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    active_port = PORT

    def _try_bind(port: int) -> HTTPServer | None:
        try:
            return HTTPServer(("0.0.0.0", port), EmbeddingHandler)
        except OSError as exc:
            if exc.errno == 98:
                if _healthcheck_running_server(port):
                    print(f"[EmbeddingServer] Bereits aktiv auf Port {port} — verwende laufende Instanz")
                    raise SystemExit(0)
                return None
            raise

    server = _try_bind(PORT)
    if server is None:
        if EMBEDDING_FALLBACK_PORT and EMBEDDING_FALLBACK_PORT != PORT:
            print(
                f"[EmbeddingServer] Port {PORT} ist belegt — versuche Fallback-Port {EMBEDDING_FALLBACK_PORT}"
            )
            server = _try_bind(EMBEDDING_FALLBACK_PORT)
            active_port = EMBEDDING_FALLBACK_PORT

        if server is None:
            print(f"[EmbeddingServer] Port {PORT} ist belegt (kein kompatibler /health Endpoint)")
            raise SystemExit(1)

    # Modell erst laden, nachdem der Port erfolgreich reserviert wurde.
    _get_model()
    RUN_DIR.mkdir(exist_ok=True)
    ACTIVE_PORT_FILE.write_text(str(active_port), encoding="utf-8")
    print(f"[EmbeddingServer] Lauscht auf http://0.0.0.0:{active_port}")
    print(f"[EmbeddingServer] Endpoint: http://localhost:{active_port}/v1/embeddings")
    try:
        server.serve_forever()
    finally:
        ACTIVE_PORT_FILE.unlink(missing_ok=True)

#!/usr/bin/env python3
"""
Bitwig Agent Full-Stack Launcher — Orchestriert alle Services.

Services:
  Neo4j (bolt://localhost:7687)        — Graph Database
  Embedding Server (localhost:8080)    — Text Embeddings
  MCP Server (stdio)                   — Bitwig Bridge
  vLLM Server (192.168.0.4:8000)       — Extern (separat starten)
  BitwigAgentBridge                    — In Bitwig (OSC-Brücke)
"""

import os
import sys
import argparse
import subprocess
import time
import socket
import logging
import shutil
import importlib.util
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

log = logging.getLogger("launcher")
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

PROJECT_ROOT = Path(__file__).parent
RUN_DIR = PROJECT_ROOT / ".run"
LOG_DIR = PROJECT_ROOT / "logs"
EMBEDDING_SERVER_SCRIPT = PROJECT_ROOT / "src/knowledge/embedding_server.py"
EMBEDDING_PID_FILE = RUN_DIR / "embedding_server.pid"
EMBEDDING_PORT_FILE = RUN_DIR / "embedding_server.port"
EMBEDDING_LOG_FILE = LOG_DIR / "embedding_server.log"


def resolve_python_executable() -> str:
    """Liefert einen funktionierenden Python-Interpreter für Subprozesse."""
    python3_path = shutil.which("python3")
    python_path = shutil.which("python")

    candidates = [
        PROJECT_ROOT / ".venv/bin/python",
        Path(sys.executable) if sys.executable else None,
        Path(python3_path) if python3_path else None,
        Path(python_path) if python_path else None,
    ]

    for candidate in candidates:
        if candidate and candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    return "python3"


VENV_PYTHON = resolve_python_executable()

load_dotenv(PROJECT_ROOT / ".env")

BITWIG_HOST = os.getenv("BITWIG_HOST", "127.0.0.1")
BITWIG_PORT = int(os.getenv("BITWIG_DM_PORT", "8001"))
EMBEDDING_PORT = int(os.getenv("EMBEDDING_PORT", "8080"))
_embedding_fallback_raw = os.getenv("EMBEDDING_FALLBACK_PORT", "").strip()
EMBEDDING_FALLBACK_PORT = int(_embedding_fallback_raw) if _embedding_fallback_raw.isdigit() else None

vllm_url = urlparse(os.getenv("VLLM_BASE_URL", "http://192.168.0.4:8000"))
VLLM_HOST = vllm_url.hostname or "192.168.0.4"
VLLM_PORT = vllm_url.port or 8000

SERVICES = {
    "neo4j": {"host": "localhost", "port": 7687, "name": "Neo4j Graph DB"},
    "embedding": {"host": "localhost", "port": EMBEDDING_PORT, "name": "Embedding Server"},
}

EXTERNAL_SERVICES = {
    "vllm": {"host": VLLM_HOST, "port": VLLM_PORT, "name": "vLLM Server (Qwen3)"},
}

PROCESSES: list[subprocess.Popen[str]] = []
MCP_PROCESS: subprocess.Popen | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bitwig Agent Full-Stack Launcher")
    parser.add_argument("--status-only", action="store_true", help="Zeigt nur den Service-Status und beendet sich")
    parser.add_argument("--embed-server-up", action="store_true", help="Startet den lokalen Embedding-Server als Singleton und beendet sich")
    return parser.parse_args()


def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Prüft ob Port offen ist."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def embedding_ports() -> list[int]:
    ports = [EMBEDDING_PORT]
    if EMBEDDING_FALLBACK_PORT and EMBEDDING_FALLBACK_PORT != EMBEDDING_PORT:
        ports.append(EMBEDDING_FALLBACK_PORT)
    return ports


def _read_embedding_active_port() -> int | None:
    try:
        value = EMBEDDING_PORT_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return int(value) if value.isdigit() else None


def check_embedding_service() -> tuple[bool, int | None]:
    ports_to_check: list[int] = []
    active_port = _read_embedding_active_port()
    if active_port is not None:
        ports_to_check.append(active_port)
    for port in embedding_ports():
        if port not in ports_to_check:
            ports_to_check.append(port)

    for port in ports_to_check:
        if check_port("localhost", port):
            return True, port
    return False, None


def _tail_log(path: Path, max_lines: int = 3) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    return "\n".join(lines[-max_lines:])


def check_bitwig_bridge(host: str = BITWIG_HOST, port: int = BITWIG_PORT, timeout: float = 1.5) -> bool:
    """Prüft die BitwigAgentBridge via UDP Ping/Pong statt TCP-Portprobe."""
    import threading

    try:
        from pythonosc import udp_client
    except ModuleNotFoundError:
        return False

    pong_port = port + 1
    received = threading.Event()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(timeout)
    try:
        sock.bind(("0.0.0.0", pong_port))
    except OSError:
        return True

    def _listen() -> None:
        try:
            sock.recv(64)
            received.set()
        except Exception:
            pass

    try:
        threading.Thread(target=_listen, daemon=True).start()
        udp_client.SimpleUDPClient(host, port).send_message("/ping", 1)
        return received.wait(timeout)
    except Exception:
        return False
    finally:
        sock.close()

def start_neo4j() -> bool:
    """Prüft ob Neo4j (Windows Desktop) erreichbar ist."""
    log.info("📊 Prüfe Neo4j Desktop (Windows bolt://localhost:7687)...")
    
    if check_port(SERVICES["neo4j"]["host"], SERVICES["neo4j"]["port"]):
        log.info("✅ Neo4j Desktop (Windows) erreichbar")
        return True
    
    log.warning("⚠️  Neo4j Desktop nicht erreichbar!")
    log.info("💡 Neo4j Desktop auf Windows 11 starten:")
    log.info("   1. Neo4j Desktop öffnen")
    log.info("   2. Database starten")
    log.info("   3. Port 7687 freigeben")
    log.info("")
    log.info("Oder SSH-Tunnel (von Linux):")
    log.info("   ssh -L 7687:localhost:7687 user@windows-host")
    return False


def start_embedding_server() -> bool:
    """Startet Embedding Server als lokalen Singleton-Service."""
    ports_info = ", ".join(str(p) for p in embedding_ports())
    log.info("🔤 Starte Embedding Server (Port(s) %s)...", ports_info)

    embedding_running, detected_port = check_embedding_service()
    if embedding_running:
        log.info("✅ Embedding Server läuft bereits (localhost:%d)", detected_port)
        return True

    if importlib.util.find_spec("sentence_transformers") is None:
        log.info("ℹ️  Embedding Server übersprungen: Paket 'sentence_transformers' fehlt")
        return False
    
    try:
        RUN_DIR.mkdir(exist_ok=True)
        LOG_DIR.mkdir(exist_ok=True)

        log_handle = EMBEDDING_LOG_FILE.open("a", encoding="utf-8")
        process = subprocess.Popen(
            [VENV_PYTHON, str(EMBEDDING_SERVER_SCRIPT)],
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )

        EMBEDDING_PID_FILE.write_text(str(process.pid), encoding="utf-8")

        for attempt in range(10):
            embedding_running, detected_port = check_embedding_service()
            if embedding_running:
                log.info("✅ Embedding Server bereit (localhost:%d)", detected_port)
                return True
            if process.poll() is not None:
                EMBEDDING_PID_FILE.unlink(missing_ok=True)
                tail = _tail_log(EMBEDDING_LOG_FILE)
                if tail:
                    log.warning("⚠️  Embedding Server Start fehlgeschlagen:\n%s", tail)
                else:
                    log.warning("⚠️  Embedding Server Start fehlgeschlagen (Exit %d)", process.returncode)
                return False
            time.sleep(1)

        log.warning("⚠️  Embedding Server startet langsam...")
        return True

    except Exception as e:
        log.warning("⚠️  Embedding Server konnte nicht gestartet werden: %s", e)
        return False


def start_mcp_server() -> subprocess.Popen | None:
    """Startet MCP Server als stdio-Prozess."""
    log.info("🌉 Starte MCP Server (stdio)...")
    
    try:
        process = subprocess.Popen(
            [VENV_PYTHON, "bitwig_mcp_server.py"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        for _ in range(10):
            if process.poll() is not None:
                stderr_output = ""
                if process.stderr is not None:
                    stderr_output = process.stderr.read().strip()
                log.error("❌ MCP Server beendet sofort (Exit Code: %d)", process.returncode)
                if stderr_output:
                    log.error("   %s", stderr_output.splitlines()[-1])
                return None
            time.sleep(0.1)

        log.info("✅ MCP Server bereit (stdio, kein TCP-Port)")
        return process
        
    except Exception as e:
        log.error("❌ MCP Server Fehler: %s", e)
        return None


def check_external_services() -> bool:
    """Prüft externe Services und warnt falls nicht erreichbar."""
    ok = True
    
    log.info("")
    log.info("🔗 Prüfe externe Services...")
    
    for name, info in EXTERNAL_SERVICES.items():
        if check_port(info["host"], info["port"]):
            log.info("✅ %s läuft", info["name"])
        else:
            log.warning("⚠️  %s nicht erreichbar (%s:%d)", 
                       info["name"], info["host"], info["port"])
            ok = False

    if check_bitwig_bridge():
        log.info("✅ BitwigAgentBridge läuft (UDP %s:%d)", BITWIG_HOST, BITWIG_PORT)
    else:
        log.warning("⚠️  BitwigAgentBridge nicht erreichbar (UDP %s:%d)", BITWIG_HOST, BITWIG_PORT)
        ok = False
    
    return ok


def print_status() -> int:
    """Zeigt Status aller Services."""
    log.info("")
    log.info("📋 SERVICE STATUS")
    log.info("═" * 60)
    
    running = 0
    missing = 0
    
    for name, info in SERVICES.items():
        if name == "embedding":
            embedding_running, detected_port = check_embedding_service()
            if embedding_running:
                log.info("✅ %s (localhost:%d)", info["name"], detected_port)
                running += 1
            else:
                log.info("❌ %s", info["name"])
                missing += 1
            continue

        if check_port(info["host"], info["port"]):
            log.info("✅ %s", info["name"])
            running += 1
        else:
            log.info("❌ %s", info["name"])
            missing += 1

    if MCP_PROCESS and MCP_PROCESS.poll() is None:
        log.info("✅ MCP Server (stdio process)")
        running += 1
    else:
        log.info("ℹ️  MCP Server (stdio, kein TCP-Port-Healthcheck)")

    if check_bitwig_bridge():
        log.info("✅ BitwigAgentBridge (UDP %s:%d)", BITWIG_HOST, BITWIG_PORT)
        running += 1
    else:
        log.info("❌ BitwigAgentBridge (UDP %s:%d)", BITWIG_HOST, BITWIG_PORT)
        missing += 1
    
    log.info("═" * 60)
    
    if not check_external_services():
        missing += 1
    
    if missing == 0:
        log.info("✨ Alle Services läufen!")
        return 0
    
    log.warning("⚠️  %d Service(s) nicht erreichbar", missing)
    return 1


def main() -> int:
    """Haupteinstiegspunkt — Orchestriert alle Services."""
    args = parse_args()

    if args.status_only:
        return print_status()

    if args.embed_server_up:
        return 0 if start_embedding_server() else 1

    log.info("")
    log.info("╔" + "═" * 58 + "╗")
    log.info("║" + " Bitwig Agent — Full Stack ".center(58) + "║")
    log.info("║" + " Starte alle benötigten Services ".center(58) + "║")
    log.info("╚" + "═" * 58 + "╝")
    log.info("")
    
    # Schritt 1: Neo4j prüfen/starten
    start_neo4j()
    
    # Schritt 2: Embedding Server starten
    start_embedding_server()
    
    # Schritt 3: MCP Server starten
    mcp_process = start_mcp_server()
    global MCP_PROCESS
    MCP_PROCESS = mcp_process
    if mcp_process:
        PROCESSES.append(mcp_process)
    
    # Schritt 4: Externe Services prüfen
    log.info("")
    check_external_services()
    
    # Status Report
    log.info("")
    status_code = print_status()
    
    if status_code != 0:
        log.info("")
        log.info("🚀 QUICK START GUIDE:")
        log.info("")
        log.info("  1️⃣  vLLM Server (Qwen3):")
        log.info("     ssh user@192.168.0.4")
        log.info("     python -m vllm.entrypoints.openai.api_server \\")
        log.info("       --model models/Qwen3-14B-AWQ --gpu-memory-utilization 0.9")
        log.info("")
        log.info("  2️⃣  Bitwig + Extension:")
        log.info("     Öffne Bitwig Studio")
        log.info("     Preferences → Add-ons → BitwigAgentBridge aktivieren")
        log.info("")
    
    # Halte Services am Leben
    log.info("")
    log.info("✨ Services starten — drücke Ctrl+C zum Beenden...")
    log.info("")
    
    try:
        while True:
            time.sleep(1)
            
            # Health Check: Prüfe ob Services noch laufen
            alive_processes: list[subprocess.Popen[str]] = []
            for proc in PROCESSES:
                if not proc:
                    continue

                if proc.poll() is None:
                    alive_processes.append(proc)
                    continue

                name = "MCP Server"
                stderr_tail = ""
                try:
                    if proc.stderr is not None:
                        stderr_lines = proc.stderr.read().strip().splitlines()
                        if stderr_lines:
                            stderr_tail = stderr_lines[-1]
                except Exception:
                    stderr_tail = ""

                log.error("❌ Prozess '%s' beendet (Exit Code: %d)", name, proc.returncode)
                if stderr_tail:
                    log.error("   %s", stderr_tail)
                raise Exception("Service-Fehler")

            PROCESSES[:] = alive_processes
    
    except KeyboardInterrupt:
        log.info("")
        log.info("⏹️  Shutdown...")
    
    finally:
        # Cleanup
        for proc in PROCESSES:
            if proc and proc.poll() is None:
                log.info("Beende Service...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

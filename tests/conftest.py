"""Shared pytest fixtures and markers."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Markers ───────────────────────────────────────────────────────────────────

def pytest_configure(config):
    config.addinivalue_line("markers", "unit: fast, no external dependencies")
    config.addinivalue_line("markers", "integration: requires Bitwig + OSC bridge")
    config.addinivalue_line("markers", "neo4j: requires Neo4j to be running")
    config.addinivalue_line("markers", "slow: takes more than 5 seconds")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def osc_available():
    """Returns True if BitwigAgentBridge is reachable."""
    import socket
    from pythonosc import udp_client

    client = udp_client.SimpleUDPClient("127.0.0.1", 8001, allow_broadcast=False)
    sock = client._sock
    sock.settimeout(1.5)
    try:
        sock.bind(("", int(os.environ.get("BITWIG_REPLY_PORT", "9001"))))
    except OSError:
        pass
    try:
        client.send_message("/ping", 1)
        sock.recvfrom(64)
        return True
    except (OSError, socket.timeout):
        return False
    finally:
        sock.close()


@pytest.fixture(scope="session")
def neo4j_available():
    """Returns True if Neo4j is reachable."""
    try:
        from neo4j import GraphDatabase
        os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
        os.environ.setdefault("NEO4J_USER", "neo4j")
        os.environ.setdefault("NEO4J_PASSWORD", "neo4jllm")
        driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "neo4jllm"))
        with driver.session() as s:
            s.run("RETURN 1").single()
        driver.close()
        return True
    except Exception:
        return False


# ── Mock-OSC Fixture für Integration-Tests ohne Bitwig ───────────────────────

@pytest.fixture(scope="session")
def mock_osc_mode() -> bool:
    """True wenn BITWIG_TEST_MODE=mock gesetzt ist (kein echtes Bitwig nötig)."""
    return os.environ.get("BITWIG_TEST_MODE", "").lower() == "mock"


@pytest.fixture
def osc_messages() -> list:
    """Sammelt OSC-Nachrichten die im Test gesendet werden (Mock-Liste)."""
    return []


@pytest.fixture
def mock_osc_client(osc_messages):
    """Ersetzt SimpleUDPClient durch einen Mock der Nachrichten aufzeichnet."""
    class _MockClient:
        def send_message(self, address: str, value):
            osc_messages.append((address, value))
    return _MockClient()

"""
OSC Client abstraction to reduce code duplication.
Handles socket binding, timeout configuration, and error recovery.
"""
import os
import socket
import struct
from pythonosc import udp_client

OSC_HOST            = os.getenv("BITWIG_HOST",        "127.0.0.1")
OSC_PORT            = int(os.getenv("BITWIG_PORT",    "8002"))
OSC_REPLY_PORT      = int(os.getenv("BITWIG_REPLY_PORT", "9002"))
OSC_STEP_PORT       = int(os.getenv("BITWIG_STEP_PORT",  "8002"))
OSC_STEP_REPLY_PORT = int(os.getenv("BITWIG_STEP_REPLY_PORT", "9002"))


def configure_dgram_socket(
    sock: socket.socket,
    *,
    timeout: float | None = None,
    reuse_port: bool = False,
) -> socket.socket:
    """Setzt die wiederkehrenden UDP-Socket-Optionen und gibt den Socket zurück.

    Zentralisiert den an ~8 Stellen duplizierten Boilerplate
    (``SO_REUSEADDR``, optional ``SO_REUSEPORT``, ``settimeout``). Bindet
    bewusst NICHT — das `bind()` bleibt beim Aufrufer, da die Call-Sites
    unterschiedliche Bind-Fehlerbehandlung haben (schlucken vs. Fehler melden).
    """
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if reuse_port and hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    if timeout is not None:
        sock.settimeout(timeout)
    return sock


class OscClient:
    """Wrapper around pythonosc SimpleUDPClient with socket binding and error handling."""

    def __init__(self, host: str = OSC_HOST, port: int = OSC_PORT, timeout: float | None = None, bind_port: int | None = None):
        """
        Args:
            host: OSC server host
            port: OSC server port
            timeout: Socket timeout in seconds (None = blocking)
            bind_port: Local port to bind for receiving replies (None = no binding)
        """
        self.client = udp_client.SimpleUDPClient(host, port, allow_broadcast=False)
        self.sock = self.client._sock
        configure_dgram_socket(self.sock, timeout=timeout, reuse_port=True)
        if bind_port is not None:
            try:
                self.sock.bind(("", bind_port))
            except OSError:
                pass

    def send_and_wait(self, address: str, value: int | float, timeout: float = 2.0) -> bytes | None:
        """Send OSC message and wait for reply.

        Args:
            address: OSC address pattern
            value: Value to send
            timeout: Receive timeout in seconds

        Returns:
            Raw OSC reply bytes, or None if timeout/error
        """
        try:
            self.send_message(address, value)
            self.sock.settimeout(timeout)
            data, _ = self.sock.recvfrom(4096)
            return data
        except socket.timeout:
            return None
        except OSError:
            return None

    def send_message(self, address: str, value: int | float) -> None:
        """Send OSC message."""
        self.client.send_message(address, value)

    def parse_int_reply(self, data: bytes) -> int | None:
        """Parse integer from OSC reply data.

        Args:
            data: Raw OSC reply bytes

        Returns:
            Parsed integer, or None if parse error
        """
        try:
            raw = data.decode("latin-1")
            tag_idx = raw.find(",i")
            if tag_idx < 0:
                return None
            padded = (tag_idx + 4) & ~3
            if padded + 4 > len(data):
                return None
            value = struct.unpack(">i", data[padded : padded + 4])[0]
            return value if 0 <= value <= 64 else None
        except (UnicodeDecodeError, struct.error, IndexError):
            return None

    def parse_string_reply(self, data: bytes, start_offset: int = 0) -> str | None:
        """Parse null-terminated string from OSC reply.

        Args:
            data: Raw OSC reply bytes
            start_offset: Where to start looking for null terminator

        Returns:
            Parsed string, or None if error
        """
        try:
            null_pos = data.find(b"\x00", start_offset)
            if null_pos <= start_offset:
                return None
            return data[start_offset:null_pos].decode("utf-8", errors="ignore")
        except Exception:
            return None

    def close(self) -> None:
        """Close socket."""
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

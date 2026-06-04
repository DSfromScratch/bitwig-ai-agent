"""
Screenshot-Server für macOS — läuft in der Aqua-Session (NICHT via SSH starten).
Starte mit: python3 screenshot_server.py

Stellt bereit:
  GET  http://localhost:9010/screenshot          → aktuellen Screen als PNG
  GET  http://localhost:9010/screenshot?window=1 → aktives Fenster
  GET  http://localhost:9010/health              → {"status":"ok"}

Von Linux aus:
  curl http://192.168.0.4:9010/screenshot -o /tmp/screen.png
"""
import http.server
import subprocess
import tempfile
import os
import json
from pathlib import Path

PORT = 9010


class ScreenshotHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path.startswith("/screenshot"):
            self._take_screenshot()
        elif self.path == "/health":
            self._health()
        else:
            self.send_error(404)

    def _take_screenshot(self):
        window_mode = "window" in self.path
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name

        try:
            args = ["screencapture", "-x"]
            if window_mode:
                args.append("-l")  # active window
            args.append(tmp)

            result = subprocess.run(args, capture_output=True, timeout=5)
            if result.returncode != 0 or not Path(tmp).exists():
                self.send_error(500, "screencapture failed")
                return

            data = Path(tmp).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _health(self):
        body = json.dumps({"status": "ok", "port": PORT}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[screenshot-server] {fmt % args}")


if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), ScreenshotHandler)
    print(f"[screenshot-server] Läuft auf Port {PORT}")
    print(f"[screenshot-server] Von Linux: curl http://$(hostname -I | awk '{{print $1}}'):{PORT}/screenshot -o screen.png")
    server.serve_forever()

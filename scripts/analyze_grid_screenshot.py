"""
Holt einen Screenshot vom Mac-Screenshot-Server, analysiert den
Bitwig Grid-Patch mit Claude Vision und speichert das Ergebnis in Neo4j.

Voraussetzung:
  Mac: python3 agent-plugin/screenshot_server.py   (in Terminal auf dem Mac starten)

Ausführen:
  python scripts/analyze_grid_screenshot.py --track 10
  python scripts/analyze_grid_screenshot.py --track 14 --device "Phase-4"
  python scripts/analyze_grid_screenshot.py --file /tmp/grid.png  # manuelle Screenshot-Datei
  python scripts/analyze_grid_screenshot.py --dry-run             # ohne Neo4j-Speicherung
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MAC_HOST       = os.getenv("BITWIG_HOST", "192.168.0.4")
SCREENSHOT_PORT = int(os.getenv("SCREENSHOT_PORT", "9010"))
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY", "")


# ── Screenshot holen ──────────────────────────────────────────────────────────

def fetch_screenshot_http(host: str = MAC_HOST, port: int = SCREENSHOT_PORT,
                          timeout: float = 8.0) -> bytes | None:
    """Holt Screenshot vom Mac HTTP-Screenshot-Server (Port 9010)."""
    url = f"http://{host}:{port}/screenshot"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"[http] Screenshot-Server nicht erreichbar ({url}): {e}")
        return None


def fetch_screenshot_vnc(host: str = MAC_HOST, password: str = "",
                         timeout: float = 10.0) -> bytes | None:
    """Holt Screenshot via VNC (benötigt Screen Sharing auf dem Mac, Port 5900)."""
    try:
        from vncdotool import api
        import tempfile
        import os

        print(f"[vnc] Verbinde mit {host}:5900 …")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        try:
            with api.connect(host, password=password or None, timeout=timeout) as client:
                client.captureScreen(tmp)
            data = Path(tmp).read_bytes()
            print(f"[vnc] Screenshot: {len(data)//1024} KB")
            return data
        finally:
            try: os.unlink(tmp)
            except Exception: pass
    except ImportError:
        print("[vnc] vncdotool nicht installiert: uv pip install vncdotool")
        return None
    except Exception as e:
        print(f"[vnc] Fehler: {e}")
        print("      Mac: System Settings → General → Sharing → Screen Sharing aktivieren")
        return None


def fetch_screenshot(host: str = MAC_HOST, port: int = SCREENSHOT_PORT,
                     vnc_password: str = "", timeout: float = 8.0) -> bytes | None:
    """Versucht HTTP-Server zuerst, dann VNC als Fallback."""
    # 1. HTTP-Screenshot-Server
    if check_server(host, port):
        data = fetch_screenshot_http(host, port, timeout)
        if data:
            return data

    # 2. VNC-Fallback
    print("[fallback] Versuche VNC …")
    data = fetch_screenshot_vnc(host, password=vnc_password, timeout=timeout)
    if data:
        return data

    print("\n❌  Kein Screenshot-Weg verfügbar. Optionen:")
    print("   A) Mac Terminal: python3 agent-plugin/screenshot_server.py")
    print("   B) Mac: System Settings → General → Sharing → Screen Sharing aktivieren")
    print("   C) Manuell: Screenshot auf Mac (Cmd+Shift+3), dann:")
    print("      scp sija@192.168.0.4:~/Desktop/Screenshot*.png /tmp/screen.png")
    print("      python scripts/analyze_grid_screenshot.py --file /tmp/screen.png")
    return None


def check_server(host: str = MAC_HOST, port: int = SCREENSHOT_PORT) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2.0) as r:
            return r.status == 200
    except Exception:
        return False


# ── Claude Vision Analyse ─────────────────────────────────────────────────────

ANALYSIS_PROMPT = """Du analysierst einen Screenshot des Bitwig Studio Grid-Editors (Poly Grid oder FX Grid).

Bitte extrahiere strukturiert:

## 1. Erkannte Module
Liste alle sichtbaren Module auf (Name, Kategorie).

## 2. Signal-Flow
Beschreibe den Signalfluss von links nach rechts:
- Audio-Pfad (Quelle → Verarbeitung → Ausgang)
- Modulations-Pfade (LFOs/Envelopes → Targets)
- Kreuzverbindungen

## 3. Patch-Architektur
Welches Synthese-Prinzip wird verwendet?
(z.B. Subtractive, FM, Wavetable, Additive, Physical Modeling, Granular)

## 4. Sound-Design-Zweck
Was für einen Klang erzeugt dieser Patch?
(z.B. "Sub-Bass mit Pitch-Envelope für Kick", "Wavetable-Lead mit Filter-Modulation")

## 5. Besonderheiten
Kreative oder ungewöhnliche Verbindungen die auffallen.

Antworte auf Deutsch. Falls kein Grid-Editor sichtbar ist, beschreibe was du siehst."""


def analyze_with_claude(image_bytes: bytes, track_name: str = "",
                        device_name: str = "") -> str | None:
    """Analysiert Grid-Screenshot mit Claude Vision API."""
    if not ANTHROPIC_KEY:
        print("❌  ANTHROPIC_API_KEY nicht gesetzt")
        return None

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    b64 = base64.standard_b64encode(image_bytes).decode()
    context = ""
    if track_name:
        context += f"\nTrack: {track_name}"
    if device_name:
        context += f"\nDevice: {device_name}"

    print("[vision] Sende Screenshot an Claude Vision …")
    try:
        msg = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=1500,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": ANALYSIS_PROMPT + context,
                    },
                ],
            }],
        )
        return msg.content[0].text
    except Exception as e:
        print(f"❌  Claude API Fehler: {e}")
        return None


# ── Neo4j Storage ─────────────────────────────────────────────────────────────

def store_analysis(track_idx: int, track_name: str, device_name: str,
                   analysis: str, project: str) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    content = (
        f"**Grid-Analyse: {track_name}** [{device_name}] — {project}\n"
        f"{analysis}"
    )
    emb = get_embeddings().embed_documents([content])[0]

    with neo4j_session() as s:
        s.run("""
            MERGE (n:GridAnalysis {track_index: $ti, project: $project})
            SET n.track_name  = $track_name,
                n.device_name = $device_name,
                n.analysis    = $analysis,
                n.content     = $content,
                n.source      = $source,
                n.embedding   = $emb
        """, ti=track_idx, project=project,
             track_name=track_name, device_name=device_name,
             analysis=analysis, content=content,
             source=f"GridAnalysis:{project}/Track{track_idx}",
             emb=emb)

        # HNSW-Index anlegen
        try:
            s.run("""
                CREATE VECTOR INDEX gridanalysis_embedding IF NOT EXISTS
                FOR (n:GridAnalysis) ON n.embedding
                OPTIONS {indexConfig: {`vector.dimensions`: 768,
                                       `vector.similarity_function`: 'cosine'}}
            """)
        except Exception:
            pass

        # Mit SoundRecipe verknüpfen
        s.run("""
            MATCH (sr:SoundRecipe {track_index: $ti, project: $project})
            MATCH (ga:GridAnalysis {track_index: $ti, project: $project})
            MERGE (ga)-[:ANALYZES]->(sr)
        """, ti=track_idx, project=project)

    print(f"✅  GridAnalysis gespeichert: Track {track_idx} ({track_name})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Grid-Screenshot → Claude Vision → Neo4j")
    parser.add_argument("--track",   type=int, default=0,  help="Track-Index in Bitwig")
    parser.add_argument("--device",  default="",           help="Device-Name (optional)")
    parser.add_argument("--project", default="Chee - Hey Now")
    parser.add_argument("--file",    default="",           help="Lokale Screenshot-Datei statt Live-Fetch")
    parser.add_argument("--dry-run", action="store_true",  help="Nur analysieren, nicht speichern")
    parser.add_argument("--host",    default=MAC_HOST)
    parser.add_argument("--port",    type=int, default=SCREENSHOT_PORT)
    args = parser.parse_args()

    # Screenshot holen
    if args.file:
        image_bytes = Path(args.file).read_bytes()
        print(f"[load] Screenshot aus Datei: {args.file} ({len(image_bytes)//1024} KB)")
    else:
        if not check_server(args.host, args.port):
            print(f"❌  Screenshot-Server nicht erreichbar auf {args.host}:{args.port}")
            print(f"\n>>> Starte auf dem Mac in einem Terminal:")
            print(f"    python3 agent-plugin/screenshot_server.py")
            sys.exit(1)

        print(f"[fetch] Screenshot von {args.host}:{args.port} …")
        image_bytes = fetch_screenshot(args.host, args.port)
        if not image_bytes:
            sys.exit(1)
        print(f"[fetch] {len(image_bytes)//1024} KB empfangen")

    # Track-Info
    track_idx  = args.track
    track_name = f"Track {track_idx}" if track_idx else "Unbekannt"
    device     = args.device

    # Falls Bitwig läuft: Track-Name nachladen
    if track_idx:
        try:
            from src.agent.osc.track_state import _get_track_names
            names = _get_track_names()
            if names and track_idx <= len(names):
                track_name = names[track_idx - 1]
                print(f"[info] Track {track_idx}: {track_name}")
        except Exception:
            pass

    # Analyse
    analysis = analyze_with_claude(image_bytes, track_name, device)
    if not analysis:
        sys.exit(1)

    print(f"\n{'═'*60}")
    print(analysis)
    print(f"{'═'*60}\n")

    if args.dry_run:
        return

    store_analysis(track_idx, track_name, device, analysis, args.project)

    # GridAnalysis auch in query_bitwig_docs einbinden
    print("\n[info] GridAnalysis-Node ist via query_bitwig_docs durchsuchbar")


if __name__ == "__main__":
    main()

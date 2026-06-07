#!/usr/bin/env python
"""
Batch-Lerner: füttert dem Agenten eine Liste von Songs (artist | title | url)
und persistiert sie als (:Song)-[:BY]->(:Artist) in Neo4j.

Eingabe: eine Textdatei mit Zeilen `<artist>|<title>|<youtube_url>`
Beispiel:
    Kevin MacLeod|Brittle Rille|https://www.youtube.com/watch?v=54cDIo-5550
    ...

Aufruf:
    python scripts/learn_songs_batch.py path/to/list.txt
    python scripts/learn_songs_batch.py path/to/list.txt --midi   (auch MIDI-Transkription)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from src.agent.tools.song_learn_tool import _do_learn  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("list_file", type=Path, help="Datei mit `artist|title|url` Zeilen")
    p.add_argument("--midi", action="store_true",
                   help="Auch MIDI via basic-pitch transkribieren (langsam)")
    args = p.parse_args()

    if not args.list_file.exists():
        print(f"❌ Datei nicht gefunden: {args.list_file}")
        return 1

    songs = []
    for line in args.list_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            print(f"⚠️  Übersprungen (Format): {line}")
            continue
        songs.append(parts)

    print(f"🎵 {len(songs)} Songs in Warteschlange (MIDI={args.midi})")
    ok = fail = 0
    t0 = time.time()
    for i, (artist, title, url) in enumerate(songs, 1):
        print(f"\n[{i}/{len(songs)}] {artist} — {title}")
        try:
            r = _do_learn(artist, title, url, args.midi)
            if "error" in r:
                print(f"  ❌ {r['error']}")
                fail += 1
            else:
                f = r["features"]
                print(f"  ✓ BPM={f['bpm']} Key={f['key']} ({r['total_seconds']}s)")
                ok += 1
        except Exception as exc:
            print(f"  ❌ {exc}")
            fail += 1

    print(f"\n────────── Fertig: {ok} OK / {fail} fehlgeschlagen / "
          f"gesamt {round(time.time() - t0, 1)}s")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

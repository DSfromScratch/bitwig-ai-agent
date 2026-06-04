"""
Holt YouTube-Transkripte und speichert sie als Document-Nodes in Neo4j.

Die Chunks landen automatisch in query_bitwig_docs (Vektorsuche über alle Document-Nodes).

Ausführen:
    python scripts/ingest_youtube_transcripts.py --channel "@bitwig"
    python scripts/ingest_youtube_transcripts.py --video "https://youtu.be/XYZ"
    python scripts/ingest_youtube_transcripts.py --playlist "PLAYLIST_URL"
    python scripts/ingest_youtube_transcripts.py --dry-run   # nur auflisten, nicht schreiben
    python scripts/ingest_youtube_transcripts.py --reset     # alle YouTube-Nodes löschen
    python scripts/ingest_youtube_transcripts.py --limit 10  # nur N Videos
    python scripts/ingest_youtube_transcripts.py --lang de   # bevorzugte Sprache (Standard: en,de)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from textwrap import shorten

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Bitwig-spezifische Begriffe die Auto-Transkripte oft falsch schreiben
_CORRECTIONS: dict[str, str] = {
    "poly grid": "Poly Grid",
    "phase 4": "Phase-4",
    "phase-4": "Phase-4",
    "fm 4": "FM-4",
    "fm4": "FM-4",
    "bitwig studio": "Bitwig Studio",
    "bitwiq": "Bitwig",
    "bit wig": "Bitwig",
    "low pass": "Low-pass",
    "high pass": "High-pass",
    "side chain": "Sidechain",
    "e q": "EQ",
    "eq 5": "EQ-5",
    "lfos": "LFOs",
    "lfo": "LFO",
    "midi": "MIDI",
    "vst": "VST",
    "daw": "DAW",
    "adsr": "ADSR",
    "bpm": "BPM",
}

_CHUNK_WORDS = 350   # Zielgröße pro Chunk
_OVERLAP_WORDS = 40  # Überlapp zwischen Chunks


def _apply_corrections(text: str) -> str:
    for wrong, right in _CORRECTIONS.items():
        text = re.sub(r"\b" + re.escape(wrong) + r"\b", right, text, flags=re.IGNORECASE)
    return text


def _fetch_video_list(source: str, limit: int | None) -> list[dict]:
    """Gibt [{id, title, url}] zurück — ohne Transkript-Download."""
    import yt_dlp  # type: ignore

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit or 9999,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source, download=False)

    entries = info.get("entries") or [info]
    result = []
    for e in entries:
        vid_id = e.get("id") or e.get("url", "").split("v=")[-1]
        title = e.get("title", vid_id)
        result.append({
            "id": vid_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
        })
    return result


def _fetch_transcript(video_id: str, lang_pref: str) -> str | None:
    """Lädt das Auto-Untertitel-Transkript via yt-dlp, gibt Rohtext zurück."""
    import yt_dlp  # type: ignore

    with tempfile.TemporaryDirectory() as tmpdir:
        # Bevorzugte Sprachen: erst explizit gesetzt, dann Fallback auf Englisch
        langs = [l.strip() for l in lang_pref.split(",")]
        if "en" not in langs:
            langs.append("en")

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "outtmpl": f"{tmpdir}/%(id)s",
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
            except Exception:
                return None

        # Suche nach heruntergeladener VTT-Datei (bevorzugte Sprache zuerst)
        vtt_files: list[Path] = []
        for lang in langs:
            vtt_files.extend(Path(tmpdir).glob(f"*.{lang}.vtt"))
            vtt_files.extend(Path(tmpdir).glob(f"*{lang}*.vtt"))
        if not vtt_files:
            vtt_files = list(Path(tmpdir).glob("*.vtt"))

        if not vtt_files:
            return None

        return _parse_vtt(vtt_files[0])


def _parse_vtt(path: Path) -> str:
    """Parst eine VTT-Datei und gibt sauberen Fließtext zurück."""
    import html
    text = path.read_text(encoding="utf-8", errors="replace")

    lines = text.splitlines()
    clean: list[str] = []
    seen: set[str] = set()

    for line in lines:
        line = line.strip()
        if re.match(r"^\d{2}:\d{2}.*-->", line):
            continue
        if line.startswith(("WEBVTT", "NOTE", "STYLE", "REGION", "Kind:", "Language:")):
            continue
        # HTML-Tags und Zeitstempel-Tags entfernen
        line = re.sub(r"<[^>]+>", "", line)
        # HTML-Entities dekodieren (&nbsp; → Leerzeichen, &amp; → & etc.)
        line = html.unescape(line).replace("\xa0", " ").strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        clean.append(line)

    return " ".join(clean)


def _chunk_text(text: str, title: str, video_url: str, chunk_words: int, overlap: int) -> list[dict]:
    """Teilt Text in überlappende Chunks auf."""
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    idx = 0
    while start < len(words):
        end = min(start + chunk_words, len(words))
        chunk_words_list = words[start:end]
        chunk_text = " ".join(chunk_words_list)
        chunk_text = _apply_corrections(chunk_text)

        source = f"YouTube:{title}#{idx}"
        content = f"**Bitwig Tutorial: {title}**\n{chunk_text}"
        chunks.append({
            "source": source,
            "content": content,
            "meta": {
                "video_url": video_url,
                "title": title,
                "chunk_index": idx,
                "word_count": len(chunk_words_list),
            },
        })
        idx += 1
        if end >= len(words):
            break
        start = end - overlap

    return chunks


def collect_transcript_chunks(
    source: str,
    lang_pref: str,
    limit: int | None,
    verbose: bool = True,
) -> list[dict]:
    """Haupt-Funktion: holt Video-Liste + Transkripte, gibt Chunks zurück."""
    if verbose:
        print(f"[fetch] Lade Video-Liste von: {source}")

    videos = _fetch_video_list(source, limit)
    if verbose:
        print(f"[fetch] {len(videos)} Videos gefunden")

    all_chunks: list[dict] = []
    for i, video in enumerate(videos, 1):
        vid_title = shorten(video["title"], width=60, placeholder="…")
        if verbose:
            print(f"  [{i:>3}/{len(videos)}] {vid_title} … ", end="", flush=True)

        transcript = _fetch_transcript(video["id"], lang_pref)
        if not transcript:
            if verbose:
                print("kein Transkript")
            continue

        word_count = len(transcript.split())
        chunks = _chunk_text(
            transcript,
            title=video["title"],
            video_url=video["url"],
            chunk_words=_CHUNK_WORDS,
            overlap=_OVERLAP_WORDS,
        )
        all_chunks.extend(chunks)
        if verbose:
            print(f"{word_count} Wörter → {len(chunks)} Chunks")

    return all_chunks


def embed_and_store(chunks: list[dict], batch_size: int, dry_run: bool) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    if dry_run:
        print(f"\n[dry-run] {len(chunks)} Chunks würden gespeichert:")
        for c in chunks[:8]:
            print(f"  {c['source']}: {c['content'][:80]}…")
        if len(chunks) > 8:
            print(f"  … und {len(chunks)-8} weitere")
        return

    print(f"\n[embed] Lade Embedding-Modell …")
    emb_model = get_embeddings()
    test_vec = emb_model.embed_query("test")
    print(f"[embed] Bereit — Dimension: {len(test_vec)}")

    total = len(chunks)
    written = 0
    t0 = time.time()

    for i in range(0, total, batch_size):
        batch = chunks[i : i + batch_size]
        texts = [c["content"] for c in batch]
        vectors = emb_model.embed_documents(texts)

        with neo4j_session() as s:
            for chunk, vec in zip(batch, vectors):
                s.run("""
                    MERGE (d:Document {source: $source})
                    SET d.content     = $content,
                        d.embedding   = $embedding,
                        d.video_url   = $video_url,
                        d.chunk_index = $chunk_index,
                        d.doc_type    = 'youtube_transcript'
                """,
                source=chunk["source"],
                content=chunk["content"],
                embedding=vec,
                video_url=chunk["meta"]["video_url"],
                chunk_index=chunk["meta"]["chunk_index"],
                )
        written += len(batch)
        elapsed = time.time() - t0
        rate = written / elapsed if elapsed > 0 else 0
        eta = (total - written) / rate if rate > 0 else 0
        print(f"  [{written:>4}/{total}] {batch[-1]['source'][:55]:55}  "
              f"{rate:.1f}/s  ETA {eta:.0f}s")

    print(f"\n[done] {written} YouTube-Chunks in Neo4j gespeichert ({time.time()-t0:.0f}s)")
    print("Automatisch durchsuchbar via query_bitwig_docs (Vektorsuche über alle Document-Nodes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube Transcript Ingest für Bitwig KB")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--channel",  help="YouTube-Kanal (z.B. '@bitwig')")
    group.add_argument("--video",    help="Einzelne Video-URL oder ID")
    group.add_argument("--playlist", help="Playlist-URL")

    parser.add_argument("--lang",    default="en,de", help="Bevorzugte Sprachen (Standard: en,de)")
    parser.add_argument("--limit",   type=int, default=None, help="Max. Anzahl Videos")
    parser.add_argument("--batch",   type=int, default=16, help="Embedding-Batch-Größe")
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht speichern")
    parser.add_argument("--reset",   action="store_true", help="Alle YouTube-Nodes vorher löschen")
    args = parser.parse_args()

    source = args.channel or args.video or args.playlist
    if args.channel and not source.startswith("http"):
        source = f"https://www.youtube.com/{source.lstrip('@') if not source.startswith('@') else source}/videos"

    if args.reset and not args.dry_run:
        from src.knowledge.neo4j_graph import session as neo4j_session
        with neo4j_session() as s:
            result = s.run("""
                MATCH (d:Document) WHERE d.doc_type = 'youtube_transcript'
                DELETE d RETURN count(d) AS c
            """).single()
            print(f"[reset] {result['c']} YouTube-Nodes gelöscht")

    chunks = collect_transcript_chunks(
        source=source,
        lang_pref=args.lang,
        limit=args.limit,
        verbose=True,
    )

    if not chunks:
        print("[warn] Keine Chunks gesammelt — Transkripte verfügbar?")
        print("Tipp: Manche Videos haben keine Auto-Untertitel.")
        return

    print(f"\n[summary] {len(chunks)} Chunks aus {len({c['meta']['title'] for c in chunks})} Videos")
    embed_and_store(chunks, args.batch, args.dry_run)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Baut die Bitwig-Wissensdatenbank auf (oder rebuildet sie).

Verwendung:
    python scripts/build_kb.py              # data/docs/ einlesen
    python scripts/build_kb.py --reset      # Datenbank vorher leeren
    python scripts/build_kb.py /pfad/zur/doku  # extra Verzeichnis hinzufügen
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge.ingest import load_all_docs, count_sources, DOCS_DIR
from src.knowledge.store import get_store, get_embeddings, CHROMA_PATH, COLLECTION


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitwig-Wissensdatenbank aufbauen")
    parser.add_argument(
        "extra_dirs",
        nargs="*",
        type=Path,
        help="Zusätzliche Verzeichnisse mit Dokumenten",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Bestehende Datenbank vorher leeren",
    )
    args = parser.parse_args()

    print("Bitwig Wissensdatenbank Builder")
    print("=" * 40)

    # Dokumente laden
    print(f"\nLade Dokumente aus: {DOCS_DIR}")
    if args.extra_dirs:
        for d in args.extra_dirs:
            print(f"  + {d}")

    docs = load_all_docs(extra_dirs=args.extra_dirs or None)

    if not docs:
        print("\nKeine Dokumente gefunden!")
        print(f"Lege PDF-, Markdown- oder Textdateien in: {DOCS_DIR}")
        sys.exit(1)

    sources = count_sources(docs)
    print(f"\nGefundene Quellen ({len(sources)}):")
    for src, count in sorted(sources.items()):
        print(f"  {src:<40} {count:>4} Chunks")
    print(f"\nGesamt: {len(docs)} Chunks")

    # Embeddings laden (Download beim ersten Mal)
    print(f"\nLade Embedding-Modell (erster Start lädt ~280 MB) ...")
    embeddings = get_embeddings()

    # Store aufbauen
    store = get_store(embeddings)

    if args.reset:
        print("Lösche bestehende Datenbank ...")
        store.delete_collection()
        store = get_store(embeddings)

    print("Erstelle Embeddings und speichere in ChromaDB ...")
    store.add_documents(docs)

    final_count = store._collection.count()
    print(f"\n✓ Fertig! {final_count} Einträge in {CHROMA_PATH}")
    print("  Der Agent kann jetzt 'query_bitwig_docs' nutzen.")


if __name__ == "__main__":
    main()

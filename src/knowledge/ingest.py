"""Dokument-Lade- und Chunk-Pipeline für die Bitwig-Wissensdatenbank."""

from __future__ import annotations

from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

DOCS_DIR = Path(__file__).parent.parent.parent / "data" / "docs"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 120


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " "],
    )


def _load_pdf(path: Path) -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader

    loader = PyPDFLoader(str(path))
    docs = loader.load()
    for doc in docs:
        doc.metadata.update({"source": path.name, "type": "pdf"})
    return docs


def _load_text(path: Path) -> list[Document]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [Document(page_content=text, metadata={"source": path.name, "type": path.suffix[1:]})]


def load_file(path: Path) -> list[Document]:
    """Lädt eine einzelne Datei und gibt gesplittete Chunks zurück."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw = _load_pdf(path)
    elif suffix in (".md", ".markdown", ".txt"):
        raw = _load_text(path)
    else:
        return []
    return _splitter().split_documents(raw)


def load_all_docs(extra_dirs: list[Path] | None = None) -> list[Document]:
    """Lädt alle Dokumente aus data/docs/ und optionalen zusätzlichen Verzeichnissen."""
    search_dirs = [DOCS_DIR]
    if extra_dirs:
        search_dirs.extend(extra_dirs)

    all_docs: list[Document] = []
    for directory in search_dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() in (".pdf", ".md", ".markdown", ".txt"):
                chunks = load_file(path)
                all_docs.extend(chunks)

    return all_docs


def count_sources(docs: list[Document]) -> dict[str, int]:
    """Zählt Chunks pro Quelldatei."""
    counts: dict[str, int] = {}
    for doc in docs:
        src = doc.metadata.get("source", "?")
        counts[src] = counts.get(src, 0) + 1
    return counts

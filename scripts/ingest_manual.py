"""
Bitwig Manual Ingestion Pipeline
=================================
Lädt das Bitwig Studio PDF-Handbuch herunter, zerlegt es in Abschnitte
und extrahiert mit einem lokalen LLM strukturiertes Wissen (Concepts,
Devices, Parameter, Workflows) mit vollem Anwendungskontext.

Ergebnis wird in Neo4j geschrieben — bestehende Nodes werden angereichert,
neue angelegt.

Usage:
    source .venv/bin/activate
    python scripts/ingest_manual.py [--dry-run] [--start-page N] [--end-page N]
"""

from __future__ import annotations
import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests
from pypdf import PdfReader
from neo4j import GraphDatabase
from openai import OpenAI

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.agent.config import config  # noqa: E402 — path manipulation required for script context

# ── Config ────────────────────────────────────────────────────────────────────

PDF_URL = "https://www.bitwig.com/media/bitwig_userguide/pdf/Bitwig_Studio_User_Guide_English_oPSjcZw.pdf"
PDF_CACHE = Path(__file__).parent.parent / ".cache" / "bitwig_manual.pdf"

VLLM_BASE_URL = config.vllm_base_url
VLLM_MODEL    = config.vllm_model

CHUNK_PAGES = 4          # Seiten pro LLM-Aufruf
LLM_TIMEOUT = 120        # Sekunden
LLM_MAX_TOKENS = 6144


# ── Extraction prompt ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a music production expert extracting structured knowledge from the Bitwig Studio manual.

For each section of text, extract ALL actionable knowledge and return ONLY valid JSON (no markdown, no explanation).

JSON schema:
{
  "concepts": [
    {
      "name": "string — Bitwig concept name (e.g. 'Clip Launcher', 'Arranger', 'The Grid')",
      "description": "string — what it is and how it works",
      "use_case": "string — when and why to use it",
      "category": "string — one of: navigation, mixing, arrangement, performance, modulation, device, browser, automation"
    }
  ],
  "devices": [
    {
      "name": "string — exact Bitwig device name",
      "type": "string — instrument or fx",
      "description": "string — what the device sounds like and what it's good for",
      "use_case": "string — typical use cases (e.g. 'warm pads, plucky leads')",
      "tips": ["string — practical production tips"]
    }
  ],
  "parameters": [
    {
      "device": "string — device this parameter belongs to",
      "name": "string — exact parameter name as shown in Bitwig",
      "description": "string — what this parameter does musically",
      "range": "string — value range (e.g. '0.0–1.0' or 'Hz' or 'dB')",
      "low_means": "string — what a low value sounds/does like",
      "high_means": "string — what a high value sounds/does like",
      "tip": "string — practical tip for this parameter"
    }
  ],
  "workflows": [
    {
      "name": "string — short descriptive name for this workflow",
      "description": "string — what this workflow achieves",
      "use_case": "string — when to use this",
      "steps": ["string — numbered step-by-step instructions"],
      "tips": ["string — practical tips"]
    }
  ]
}

Rules:
- Prefer concrete, actionable descriptions over abstract ones.
- If a section has no relevant knowledge, return {"concepts":[],"devices":[],"parameters":[],"workflows":[]}.
- Always return valid JSON only — no prose, no markdown fences.
- Device names must match exactly as shown in Bitwig UI.
- For parameters: extract explicitly named parameters AND infer parameter names from descriptions.
  Examples of inference:
    "has a Decay control" → parameter name "Decay"
    "two feedback controls" → parameters "Feedback 1" and "Feedback 2"
    "adjustable frequency range" → parameter "Frequency"
    "Tune knob" → parameter "Tune"
    "Mix control for blending dry and wet" → parameter "Mix"
    "sidechain input" → parameter "Sidechain"
  Use short, clear names (1–3 words) matching typical Bitwig UI style.
- For each parameter, describe its musical effect and what low/high values mean in practice.
"""

USER_TEMPLATE = """Extract all knowledge from this Bitwig Studio manual section.
For devices, extract ALL parameters — both explicitly named AND inferred from descriptions of controls/knobs/sliders.

--- SECTION START ---
{text}
--- SECTION END ---

Return JSON only."""


# ── PDF handling ──────────────────────────────────────────────────────────────

def download_pdf() -> Path:
    if PDF_CACHE.exists():
        print(f"[pdf] Using cached manual: {PDF_CACHE}")
        return PDF_CACHE

    PDF_CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"[pdf] Downloading Bitwig manual from {PDF_URL} ...")
    resp = requests.get(PDF_URL, stream=True, timeout=60)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    written = 0
    with open(PDF_CACHE, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            written += len(chunk)
            if total:
                pct = written / total * 100
                print(f"\r  {pct:.0f}% ({written//1024}KB)", end="", flush=True)
    print(f"\n[pdf] Saved to {PDF_CACHE}")
    return PDF_CACHE


def extract_pages(pdf_path: Path, start: int = 0, end: int | None = None) -> list[tuple[int, str]]:
    """Returns list of (page_number, text) tuples."""
    reader = PdfReader(str(pdf_path))
    pages = []
    end = end or len(reader.pages)
    for i, page in enumerate(reader.pages[start:end], start=start + 1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append((i, text))
    print(f"[pdf] Extracted {len(pages)} pages with content")
    return pages


def chunk_pages(pages: list[tuple[int, str]], size: int = CHUNK_PAGES) -> list[tuple[str, int, int]]:
    """Groups pages into chunks. Returns (combined_text, first_page, last_page)."""
    chunks = []
    for i in range(0, len(pages), size):
        group = pages[i:i + size]
        text = "\n\n".join(f"[Page {n}]\n{t}" for n, t in group)
        chunks.append((text, group[0][0], group[-1][0]))
    return chunks


# ── LLM extraction ────────────────────────────────────────────────────────────

def extract_knowledge(client: OpenAI, text: str) -> dict:
    """Calls LLM to extract structured knowledge from a text chunk."""
    try:
        resp = client.chat.completions.create(
            model=VLLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "/no_think\n" + USER_TEMPLATE.format(text=text[:6000])},
            ],
            max_tokens=LLM_MAX_TOKENS,
            temperature=0.1,
            timeout=LLM_TIMEOUT,
        )
        raw = resp.choices[0].message.content.strip()

        # <think>-Blöcke entfernen (Qwen3 denkt auch mit /no_think manchmal)
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"<think>.*", "", raw, flags=re.DOTALL).strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        # "Extra data": nimm nur den ersten vollständigen JSON-Block
        brace_depth = 0
        end_idx = 0
        for i, ch in enumerate(raw):
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    end_idx = i + 1
                    break
        if end_idx:
            raw = raw[:end_idx]

        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [warn] JSON parse error: {e}")
        return {"concepts": [], "devices": [], "parameters": [], "workflows": []}
    except Exception as e:
        print(f"  [warn] LLM error: {e}")
        return {"concepts": [], "devices": [], "parameters": [], "workflows": []}


# ── Neo4j writing ─────────────────────────────────────────────────────────────

def write_to_neo4j(driver, data: dict, source_pages: str, dry_run: bool = False) -> dict:
    counts = {"concepts": 0, "devices": 0, "parameters": 0, "workflows": 0}

    if dry_run:
        for k, v in data.items():
            if v:
                counts[k] = len(v)
        return counts

    with driver.session() as s:
        for concept in data.get("concepts", []):
            if not concept.get("name"):
                continue
            s.run("""
                MERGE (c:Concept {name: $name})
                SET c.description  = coalesce(c.description, $description),
                    c.use_case     = coalesce(c.use_case, $use_case),
                    c.category     = coalesce(c.category, $category),
                    c.source       = $source
            """, name=concept["name"],
                 description=concept.get("description", ""),
                 use_case=concept.get("use_case", ""),
                 category=concept.get("category", ""),
                 source=source_pages)
            counts["concepts"] += 1

        for device in data.get("devices", []):
            if not device.get("name"):
                continue
            s.run("""
                MERGE (d:Device {name: $name})
                SET d.description = coalesce(d.description, $description),
                    d.use_case    = coalesce(d.use_case, $use_case),
                    d.device_type = coalesce(d.device_type, $dtype),
                    d.tips        = coalesce(d.tips, $tips),
                    d.source      = $source
            """, name=device["name"],
                 description=device.get("description", ""),
                 use_case=device.get("use_case", ""),
                 dtype=device.get("type", ""),
                 tips=json.dumps(device.get("tips", [])),
                 source=source_pages)
            counts["devices"] += 1

        for param in data.get("parameters", []):
            if not param.get("name") or not param.get("device"):
                continue
            s.run("""
                MATCH (d:Device {name: $device})
                MERGE (p:Parameter {name: $name, device: $device})
                SET p.description = coalesce(p.description, $description),
                    p.range       = coalesce(p.range, $range),
                    p.low_means   = coalesce(p.low_means, $low_means),
                    p.high_means  = coalesce(p.high_means, $high_means),
                    p.tip         = coalesce(p.tip, $tip),
                    p.source      = $source
                MERGE (d)-[:HAS_PARAMETER]->(p)
            """, device=param["device"],
                 name=param["name"],
                 description=param.get("description", ""),
                 range=param.get("range", ""),
                 low_means=param.get("low_means", ""),
                 high_means=param.get("high_means", ""),
                 tip=param.get("tip", ""),
                 source=source_pages)
            counts["parameters"] += 1

        for wf in data.get("workflows", []):
            if not wf.get("name"):
                continue
            s.run("""
                MERGE (w:Workflow {name: $name})
                SET w.description = coalesce(w.description, $description),
                    w.use_case    = coalesce(w.use_case, $use_case),
                    w.steps       = coalesce(w.steps, $steps),
                    w.tips        = coalesce(w.tips, $tips),
                    w.source      = $source
            """, name=wf["name"],
                 description=wf.get("description", ""),
                 use_case=wf.get("use_case", ""),
                 steps=json.dumps(wf.get("steps", [])),
                 tips=json.dumps(wf.get("tips", [])),
                 source=source_pages)
            counts["workflows"] += 1

    return counts


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest Bitwig manual into Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to Neo4j, just print")
    parser.add_argument("--start-page", type=int, default=0, help="Start from this page (0-indexed)")
    parser.add_argument("--end-page", type=int, default=None, help="Stop at this page")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_PAGES, help="Pages per LLM call")
    args = parser.parse_args()

    # Init clients
    llm = OpenAI(base_url=VLLM_BASE_URL + "/v1", api_key="dummy")
    driver = None if args.dry_run else GraphDatabase.driver(
        config.neo4j_uri, auth=(config.neo4j_user, config.neo4j_password)
    )

    # Download + parse PDF
    pdf_path = download_pdf()
    pages = extract_pages(pdf_path, args.start_page, args.end_page)
    chunks = chunk_pages(pages, args.chunk_size)

    print(f"\n[ingest] {len(chunks)} chunks to process")
    if args.dry_run:
        print("[ingest] DRY RUN — no Neo4j writes\n")

    total = {"concepts": 0, "devices": 0, "parameters": 0, "workflows": 0}

    for i, (text, first_page, last_page) in enumerate(chunks, 1):
        label = f"p{first_page}-{last_page}"
        print(f"[{i}/{len(chunks)}] Pages {first_page}–{last_page} ...", end=" ", flush=True)

        t0 = time.time()
        data = extract_knowledge(llm, text)
        elapsed = time.time() - t0

        counts = write_to_neo4j(driver, data, label, args.dry_run)
        total = {k: total[k] + counts[k] for k in total}

        parts = [f"{v} {k}" for k, v in counts.items() if v > 0]
        summary = ", ".join(parts) if parts else "nothing extracted"
        print(f"{summary}  ({elapsed:.1f}s)")

        if args.dry_run and any(v > 0 for v in counts.values()):
            for key, items in data.items():
                for item in items[:2]:
                    print(f"    [{key}] {item.get('name', '?')}: {str(item.get('description', ''))[:80]}")

    if driver:
        driver.close()

    print(f"\n[done] Total: concepts={total['concepts']}, devices={total['devices']}, "
          f"parameters={total['parameters']}, workflows={total['workflows']}")


if __name__ == "__main__":
    main()

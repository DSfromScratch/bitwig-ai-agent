"""
Zeigt Bitwig Grid-Patches als Mermaid-Workflow-Diagramme und VNC-Screenshots an.

Ausführen:
    python scripts/show_grid_workflow.py --project "Chee - Hey Now"
    python scripts/show_grid_workflow.py --track 14           # nur ein Track
    python scripts/show_grid_workflow.py --no-screenshot      # nur Diagramme
    python scripts/show_grid_workflow.py --save /tmp/grids/   # PNGs speichern
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Mermaid-Generator ─────────────────────────────────────────────────────────

# Seiten-Namen → Modul-Rollen (für Mermaid-Knoten-Farben)
_PAGE_ROLE = {
    # Quellen
    "oscillator": "osc", "osc": "osc", "sine": "osc", "saw": "osc",
    "sawtooth": "osc", "wavetable": "osc", "swarm": "osc", "noise": "osc",
    "phasor": "osc", "sampler": "osc",
    "tune - r": "osc", "tune - b": "osc", "tune - y": "osc", "tune - m": "osc",
    "sm - r": "osc", "sm - b": "osc", "sm - y": "osc", "sm - m": "osc",
    # Filter
    "filter": "filter", "filter fm": "filter", "main": "filter",
    # Modulation
    "adsr": "env", "envelope": "env", "env": "env", "ad": "env", "ar": "env",
    "segments": "env",
    "lfo": "lfo", "vibrato": "lfo", "curves": "lfo",
    "xy": "mod", "modulation": "mod",
    # Mix/Routing
    "mix": "mix", "output": "mix", "routing": "mix",
    # FX
    "fx": "fx", "delay": "fx", "reverb": "fx", "chorus": "fx",
}

_ROLE_STYLE = {
    "osc":    "fill:#1a3a5c,color:#7ecbff,stroke:#7ecbff",
    "filter": "fill:#2d1a4a,color:#c17eff,stroke:#c17eff",
    "env":    "fill:#1a3d1a,color:#7eff9e,stroke:#7eff9e",
    "lfo":    "fill:#3d2d00,color:#ffcf7e,stroke:#ffcf7e",
    "mod":    "fill:#3d1a1a,color:#ff9e7e,stroke:#ff9e7e",
    "mix":    "fill:#1a1a1a,color:#aaaaaa,stroke:#888888",
    "fx":     "fill:#1a2d3d,color:#7ecfff,stroke:#7ecfff",
}


def _page_role(page_name: str) -> str:
    key = page_name.lower().strip()
    for k, v in _PAGE_ROLE.items():
        if k in key:
            return v
    return "mix"


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")


def _build_mermaid(track_name: str, device: str, pages: list[dict]) -> str:
    """Generiert Mermaid-Flowchart aus Parameter-Seiten."""
    if not pages:
        return f"graph LR\n    A[{device}\\nKeine Seiten-Daten]"

    lines = ["graph LR"]
    styles: list[str] = []
    node_ids: list[str] = []

    # Knoten anlegen
    for page in pages:
        pname = page.get("name", "?")
        role  = _page_role(pname)
        nid   = _safe_id(pname)
        # Wichtigste Parameter als Label
        key_params = [
            p["name"] for p in page.get("params", [])
            if p.get("name") and p["name"].lower() not in ("", "—", "-")
        ][:3]
        label = pname
        if key_params:
            label += "\\n" + " · ".join(key_params)
        lines.append(f'    {nid}["{label}"]')
        if role in _ROLE_STYLE:
            styles.append(f"    style {nid} {_ROLE_STYLE[role]}")
        node_ids.append((nid, role, pname))

    # Signal-Fluss ableiten — heuristisch
    lines.append("")
    lines.append("    %% Signal-Fluss")

    # I/O-Knoten
    lines.append('    PitchIn(["🎹 Pitch In"]):::io')
    lines.append('    GateIn(["⚡ Gate In"]):::io')
    lines.append('    AudioOut(["🔊 Audio Out"]):::io')
    styles.append("    classDef io fill:#0d0d0d,color:#666,stroke:#444")

    # Pitch → Oszillatoren
    osc_nodes = [nid for nid, role, _ in node_ids if role == "osc"]
    for nid in osc_nodes:
        lines.append(f"    PitchIn --> {nid}")

    # Gate → Hüllkurven
    env_nodes = [nid for nid, role, _ in node_ids if role == "env"]
    for nid in env_nodes:
        lines.append(f"    GateIn --> {nid}")

    # Oszillatoren → Filter (wenn vorhanden, sonst direkt → Audio Out)
    filter_nodes = [nid for nid, role, _ in node_ids if role == "filter"]
    mix_nodes    = [nid for nid, role, _ in node_ids if role == "mix"]

    target = filter_nodes[0] if filter_nodes else (mix_nodes[0] if mix_nodes else "AudioOut")
    for nid in osc_nodes:
        lines.append(f"    {nid} --> {target}")

    # Hüllkurven modulieren Filter
    for env_nid in env_nodes:
        if filter_nodes:
            lines.append(f"    {env_nid} -.->|mod| {filter_nodes[0]}")

    # LFO → erste Quelle / Filter
    lfo_nodes = [nid for nid, role, _ in node_ids if role == "lfo"]
    for lfo_nid in lfo_nodes:
        mod_target = osc_nodes[0] if osc_nodes else (filter_nodes[0] if filter_nodes else "AudioOut")
        lines.append(f"    {lfo_nid} -.->|mod| {mod_target}")

    # Filter → Mix → Audio Out
    if filter_nodes and mix_nodes:
        lines.append(f"    {filter_nodes[0]} --> {mix_nodes[0]}")
        lines.append(f"    {mix_nodes[0]} --> AudioOut")
    elif filter_nodes:
        lines.append(f"    {filter_nodes[0]} --> AudioOut")
    elif mix_nodes:
        lines.append(f"    {mix_nodes[0]} --> AudioOut")
    elif osc_nodes:
        lines.append(f"    {osc_nodes[0]} --> AudioOut")

    # FX → Audio Out
    fx_nodes = [nid for nid, role, _ in node_ids if role == "fx"]
    for fx_nid in fx_nodes:
        lines.append(f"    AudioOut --> {fx_nid}")

    lines.append("")
    lines.extend(styles)

    return "\n".join(lines)


# ── VNC-Screenshot ────────────────────────────────────────────────────────────

def _activate_bitwig_mac() -> None:
    """Bringt Bitwig Studio auf dem Mac in den Vordergrund."""
    import subprocess
    try:
        subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "sija@192.168.0.4",
             "osascript -e 'tell application \"Bitwig Studio\" to activate'"],
            timeout=3, capture_output=True,
        )
        time.sleep(0.8)  # Fenster rendern lassen
    except Exception:
        pass


def _autocrop_modules(img_path: Path) -> Path:
    """Findet Grid-Module (helle Bereiche) und schneidet darauf zu."""
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(img_path).convert("RGB")
        arr = np.array(img)

        # Pixel die heller als Schwelle sind (Module haben helle Elemente)
        brightness = arr.mean(axis=2)
        mask = brightness > 25   # alles was nicht fast-schwarz ist

        rows = np.any(mask, axis=1)
        cols = np.any(mask, axis=0)

        if not rows.any() or not cols.any():
            return img_path

        rmin, rmax = np.where(rows)[0][[0, -1]]
        cmin, cmax = np.where(cols)[0][[0, -1]]

        # Padding
        pad = 80
        rmin = max(0, rmin - pad)
        rmax = min(img.height, rmax + pad)
        cmin = max(0, cmin - pad)
        cmax = min(img.width, cmax + pad)

        cropped = img.crop((cmin, rmin, cmax, rmax))
        crop_path = img_path.parent / (img_path.stem + "_modules.png")
        cropped.save(crop_path)
        return crop_path
    except Exception:
        return img_path


def _take_screenshot(track_idx: int, save_dir: Path | None = None) -> Path | None:
    try:
        from scripts.analyze_grid_screenshot import fetch_screenshot
        from src.agent.osc.project_scan import open_track_device

        opened = open_track_device(track_idx, timeout=3.0)
        if not opened:
            return None
        time.sleep(0.8)

        # Bitwig in Vordergrund bringen
        _activate_bitwig_mac()
        time.sleep(1.2)

        img = fetch_screenshot(timeout=12.0)
        if not img:
            return None

        out_dir = save_dir or Path("/tmp/bitwig_grids")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"grid_track_{track_idx:02d}.png"
        out_path.write_bytes(img)

        # Auto-Crop auf Modul-Bereich
        cropped = _autocrop_modules(out_path)
        return cropped
    except Exception as e:
        print(f"    Screenshot-Fehler: {e}")
        return None


# ── Haupt-Funktion ────────────────────────────────────────────────────────────

def show_grid_workflows(
    project: str,
    track_filter: int | None = None,
    do_screenshot: bool = True,
    save_dir: Path | None = None,
) -> list[dict]:
    """Scannt Grid-Tracks und gibt Mermaid-Diagramme + Screenshot-Pfade zurück."""
    from src.agent.osc.project_scan import scan_project, query_track_params_all

    _GRID_DEVICES = {"poly grid", "fx grid", "note grid"}

    print(f"[scan] Scanne {project} …")
    project_data = scan_project(timeout=5.0)
    all_tracks = project_data.get("tracks", [])
    if not all_tracks and not project_data.get("_raw"):
        print("❌ Bitwig nicht erreichbar")
        return []

    results = []
    for track in all_tracks:
        idx   = track.get("idx", 0)
        name  = track.get("name", f"Track {idx}")
        devs  = track.get("devices", [])

        if track_filter and idx != track_filter:
            continue

        if not any(d.lower() in _GRID_DEVICES for d in devs):
            continue

        device = next((d for d in devs if d.lower() in _GRID_DEVICES), devs[0] if devs else "")
        print(f"\n  Track {idx:>2}: {name} [{device}]")

        # Parameter-Seiten laden
        params = query_track_params_all(idx, timeout=10.0)
        pages  = params.get("pages", [])
        print(f"         {len(pages)} Seiten: {', '.join(p['name'] for p in pages)}")

        # Mermaid generieren
        mermaid = _build_mermaid(name, device, pages)

        # Screenshot
        screenshot = None
        if do_screenshot:
            print(f"         Screenshot …", end="", flush=True)
            screenshot = _take_screenshot(idx, save_dir)
            print(f" {'OK → ' + str(screenshot) if screenshot else 'fehlgeschlagen'}")

        results.append({
            "track_index":  idx,
            "track_name":   name,
            "device":       device,
            "pages":        pages,
            "mermaid":      mermaid,
            "screenshot":   screenshot,
        })

        time.sleep(0.3)

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project",       default="Chee - Hey Now")
    parser.add_argument("--track",         type=int, default=None)
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--save",          default="/tmp/bitwig_grids")
    args = parser.parse_args()

    results = show_grid_workflows(
        project=args.project,
        track_filter=args.track,
        do_screenshot=not args.no_screenshot,
        save_dir=Path(args.save),
    )

    if not results:
        print("\nKeine Grid-Tracks gefunden.")
        return

    print(f"\n{'═'*70}")
    print(f"  {len(results)} Grid-Patches — Workflow-Diagramme")
    print(f"{'═'*70}\n")

    for r in results:
        print(f"## Track {r['track_index']}: {r['track_name']} [{r['device']}]")
        print()
        print("```mermaid")
        print(r["mermaid"])
        print("```")
        if r["screenshot"]:
            print(f"\n📸 Screenshot: {r['screenshot']}")
        print()


if __name__ == "__main__":
    main()

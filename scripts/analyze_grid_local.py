"""
Lokale Grid-Screenshot-Analyse ohne externen API-Key.

Pipeline:
  1. VNC-Screenshot holen (oder Datei laden)
  2. Surya OCR  → Modul-Namen + Parameter-Werte aus dem Bild lesen
  3. OpenCV     → Modul-Rechtecke + Kabel-Linien erkennen
  4. NetworkX   → Patch-Topologie als Graph modellieren
  5. Neo4j      → GridAnalysis-Node aktualisieren

Ausführen:
  python scripts/analyze_grid_local.py --project "Chee - Hey Now"
  python scripts/analyze_grid_local.py --track 13
  python scripts/analyze_grid_local.py --file /tmp/grid.png --track 13
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import networkx as nx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── Bitwig Kabel-Farben (HSV) ─────────────────────────────────────────────────
# In Bitwig: gelb = Audio, grün = CV, blau = Note, cyan = Gate, rot = custom
_CABLE_COLORS = {
    "Audio":    ((20,  80, 150), (38, 255, 255)),   # gelb/orange
    "CV":       ((38,  60, 150), (80, 255, 255)),   # grün
    "Note":     ((90,  80, 120), (130, 255, 255)),  # blau
    "Gate":     ((80,  50, 100), (100, 255, 255)),  # cyan
    "Custom":   ((0,  100,  80), (15, 255, 255)),   # rot
}

# ── Preprocessing ─────────────────────────────────────────────────────────────

def preprocess_for_ocr(img_bgr: np.ndarray) -> np.ndarray:
    """Optimiert das Bild für OCR auf dunklem Hintergrund."""
    # Zu Grau, dann invertieren + Kontrast erhöhen
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # CLAHE für lokale Kontrastverstärkung
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    # Threshold: hellen Text auf dunklem Hintergrund
    _, thresh = cv2.threshold(enhanced, 60, 255, cv2.THRESH_BINARY)
    return thresh


# ── Modul-Erkennung via OpenCV ────────────────────────────────────────────────

def detect_modules(img_bgr: np.ndarray) -> list[dict]:
    """Findet Modul-Rechtecke im Grid via Kontur-Erkennung."""
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

    # Kanten finden
    edges = cv2.Canny(gray, 20, 80)
    # Rechtecke schließen
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    modules = []
    h, w = img_bgr.shape[:2]
    min_area = (w * h) * 0.001   # mind. 0.1% der Bildfläche
    max_area = (w * h) * 0.3     # max 30%

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if not (min_area < area < max_area):
            continue
        x, y, mw, mh = cv2.boundingRect(cnt)
        aspect = mw / mh if mh > 0 else 0
        # Module sind breiter als hoch (aspect > 0.5) und nicht zu schmal
        if 0.3 < aspect < 5 and mw > 40 and mh > 30:
            modules.append({"x": x, "y": y, "w": mw, "h": mh, "area": area})

    # Duplikate entfernen (überlappende Rechtecke)
    modules.sort(key=lambda m: -m["area"])
    filtered = []
    for m in modules:
        overlap = False
        for f in filtered:
            ix = max(m["x"], f["x"])
            iy = max(m["y"], f["y"])
            ex = min(m["x"]+m["w"], f["x"]+f["w"])
            ey = min(m["y"]+m["h"], f["y"]+f["h"])
            if ex > ix and ey > iy:
                inter = (ex-ix) * (ey-iy)
                if inter / m["area"] > 0.5:
                    overlap = True
                    break
        if not overlap:
            filtered.append(m)

    return filtered


# ── Kabel-Erkennung via Farb-Segmentierung ────────────────────────────────────

def detect_cables(img_bgr: np.ndarray) -> list[dict]:
    """Erkennt Bitwig-Kabel via Connected-Component-Analyse der Farbpixel.

    Bitwig-Kabel sind gebogene Kurven — HoughLinesP erkennt nur Geraden.
    Stattdessen: Farbmaske → verbundene Komponenten → Endpunkte bestimmen.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    cables = []

    for sig_type, (lower, upper) in _CABLE_COLORS.items():
        mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
        if cv2.countNonZero(mask) < 20:
            continue

        # Kleine Lücken schließen
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        # Verbundene Komponenten finden
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            closed, connectivity=8
        )

        for lbl in range(1, num_labels):
            area = stats[lbl, cv2.CC_STAT_AREA]
            if area < 40:   # zu klein = Rauschen
                continue

            # Pixel dieser Komponente
            ys, xs = np.where(labels == lbl)
            if len(xs) < 2:
                continue

            # Endpunkte: linkester und rechtester Punkt der Kurve
            # (bei horizontalen Verbindungen in Bitwig Grid)
            left_idx  = np.argmin(xs)
            right_idx = np.argmax(xs)

            length = float(np.sqrt((xs[right_idx]-xs[left_idx])**2 +
                                   (ys[right_idx]-ys[left_idx])**2))

            if length < 30:  # zu kurz = kein Kabel
                continue

            cables.append({
                "type":   sig_type,
                "x1":     int(xs[left_idx]),
                "y1":     int(ys[left_idx]),
                "x2":     int(xs[right_idx]),
                "y2":     int(ys[right_idx]),
                "length": length,
                "area":   int(area),
            })

    return cables


# ── Surya OCR ─────────────────────────────────────────────────────────────────

_easyocr_reader = None

def _load_ocr():
    global _easyocr_reader
    if _easyocr_reader is None:
        print("  [ocr] Lade EasyOCR …", end="", flush=True)
        import easyocr
        _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        print(" bereit")
    return _easyocr_reader


def ocr_grid(img_pil) -> list[dict]:
    """Liest alle Texte aus dem Grid-Screenshot mit EasyOCR.
    Optimiert für weißen/hellen Text auf dunklem Hintergrund (Bitwig Grid).
    """
    reader = _load_ocr()
    img_arr = np.array(img_pil.convert("RGB"))

    # Kontrast via LAB-Farbraum verbessern (erhält Farben — wichtig für orange Text)
    img_arr_bgr = cv2.cvtColor(img_arr, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(img_arr_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    l = clahe.apply(l)
    enhanced_lab = cv2.merge([l, a, b])
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    img_enhanced = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2RGB)

    # Hochskalieren für bessere OCR (2x)
    h, w = img_enhanced.shape[:2]
    img_big = cv2.resize(img_enhanced, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    _scale = 2.0

    results = reader.readtext(img_big, detail=1, paragraph=False, min_size=10)
    texts = []
    for (bbox_pts, text, conf) in results:
        txt = text.strip()
        if not txt or len(txt) < 2 or conf < 0.2:
            continue
        # Koordinaten zurück auf Originalauflösung skalieren
        xs = [p[0] / _scale for p in bbox_pts]
        ys = [p[1] / _scale for p in bbox_pts]
        texts.append({
            "text": txt,
            "x": int(min(xs)), "y": int(min(ys)),
            "w": int(max(xs)-min(xs)), "h": int(max(ys)-min(ys)),
            "conf": float(conf),
        })
    return texts


# ── Topologie-Graph ───────────────────────────────────────────────────────────

def split_modules_by_ocr(modules: list[dict], texts: list[dict],
                          img_w: int) -> list[dict]:
    """Teilt erkannte Module anhand von OCR-Modul-Namen in Unter-Module auf.

    Bitwig-Modul-Titel sind typisch kurz (2-12 Zeichen) und stehen oben
    im Modul. Findet Titel-Texte und erstellt einen Sub-Modul-Bereich
    für jeden erkannten Namen.
    """
    # Bekannte Bitwig-Modul-Namen
    _KNOWN_MODULES = {
        "swarm", "adsr", "ad", "ar", "lfo", "sine", "sawtooth", "pulse",
        "noise", "filter", "svf", "comb", "wavetable", "phasor", "mixer",
        "blend", "vibrato", "phase-4", "reverb", "delay", "chorus",
        "polysynth", "sampler", "distortion", "saturator", "unison settings",
    }

    title_texts = [
        t for t in texts
        if t["text"].strip().lower() in _KNOWN_MODULES
        and t["conf"] > 0.5
    ]

    if len(title_texts) <= 1:
        return modules  # Kein Split nötig

    # Sortiere nach X-Position
    title_texts.sort(key=lambda t: t["x"])

    # Für jedes Modul aus dem Kontext (Spaltenbreite ~ Abstand zwischen Titeln)
    split = []
    for i, title in enumerate(title_texts):
        x_start = title["x"] - 20
        x_end   = (title_texts[i+1]["x"] - 20) if i+1 < len(title_texts) else img_w

        # Finde passendes Basis-Modul
        best = None
        for m in modules:
            if m["x"] <= title["x"] <= m["x"] + m["w"]:
                best = m
                break

        if best:
            split.append({
                "x": x_start, "y": best["y"],
                "w": x_end - x_start, "h": best["h"],
                "area": (x_end - x_start) * best["h"],
                "_label": title["text"],
            })
        else:
            split.append({
                "x": x_start, "y": 0,
                "w": x_end - x_start, "h": 200,
                "area": 200 * (x_end - x_start),
                "_label": title["text"],
            })

    return split if split else modules


def build_topology(modules: list[dict], cables: list[dict],
                   texts: list[dict]) -> nx.DiGraph:
    """Baut NetworkX-Graph aus erkannten Modulen und Kabeln."""
    # Module anhand OCR-Titel aufteilen
    h_img = max((m["y"] + m["h"] for m in modules), default=500)
    w_img = max((m["x"] + m["w"] for m in modules), default=1000)
    modules = split_modules_by_ocr(modules, texts, w_img)

    G = nx.DiGraph()

    # Module als Knoten
    for i, m in enumerate(modules):
        cx, cy = m["x"] + m["w"]//2, m["y"] + m["h"]//2
        # Texte die in diesem Modul liegen
        mod_texts = [
            t["text"] for t in texts
            if m["x"] < t["x"] < m["x"]+m["w"]
            and m["y"] < t["y"] < m["y"]+m["h"]
        ]
        label = mod_texts[0] if mod_texts else f"Module_{i}"
        G.add_node(i, label=label, cx=cx, cy=cy,
                   bbox=(m["x"], m["y"], m["w"], m["h"]),
                   texts=mod_texts)

    # Kabel als Kanten — Endpunkte dem nächsten Modul zuordnen
    def nearest_module(x, y):
        """Findet nächstes Modul — prüft Bounding-Box-Nähe statt nur Zentrum."""
        best, best_dist = -1, float("inf")
        for i, data in G.nodes(data=True):
            bx, by, bw, bh = data["bbox"]
            # Abstand zum Rand der Bounding-Box
            dx = max(0, bx - x, x - (bx + bw))
            dy = max(0, by - y, y - (by + bh))
            d = dx**2 + dy**2
            if d < best_dist:
                best, best_dist = i, d
        # Schwellwert: 300px (Kabel-Endpunkt muss in der Nähe eines Moduls sein)
        return best if best_dist < (300**2) else -1

    for cable in cables:
        src = nearest_module(cable["x1"], cable["y1"])
        dst = nearest_module(cable["x2"], cable["y2"])
        if src != -1 and dst != -1 and src != dst:
            G.add_edge(src, dst,
                       signal=cable["type"],
                       length=cable["length"])

    return G


def graph_to_description(G: nx.DiGraph, track_name: str) -> str:
    """Wandelt den Topologie-Graph in eine lesbare Beschreibung um."""
    if not G.nodes:
        return "Keine Module erkannt."

    parts = [f"**Erkannte Patch-Topologie: {track_name}**\n"]

    # Module
    parts.append("Module:")
    for _, data in G.nodes(data=True):
        texts = data.get("texts", [])
        label = data.get("label", "?")
        extra = [t for t in texts if t != label][:3]
        line = f"  • {label}"
        if extra:
            line += f"  [{', '.join(extra)}]"
        parts.append(line)

    # Verbindungen
    if G.edges:
        parts.append("\nKabel-Verbindungen:")
        for src, dst, data in G.edges(data=True):
            src_label = G.nodes[src].get("label", f"Mod{src}")
            dst_label = G.nodes[dst].get("label", f"Mod{dst}")
            sig = data.get("signal", "?")
            parts.append(f"  {src_label} ──[{sig}]──→ {dst_label}")

    return "\n".join(parts)


def graph_to_mermaid(G: nx.DiGraph) -> str:
    """Konvertiert den Topologie-Graph in Mermaid-Code."""
    lines = ["graph LR"]
    _SIG_STYLE = {
        "Audio":  "-->",
        "CV":     "-.->",
        "Note":   "==>",
        "Gate":   "-->",
        "Custom": "-->",
    }
    seen_nodes = set()
    for node, data in G.nodes(data=True):
        nid = f"N{node}"
        label = data.get("label", f"Module {node}")
        if nid not in seen_nodes:
            lines.append(f'    {nid}["{label}"]')
            seen_nodes.add(nid)
    for src, dst, edata in G.edges(data=True):
        sig = edata.get("signal", "Audio")
        arrow = _SIG_STYLE.get(sig, "-->")
        lines.append(f"    N{src} {arrow}|{sig}| N{dst}")
    return "\n".join(lines)


# ── Annotiertes Debug-Bild ────────────────────────────────────────────────────

def draw_annotations(img_bgr: np.ndarray, modules: list[dict],
                     cables: list[dict], texts: list[dict]) -> np.ndarray:
    out = img_bgr.copy()
    _SIG_BGR = {
        "Audio": (0, 200, 255), "CV": (0, 255, 100),
        "Note": (255, 100, 0), "Gate": (255, 255, 0), "Custom": (0, 80, 255),
    }
    for m in modules:
        cv2.rectangle(out, (m["x"], m["y"]),
                      (m["x"]+m["w"], m["y"]+m["h"]), (0, 255, 180), 2)
    for c in cables:
        color = _SIG_BGR.get(c["type"], (200, 200, 200))
        cv2.line(out, (c["x1"], c["y1"]), (c["x2"], c["y2"]), color, 2)
    for t in texts[:40]:
        cv2.putText(out, t["text"][:20], (int(t["x"]), int(t["y"])),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    return out


# ── Hauptpipeline ─────────────────────────────────────────────────────────────

def analyze_grid(img_pil, track_name: str = "", save_debug: Path | None = None) -> dict:
    """Vollständige lokale Grid-Analyse ohne externe API."""
    from PIL import Image

    print(f"  [cv] Bild: {img_pil.size[0]}x{img_pil.size[1]}")

    # BGR für OpenCV
    img_bgr = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

    # 1. Modul-Rechtecke
    print("  [cv] Erkenne Module …", end="", flush=True)
    modules = detect_modules(img_bgr)
    print(f" {len(modules)} gefunden")

    # 2. Kabel
    print("  [cv] Erkenne Kabel …", end="", flush=True)
    cables = detect_cables(img_bgr)
    cable_types = {}
    for c in cables:
        cable_types[c["type"]] = cable_types.get(c["type"], 0) + 1
    print(f" {len(cables)} ({', '.join(f'{k}:{v}' for k,v in cable_types.items())})")

    # 3. OCR
    print("  [ocr] Lese Text …", end="", flush=True)
    texts = ocr_grid(img_pil)
    # Nur konfidente Treffer
    texts = [t for t in texts if t["conf"] > 0.4]
    text_words = [t["text"] for t in texts]
    print(f" {len(texts)} Texte: {', '.join(text_words[:8])}")

    # 4. Graph
    G = build_topology(modules, cables, texts)
    description = graph_to_description(G, track_name)
    mermaid = graph_to_mermaid(G)

    # 5. Debug-Bild
    if save_debug:
        annotated = draw_annotations(img_bgr, modules, cables, texts)
        cv2.imwrite(str(save_debug), annotated)
        print(f"  [debug] Annotiertes Bild: {save_debug}")

    return {
        "modules":     modules,
        "cables":      cables,
        "texts":       text_words,
        "graph":       G,
        "description": description,
        "mermaid":     mermaid,
        "module_count": len(modules),
        "cable_count":  len(cables),
        "ocr_texts":    text_words,
    }


def store_analysis(result: dict, track_idx: int, track_name: str,
                   device: str, project: str) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    content = (
        f"**Grid-Analyse (lokal): {track_name}** [{device}] — {project}\n"
        f"Erkannte Module: {', '.join(result['ocr_texts'][:12])}\n"
        f"Kabel-Typen: {', '.join(set(c['type'] for c in result['cables']))}\n"
        f"{result['description']}"
    )
    emb = get_embeddings().embed_documents([content])[0]

    with neo4j_session() as s:
        s.run("""
            MERGE (n:GridAnalysis {track_index: $ti, project: $project})
            SET n.track_name    = $name,
                n.device_name   = $device,
                n.ocr_texts     = $texts,
                n.module_count  = $mc,
                n.cable_count   = $cc,
                n.mermaid_cv    = $mermaid,
                n.analysis_cv   = $desc,
                n.content       = $content,
                n.source        = $source,
                n.embedding     = $emb
        """, ti=track_idx, project=project, name=track_name,
             device=device, texts=result["ocr_texts"][:20],
             mc=result["module_count"], cc=result["cable_count"],
             mermaid=result["mermaid"], desc=result["description"],
             content=content,
             source=f"GridAnalysis:{project}/Track{track_idx}",
             emb=emb)

        s.run("""
            MATCH (sr:SoundRecipe {track_index: $ti, project: $project})
            MATCH (ga:GridAnalysis {track_index: $ti, project: $project})
            MERGE (ga)-[:ANALYZES]->(sr)
        """, ti=track_idx, project=project)

    print(f"  ✅ GridAnalysis gespeichert (Track {track_idx})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="Chee - Hey Now")
    parser.add_argument("--track",   type=int, default=None)
    parser.add_argument("--file",    default="", help="Lokale PNG-Datei")
    parser.add_argument("--debug",   action="store_true", help="Annotiertes Bild speichern")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait",    action="store_true",
                        help="Warte auf Enter bevor Screenshot gemacht wird (Bitwig manuell in Vordergrund bringen)")
    args = parser.parse_args()

    from src.agent.osc.project_scan import scan_project, open_track_device
    from scripts.analyze_grid_screenshot import fetch_screenshot
    from scripts.show_grid_workflow import _activate_bitwig_mac
    from PIL import Image
    from io import BytesIO

    _GRID_DEVICES = {"poly grid", "fx grid", "note grid"}

    # Tracks bestimmen
    project_data = scan_project(timeout=5.0)
    all_tracks = project_data.get("tracks", [])

    grid_tracks = [
        t for t in all_tracks
        if any(d.lower() in _GRID_DEVICES for d in t.get("devices", []))
        and (args.track is None or t["idx"] == args.track)
    ]

    if not grid_tracks and args.file:
        grid_tracks = [{"idx": args.track or 0, "name": "Track", "devices": ["Poly Grid"]}]

    if not grid_tracks:
        print("Keine Grid-Tracks gefunden")
        return

    debug_dir = Path("/tmp/bitwig_grids_cv")
    debug_dir.mkdir(exist_ok=True)

    for track in grid_tracks:
        idx    = track["idx"]
        name   = track["name"]
        device = next((d for d in track.get("devices",[]) if d.lower() in _GRID_DEVICES),
                      track.get("devices",["?"])[0])

        print(f"\n{'─'*60}")
        print(f"Track {idx}: {name} [{device}]")

        # Screenshot laden
        if args.file:
            img_pil = Image.open(args.file)
        else:
            opened = open_track_device(idx, timeout=3.0)
            if not opened:
                print("  Konnte Device nicht öffnen")
                continue
            _activate_bitwig_mac()
            time.sleep(1.5)
            raw = fetch_screenshot(timeout=12.0)
            if not raw:
                print("  Screenshot fehlgeschlagen")
                continue
            img_pil = Image.open(BytesIO(raw))
            # Auf Modul-Bereich zuschneiden
            w, h = img_pil.size
            img_pil = img_pil.crop((70, 280, w-70, h-100))

        debug_path = (debug_dir / f"track_{idx:02d}_annotated.png") if args.debug else None

        result = analyze_grid(img_pil, track_name=name, save_debug=debug_path)

        print(f"\n{result['description']}")
        print(f"\nMermaid:\n```mermaid\n{result['mermaid']}\n```")

        if not args.dry_run:
            store_analysis(result, idx, name, device, args.project)


if __name__ == "__main__":
    main()

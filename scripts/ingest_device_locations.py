"""
Reichert Device-Nodes in Neo4j mit:
  - builtin_uuid  (Bitwig-interne UUID für direktes Laden)
  - browser_tab   (Instruments / Audio FX / MIDI FX / Grid)
  - ui_path       (Browser-Navigationspfad + Shortcuts)
  - load_cmd      (OSC-Befehl zum Laden)

Usage:
    source .venv/bin/activate
    python scripts/ingest_device_locations.py [--dry-run]
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from neo4j import GraphDatabase

NEO4J_URI      = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jllm")

# ── 1. Built-in UUIDs (aus Java-Extension) ───────────────────────────────────
# Ermöglicht direktes Laden per insertBitwigDevice(uuid) ohne Browser-Navigation

BUILTIN_UUIDS: dict[str, str] = {
    "Amp":                  "41be8f3a-6d24-4442-9508-8548dbe62d47",
    "Arpeggiator":          "4d407a2b-c91b-4e4c-9a89-c53c19fe6251",
    "Audio MOD":            "01c7c48f-40cd-40cd-8a9a-1f258f1cc7d5",
    "Audio Receiver":       "46b3e40a-629c-42c2-9e14-a1ccbcaa903b",
    "Bend":                 "6aec6e78-9c1e-4c0b-8a88-0c2c37890a1d",
    "Bit-8":                "43875255-6f1f-4d54-a5ad-c45bff793477",
    "Blur":                 "72a3018d-788b-472c-b1d7-16419d00f4c6",
    "Chain":                "03ec3a24-b3c9-4ba4-b6dc-855178d60de7",
    "Channel Filter":       "c5a1bb2d-a589-4fda-b3cf-911cfd6297be",
    "Channel Map":          "0f003fa3-adcc-4684-81f7-f0e11c09c5b4",
    "Chorus":               "d275f9a6-0e4a-409c-9dc4-d74af90bc7ae",
    "Chorus+":              "1b8f2226-c432-4a0a-9830-69bc76d1a276",
    "Comb":                 "20e18780-8438-48d3-b234-40dcbaa947b8",
    "Compressor":           "2b1b4787-8d74-4138-877b-9197209eef0f",
    "Compressor+":          "42b32cd2-6275-4ff1-970f-4fac71d15ad9",
    "Convolution Reverb":   "528f7939-87c0-4997-8e71-6331d2eee388",
    "DC Offset":            "ee445061-a0ee-4322-991a-b60212db04ed",
    "De-Esser":             "8750db61-e9d3-4d0e-a610-e734006a64dc",
    "Delay":                "2a7a7328-3f7a-4afb-95eb-5230c298bb90",
    "Delay+":               "f2baa2a8-36c5-4a79-b1d9-a4e461c45ee9",
    "Delay-1":              "2a7a7328-3f7a-4afb-95eb-5230c298bb90",
    "Delay-2":              "71539d5d-1c7a-4dac-8f74-29e23b89b599",
    "Delay-4":              "f95a0e18-5a8b-4f53-93ad-8be73fd668bd",
    "Distortion":           "41b34699-8e5d-4534-a429-a67d488ba6ac",
    "Dribble":              "d98f7ce5-564e-4b95-926a-4e7b50a251c6",
    "Drum Machine":         "8ea97e45-0255-40fd-bc7e-94419741e9d1",
    "Dual Pan":             "c94820f8-3779-438b-a85b-868e57b746cc",
    "Dynamics":             "22e785a2-a187-41e9-a0f2-66343694014c",
    "Echo":                 "43c102c9-ce32-4dd8-b207-f0831733b17b",
    "EQ+":                  "e4815188-ba6f-4d14-bcfc-2dcb8f778ccb",
    "EQ-2":                 "01af068e-1e49-4777-a6e6-7f1dc679227a",
    "EQ-5":                 "227e2e3c-75d5-46f3-960d-8fb5529fe29f",
    "EQ-DJ":                "3cc1b71a-e22a-42cf-89f0-316475368fb3",
    "Filter":               "4ccfc70e-59bd-4e97-a8a7-d8cdce88bf42",
    "Filter +":             "6d621c1c-ab64-43b4-aea3-dad37e6f649c",
    "Flanger":              "8393c436-b11b-4fee-85dd-b2ef0a2ed380",
    "Flanger+":             "a99f8c3c-7813-4e6b-a18a-302c74286efc",
    "FM-4":                 "7a0a94df-3aa4-4bb5-8e24-2511999871ad",
    "Focus":                "42208fc5-02fd-42b4-9681-a8fadb46575f",
    "Freq Shifter":         "7ec87fdf-0bf8-42e7-b54b-5d8b68e330b1",
    "Freq Shift+":          "eb28831d-2478-4918-bd51-bcc1ff4c7eed",
    "Freq Split":           "3f3c3200-e6aa-4578-8e06-f573ed65206e",
    "FX Grid":              "a0cb2ec0-2464-461c-8165-296f98905539",
    "FX Layer":             "96456481-4c52-423a-8485-4604b15d0183",
    "FX Selector":          "8fd471db-15df-44c6-b497-4bb851d4fd46",
    "Gate":                 "556300ac-3a6e-4423-966a-5d5dde459a1b",
    "Harmonic Split":       "c90b6d52-898b-4dad-aa58-2c58add7c94f",
    "Harmonize":            "ff299d28-d822-4686-ac0a-03c0ae69b32d",
    "Humanize":             "f7b6f2a6-bfca-41ec-8646-b68e0f4cf12b",
    "HW FX":                "29b93a99-eb3a-4b19-8c12-8b4391f5a1ea",
    "HW Instrument":        "6a27aef7-bba5-4b0d-af98-7c192f84fbc2",
    "Instrument Layer":     "5024be2e-65d6-4d40-bbfe-8b2ea993c445",
    "Instrument Selector":  "9588fbcf-721a-438b-8555-97e4231f7d2c",
    "Ladder Filter":        "abfbbd63-8801-4bdb-a1ad-4b197f4d41e0",
    "Latch":                "93c9d566-4cc9-4895-bf5b-475cab44eba9",
    "LFO MOD":              "613dd120-9f55-4d24-97ac-f7902ffa7ce7",
    "Limiter":              "8da7251e-2578-4bcc-b3c4-8f4ec2e115d0",
    "Peak Limiter":         "8da7251e-2578-4bcc-b3c4-8f4ec2e115d0",
    "Micro-Pitch":          "4ac40334-99cc-43a3-b693-f3dc63211f0c",
    "Mid-Side Split":       "a6c9b12f-45a5-43e3-b100-b74ecf77367b",
    "MIDI CC":              "a0b8f27a-128e-4f72-b9fc-a277060b87ee",
    "Multi-Note":           "0a015261-7546-4f6d-9197-098a26ff2c20",
    "Multiband FX-2":       "214857d6-b468-4257-9bc9-92f017af1782",
    "Multiband FX-3":       "f97699d1-3b8e-4363-8ede-4994e276cc97",
    "Note Delay":           "9f3cc825-3284-4c5a-b51f-01219de13b7c",
    "Note Filter":          "ef7559c8-49ae-4657-95be-11abb896c969",
    "Note Grid":            "264d6f4e-5067-46c9-a4fa-a75a295d9e01",
    "Note Length":          "4c396eb6-953d-4de0-afaa-63276fc1150b",
    "Note MOD":             "1179be46-4d43-4a26-bb5f-430bc3fef9ba",
    "Note Receiver":        "c6153773-ed96-4cca-a767-5cf3d5dceacb",
    "Note Repeats":         "a68e0f1b-bcc6-45c2-b09e-8c8771f83e50",
    "Note Transpose":       "0815cd9e-3a31-4429-a268-dabd952a3b68",
    "Organ":                "f2dcfe9a-7b66-4c84-984a-b25685a1c21a",
    "Oscilloscope":         "ffe670a2-09aa-4c9b-8822-5161a9cca686",
    "Phase-4":              "252723bf-68a6-4ee6-81f8-95ba4d0fb467",
    "Phaser":               "fc87ae07-1624-449f-8dae-2db5d93e1aa9",
    "Phaser+":              "fd7a9e6c-6992-40c2-be3b-ac8ed48553e9",
    "Pitch Shifter":        "384fe469-6023-4f69-9560-e0c2eec2da49",
    "Poly Grid":            "a33bba66-8cd4-4f89-aee5-68bf67f70a54",
    "Polymer":              "8f58138b-03aa-4e9d-83bd-a038c99a4ef5",
    "Polysynth":            "a9ffacb5-33e9-4fc7-8621-b1af31e410ef",
    "Resonator Bank":       "b64070ae-5a59-4640-bb6a-194619bc12d8",
    "Reverb":               "5a1cb339-1c4a-4cc7-9cae-bd7a2058153d",
    "Ring-Mod":             "374feaeb-c785-4243-9d08-3f9099b4c0cb",
    "Rotary":               "8fc25e70-b92b-4096-8270-42e492df501a",
    "Sampler":              "468bc14b-b2e7-45a1-9666-e83117fe404e",
    "Saturator":            "93d11348-86ae-4ead-9fe7-84ac03b9369c",
    "Sculpt":               "8d9d63db-9991-4e46-8b4c-77755d1fcaab",
    "Spectrum":             "fcd9aa65-ebbb-4337-a97e-69929322ef47",
    "Step MOD":             "18a37a4d-8613-442d-a6eb-931002ba9a36",
    "Stereo Split":         "96196ffe-658f-46c4-84ba-153799be3657",
    "Tool":                 "e67b9c56-838d-4fba-8e3e-ae4e02cccbcb",
    "Transient Control":    "71e6dbd8-a117-4ff0-85e8-5650f5a76d98",
    "Transient Split":      "7c3c7bb2-625d-4915-ae95-943ee9aa807d",
    "Tremolo":              "f3b90fff-402b-4187-9aab-620f441577b9",
    "Velocity Curve":       "066d0065-99a4-47da-b0f7-9468ef69c1cf",
    "XY FX":                "51169152-c144-4a38-95ba-1390fb579a1f",
    "XY Instrument":        "bab3f04d-d3b6-4dfa-86f9-506e0b091ca8",
    "Multiband Compressor": "214857d6-b468-4257-9bc9-92f017af1782",
}

# ── 2. UI-Navigation: wo ist was in Bitwig ───────────────────────────────────
# browser_tab: welcher Reiter im Browser (B-Taste)
# ui_path:     Navigationspfad im Browser
# load_cmd:    OSC-Befehl zum Laden
# shortcut:    Tastenkürzel oder Beschreibung wie man hinkommt

UI_LOCATIONS: dict[str, dict] = {
    # ── Instruments ──────────────────────────────────────────────────────────
    "Phase-4":          {"tab": "Instruments", "path": "Instruments > Synthesizers > Phase-4",        "panel": "Device Panel (unten)"},
    "FM-4":             {"tab": "Instruments", "path": "Instruments > Synthesizers > FM-4",            "panel": "Device Panel (unten)"},
    "Polysynth":        {"tab": "Instruments", "path": "Instruments > Synthesizers > Polysynth",       "panel": "Device Panel (unten)"},
    "Polymer":          {"tab": "Instruments", "path": "Instruments > Synthesizers > Polymer",         "panel": "Device Panel (unten)"},
    "Sampler":          {"tab": "Instruments", "path": "Instruments > Sampler",                        "panel": "Device Panel (unten)"},
    "Drum Machine":     {"tab": "Instruments", "path": "Instruments > Drums > Drum Machine",           "panel": "Device Panel (unten), eigenes Fenster öffnen mit ↗"},
    "Organ":            {"tab": "Instruments", "path": "Instruments > Synthesizers > Organ",           "panel": "Device Panel (unten)"},
    "Poly Grid":        {"tab": "Instruments", "path": "Instruments > Grid > Poly Grid",               "panel": "Device Panel → Grid-Editor öffnen mit Klick auf Vorschau"},
    "FX Grid":          {"tab": "Audio FX",    "path": "Audio FX > Grid > FX Grid",                    "panel": "Device Panel → Grid-Editor öffnen mit Klick auf Vorschau"},
    "Note Grid":        {"tab": "MIDI FX",     "path": "MIDI FX > Grid > Note Grid",                   "panel": "Device Panel (unten)"},
    # ── Audio FX ─────────────────────────────────────────────────────────────
    "Compressor":       {"tab": "Audio FX", "path": "Audio FX > Dynamics > Compressor",               "panel": "Device Panel oder FX-Chain rechtsklick → Insert Device"},
    "Compressor+":      {"tab": "Audio FX", "path": "Audio FX > Dynamics > Compressor+",              "panel": "Device Panel"},
    "Limiter":          {"tab": "Audio FX", "path": "Audio FX > Dynamics > Peak Limiter",             "panel": "Device Panel"},
    "Transient Control":{"tab": "Audio FX", "path": "Audio FX > Dynamics > Transient Control",        "panel": "Device Panel"},
    "Dynamics":         {"tab": "Audio FX", "path": "Audio FX > Dynamics > Dynamics",                 "panel": "Device Panel"},
    "Gate":             {"tab": "Audio FX", "path": "Audio FX > Dynamics > Gate",                     "panel": "Device Panel"},
    "EQ-5":             {"tab": "Audio FX", "path": "Audio FX > EQ > EQ-5",                           "panel": "Device Panel, Erweiterte Ansicht mit ↗ für EQ-Kurve"},
    "EQ-2":             {"tab": "Audio FX", "path": "Audio FX > EQ > EQ-2",                           "panel": "Device Panel"},
    "EQ+":              {"tab": "Audio FX", "path": "Audio FX > EQ > EQ+",                            "panel": "Device Panel, Erweiterte Ansicht mit ↗"},
    "EQ-DJ":            {"tab": "Audio FX", "path": "Audio FX > EQ > EQ-DJ",                          "panel": "Device Panel"},
    "Reverb":           {"tab": "Audio FX", "path": "Audio FX > Reverb > Reverb",                     "panel": "Device Panel"},
    "Convolution Reverb":{"tab": "Audio FX","path": "Audio FX > Reverb > Convolution Reverb",         "panel": "Device Panel"},
    "Delay+":           {"tab": "Audio FX", "path": "Audio FX > Delay > Delay+",                      "panel": "Device Panel"},
    "Delay-1":          {"tab": "Audio FX", "path": "Audio FX > Delay > Delay-1",                     "panel": "Device Panel"},
    "Delay-2":          {"tab": "Audio FX", "path": "Audio FX > Delay > Delay-2",                     "panel": "Device Panel"},
    "Chorus+":          {"tab": "Audio FX", "path": "Audio FX > Modulation > Chorus+",                "panel": "Device Panel"},
    "Flanger+":         {"tab": "Audio FX", "path": "Audio FX > Modulation > Flanger+",               "panel": "Device Panel"},
    "Phaser+":          {"tab": "Audio FX", "path": "Audio FX > Modulation > Phaser+",                "panel": "Device Panel"},
    "Freq Shift+":      {"tab": "Audio FX", "path": "Audio FX > Modulation > Freq Shifter+",          "panel": "Device Panel"},
    "Saturator":        {"tab": "Audio FX", "path": "Audio FX > Distortion > Saturator",              "panel": "Device Panel"},
    "Amp":              {"tab": "Audio FX", "path": "Audio FX > Distortion > Amp",                    "panel": "Device Panel"},
    "Distortion":       {"tab": "Audio FX", "path": "Audio FX > Distortion > Distortion",             "panel": "Device Panel"},
    "Ladder Filter":    {"tab": "Audio FX", "path": "Audio FX > Filter > Ladder",                     "panel": "Device Panel"},
    "Filter +":         {"tab": "Audio FX", "path": "Audio FX > Filter > Filter+",                    "panel": "Device Panel"},
    "Spectrum":         {"tab": "Audio FX", "path": "Audio FX > Utility > Spectrum",                  "panel": "Device Panel, öffnet Spektrogramm-Fenster"},
    "Oscilloscope":     {"tab": "Audio FX", "path": "Audio FX > Utility > Oscilloscope",              "panel": "Device Panel"},
    "Tool":             {"tab": "Audio FX", "path": "Audio FX > Utility > Tool",                      "panel": "Device Panel"},
    "Multiband Compressor":{"tab": "Audio FX","path": "Audio FX > Dynamics > Multiband Compressor",  "panel": "Device Panel"},
    # ── MIDI FX ──────────────────────────────────────────────────────────────
    "Arpeggiator":      {"tab": "MIDI FX", "path": "MIDI FX > Arpeggiator",                           "panel": "Device Panel, vor dem Instrument einfügen"},
    "Chord":            {"tab": "MIDI FX", "path": "MIDI FX > Chord",                                 "panel": "Device Panel, vor dem Instrument"},
    "Note Repeats":     {"tab": "MIDI FX", "path": "MIDI FX > Note Repeats",                          "panel": "Device Panel"},
    "Harmonize":        {"tab": "MIDI FX", "path": "MIDI FX > Harmonize",                             "panel": "Device Panel, vor dem Instrument"},
    "Note Length":      {"tab": "MIDI FX", "path": "MIDI FX > Note Length",                           "panel": "Device Panel"},
    "Channel Filter":   {"tab": "MIDI FX", "path": "MIDI FX > Channel Filter",                        "panel": "Device Panel"},
    # ── Grid-Module (spezielle Navigation) ───────────────────────────────────
    "SVF":              {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → Filter > SVF",          "panel": "Grid-Editor (Klick auf Poly Grid / FX Grid Vorschau)"},
    "ADSR":             {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → Envelope > ADSR",       "panel": "Grid-Editor"},
    "Wavetable":        {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → Oscillator > Wavetable","panel": "Grid-Editor"},
    "Low-pass LD":      {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → Filter > Low-pass LD",  "panel": "Grid-Editor"},
    "LFO":              {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → LFO > LFO",             "panel": "Grid-Editor"},
    "Phasor":           {"tab": "Grid",     "path": "Grid-Editor → Tab-Taste → Phase > Phasor",        "panel": "Grid-Editor"},
}

# ── 3. Für alle anderen: automatisch aus device_type ableiten ─────────────────
DTYPE_TO_TAB = {
    "instrument":  ("Instruments", "Instruments"),
    "fx":          ("Audio FX",    "Audio FX"),
    "modulation":  ("Audio FX",    "Audio FX > Modulation"),
    "MIDI":        ("MIDI FX",     "MIDI FX"),
    "hardware":    ("Audio FX",    "Audio FX > Hardware"),
    "data":        ("Grid",        "Grid-Editor → Tab"),
    "display":     ("Grid",        "Grid-Editor → Tab → Display"),
    "mixing":      ("Grid",        "Grid-Editor → Tab → Mix"),
    "oscillator":  ("Grid",        "Grid-Editor → Tab → Oscillator"),
    "pitch":       ("Grid",        "Grid-Editor → Tab → Pitch"),
    "envelope":    ("Grid",        "Grid-Editor → Tab → Envelope"),
    "filter":      ("Grid",        "Grid-Editor → Tab → Filter"),
    "lfo":         ("Grid",        "Grid-Editor → Tab → LFO"),
    "shaper":      ("Grid",        "Grid-Editor → Tab → Shaper"),
    "phase":       ("Grid",        "Grid-Editor → Tab → Phase"),
    "utility":     ("Grid",        "Grid-Editor → Tab → Level"),
}


def run(driver, dry_run: bool):
    counts = {"uuid": 0, "ui_location": 0, "auto_tab": 0}

    with driver.session() as s:
        all_devices = s.run(
            "MATCH (d:Device) RETURN d.name AS name, d.device_type AS dtype"
        ).data()

        for d in all_devices:
            name = d["name"]
            dtype = d.get("dtype") or ""
            updates: dict[str, str] = {}

            # UUID
            uuid = BUILTIN_UUIDS.get(name)
            if uuid:
                updates["builtin_uuid"] = uuid
                updates["load_cmd"] = f"/browser/device/load {name}"
                counts["uuid"] += 1

            # Expliziter UI-Pfad
            loc = UI_LOCATIONS.get(name)
            if loc:
                updates["browser_tab"] = loc["tab"]
                updates["ui_path"] = loc["path"]
                updates["ui_panel"] = loc["panel"]
                counts["ui_location"] += 1
            else:
                # Automatisch aus device_type ableiten
                tab_info = DTYPE_TO_TAB.get(dtype)
                if tab_info and "browser_tab" not in updates:
                    tab, path_base = tab_info
                    updates["browser_tab"] = tab
                    updates["ui_path"] = f"{path_base} > {name}"
                    counts["auto_tab"] += 1

            if updates and not dry_run:
                set_clause = ", ".join(f"d.{k} = ${k}" for k in updates)
                s.run(
                    f"MATCH (d:Device {{name: $name}}) SET {set_clause}",
                    name=name, **updates
                )
            elif updates and dry_run:
                pass  # just count

        return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    counts = run(driver, args.dry_run)
    driver.close()

    mode = "[dry-run] " if args.dry_run else ""
    print(f"{mode}[done] uuid={counts['uuid']}, ui_location={counts['ui_location']}, auto_tab={counts['auto_tab']}")


if __name__ == "__main__":
    main()

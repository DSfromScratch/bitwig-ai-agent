"""Aktualisiert Workflow-Nodes und erstellt OscCommand-Dokumentation in Neo4j.

Änderungen:
  1. Workflow-Nodes: Device-Namen korrigieren + osc_steps JSON hinzufügen
  2. OscCommand-Nodes: vollständige Dokumentation aller Extension-Endpoints

Run from repo root:
    .venv/bin/python scripts/update_workflows_and_osc_docs.py
"""
from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── 1. Workflow Updates ────────────────────────────────────────────────────────

WORKFLOW_UPDATES = [
    {
        "name": "Dubstep Reese Bass",
        "steps": (
            "FM-4 auf Bass-Track laden\n"
            "Algorithmus: Op1 moduliert Op2 (Kette)\n"
            "Op1 Ratio: 1.0, Op2 Ratio: 1.5\n"
            "Op1 Detune: +8 Cents\n"
            "Distortion: Mode=Fold, Drive=0.4\n"
            "Ladder-Filter: Cutoff 800Hz, Resonance 0.3\n"
            "Compressor: Threshold -18dB, Ratio 4:1, Attack 2ms"
        ),
        "osc_steps": [
            {"cmd": "/track/add/instrument",             "comment": "Neuen Instrument-Track anlegen"},
            {"cmd": "/browser/device/load FM-4",         "comment": "FM-4 Synthesizer laden (UUID-Insert, kein Browser nötig)"},
            {"cmd": "/device/param/named algorithm 0.5", "comment": "FM-Algorithmus: Op1→Op2 Kette"},
            {"cmd": "/device/param/named op1_ratio 0.5", "comment": "Op1 Ratio = 1.0 (normalized ~0.5)"},
            {"cmd": "/device/param/named op2_ratio 0.6", "comment": "Op2 Ratio = 1.5 (normalized ~0.6)"},
            {"cmd": "/device/param/named op1_tune 0.52", "comment": "Op1 Detune +8 Cents"},
            {"cmd": "/browser/device/load Distortion",   "comment": "Distortion-FX hinzufügen"},
            {"cmd": "/device/param/named drive 0.4",     "comment": "Distortion Drive = 0.4"},
            {"cmd": "/browser/device/load Ladder",       "comment": "Ladder-Filter laden"},
            {"cmd": "/device/param/named cutoff 0.45",   "comment": "Cutoff ~800Hz"},
            {"cmd": "/device/param/named resonance 0.3", "comment": "Resonance = 0.3"},
            {"cmd": "/browser/device/load Compressor",   "comment": "Compressor laden"},
            {"cmd": "/device/param/named threshold 0.3", "comment": "Threshold -18dB"},
            {"cmd": "/device/param/named ratio 0.4",     "comment": "Ratio 4:1"},
            {"cmd": "/device/param/named attack 0.15",   "comment": "Attack 2ms"},
        ],
    },
    {
        "name": "Dubstep Half-Time Drums",
        "steps": (
            "v9 Kick auf Kick-Pad (MIDI 36): Tune -18, Punch 0.8, Decay 0.5s\n"
            "v9 Snare auf Snare-Pad (MIDI 38): Beat 3 (half-time), Reverb 1.5s\n"
            "v9 Hat Closed auf HiHat-Pad (MIDI 42): 8tel-Noten, vel 60/100 alternierend\n"
            "Sidechain: Compressor auf Bass-Track, Input=Kick\n"
            "Sidechain: Threshold -20dB, Ratio 6:1, Attack 2ms, Release 80ms"
        ),
        "osc_steps": [
            {"cmd": "/track/add/instrument",                 "comment": "Drum-Track anlegen"},
            {"cmd": "/browser/device/load Drum Machine",     "comment": "Drum Machine laden"},
            {"cmd": "/drum/pad/pitch/enter 36",              "comment": "Kick-Pad betreten (MIDI pitch 36)"},
            {"cmd": "/browser/device/load v9 Kick",          "comment": "v9 Kick in Kick-Pad laden"},
            {"cmd": "/drum/pad/pitch/enter 38",              "comment": "Snare-Pad betreten (MIDI pitch 38)"},
            {"cmd": "/browser/device/load v9 Snare",         "comment": "v9 Snare in Snare-Pad laden"},
            {"cmd": "/drum/pad/pitch/enter 42",              "comment": "HiHat-Pad betreten (MIDI pitch 42)"},
            {"cmd": "/browser/device/load v9 Hat Closed",    "comment": "v9 Hat Closed in HiHat-Pad laden"},
            {"cmd": "/track/add/instrument",                 "comment": "Bass-Track für Sidechain anlegen"},
            {"cmd": "/browser/device/load Compressor",       "comment": "Compressor auf Bass-Track laden"},
            {"note": "Sidechain-Input muss manuell in Bitwig UI gesetzt werden — kein OSC-Befehl verfügbar"},
            {"cmd": "/device/param/named threshold 0.25",    "comment": "Threshold -20dB"},
            {"cmd": "/device/param/named ratio 0.5",         "comment": "Ratio 6:1"},
            {"cmd": "/device/param/named attack 0.15",       "comment": "Attack 2ms"},
            {"cmd": "/device/param/named release 0.35",      "comment": "Release 80ms"},
        ],
    },
    {
        "name": "Sidechain Kompression",
        "steps": (
            "Compressor auf Ziel-Track laden\n"
            "Sidechain-Input: Kick-Track (manuell in Bitwig UI)\n"
            "Threshold: -20 dB\n"
            "Ratio: 6:1\n"
            "Attack: 2 ms\n"
            "Release: 80 ms"
        ),
        "osc_steps": [
            {"cmd": "/browser/device/load Compressor",    "comment": "Compressor auf Ziel-Track laden"},
            {"note": "Sidechain-Input muss manuell in Bitwig UI konfiguriert werden"},
            {"cmd": "/device/param/named threshold 0.25", "comment": "Threshold -20dB (norm: ~0.25)"},
            {"cmd": "/device/param/named ratio 0.5",      "comment": "Ratio 6:1 (norm: ~0.5)"},
            {"cmd": "/device/param/named attack 0.15",    "comment": "Attack 2ms"},
            {"cmd": "/device/param/named release 0.35",   "comment": "Release 80ms"},
        ],
    },
    {
        "name": "Mastering Chain",
        "steps": (
            "EQ-5: Korrektur-EQ, HPF bei 30Hz\n"
            "Compressor: Threshold -18dB, Ratio 2:1, soft knee\n"
            "Saturator: Drive 0.15 für Wärme\n"
            "EQ-5: High Shelf +1.5dB bei 8kHz\n"
            "Limiter: Ceiling -0.3 dBTP, Lookahead 1ms\n"
            "Ziel: -14 LUFS für Streaming"
        ),
        "osc_steps": [
            {"cmd": "/track/add/effect",                    "comment": "Master-Return-Track (oder auf Master-Track arbeiten)"},
            {"cmd": "/browser/device/load EQ-5",            "comment": "EQ-5 für HPF + Korrekturen laden"},
            {"cmd": "/eq/freq/1 0.08",                      "comment": "Band 1 Frequenz ~30Hz (HPF)"},
            {"cmd": "/browser/device/load Compressor",      "comment": "Bus-Compressor laden"},
            {"cmd": "/device/param/named threshold 0.32",   "comment": "Threshold -18dB"},
            {"cmd": "/device/param/named ratio 0.25",       "comment": "Ratio 2:1 (soft)"},
            {"cmd": "/browser/device/load Saturator",       "comment": "Saturator für analoge Wärme"},
            {"cmd": "/device/param/named drive 0.15",       "comment": "Leichter Drive (0.15)"},
            {"cmd": "/browser/device/load EQ-5",            "comment": "Zweiter EQ für High-Shelf"},
            {"cmd": "/eq/gain/8 0.55",                      "comment": "High Shelf +1.5dB bei 8kHz (Band 8)"},
            {"cmd": "/browser/device/load Limiter",         "comment": "True-Peak-Limiter laden"},
            {"cmd": "/device/param/named ceiling 0.49",     "comment": "Ceiling -0.3 dBTP"},
        ],
    },
]

# ── 2. OscCommand Dokumentation ───────────────────────────────────────────────
# Alle Endpoints aus BitwigAgentBridgeExtension.java

OSC_COMMANDS: list[dict] = [
    # ── Transport ─────────────────────────────────────────────────────────────
    {"address": "/transport/play",     "args": "<1|0>",          "category": "transport",
     "description": "Play (1) oder Stop (0). Ohne Argument: Play.",
     "example": "/transport/play 1"},
    {"address": "/transport/stop",     "args": "",               "category": "transport",
     "description": "Transport stoppen.",
     "example": "/transport/stop"},
    {"address": "/transport/tempo",    "args": "<bpm:float>",    "category": "transport",
     "description": "Tempo in BPM setzen (rawValue, z.B. 174.0).",
     "example": "/transport/tempo 174"},
    {"address": "/tempo/raw",          "args": "<bpm:float>",    "category": "transport",
     "description": "Alias für /transport/tempo — Python-Kompatibilität.",
     "example": "/tempo/raw 128"},
    {"address": "/transport/position", "args": "<beat:float>",   "category": "transport",
     "description": "Transport-Position setzen (in Beats).",
     "example": "/transport/position 0"},
    {"address": "/transport/loop/start",  "args": "<beat:float>","category": "transport",
     "description": "Loop-Startpunkt (in Beats).", "example": "/transport/loop/start 0"},
    {"address": "/transport/loop/end",    "args": "<beat:float>","category": "transport",
     "description": "Loop-Endpunkt (in Beats).", "example": "/transport/loop/end 16"},
    {"address": "/transport/loop/active", "args": "<0|1|-1>",    "category": "transport",
     "description": "Loop aktivieren (1), deaktivieren (0), oder togglen (-1).",
     "example": "/transport/loop/active 1"},
    {"address": "/record",             "args": "",               "category": "transport",
     "description": "Aufnahme starten/stoppen.", "example": "/record"},
    {"address": "/repeat",             "args": "<0|1|-1>",       "category": "transport",
     "description": "Loop/Repeat togglen oder setzen.", "example": "/repeat 1"},
    {"address": "/undo",               "args": "",               "category": "transport",
     "description": "Letzte Aktion rückgängig machen.", "example": "/undo"},

    # ── Tracks erstellen ──────────────────────────────────────────────────────
    {"address": "/track/add/instrument","args": "",              "category": "track",
     "description": "Neuen Instrument-Track am Ende hinzufügen.",
     "example": "/track/add/instrument"},
    {"address": "/track/add/audio",    "args": "",               "category": "track",
     "description": "Neuen Audio-Track hinzufügen.", "example": "/track/add/audio"},
    {"address": "/track/add/effect",   "args": "",               "category": "track",
     "description": "Neuen Return/Effect-Track hinzufügen.", "example": "/track/add/effect"},
    {"address": "/track/add/group",    "args": "",               "category": "track",
     "description": "Neuen Group-Track (via create_group_track Action).",
     "example": "/track/add/group"},
    {"address": "/track/delete/last",  "args": "",               "category": "track",
     "description": "Aktuell ausgewählten Track löschen.", "example": "/track/delete/last"},

    # ── Track-Steuerung (n=1–16) ──────────────────────────────────────────────
    {"address": "/track/{n}/select",   "args": "",               "category": "track",
     "description": "Track n auswählen (n=1–16). Setzt CursorTrack.",
     "example": "/track/1/select"},
    {"address": "/track/{n}/volume",   "args": "<0.0–1.0>",      "category": "track",
     "description": "Track-Lautstärke setzen (0.0=still, 0.8≈0dB, 1.0=+6dB).",
     "example": "/track/1/volume 0.8"},
    {"address": "/track/{n}/pan",      "args": "<0.0–1.0>",      "category": "track",
     "description": "Track-Pan setzen (0.0=links, 0.5=Mitte, 1.0=rechts).",
     "example": "/track/1/pan 0.5"},
    {"address": "/track/{n}/mute",     "args": "<0|1|-1>",       "category": "track",
     "description": "Mute setzen (1), deaktivieren (0), togglen (-1).",
     "example": "/track/1/mute 1"},
    {"address": "/track/{n}/solo",     "args": "<0|1|-1>",       "category": "track",
     "description": "Solo setzen, deaktivieren oder togglen.",
     "example": "/track/1/solo -1"},
    {"address": "/track/{n}/send/{m}", "args": "<0.0–1.0>",      "category": "track",
     "description": "Send-Level von Track n zu Return-Track m (0-indexed) setzen.",
     "example": "/track/1/send/0 0.55"},

    # ── Effect/Return-Tracks (n=1–8) ──────────────────────────────────────────
    {"address": "/effect/{n}/select",  "args": "",               "category": "track",
     "description": "Return-Track n auswählen (n=1–8).", "example": "/effect/1/select"},
    {"address": "/effect/{n}/volume",  "args": "<0.0–1.0>",      "category": "track",
     "description": "Return-Track-Lautstärke setzen.", "example": "/effect/1/volume 0.8"},

    # ── Browser ───────────────────────────────────────────────────────────────
    {"address": "/browser/device/load","args": "<name:string>",  "category": "browser",
     "description": (
         "Instrument oder Device nach Name laden. "
         "Für Built-in Bitwig Devices (Phase-4, FM-4, Polysynth, Drum Machine, v9 Kick, etc.) "
         "wird insertBitwigDevice(UUID) verwendet — kein Browser-Dialog, sofort. "
         "Für VST/Presets: PopupBrowser öffnen + fuzzy-Suche + commit. "
         "Bekannte Built-in Namen: Phase-4, FM-4, Polysynth, Polymer, Poly Grid, Drum Machine, "
         "Reverb, Delay, Delay+, Compressor, Distortion, Ladder, EQ-5, EQ+, Saturator, Limiter, "
         "v9 Kick, v9 Snare, v9 Hat Closed, v9 Hat Open, v9 Clap, v9 Tom, v9 Ride, "
         "v8 Kick, v8 Snare, v8 Hat, v1 Kick, v1 Snare, Sampler, Organ, Chorus, Flanger."
     ),
     "example": "/browser/device/load Phase-4"},
    {"address": "/browser/preset/load","args": "<name:string>",  "category": "browser",
     "description": "Preset für das aktuelle Device laden (fuzzy-Suche).",
     "example": "/browser/preset/load Reese Bass"},
    {"address": "/browser/fx/load",    "args": "<name:string>",  "category": "browser",
     "description": "FX-Chain-Preset aus Audioeffekte-Kategorie laden.",
     "example": "/browser/fx/load Guitar Crunchy"},
    {"address": "/browser/collection", "args": "<name:string>",  "category": "browser",
     "description": "Smart-Collection als Vorfilter setzen (vor /browser/device/load).",
     "example": "/browser/collection BitwigAgent"},
    {"address": "/browser/commit",     "args": "",               "category": "browser",
     "description": "Aktuelle Browser-Auswahl bestätigen und laden.", "example": "/browser/commit"},
    {"address": "/browser/cancel",     "args": "",               "category": "browser",
     "description": "Browser schließen ohne zu laden.", "example": "/browser/cancel"},
    {"address": "/browser/next",       "args": "<n:int>",        "category": "browser",
     "description": "n Schritte im Browser vorwärts navigieren.", "example": "/browser/next 1"},
    {"address": "/browser/prev",       "args": "<n:int>",        "category": "browser",
     "description": "n Schritte im Browser rückwärts.", "example": "/browser/prev 1"},
    {"address": "/browser/catalog/save","args": "<path:string>", "category": "browser",
     "description": "Browser-Katalog als JSON-Datei speichern (für Debugging).",
     "example": "/browser/catalog/save /home/user/catalog.json"},

    # ── Drum Machine ──────────────────────────────────────────────────────────
    {"address": "/drum/pad/pitch/enter","args": "<pitch:int>",   "category": "drum",
     "description": (
         "CursorDevice in die Device-Kette des Drum-Pads für MIDI-Pitch navigieren. "
         "Danach /browser/device/load <name> für das Pad-Instrument verwenden. "
         "Pitch-Map: kick=36, snare=38, hihat=42, clap=39, openhat=46, tom=41, crash=49."
     ),
     "example": "/drum/pad/pitch/enter 36"},

    # ── Device-Parameter ──────────────────────────────────────────────────────
    {"address": "/device/param/{p}/value","args": "<0.0–1.0>",  "category": "device",
     "description": "Parameter p (1–8) der aktuellen Remote-Control-Seite setzen.",
     "example": "/device/param/1/value 0.5"},
    {"address": "/device/param/named",  "args": "<name> <0.0–1.0>","category": "device",
     "description": (
         "Parameter nach Name setzen. Sucht in der aktuellen Remote-Control-Seite (8 Parameter). "
         "Normierter Wert 0.0–1.0. Seite wechseln mit /device/param/page/next falls nötig."
     ),
     "example": "/device/param/named cutoff 0.6"},
    {"address": "/device/param/page/next","args": "",            "category": "device",
     "description": "Nächste Remote-Control-Seite wählen.", "example": "/device/param/page/next"},
    {"address": "/device/param/page/prev","args": "",            "category": "device",
     "description": "Vorherige Remote-Control-Seite wählen.", "example": "/device/param/page/prev"},
    {"address": "/device/param/page/set","args": "<n:int>",      "category": "device",
     "description": "Remote-Control-Seite direkt auf Index n setzen.", "example": "/device/param/page/set 0"},

    # ── EQ ────────────────────────────────────────────────────────────────────
    {"address": "/eq/freq/{b}",        "args": "<0.0–1.0>",      "category": "eq",
     "description": "EQ-Band-Frequenz setzen (b=1–8, normiert: 0.0=20Hz, 1.0=20kHz log).",
     "example": "/eq/freq/3 0.5"},
    {"address": "/eq/gain/{b}",        "args": "<0.0–1.0>",      "category": "eq",
     "description": "EQ-Band-Gain setzen (0.5=0dB, 0.0=-24dB, 1.0=+24dB).",
     "example": "/eq/gain/3 0.55"},
    {"address": "/eq/q/{b}",           "args": "<0.0–1.0>",      "category": "eq",
     "description": "EQ-Band Q-Faktor (Güte/Bandbreite) setzen.", "example": "/eq/q/3 0.5"},

    # ── Clip ──────────────────────────────────────────────────────────────────
    {"address": "/clip/create",        "args": "<slot:int> <len:int>","category": "clip",
     "description": "Leeren Clip in Slot (0-basiert) mit Länge in Beats anlegen + auswählen.",
     "example": "/clip/create 0 16"},
    {"address": "/clip/select",        "args": "<slot:int>",     "category": "clip",
     "description": "Clip-Slot auswählen (0-basiert).", "example": "/clip/select 0"},
    {"address": "/clip/launch",        "args": "<slot:int>",     "category": "clip",
     "description": "Clip in Slot starten.", "example": "/clip/launch 0"},
    {"address": "/clip/clear",         "args": "",               "category": "clip",
     "description": "Alle Noten im aktiven Clip löschen.", "example": "/clip/clear"},
    {"address": "/clip/step_size",     "args": "<beats:float>",  "category": "clip",
     "description": "Schrittauflösung setzen (0.25=1/16, 0.5=1/8, 1.0=1/4).",
     "example": "/clip/step_size 0.25"},
    {"address": "/clip/note/beat",     "args": "<beat> <pitch> <vel:0-1> <dur>","category": "clip",
     "description": "Note nach Beat-Position schreiben (beat in Beats ab 0.0).",
     "example": "/clip/note/beat 0.0 36 0.9 0.25"},
    {"address": "/clip/notes/write",   "args": "<json_array>",   "category": "clip",
     "description": (
         "Batch-Write: JSON-Array mit [{step,pitch,vel,dur},...] in aktiven Clip schreiben. "
         "Effizienteste Methode für viele Noten. Sendet ACK auf /clip/notes/written."
     ),
     "example": '/clip/notes/write [{"step":0,"pitch":36,"vel":0.9,"dur":0.25}]'},
    {"address": "/clip/note/count",    "args": "",               "category": "clip",
     "description": "Noten-Anzahl des aktuellen Tracks abfragen (returns /clip/note/count/response).",
     "example": "/clip/note/count"},

    # ── Arrange ───────────────────────────────────────────────────────────────
    {"address": "/arrange/record/start","args": "",              "category": "arrange",
     "description": "Arrangement-Recording starten (+ Arrange-View + Play).",
     "example": "/arrange/record/start"},
    {"address": "/arrange/record/stop", "args": "",              "category": "arrange",
     "description": "Arrangement-Recording stoppen.", "example": "/arrange/record/stop"},
    {"address": "/arrange/view",        "args": "",              "category": "arrange",
     "description": "Zur Arrange-Ansicht wechseln.", "example": "/arrange/view"},
    {"address": "/arrange/insert/file", "args": "<path:string>", "category": "arrange",
     "description": "Audio-Datei als Device (Sampler) auf CursorTrack einfügen.",
     "example": "/arrange/insert/file /home/user/sample.wav"},
    {"address": "/sampler/load",        "args": "<path:string>", "category": "arrange",
     "description": "CursorDevice durch Sampler mit Audio-File ersetzen.",
     "example": "/sampler/load /home/user/beat.wav"},

    # ── Scenes ────────────────────────────────────────────────────────────────
    {"address": "/scene/{n}/launch",   "args": "",               "category": "scene",
     "description": "Szene n starten (n=1–8).", "example": "/scene/1/launch"},
    {"address": "/scene/{n}/stop",     "args": "",               "category": "scene",
     "description": "Szene n stoppen.", "example": "/scene/1/stop"},

    # ── Agent Status ──────────────────────────────────────────────────────────
    {"address": "/agent/status",       "args": "",               "category": "agent",
     "description": "Vollständigen Projekt-Status abrufen (Track-Liste, BPM, Playing).",
     "example": "/agent/status"},
    {"address": "/agent/track/count",  "args": "",               "category": "agent",
     "description": "Anzahl und Namen aller Tracks abfragen.",
     "example": "/agent/track/count"},
    {"address": "/agent/effect/count", "args": "",               "category": "agent",
     "description": "Anzahl der Return/Effect-Tracks abfragen.",
     "example": "/agent/effect/count"},
    {"address": "/ping",               "args": "",               "category": "agent",
     "description": "Verbindungstest — Bitwig antwortet mit /pong.", "example": "/ping"},
    {"address": "/agent/ui/response",  "args": "<text:string>",  "category": "agent",
     "description": "Text als Popup-Notification in Bitwig anzeigen.",
     "example": "/agent/ui/response Fertig!"},
]


# ── Ingestion ──────────────────────────────────────────────────────────────────

def run() -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session, is_available

    if not is_available():
        print("Neo4j nicht erreichbar — abgebrochen.")
        sys.exit(1)

    with neo4j_session() as s:
        # 1. Workflow-Nodes aktualisieren
        print("=== Workflow-Nodes aktualisieren ===")
        for w in WORKFLOW_UPDATES:
            osc_json = json.dumps(w["osc_steps"], ensure_ascii=False)
            result = s.run(
                """
                MATCH (w:Workflow {name: $name})
                SET w.steps     = $steps,
                    w.osc_steps = $osc_steps
                RETURN count(w) AS n
                """,
                name=w["name"],
                steps=w["steps"],
                osc_steps=osc_json,
            ).single()
            n = result["n"] if result else 0
            print(f"  {'OK' if n else 'NOT FOUND':8}  {w['name']} ({len(w['osc_steps'])} OSC-Steps)")

        # 2. OscCommand-Nodes erstellen
        print(f"\n=== OscCommand-Nodes ({len(OSC_COMMANDS)} Endpoints) ===")
        for cmd in OSC_COMMANDS:
            s.run(
                """
                MERGE (c:OscCommand {address: $address})
                SET c.args        = $args,
                    c.category    = $category,
                    c.description = $description,
                    c.example     = $example
                """,
                address=cmd["address"],
                args=cmd.get("args", ""),
                category=cmd["category"],
                description=cmd["description"],
                example=cmd.get("example", ""),
            )
        print(f"  {len(OSC_COMMANDS)} OscCommand-Nodes gespeichert.")

    print("\nFertig.")


if __name__ == "__main__":
    run()

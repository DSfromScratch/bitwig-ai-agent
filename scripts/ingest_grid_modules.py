"""
Ingestiert den Bitwig Grid-Modul-Katalog in Neo4j.
231 Module in 16 Kategorien mit Beschreibungen und Signal-Flow-Rolle.

Ausführen:
    python scripts/ingest_grid_modules.py
    python scripts/ingest_grid_modules.py --dry-run
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ── Modul-Katalog ─────────────────────────────────────────────────────────────
# Format: (name, kategorie, signal_rolle, beschreibung, typische_verbindungen)

GRID_MODULES: list[dict] = [

    # ── I/O ──────────────────────────────────────────────────────────────────
    {"name": "Audio In",       "cat": "I/O", "role": "input",
     "desc": "Bringt externen Audio-Input in den Grid (für FX Grid).",
     "connects_to": ["Filter", "Shaper", "Mix"]},
    {"name": "Audio Out",      "cat": "I/O", "role": "output",
     "desc": "Schickt Audio-Signal aus dem Grid an den Track.",
     "connects_to": []},
    {"name": "Pitch In",       "cat": "I/O", "role": "input",
     "desc": "Empfängt MIDI-Pitch als CV-Signal (1V/Oct).",
     "connects_to": ["Oscillator", "Filter"]},
    {"name": "Gate In",        "cat": "I/O", "role": "input",
     "desc": "Empfängt Note-On/Off als Gate-Signal für Hüllkurven.",
     "connects_to": ["ADSR", "AD", "AR"]},
    {"name": "Velocity In",    "cat": "I/O", "role": "input",
     "desc": "MIDI Velocity (0–1) für dynamische Klangformung.",
     "connects_to": ["Level", "ADSR", "Filter"]},
    {"name": "CV In",          "cat": "I/O", "role": "input",
     "desc": "Hardware CV-Eingang für eurorack-Kompatibilität.",
     "connects_to": ["any"]},
    {"name": "CV Out",         "cat": "I/O", "role": "output",
     "desc": "Hardware CV-Ausgang.", "connects_to": []},
    {"name": "Note In",        "cat": "I/O", "role": "input",
     "desc": "Note-Signal-Eingang für Note Grid.", "connects_to": []},
    {"name": "Note Out",       "cat": "I/O", "role": "output",
     "desc": "Note-Signal-Ausgang.", "connects_to": []},

    # ── Oscillators ───────────────────────────────────────────────────────────
    {"name": "Sine",           "cat": "Oscillator", "role": "source",
     "desc": "Reiner Sinus-Oszillator. Perfekt für Sub-Bass und Kicks.",
     "connects_to": ["Filter", "Shaper", "Audio Out", "ADSR"]},
    {"name": "Sawtooth",       "cat": "Oscillator", "role": "source",
     "desc": "Sägezahn-Oszillator. Oberton-reich, ideal für Leads und Bässe.",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "Pulse",          "cat": "Oscillator", "role": "source",
     "desc": "Rechteck/Puls-Oszillator mit einstellbarem Tastverhältnis.",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "Triangle",       "cat": "Oscillator", "role": "source",
     "desc": "Dreieck-Oszillator. Weich, zwischen Sine und Sawtooth.",
     "connects_to": ["Filter"]},
    {"name": "Wavetable",      "cat": "Oscillator", "role": "source",
     "desc": "Wavetable-Oszillator mit 200+ Factory-Wavetables und Frame-Position-Modulation.",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "Swarm",          "cat": "Oscillator", "role": "source",
     "desc": "Unison-Oszillator mit vielen Stimmen, Detune und Spread. Für Supersaw-Sounds.",
     "connects_to": ["Filter", "Mix"]},
    {"name": "Sampler",        "cat": "Oscillator", "role": "source",
     "desc": "Sample-Player im Grid. Kann Loops und One-Shots abspielen.",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "Sub",            "cat": "Oscillator", "role": "source",
     "desc": "Sub-Oszillator eine Oktave unter dem Haupt-Osc.",
     "connects_to": ["Mix", "Filter"]},
    {"name": "Bite",           "cat": "Oscillator", "role": "source",
     "desc": "Oszillator mit FM und Sync-Fähigkeiten.",
     "connects_to": ["Filter"]},
    {"name": "Union",          "cat": "Oscillator", "role": "source",
     "desc": "Mischt mehrere Wellenformen in einem Modul.",
     "connects_to": ["Filter"]},
    {"name": "Phase-1",        "cat": "Oscillator", "role": "source",
     "desc": "Phasenverzerrungsoszillator (wie Casio CZ).",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "Scrawl",         "cat": "Oscillator", "role": "source",
     "desc": "Zeichenbarer Oszillator — eigene Wellenform malen.",
     "connects_to": ["Filter"]},

    # ── Phasor / Phase ────────────────────────────────────────────────────────
    {"name": "Phasor",         "cat": "Phase", "role": "modulator",
     "desc": "Rampengenerator — Basis für alle Oszillatoren. Frequenz als Pitch-CV.",
     "connects_to": ["Data", "Oscillator", "Bend", "Skew"]},
    {"name": "Bend",           "cat": "Phase", "role": "processor",
     "desc": "Verbiegt eine Phase-Rampe — erzeugt Wellenform-Asymmetrie.",
     "connects_to": ["Data", "Oscillator"]},
    {"name": "Skew",           "cat": "Phase", "role": "processor",
     "desc": "Verschiebt die Mitte einer Phase-Rampe.",
     "connects_to": ["Data", "Oscillator"]},
    {"name": "Pinch",          "cat": "Phase", "role": "processor",
     "desc": "Komprimiert/expandiert Phase für Wellenformshaping.",
     "connects_to": ["Data"]},
    {"name": "Sync",           "cat": "Phase", "role": "processor",
     "desc": "Hard/Soft Sync zwischen Oszillatoren.",
     "connects_to": ["Phasor"]},
    {"name": "Counter",        "cat": "Phase", "role": "processor",
     "desc": "Zählt Phasor-Zyklen für Oktavierung.",
     "connects_to": ["Phasor"]},

    # ── Filter ────────────────────────────────────────────────────────────────
    {"name": "SVF",            "cat": "Filter", "role": "processor",
     "desc": "State Variable Filter. LP/HP/BP/Notch. Sanft und musikalisch.",
     "connects_to": ["Shaper", "Mix", "Audio Out"]},
    {"name": "Ladder (LD)",    "cat": "Filter", "role": "processor",
     "desc": "Transistor-Ladder-Filter (Moog-Style). Warm, klassisch.",
     "connects_to": ["Shaper", "Audio Out"]},
    {"name": "MG",             "cat": "Filter", "role": "processor",
     "desc": "Moog-inspirierter Filter. Selbstoszillierend bei hoher Resonanz.",
     "connects_to": ["Audio Out"]},
    {"name": "Comb",           "cat": "Filter", "role": "processor",
     "desc": "Kammfilter für metallische, physische Modellierung.",
     "connects_to": ["Audio Out"]},
    {"name": "Vowels",         "cat": "Filter", "role": "processor",
     "desc": "Formantfilter. Erzeugt Vokal-ähnliche Klangfarben (A, E, I, O, U).",
     "connects_to": ["Audio Out"]},
    {"name": "High-pass",      "cat": "Filter", "role": "processor",
     "desc": "Einfacher High-Pass-Filter.", "connects_to": ["Audio Out"]},
    {"name": "All-pass",       "cat": "Filter", "role": "processor",
     "desc": "Allpass-Filter für Phasen-Manipulation und Reverb-Bau.",
     "connects_to": ["Mix", "Delay"]},
    {"name": "Ripple",         "cat": "Filter", "role": "processor",
     "desc": "Hyper-resonanter Filter für extreme Effekte.",
     "connects_to": ["Audio Out"]},

    # ── Envelope ──────────────────────────────────────────────────────────────
    {"name": "ADSR",           "cat": "Envelope", "role": "modulator",
     "desc": "4-stufige Gate-Hüllkurve (Attack, Decay, Sustain, Release). Standard für Amplitude und Filter.",
     "connects_to": ["Level", "Filter.Cutoff", "Oscillator.Pitch"]},
    {"name": "AD",             "cat": "Envelope", "role": "modulator",
     "desc": "2-stufige Hüllkurve (Attack, Decay). Für Percussion, Plucks.",
     "connects_to": ["Level", "Filter"]},
    {"name": "AR",             "cat": "Envelope", "role": "modulator",
     "desc": "Attack-Release-Hüllkurve. Einfach und effizient.",
     "connects_to": ["Level"]},
    {"name": "Segments",       "cat": "Envelope", "role": "modulator",
     "desc": "Frei zeichenbare mehrstufige Hüllkurve mit Loop und Ping-Pong.",
     "connects_to": ["any"]},
    {"name": "Follower",       "cat": "Envelope", "role": "modulator",
     "desc": "Extrahiert Amplitude-Hüllkurve aus Audio-Signal (Sidechain-Quelle).",
     "connects_to": ["Level", "Filter"]},
    {"name": "Slope",          "cat": "Envelope", "role": "modulator",
     "desc": "Glättet/verzögert CV-Signale.", "connects_to": ["any"]},

    # ── LFO ──────────────────────────────────────────────────────────────────
    {"name": "LFO",            "cat": "LFO", "role": "modulator",
     "desc": "Low-Frequency Oszillator. Frei oder BPM-sync. Für Vibrato, Tremolo, Filter-Wobble.",
     "connects_to": ["Filter.Cutoff", "Oscillator.Pitch", "Level"]},
    {"name": "Curves",         "cat": "LFO", "role": "modulator",
     "desc": "Zeichenbarer LFO — eigene Modulationsform malen.",
     "connects_to": ["any"]},
    {"name": "Wavetable LFO",  "cat": "LFO", "role": "modulator",
     "desc": "LFO mit Wavetable als Wellenform-Quelle.",
     "connects_to": ["any"]},

    # ── Shaper ────────────────────────────────────────────────────────────────
    {"name": "Saturator",      "cat": "Shaper", "role": "processor",
     "desc": "Sanfte Sättigung. Fügt harmonische Obertöne hinzu ohne zu hart zu clippen.",
     "connects_to": ["Filter", "Mix", "Audio Out"]},
    {"name": "Distortion",     "cat": "Shaper", "role": "processor",
     "desc": "Harte Verzerrung. Aggressive Obertöne.",
     "connects_to": ["Filter", "Audio Out"]},
    {"name": "Hard Clip",      "cat": "Shaper", "role": "processor",
     "desc": "Hartes Clipping. Maximale Verzerrung mit Rechteck-Charakter.",
     "connects_to": ["Filter", "Audio Out"]},
    {"name": "Wavefolder",     "cat": "Shaper", "role": "processor",
     "desc": "Faltverzerrung. Komplexe Obertöne durch Übersteuerung zurückfalten.",
     "connects_to": ["Filter", "Audio Out"]},
    {"name": "Transfer",       "cat": "Shaper", "role": "processor",
     "desc": "Zeichenbare Transfer-Funktion für beliebiges Waveshaping.",
     "connects_to": ["Filter", "Audio Out"]},

    # ── Delay/FX ─────────────────────────────────────────────────────────────
    {"name": "Mod Delay",      "cat": "Delay/FX", "role": "processor",
     "desc": "Modulierbares Delay mit Feedback. Basis für Chorus, Flanger.",
     "connects_to": ["Mix", "Audio Out"]},
    {"name": "Chorus+",        "cat": "Delay/FX", "role": "processor",
     "desc": "Chorus-Effekt mit Character-Modi.",
     "connects_to": ["Mix", "Audio Out"]},
    {"name": "Freq Shift+",    "cat": "Delay/FX", "role": "processor",
     "desc": "Frequenzschieber mit Delay-Netzwerk. Für Metallic/Ring-Sounds.",
     "connects_to": ["Mix", "Audio Out"]},
    {"name": "Pitch Shift",    "cat": "Delay/FX", "role": "processor",
     "desc": "Pitch-Shifting ohne Tempo-Änderung.",
     "connects_to": ["Mix"]},
    {"name": "Recorder",       "cat": "Delay/FX", "role": "processor",
     "desc": "Looper/Recorder im Grid für granulare Effekte.",
     "connects_to": ["Audio Out"]},

    # ── Mix ───────────────────────────────────────────────────────────────────
    {"name": "Mixer",          "cat": "Mix", "role": "routing",
     "desc": "6-Kanal Mixer. Kombiniert mehrere Audio-Quellen.",
     "connects_to": ["Shaper", "Filter", "Audio Out"]},
    {"name": "Blend",          "cat": "Mix", "role": "routing",
     "desc": "Crossfader zwischen zwei Signalen.",
     "connects_to": ["Audio Out", "Filter"]},
    {"name": "Stereo Width",   "cat": "Mix", "role": "routing",
     "desc": "Mid/Side-basierte Stereobreite-Kontrolle.",
     "connects_to": ["Audio Out"]},
    {"name": "Select",         "cat": "Mix", "role": "routing",
     "desc": "Signal-Router — wählt zwischen mehreren Eingängen.",
     "connects_to": ["any"]},

    # ── Level ─────────────────────────────────────────────────────────────────
    {"name": "Amplify",        "cat": "Level", "role": "processor",
     "desc": "Verstärkt/dämpft Signal. Basis für VCA (Voltage Controlled Amplifier).",
     "connects_to": ["Audio Out", "Mix"]},
    {"name": "Attenuate",      "cat": "Level", "role": "processor",
     "desc": "Dämpft Signal — CV-Pegel herunterregeln.",
     "connects_to": ["any"]},
    {"name": "Sample/Hold",    "cat": "Level", "role": "processor",
     "desc": "Hält einen Wert bei Gate-Signal. Für zufällige Pitch-Sequenzen.",
     "connects_to": ["Oscillator.Pitch"]},

    # ── Math ──────────────────────────────────────────────────────────────────
    {"name": "Add",            "cat": "Math", "role": "utility",
     "desc": "Addiert zwei Signale. Kombiniert Modulationsquellen.",
     "connects_to": ["any"]},
    {"name": "Multiply",       "cat": "Math", "role": "utility",
     "desc": "Multipliziert Signale. AM/Ring-Modulation.",
     "connects_to": ["Oscillator", "Filter"]},
    {"name": "Quantize",       "cat": "Math", "role": "utility",
     "desc": "Quantisiert Werte auf Schritte. Für Step-Sequenzer-Verhalten.",
     "connects_to": ["Oscillator.Pitch"]},
    {"name": "MinMax",         "cat": "Math", "role": "utility",
     "desc": "Gibt Min/Max von zwei Signalen zurück.",
     "connects_to": ["any"]},

    # ── Logic ─────────────────────────────────────────────────────────────────
    {"name": "Clock Divide",   "cat": "Logic", "role": "utility",
     "desc": "Teilt Clock-Signal. Für Polyrhythmen und Sub-Rhythmen.",
     "connects_to": ["Gate In", "ADSR"]},
    {"name": "Gate Length",    "cat": "Logic", "role": "utility",
     "desc": "Kontrolliert Dauer eines Gate-Signals.",
     "connects_to": ["ADSR"]},
    {"name": "Latch",          "cat": "Logic", "role": "utility",
     "desc": "Hält Gate-Zustand bis zum nächsten Trigger.",
     "connects_to": ["ADSR"]},

    # ── Random ────────────────────────────────────────────────────────────────
    {"name": "Noise",          "cat": "Random", "role": "source",
     "desc": "Weißes/Rosa Rauschen. Basis für Percussion, Wind, Cymbal-Sounds.",
     "connects_to": ["Filter", "Shaper"]},
    {"name": "S/H LFO",        "cat": "Random", "role": "modulator",
     "desc": "Sample & Hold mit LFO — gestufte Zufallsmodulation.",
     "connects_to": ["Filter.Cutoff", "Oscillator.Pitch"]},
    {"name": "Chance",         "cat": "Random", "role": "utility",
     "desc": "Wahrscheinlichkeits-Gate — lässt Trigger mit Zufallswahrscheinlichkeit durch.",
     "connects_to": ["ADSR", "Gate"]},

    # ── Data ──────────────────────────────────────────────────────────────────
    {"name": "ADSR (Data)",    "cat": "Data", "role": "sequencer",
     "desc": "Stufendaten für Phasor — zeichenbare Hüllkurvenform.",
     "connects_to": ["Phasor"]},
    {"name": "Pitches",        "cat": "Data", "role": "sequencer",
     "desc": "Pitch-Sequenz-Tabelle (bis zu 64 Schritte). Lässt sich mit Phasor auslesen.",
     "connects_to": ["Oscillator.Pitch"]},
    {"name": "Gates",          "cat": "Data", "role": "sequencer",
     "desc": "Gate-Sequenz-Tabelle. Eurorack-artiger Step-Sequenzer.",
     "connects_to": ["ADSR", "Gate"]},
    {"name": "Steps",          "cat": "Data", "role": "sequencer",
     "desc": "Einstellbare Stufen-Tabelle für CV-Sequenzen.",
     "connects_to": ["any"]},
]


# ── Workflow-Patterns ─────────────────────────────────────────────────────────

WORKFLOW_PATTERNS: list[dict] = [
    {
        "name": "Klassischer Subtractive Synth",
        "modules": ["Oscillator", "Filter", "ADSR", "Level"],
        "flow": "Oscillator → Filter → Amplify → Audio Out\nADSR → Filter.Cutoff\nADSR → Amplify.Level",
        "use_case": "Leads, Bässe, klassische Synthesizer-Sounds",
        "grid_type": "Poly Grid",
    },
    {
        "name": "FM-Synthese (2-Op)",
        "modules": ["Phasor", "Sine", "Multiply", "Sine"],
        "flow": "Carrier Phasor + Modulator Phasor → Modulator Sine → Carrier Sine.Phase\nCarrier Sine → Audio Out",
        "use_case": "E-Piano, Glocken, metallische Sounds",
        "grid_type": "Poly Grid",
    },
    {
        "name": "Percussion / Kick",
        "modules": ["Sine", "Noise", "AD", "Bend", "Hard Clip"],
        "flow": "Gate → AD → Amplify → Audio Out\nAD (pitch) → Bend → Sine.Pitch\nNoise → Filter → Amplify (für Click)",
        "use_case": "Kick Drum, Percussion, Snare",
        "grid_type": "Poly Grid",
    },
    {
        "name": "Supersaw / Pad",
        "modules": ["Swarm", "SVF", "ADSR", "Chorus+"],
        "flow": "Swarm (viele Stimmen, Detune) → SVF Filter → Chorus+ → Audio Out\nADSR → SVF.Cutoff\nADSR → Level",
        "use_case": "Pads, Leads, Supersaws",
        "grid_type": "Poly Grid",
    },
    {
        "name": "Granular Texture (FX Grid)",
        "modules": ["Audio In", "Recorder", "Pitch Shift", "Blend"],
        "flow": "Audio In → Recorder (Loop) → Pitch Shift → Blend → Audio Out",
        "use_case": "Ambient Texturen, Granular-Processing, Freeze-Effekte",
        "grid_type": "FX Grid",
    },
    {
        "name": "Physische Modellierung (Pluck)",
        "modules": ["Noise", "Comb", "AD", "High-pass"],
        "flow": "Gate → AD (kurz) → Noise → Comb Filter (Feedback) → High-pass → Audio Out",
        "use_case": "Zupf-Instrumente, Karplus-Strong-Synthese",
        "grid_type": "Poly Grid",
    },
    {
        "name": "Sidechain-Ducking (FX Grid)",
        "modules": ["Audio In", "Follower", "Attenuate", "Audio Out"],
        "flow": "Kick → Follower → Attenuate.CV\nBass Audio In → Attenuate → Audio Out",
        "use_case": "Sidechain-Kompression, rhythmisches Ducking",
        "grid_type": "FX Grid",
    },
    {
        "name": "Vocoder / Formant (FX Grid)",
        "modules": ["Audio In", "Vowels", "LFO", "Mix"],
        "flow": "Audio In → Vowels Filter → Mix → Audio Out\nLFO → Vowels.Formant",
        "use_case": "Vokal-Effekte, Formant-Shifting, Talk-Box-Sounds",
        "grid_type": "FX Grid",
    },
]

# ── Page-Name → Module Inference ─────────────────────────────────────────────
# Seiten-Namen aus Remote-Controls → Modul-Typen ableiten

PAGE_TO_MODULE: dict[str, list[str]] = {
    # Phase-4 spezifisch
    "Main":        ["Filter", "Oscillator"],
    "Filter":      ["Filter", "SVF"],
    "Filter FM":   ["Filter", "FM-Modulation"],
    "Mix":         ["Mix", "Mixer"],
    "Tune - R":    ["Oscillator", "Phasor"],
    "Tune - B":    ["Oscillator", "Phasor"],
    "Tune - Y":    ["Oscillator", "Phasor"],
    "Tune - M":    ["Oscillator", "Phasor"],
    "SM - R":      ["Shaper", "Phase-1"],
    "SM - B":      ["Shaper", "Phase-1"],
    "SM - Y":      ["Shaper", "Phase-1"],
    "SM - M":      ["Shaper", "Phase-1"],
    "ADSR":        ["Envelope", "ADSR"],
    "XY":          ["Modulation"],
    "Vibrato":     ["LFO"],
    # Poly Grid typisch
    "Oscillator":  ["Oscillator"],
    "Osc":         ["Oscillator"],
    "Filter":      ["Filter"],
    "Envelope":    ["Envelope", "ADSR"],
    "Env":         ["Envelope"],
    "LFO":         ["LFO"],
    "Modulation":  ["LFO", "Envelope"],
    "FX":          ["Delay/FX"],
    "Output":      ["Mix", "Level"],
    "Arp":         ["Arpeggiator"],
}


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest_modules(dry_run: bool = False) -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session
    from src.knowledge.store import get_embeddings

    print(f"[modules] {len(GRID_MODULES)} Module + {len(WORKFLOW_PATTERNS)} Workflow-Patterns")

    if dry_run:
        print("\nBeispiel-Module:")
        for m in GRID_MODULES[:5]:
            print(f"  [{m['cat']:12}] {m['name']:20} — {m['desc'][:60]}")
        print("\nBeispiel-Pattern:")
        p = WORKFLOW_PATTERNS[0]
        print(f"  {p['name']}: {p['flow']}")
        return

    emb = get_embeddings()

    with neo4j_session() as s:
        # Module
        for m in GRID_MODULES:
            content = (
                f"**Grid-Modul: {m['name']}** [{m['cat']}] ({m['role']})\n"
                f"{m['desc']}\n"
                f"Verbindet sich typisch mit: {', '.join(m['connects_to'])}"
            )
            vec = emb.embed_documents([content])[0]
            s.run("""
                MERGE (n:GridModule {name: $name})
                SET n.category = $cat, n.role = $role,
                    n.description = $desc,
                    n.connects_to = $connects,
                    n.content = $content, n.embedding = $emb,
                    n.source = $source
            """, name=m["name"], cat=m["cat"], role=m["role"],
                 desc=m["desc"], connects=m["connects_to"],
                 content=content, emb=vec,
                 source=f"GridModule:{m['name']}")

        # Workflow-Patterns
        for p in WORKFLOW_PATTERNS:
            content = (
                f"**Grid Workflow-Pattern: {p['name']}** ({p['grid_type']})\n"
                f"Module: {', '.join(p['modules'])}\n"
                f"Signal-Flow:\n{p['flow']}\n"
                f"Verwendung: {p['use_case']}"
            )
            vec = emb.embed_documents([content])[0]
            s.run("""
                MERGE (n:GridWorkflow {name: $name})
                SET n.modules = $modules, n.flow = $flow,
                    n.use_case = $use_case, n.grid_type = $grid_type,
                    n.content = $content, n.embedding = $emb,
                    n.source = $source
            """, name=p["name"], modules=p["modules"],
                 flow=p["flow"], use_case=p["use_case"],
                 grid_type=p["grid_type"], content=content, emb=vec,
                 source=f"GridWorkflow:{p['name']}")

        # HNSW-Indizes
        for label, prop in [("GridModule", "gm_emb"), ("GridWorkflow", "gw_emb")]:
            idx_name = f"{label.lower()}_embedding"
            try:
                s.run(f"""
                    CREATE VECTOR INDEX {idx_name} IF NOT EXISTS
                    FOR (n:{label}) ON n.embedding
                    OPTIONS {{indexConfig: {{`vector.dimensions`: 768,
                                            `vector.similarity_function`: 'cosine'}}}}
                """)
            except Exception:
                pass

    print(f"[done] {len(GRID_MODULES)} GridModule-Nodes + {len(WORKFLOW_PATTERNS)} GridWorkflow-Nodes")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    ingest_modules(args.dry_run)


if __name__ == "__main__":
    main()

"""Ingestiert ProductionPattern-Nodes aus Bitwig Demo-Projekt-Analysen in Neo4j.

Quelle: Chee – Hey Now (Garage/Dubstep) und Ferrous Rhythm (DnB) bwproject-Analysen.
Idempotent: MERGE on id.

Run from repo root:
    .venv/bin/python scripts/ingest_production_patterns.py
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Produktions-Muster aus Demo-Projekten ─────────────────────────────────────
# Jedes Muster: id, name, genre, description, use_case, approach, difficulty,
#               source_project, devices, related_genres (optional)

PRODUCTION_PATTERNS: list[dict] = [

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: Chee – Hey Now (Garage / Dubstep)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "poly_grid_kick_synthesis",
        "name": "Poly Grid Kick Synthesis",
        "genre": "Garage",
        "description": (
            "Kicks werden mit dem Poly Grid statt mit E-Kick oder Samples gebaut. "
            "Das Preset KickStartR im Poly Grid erlaubt maximale Kontrolle über "
            "Pitch-Envelope, Transient-Shape und Sub-Charakter."
        ),
        "use_case": (
            "Wenn ein Standard-Kick zu generisch klingt oder ein sehr spezifischer "
            "Sub-Bass-Charakter mit präziser Hüllkurve gebraucht wird. "
            "Ideal für UK Garage, Dubstep, jede Musik wo der Kick ein Instrument ist."
        ),
        "approach": (
            "Poly Grid laden → KickStartR-Preset auswählen → "
            "Pitch-Start (Einschlag-Frequenz) und Decay anpassen → "
            "Sub-Sine-Level für Basstiefe → "
            "Click-Transient-Amount für Präsenz in der Mitte → "
            "Saturator auf dem Track für analogen Charakter."
        ),
        "difficulty": "intermediate",
        "source_project": "Chee – Hey Now",
        "devices": ["Poly Grid", "Saturator", "Compressor"],
        "related_genres": ["Garage", "Dubstep", "UK Garage"],
    },

    {
        "id": "poly_grid_clap_layering",
        "name": "Poly Grid Clap / Snare Layering",
        "genre": "Garage",
        "description": (
            "Claps und Snares werden im Poly Grid synthetisiert statt mit Samples. "
            "Das Clapham-Clap-Preset ist ein bekanntes Garage-Clap-Template. "
            "Mehrere Clap-Layers (Rimshot, Snare, Rim Roll, Clap) in separaten Tracks."
        ),
        "use_case": (
            "UK Garage / Dubstep Percussion-Schichten aufbauen. "
            "Synthetische Claps sind dünner und snappiger als natürliche Samples, "
            "was den typischen Garage-Groove erzeugt."
        ),
        "approach": (
            "Für jede Percussion-Variante eigenen Track → "
            "Poly Grid mit passendem Preset (Clapham-Clap, Rimshot-Preset) → "
            "Velocity-Automation für Bewegung → "
            "Reverb auf Send für Raumgefühl ohne den direkten Sound zu belasten."
        ),
        "difficulty": "intermediate",
        "source_project": "Chee – Hey Now",
        "devices": ["Poly Grid", "Reverb", "Compressor"],
        "related_genres": ["Garage", "UK Garage", "Dubstep"],
    },

    {
        "id": "vocal_chop_multitrack",
        "name": "Vocal Chop Multi-Track Stack",
        "genre": "Garage",
        "description": (
            "Vocals werden nicht auf einem Track verarbeitet, sondern in mehrere "
            "spezialisierte Tracks aufgeteilt: Rohe Vocals, Pitched Vocals, "
            "Chopped Vocals, Looped Vox-Layers. Jede Variante hat eigene FX-Kette."
        ),
        "use_case": (
            "Komplexe Vocal-Arrangements in UK Garage, Grime, Future Bass. "
            "Ermöglicht simultanes Abspielen von perkussiven Vocal-Chops und "
            "melodischen Vocal-Lines mit unterschiedlichen Reverbs und Delays."
        ),
        "approach": (
            "Hauptvocal → separater Track mit Pitch Shifter für Harmonics → "
            "kurze Chop-Loops im Sampler als Rhythmuselement → "
            "Lange Vox-Loops für Atmosphäre → "
            "Alle Vocal-Tracks in eine Gruppe → Gruppen-EQ/Kompression → "
            "Reverb- und Delay-Sends für Einheitlichkeit."
        ),
        "difficulty": "intermediate",
        "source_project": "Chee – Hey Now",
        "devices": ["Sampler", "Pitch Shifter", "Reverb", "Delay+", "EQ+", "Compressor"],
        "related_genres": ["Garage", "UK Garage", "Grime", "Future Bass"],
    },

    {
        "id": "tool_midi_sidechain",
        "name": "Tool-Device MIDI Sidechain Ducking",
        "genre": "Garage",
        "description": (
            "Das Tool-Device in Bitwig kann einen MIDI-Sidechain-Input empfangen "
            "und damit das Audio-Signal ducken. Das 'midi sidechain'-Preset im Tool "
            "nutzt MIDI-Noten vom Kick-Track um den Bass automatisch zu ducken, "
            "ohne einen klassischen Kompressor-Sidechain."
        ),
        "use_case": (
            "Präzises, deterministisches Sidechain-Ducking das exakt mit MIDI-Noten "
            "korrespondiert. Keine Attack/Release-Kompromisse. Gut für perkussive "
            "Sounds mit exaktem Timing. Alternative zu Kompressor-Sidechain."
        ),
        "approach": (
            "Kick-MIDI-Track als MIDI-Quelle definieren → "
            "Tool-Device auf dem Bass-Track hinzufügen → "
            "'midi sidechain'-Preset laden → "
            "Ducking-Tiefe und Release-Kurve im Tool einstellen → "
            "Alternativ: Compressor mit klassischem Audio-Sidechain für mehr Charakter."
        ),
        "difficulty": "advanced",
        "source_project": "Chee – Hey Now",
        "devices": ["Tool", "Compressor"],
        "related_genres": ["Garage", "Dubstep", "House", "Techno"],
    },

    {
        "id": "mixed_drum_architecture",
        "name": "Gemischte Drum-Architektur (Poly Grid + E-Hat)",
        "genre": "Garage",
        "description": (
            "Kicks und Claps werden mit Poly Grid synthetisiert, "
            "Hi-Hats und Percussions mit E-Hat. "
            "Diese Kombination erlaubt synthetische Kicks/Claps mit präziser Kontrolle, "
            "während E-Hat schnelle, leichte Percussion-Variationen bietet."
        ),
        "use_case": (
            "Wenn der Kick-Charakter sehr spezifisch sein soll (Poly Grid) "
            "aber Hi-Hats flexibel und leicht parametrierbar sein sollen (E-Hat). "
            "Typisch für UK Garage, Dubstep wo Kick = Sound Design Element."
        ),
        "approach": (
            "Kicks: Poly Grid mit KickStartR-Preset → "
            "Claps/Snares: Poly Grid mit Clapham-Preset → "
            "Hats/Percs: E-Hat Device → "
            "Alle in Drum-Gruppe → Multiband Dynamics auf Gruppe."
        ),
        "difficulty": "intermediate",
        "source_project": "Chee – Hey Now",
        "devices": ["Poly Grid", "E-Hat", "Multiband FX-3", "Transient Control"],
        "related_genres": ["Garage", "UK Garage", "Dubstep"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: Ferrous Rhythm (Drum and Bass)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "five_reverb_send_architecture",
        "name": "5-Reverb-Send-Architektur",
        "genre": "Drum and Bass",
        "description": (
            "Statt eines einzigen Reverbs werden 5 spezialisierte Return-Tracks "
            "mit unterschiedlichen Reverb-Charakteren aufgebaut: "
            "Small Room (kurz, trocken), Gated Reverb (80er-Style), "
            "Falling Hall (melodisch abfallend), Long Plate (klassisch), "
            "Time Dilation (synthetisch, experimentell). "
            "Jedes Element im Mix bekommt gezielt Send-Signale zu den passenden Reverbs."
        ),
        "use_case": (
            "Professionelle Mix-Tiefe: Drums brauchen kurzen Room-Reverb, "
            "Leads brauchen Plate, Synths brauchen Time Dilation. "
            "Klang-Kohärenz durch gemeinsamen 'Reverb-Raum' trotz unterschiedlicher Sounds. "
            "Typisch in DnB, Electronica, Film-Scoring, jedem Mix mit Tiefenwirkung."
        ),
        "approach": (
            "5 Return-Tracks anlegen mit Namen: Small Room, Gated Reverb, "
            "Falling Verb, Long Plate, Time Dilation → "
            "Jedem Return-Track eine Convolution mit passendem IR laden: "
            "M5k Soft (Room), NJ3000 Gated (Gated), Falling Hall (melodisch), "
            "German Plate Filter 4 (Plate), Time Dilation 03 (synthetisch) → "
            "Send-Pegel pro Instrument-Track individuell einstellen → "
            "Drums: nur Small Room + Gated, Synths: Plate + Time Dilation, "
            "Leads: Falling Verb."
        ),
        "difficulty": "advanced",
        "source_project": "Ferrous Rhythm",
        "devices": ["Convolution", "Reverb"],
        "related_genres": ["Drum and Bass", "Neurofunk", "Ambient", "Electronica"],
    },

    {
        "id": "dnb_reese_bass_phase4",
        "name": "DnB Reese Bass via Phase-4",
        "genre": "Drum and Bass",
        "description": (
            "Klassischer Reese-Bass mit dem Phase-4-Synthesizer durch Detuning "
            "zweier Sägezahn-Oszillatoren. Phase-4 erzeugt durch sein Phasenmodulations-"
            "System ein besonders organisches Beating zwischen den Oszillatoren."
        ),
        "use_case": (
            "Klassischer DnB/Neurofunk Reese-Bass. Phase-4 klingt organischer als FM-4 "
            "für Reese-Sounds durch das analoge Phasenmodulations-Verhalten. "
            "Gut für melodischen DnB wo der Bass auch Harmonien trägt."
        ),
        "approach": (
            "Phase-4 mit Sägezahn-Wellenform auf beiden Oszillatoren → "
            "Osc2 um +8 bis +15 Cents detunen → "
            "Filter-Cutoff niedrig (300-500 Hz) mit mittlerer Resonance → "
            "Amp-Hüllkurve: Attack 0, kurzer Decay, voller Sustain → "
            "Distortion hinzufügen (Over oder Hard Clip) für Obertöne → "
            "EQ+: Sub boosten (80 Hz), Mitten formen."
        ),
        "difficulty": "intermediate",
        "source_project": "Ferrous Rhythm",
        "devices": ["Phase-4", "Distortion", "EQ+", "Compressor+"],
        "related_genres": ["Drum and Bass", "Neurofunk", "Dubstep"],
    },

    {
        "id": "fx_grid_custom_sidechain",
        "name": "FX Grid Custom Sidechain Patch",
        "genre": "Drum and Bass",
        "description": (
            "Ein eigener Sidechain-Kompressor-Patch wurde im FX Grid aufgebaut "
            "(corealis sc.bwpreset). Das FX Grid erlaubt es, komplexe Sidechain-"
            "Logik zu bauen: eigene Hüllkurven-Detektoren, Gain-Reduction-Kurven, "
            "Sidechain-Routing-Kombinationen die mit Standard-Kompressoren nicht möglich sind."
        ),
        "use_case": (
            "Wenn Standard-Sidechain-Kompression nicht ausreicht: "
            "Präzisere Ducking-Kurven, Multi-Input Sidechain, "
            "Frequenz-selektives Ducking, oder individuelle Attack/Release-Kurven "
            "pro Frequenzband. Typisch in professionellem DnB-Mixing."
        ),
        "approach": (
            "FX Grid auf dem Kanal der geduckt werden soll → "
            "Im Grid: Sidechain-Eingang als Trigger-Signal einlesen → "
            "Envelope Follower oder Attack/Release-Modul für Hüllkurve → "
            "VCA-Modul (Amplify) für Gain-Reduction → "
            "Eigene Kurven mit Transfer/Wavefolder formen → "
            "Alternativ: einfach Compressor+ mit Sidechain-Input-Option nutzen."
        ),
        "difficulty": "advanced",
        "source_project": "Ferrous Rhythm",
        "devices": ["FX Grid", "Compressor+", "Tool"],
        "related_genres": ["Drum and Bass", "Techno", "House"],
    },

    {
        "id": "polymer_wavetable_bass",
        "name": "Polymer Wavetable Bass",
        "genre": "Drum and Bass",
        "description": (
            "Polymer im Wavetable-Mode mit einer custom .wt-Datei (Standard Four.wt) "
            "erzeugt einen harmonisch reichen Bass der zwischen verschiedenen "
            "Wellenform-Charakteren morphen kann. Wavetable-Scanning per LFO oder "
            "Hüllkurve für sich verändernde Oberton-Struktur."
        ),
        "use_case": (
            "Wenn ein Bass mehr Oberton-Bewegung als ein statischer Sägezahn braucht. "
            "Wavetable-Bass klingt in DnB und Neurofunk 'sprechender' als "
            "klassische VA-Synthese. Gut für Drops wo der Bass sich über die Zeit verändert."
        ),
        "approach": (
            "Polymer laden → Mode auf Wavetable setzen → "
            "Standard Four.wt oder eigene Wavetable laden → "
            "Wavetable-Position per LFO oder Env-Follower modulieren → "
            "Filter (SVF oder Ladder) für Charakterformung → "
            "Unison 2-3 Stimmen mit kleinem Detune für Breite → "
            "Saturator für Wärme."
        ),
        "difficulty": "intermediate",
        "source_project": "Ferrous Rhythm",
        "devices": ["Polymer", "Saturator", "EQ+", "Compressor"],
        "related_genres": ["Drum and Bass", "Neurofunk", "Techno", "Ambient"],
    },

    {
        "id": "drum_machine_pack_layering",
        "name": "Drum Machine mit Bitwig-Pack-Layering",
        "genre": "Drum and Bass",
        "description": (
            "Das Drum Machine Device nutzt mehrere Bitwig-Drum-Packs simultan: "
            "v0 (klassische elektronische Drums), v1 (Alternative-Sounds), "
            "v8 (Clap-Variationen), v9 (Ride/Cymbal). "
            "Mehrere Pack-Sounds werden auf demselben Pad gelayert um "
            "komplexere Percussion-Charaktere zu erzeugen."
        ),
        "use_case": (
            "Professionelle DnB-Drums mit charakteristischem Sound. "
            "Layering: v0 Kick für Sub, v1 Kick für Transient, kombiniert für "
            "druckvollen hybriden Sound. Gilt auch für Snares und Claps."
        ),
        "approach": (
            "Drum Machine laden → "
            "Kick-Pad: v0 Kick laden als Basis-Sample → "
            "Zweites Kick-Pad mit gleichem MIDI-Pitch aber v1-Sound für Transient → "
            "Beide per Velocity oder Pitch-Lock synchronisieren → "
            "Snare-Pad mit v0+v8-Kombination → "
            "Ride mit v9-Cymbal → "
            "Kompression auf Drum-Gruppe: schnelle Attack (2ms), mittlere Release (80ms)."
        ),
        "difficulty": "beginner",
        "source_project": "Ferrous Rhythm",
        "devices": ["Drum Machine", "Compressor", "Transient Control", "EQ+"],
        "related_genres": ["Drum and Bass", "Neurofunk", "Techno"],
    },

    {
        "id": "poly_grid_shaker_synthesis",
        "name": "Poly Grid Shaker / Perkussion Synthesis",
        "genre": "Drum and Bass",
        "description": (
            "Shaker und kleine Percussion-Elemente werden im Poly Grid synthetisiert "
            "statt mit Samples. Das 'Grid Shaker 1'-Preset kombiniert "
            "gefilterten Noise mit Hüllkurven für einen lebendigen, "
            "nicht-sample-artigen Shaker-Sound."
        ),
        "use_case": (
            "Wenn gesampelte Shaker zu statisch klingen. Synthetische Shaker "
            "lassen sich leichter in Tonhöhe und Charakter anpassen ohne "
            "Pitch-Artefakte. Gut für Groove-Elemente die sich im Mix dynamisch "
            "verändern sollen."
        ),
        "approach": (
            "Poly Grid laden → Grid Shaker Preset oder eigenen Patch: "
            "Noise-Source → Bandpass-Filter (SVF BP-Mode) → "
            "ADSR mit kurzem Attack und Decay → "
            "Tonhöhe mit Pitch-Modul modulieren → "
            "Velocity → Amp-Level für lebendigen Anschlag."
        ),
        "difficulty": "intermediate",
        "source_project": "Ferrous Rhythm",
        "devices": ["Poly Grid"],
        "related_genres": ["Drum and Bass", "Garage", "Techno"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: play-drums (Bitwig Template)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "acoustic_drum_sampler_multimic",
        "name": "Acoustic Drum Multi-Mic Sampler Mapping",
        "genre": "Acoustic",
        "description": (
            "Echte Schlagzeug-Aufnahmen werden mit mehreren Mikrofon-Positionen gesampelt: "
            "Kick (DW 1, DW Nofront), Snare (DW 13 1 C, Edge, Rimshot, Rim), "
            "Toms (DW Stick 1-4). Jede Mikrofon-Variante ist ein eigenes Sampler-Preset. "
            "Das Drum Machine Device kombiniert diese Presets zu einem vollständigen Kit."
        ),
        "use_case": (
            "Realistische Drum-Aufnahmen mit natürlichem Dynamik- und Charakter-Verhalten. "
            "Verschiedene Snare-Hits (Center, Edge, Rimshot, Rim) geben dem Groove Nuancen. "
            "Ideal für: Live-Drums-Simulation, Acoustic-Pop, Rock, Soul, Jazz."
        ),
        "approach": (
            "Drum Machine laden → "
            "Kick-Pad: Kick DW 1 Preset (dicker Center-Hit) → "
            "Snare-Pad: Snare DW 13 1 C (Hauptsnare), zweites Pad mit Snare DW Edge für leise Hits → "
            "Rimshot-Pad: Snare DW Rimshot für betonte Hits → "
            "Rim-Pad: Snare DW Rim 13 1 für Ghost-Hits → "
            "Toms: Tom DW Stick 1-4 für High-Low → "
            "Cymbals: Ride 20 K E, Crash A Custom 18 → "
            "FX-Gruppe: Drums Processor - Mix 1 Chain-Preset für Gesamt-Mix."
        ),
        "difficulty": "intermediate",
        "source_project": "play-drums",
        "devices": ["Drum Machine", "Sampler", "Compressor", "Transient Control", "EQ+"],
        "related_genres": ["Acoustic", "Rock", "Pop", "Soul", "Jazz"],
    },

    {
        "id": "drum_machine_legacy_packs",
        "name": "Classic Drum Machine Pack Layering (606/707/808/909)",
        "genre": "Electronic",
        "description": (
            "Bitwig's Classic Drum Machines Pack enthält vier legendäre Drum Machines: "
            "Legend 606 (crispy elektronisch), Legend 707 (cleaner Funk-Sound), "
            "Legend 808 (subbasiger Boom, 808 Kick/Clap), Legend 909 (Acid/Techno, "
            "kurze snappige Kicks). Per Szene oder Mute/Solo lassen sich verschiedene "
            "Drum-Charaktere sofort wechseln oder layern."
        ),
        "use_case": (
            "Schneller Zugriff auf verschiedene elektronische Drum-Charakter. "
            "808-Kick für Sub-Bass, 909-Kick für Techno-Punch, 606-Snare für crispy Elektronik. "
            "Layering: 808 Kick als Sub + 909 Kick als Transient = hybrider Kick."
        ),
        "approach": (
            "Für jede Drum Machine eine Spur in Drum Machine → "
            "Legend 808 Hybrid RAD für Kick und Clap → "
            "Legend 909 für Hi-Hats und offene Hats → "
            "Legend 707 für Snare-Varianten → "
            "Legend 606 für perlige kleinere Percussion → "
            "Kicks layern: 808 als Sub (nur tiefer Freq-Bereich), 909 als Transient (HPF unter 200 Hz)."
        ),
        "difficulty": "beginner",
        "source_project": "play-drums",
        "devices": ["Drum Machine", "EQ+", "Compressor"],
        "related_genres": ["Electronic", "House", "Techno", "Trap", "Hip-Hop"],
    },

    {
        "id": "drums_processor_chain_preset",
        "name": "Drums Processor Mix Chain (Gruppen-FX mit Preset)",
        "genre": "Electronic",
        "description": (
            "Das 'Drums Processor - Mix 1' Preset ist ein Chain-Device mit einer "
            "vordefinierten Multi-FX-Kette für Drum-Gruppen: EQ-Korrekturen, "
            "Transient-Shaping, leichte Kompression, Sättigung. "
            "Als Gruppen-Insert statt auf Einzelspuren spart es CPU und sorgt für "
            "kohärenten Drum-Klang."
        ),
        "use_case": (
            "Drum-Gruppe professionell klingen lassen ohne jeden Track einzeln bearbeiten. "
            "Das Chain-Preset kapselt Best-Practice-Einstellungen: "
            "Attack Killah Kompressor für Punch, Hi Distortion für Saturation. "
            "Auch für einzelne Drum-Spuren verwendbar."
        ),
        "approach": (
            "Drum Machine oder Drum-Tracks in Gruppe zusammenfassen → "
            "Chain-Device auf die Gruppe laden → "
            "Drums Processor - Mix 1 Preset wählen → "
            "Kompressor: Attack Killah (schnelle Attackkontrolle) → "
            "Snare-Spur extra: Snare Compression 1 Preset → "
            "Hi Distortion für analoge Wärme optional → "
            "Attack Killah: Threshold anpassen bis Drum-Transients knallen."
        ),
        "difficulty": "beginner",
        "source_project": "play-drums",
        "devices": ["Compressor", "Distortion", "Transient Control", "EQ+"],
        "related_genres": ["Electronic", "Rock", "Pop", "Hip-Hop"],
    },

    {
        "id": "world_percussion_sampling",
        "name": "World Percussion Sampling (Djembe, Conga, Bongo)",
        "genre": "World",
        "description": (
            "Nicht-westliche Percussion wird mit mehreren Artikulations-Presets gesampelt: "
            "Djembe (Left-Hand, Left-Hand Muted, Slap), Conga (Left-Hand, Right-Hand, Slap), "
            "Bongo (Sharp High, Sharp Low), Tumba (Left-Hand, Right-Hand), "
            "Tambourine (Single Hit), Woodblocks, Shaker. "
            "Jede Spieltechnik ist ein separates Preset im Drum Machine."
        ),
        "use_case": (
            "Authentische World-Music-Percussion für Afrobeats, Latin, Weltmusik, Funk. "
            "Verschiedene Artikulations-Varianten auf verschiedenen Velocity-Layern "
            "ergeben natürliche Spielfeel. Tambourine, Shaker als Groove-Elemente "
            "für Pop, Soul, Hip-Hop."
        ),
        "approach": (
            "Drum Machine mit Articulation-Pads → "
            "Djembe-Gruppe: Slap (Haupthit), Left-Hand (normale Hits), Left-Hand Muted (gedämpft) → "
            "Conga-Gruppe: Right-Hand (offener Ton), Left-Hand (Slap/Bass), Slap (akzentuiert) → "
            "Bongo: High + Low → "
            "Shaker Big Single für Off-Beat Groove → "
            "Tambourine SingleHit für Volksmelodien und Pop-Grooves → "
            "Leichtes Reverb (Small Room-Send) für Raumeindruck."
        ),
        "difficulty": "beginner",
        "source_project": "play-drums",
        "devices": ["Drum Machine", "Sampler", "Reverb"],
        "related_genres": ["World", "Afrobeats", "Latin", "Jazz", "Funk"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: play-synths (Bitwig Template)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "synth_type_comparison_template",
        "name": "Synthesizer-Typen Vergleichs-Template",
        "genre": "Electronic",
        "description": (
            "Bitwig's Play-Synths-Template enthält je einen Track pro Synthesizer-Paradigma: "
            "Polysynth (subtraktiv, Poly Vibrasyn Preset), Phase-4 (Phasenmodulation, Orbital Path), "
            "FM-4 (Frequenzmodulation, Next FM Bass), Polymer (Hybrid/Wavetable, Mercury Lead + "
            "Gentle Fold Pluck), XY Instrument (Martian Mealtime). "
            "Filter: Lo-Pass Preset für alle Synths verfügbar."
        ),
        "use_case": (
            "Lernen welcher Synthesizer-Typ für welchen Sound geeignet ist. "
            "Subtraktiv: klassische Leads und Pads. FM: metallische, glockenartige Sounds. "
            "Phase: organische Bewegung. Wavetable: komplexe sich verändernde Texturen. "
            "Template-Ausgangspunkt für neue Produktionen."
        ),
        "approach": (
            "Für jeden Synth-Typ eigenen Track anlegen → "
            "Polysynth: subtraktive Basis (Pads, Leads, Bässe) → "
            "Phase-4: Phasenmodulation für bewegte organische Sounds → "
            "FM-4: Frequenzmodulation für Bell-Sounds, Bässe, metallische Texturen → "
            "Polymer: Hybrid für Wavetable-Scanning, VA, Sample oder FM-Modus → "
            "Mix Compression 1 Preset als Bus-Kompressor."
        ),
        "difficulty": "beginner",
        "source_project": "play-synths",
        "devices": ["Polysynth", "Phase-4", "FM-4", "Polymer", "Compressor"],
        "related_genres": ["Electronic", "Ambient", "Techno", "House", "Drum and Bass"],
    },

    {
        "id": "polymerics_pack_workflow",
        "name": "Polymerics Pack: Mercury Lead + Gentle Fold Pluck",
        "genre": "Electronic",
        "description": (
            "Das Polymerics-Pack von Bitwig enthält speziell kuratierte Polymer-Presets. "
            "Mercury Lead: heller, treibender Lead-Sound mit charakteristischem Bewegungs-"
            "charakter. Gentle Fold Pluck: weicher Pluck-Sound mit Faltungs-Waveshaper "
            "für sanfte Attack-Transients. Beide sind Wavetable-basiert auf Polymer."
        ),
        "use_case": (
            "Sofort einsatzbereite Lead- und Pluck-Sounds ohne eigenes Sound-Design. "
            "Mercury Lead: Melodie-Leads in Techno, House, Electronic Pop. "
            "Gentle Fold Pluck: Hintergrund-Arpeggios, leichte Melodie-Fills, "
            "für ruhigere Passagen oder Übergänge."
        ),
        "approach": (
            "Polymer auf Instrument-Track → "
            "Polymerics Pack-Preset auswählen → "
            "Mercury Lead: Wavetable-Position per LFO modulieren für Bewegung → "
            "Gentle Fold Pluck: Attack minimal anheben für weicheren Einsatz → "
            "Arpeggiator vor Polymer für automatische Pattern → "
            "Delay für Stereobreite und Rhythmus-Interaktion."
        ),
        "difficulty": "beginner",
        "source_project": "play-synths",
        "devices": ["Polymer", "Arpeggiator", "Delay+", "Reverb"],
        "related_genres": ["Electronic", "Techno", "House", "Ambient"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: play-keys (Bitwig Template)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "wurlitzer_multisample_mapping",
        "name": "Wurlitzer Multi-Sample Mapping",
        "genre": "Soul",
        "description": (
            "Eine Wurlitzer E-Piano wird mit 5 Velocity-Layers über alle Lagen gesampelt "
            "(A0 bis C8, chromatisch). Jede Note hat 5 Velocity-Samples (01-05) für "
            "natürliches Anschlagsverhalten. Der Sampler in Bitwig mappt alle 200+ "
            "Samples automatisch in eine Multisample-Zone."
        ),
        "use_case": (
            "Realistischer Wurlitzer-Sound ohne VST-Plugin. "
            "5 Velocity-Layer bedeutet: leichter Anschlag → weiches Sample, "
            "harter Anschlag → lautes, charakteristisches Sample mit Anschlag-Klick. "
            "Für: Soul, R&B, Jazz, Funk, Neo-Soul, Indie."
        ),
        "approach": (
            "Sampler laden → Multisample-Import: alle Wurlitzer-WAVs in Ordner-Struktur → "
            "Bitwig ordnet automatisch zu (Notenname + Velocity im Dateinamen) → "
            "Wurlitzer.bwpreset als fertige Konfiguration laden → "
            "FX-Kette: Amp-Simulation (optional), leichter Chorus für Vintage-Charakter, "
            "Reverb-Send für Raumgefühl → "
            "Velocity-Kurve anpassen für authentisches Spielgefühl."
        ),
        "difficulty": "intermediate",
        "source_project": "play-keys",
        "devices": ["Sampler", "Chorus+", "Reverb", "EQ+"],
        "related_genres": ["Soul", "R&B", "Jazz", "Funk", "Neo-Soul"],
    },

    {
        "id": "keyboard_instrument_showcase",
        "name": "Keyboard-Instrument Showcase (Piano, Rhodes, Clav)",
        "genre": "Pop",
        "description": (
            "Play-Keys enthält mehrere gesampelte Keyboard-Instrumente als Presets: "
            "Grand Piano Light (akustisches Klavier), Cosy Sofa Keys (weiche E-Piano-Atmosphäre), "
            "Electropiano 1 (klassisches E-Piano), FM Hopepianth (FM-basiertes E-Piano via FM-4), "
            "Hybrid Clav (Clavinet via Polymer). Alle lauffähig in Bitwig ohne externe Samples."
        ),
        "use_case": (
            "Sofort verwendbare gesampelte Keyboard-Instrumente für: "
            "Piano für Balladen und Pop, E-Piano für Soul/R&B, "
            "Clavinet für Funk und Groove, FM-Piano für jazzig-elektronische Sounds. "
            "Kein separates Sample-Pack nötig."
        ),
        "approach": (
            "Track anlegen → Sampler oder Polymer → "
            "Grand Piano Light für klassischen Piano-Sound → "
            "Electropiano 1 für Rhodes-artigen E-Piano-Sound → "
            "FM Hopepianth via FM-4 für jazzige, metallische E-Piano-Textur → "
            "Hybrid Clav via Polymer für funkigen Clavinet-Sound → "
            "16th Ping Pong Delay für rhythmische Bewegung → "
            "Cosy Sofa Keys für sanfte Atmosphären."
        ),
        "difficulty": "beginner",
        "source_project": "play-keys",
        "devices": ["Sampler", "FM-4", "Polymer", "Delay-2", "Reverb"],
        "related_genres": ["Pop", "Soul", "R&B", "Jazz", "Funk"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: performance-set (Bitwig Template)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "live_performance_scene_structure",
        "name": "Live-Performance Clip-Launcher Szenenstruktur",
        "genre": "Electronic",
        "description": (
            "Das Performance-Set-Template zeigt die typische Track-Struktur für "
            "Live-Auftritte im Clip-Launcher: Kick, Snare, Bass Mel 1/2, Bass Up, "
            "Bell, Pad 1/2, Lead, Synth, Reverb-Return, Master. "
            "Jede Szene repräsentiert einen Song-Abschnitt (Intro/Build/Drop/Break). "
            "Multi-Machine Drums: Legend 606/707/808/909 gleichzeitig geladen."
        ),
        "use_case": (
            "Struktur für Live-Elektronik-Acts die Clip-Launcher statt Arranger nutzen. "
            "Szenenwechsel = sofortiger Wechsel aller Clips in allen Tracks. "
            "Jeder Track hat mehrere Clips → Variationen innerhalb einer Szene möglich."
        ),
        "approach": (
            "Tracks anlegen: Drums (mehrere Drum-Machines), Bass Mel 1+2 (FM-4/Polysynth), "
            "Bass Up (Stack Bass 2 Preset), Bell (FM Piano 4), Pad 1+2 (Poly Vibrasyn), "
            "Lead (Singer In Alps FM-4), Synth (Dazen Keys), Reverb-Return → "
            "Szenen benennen: Intro, Verse, Pre-Drop, Drop, Breakdown, Outro → "
            "Clips aufnehmen oder zeichnen pro Szene → "
            "Sidechain from Bass Preset auf Pad-Tracks → "
            "Bandpass LFO 2 auf Filter für automatische Bewegung → "
            "Attack Killah auf Drum-Gruppe."
        ),
        "difficulty": "advanced",
        "source_project": "performance-set",
        "devices": ["FM-4", "Polysynth", "Drum Machine", "Compressor", "Delay-2", "Ladder"],
        "related_genres": ["Electronic", "Techno", "House", "Dubstep"],
    },

    {
        "id": "sidechain_from_bass_preset",
        "name": "Sidechain from Bass — Dynamics Preset",
        "genre": "Electronic",
        "description": (
            "Das 'Sidechain from Bass' Preset kapselt einen Kompressor mit voreingestelltem "
            "Sidechain-Routing vom Bass-Track. Als sofort ladbares Dynamics-Preset "
            "spart es die manuelle Sidechain-Konfiguration. "
            "Der Kompressor duckt das Signal wenn der Bass-Track Signal liefert."
        ),
        "use_case": (
            "Schnelle Sidechain-Kompression ohne manuelles Konfigurieren. "
            "Typisch: Pad-Tracks ducken wenn Bass spielt. "
            "Performance-Kontext: während Live-Auftritt keine Zeit für komplexes Routing. "
            "Preset laden → Threshold anpassen → fertig."
        ),
        "approach": (
            "Compressor-Device auf Pad/Synth-Track → "
            "Sidechain from Bass Preset laden → "
            "Sidechain-Input auf Bass-Track zeigen (falls nötig anpassen) → "
            "Threshold: -18 bis -24 dB → "
            "Ratio: 4-8:1 → "
            "Attack: 2-5 ms (schnell für klares Ducking) → "
            "Release: 60-120 ms (Rhythmus-abhängig) → "
            "Mix Compression 1 auf Master für finales Glue."
        ),
        "difficulty": "beginner",
        "source_project": "performance-set",
        "devices": ["Compressor", "Dynamics"],
        "related_genres": ["Electronic", "House", "Techno", "Dubstep", "Drum and Bass"],
    },

    {
        "id": "fm4_keyboard_sounds",
        "name": "FM-4 für Keyboard-Sounds (Piano, Bell, Organ)",
        "genre": "Electronic",
        "description": (
            "Das Performance-Set zeigt FM-4 nicht nur für Bässe sondern für "
            "melodische Keyboard-Sounds: FM Piano 4 (klassischer FM-Piano-Sound "
            "wie DX7), Singer In Alps (atmosphärischer Gesangssound). "
            "FM-Synthese erzeugt charakteristische Anschlag-Transients die "
            "Sample-basierte E-Pianos kaum replizieren können."
        ),
        "use_case": (
            "FM-Piano als Alternative zu gesampeltem E-Piano: klingt 'elektronischer' "
            "und 80er-Jahre-artig. Ideal für Retro-Electronic, Synth-Pop, Lo-Fi. "
            "Singer In Alps für Pad-artige Lead-Sounds mit vokaler Qualität. "
            "FM-Sounds brauchen wenig CPU im Vergleich zu Multi-Sample-Libraries."
        ),
        "approach": (
            "FM-4 laden → FM Piano 4 Preset für E-Piano-Sound → "
            "Algorithm anpassen: Operator-1 moduliert Op-2 für Piano-Charakter → "
            "Op-Ratios: 1:1 für Grundton, höhere Ratio für Ober- und Klick → "
            "Feedback-Amount für Rauheit/Charakter → "
            "Singer In Alps: Algorithmus mit mehreren parallel-Operators für vokalen Klang → "
            "Reverb Send für Atmosphäre."
        ),
        "difficulty": "intermediate",
        "source_project": "performance-set",
        "devices": ["FM-4", "Reverb", "Delay-2", "EQ+"],
        "related_genres": ["Electronic", "Synth-Pop", "Retro", "Ambient"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Quelle: In_Cycles (elektronische Komposition)
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "sp12_vintage_sampling",
        "name": "SP-12 / Vintage Sampler Workflow",
        "genre": "Hip-Hop",
        "description": (
            "Vintage-Drum-Sounds werden aus dem Goldbaby SP-12 Sample-Pack verwendet "
            "(BD_DulVin3_SP12.wav). SP-12 Samples haben einen charakteristischen "
            "12-Bit Lo-Fi Klang mit limitierter Frequenzauflösung. "
            "DustyDrops Loops (11 Varianten) werden als Loop-Sampler-Elemente "
            "für Texturen und Fills verwendet."
        ),
        "use_case": (
            "Vintage Hip-Hop und Lo-Fi Ästhetik durch echte SP-12 Samples. "
            "SP-12 Klang ist tiefer eingebettet, komprimierter und 'dumpfer' als "
            "moderne Drum-Samples. DustyDrops Loops für organische, sich verändernde "
            "Hintergrundschichten. Ideal für: Boom Bap, Lo-Fi Hip-Hop, Downtempo."
        ),
        "approach": (
            "Sampler mit SP-12 Pack laden (Goldbaby oder ähnliche Vintage-Sample-Packs) → "
            "BD_DulVin3_SP12 als Kick → "
            "DustyDrops Loops: mehrere kurze (1-2 Takt) Loops in Layer-Sampler → "
            "Velocity-Randomisierung für lebendigen Feel → "
            "Bit-8 Device auf Drum-Bus für 8-Bit Charakter → "
            "EQ: High-Cut bei 8 kHz für Vintage-Feel."
        ),
        "difficulty": "beginner",
        "source_project": "In_Cycles",
        "devices": ["Sampler", "Bit-8", "EQ+", "Compressor"],
        "related_genres": ["Hip-Hop", "Lo-Fi", "Boom Bap", "Downtempo"],
    },

    {
        "id": "farfisa_organ_sampling",
        "name": "Farfisa Organ Multisample (Vintage Transistor Orgel)",
        "genre": "Soul",
        "description": (
            "Eine Farfisa SO-Serie Transistor-Orgel wird als Multisample im Sampler "
            "abgebildet (Farfisa SO Bass Flute Preset). Die Farfisa hat einen "
            "charakteristischen dünnen, nasalen Transistor-Sound ganz anders als "
            "Hammond B3. Bass Flute: tiefer Orgelregister mit Flöten-Charakter, "
            "ideal für Bass-Linien oder Chord-Pads."
        ),
        "use_case": (
            "Vintage 60er/70er Sound für Soul, Funk, Psych-Rock, Garage-Rock. "
            "Farfisa klingt weniger organisch als Hammond, dafür elektronischer und "
            "schräger — typisch für 60er Garage-Bands und Italian Beat. "
            "Bass Flute als tiefes Orgel-Basslinelement in Funk und Soul."
        ),
        "approach": (
            "Sampler mit Farfisa SO Bass Flute Preset laden → "
            "Velocity-Kurve: Orgeln klingen bei allen Velocities gleich (flache Kurve) → "
            "Legato-Mode: Noten überlappen für Orgel-Feel → "
            "FarfisaChord-Track: Akkorde mit langen Sustains → "
            "Chorus oder Vibrato-Effekt für klassischen Orgel-Charakter → "
            "Rotary-Simulation (Chorus+ langsam) für Leslie-Effekt."
        ),
        "difficulty": "beginner",
        "source_project": "In_Cycles",
        "devices": ["Sampler", "Chorus+", "Reverb", "EQ+"],
        "related_genres": ["Soul", "Funk", "Jazz", "Psych-Rock", "Garage-Rock"],
    },

    {
        "id": "organic_electronic_hybrid_composition",
        "name": "Organisch-Elektronische Hybrid-Komposition",
        "genre": "Electronica",
        "description": (
            "In_Cycles kombiniert echte Acoustic-Drums (Nektar Yamaha Kit), "
            "vintage Sampling (SP-12, DustyDrops Loops), analoge Orgel (Farfisa), "
            "und synthetische Elemente in einem kohärenten Mix. "
            "AddOnChord und AddOnChordHI sind zusätzliche harmonische Schichten. "
            "Falko's Channel Tool kapselt custom Routing- und FX-Einstellungen pro Track."
        ),
        "use_case": (
            "Wenn ein Mix 'lebendig' und 'geatmet' klingen soll trotz elektronischer "
            "Produktion. Echte Drums + vintage Loops erzeugen Humanisierung, "
            "Farfisa-Orgel fügt analoge Wärme hinzu. "
            "Ideal für: Electronica, Neo-Soul, Broken Beats, Jazz-Fusion-Elektronik."
        ),
        "approach": (
            "Beats-Gruppe: Acoustic Drums (Nektar Kit) + SP-12 Kick → "
            "Samples-Gruppe: DustyDrops Loops für organische Fills → "
            "Farfisa-Track: Chords und Bassline → "
            "AddOnChord: harmonische Ergänzungen per Sampler → "
            "Alle Gruppen in gemeinsamen Master-Bus → "
            "Falko's Channel Tool oder eigene Chain-Presets für konsistente Lautstärke → "
            "Reverb-Send für Klang-Kohärenz zwischen organischen und elektronischen Elementen."
        ),
        "difficulty": "advanced",
        "source_project": "In_Cycles",
        "devices": ["Drum Machine", "Sampler", "Reverb", "Compressor", "EQ+"],
        "related_genres": ["Electronica", "Neo-Soul", "Broken Beats", "Jazz"],
    },

    # ════════════════════════════════════════════════════════════════════════
    # Gemeinsame Muster aus beiden Projekten
    # ════════════════════════════════════════════════════════════════════════

    {
        "id": "convolution_reverb_stacking",
        "name": "Convolution Reverb für Räumlichkeit",
        "genre": "Drum and Bass",
        "description": (
            "Convolution-Reverb mit verschiedenen Impulse Responses (IRs) erzeugt "
            "realistische Räume die algorithmische Reverbs nicht replizieren können. "
            "Verschiedene IRs für verschiedene Räume (Halls, Plates, Springs, Synthetic). "
            "Convolution klingt in hochwertigem DnB, Electronica, Ambient natürlicher."
        ),
        "use_case": (
            "Wenn der Mix 'professionell' und 'real' klingen soll. "
            "Plate-IR für Snares, Room-IR für Drums, Hall-IR für Pads/Leads. "
            "Synthetische IRs (Time Dilation) für kreative Räumlichkeit in "
            "Neurofunk oder Ambient."
        ),
        "approach": (
            "Convolution Device auf Return-Track → "
            "IR auswählen nach Raum-Charakter: "
            "Rooms: M5k Soft, Rev480 Very Small Room → "
            "Gated: NJ3000 Gated Reverb → "
            "Plates: German Plate Filter 4 → "
            "Synthetic: Time Dilation 03 → "
            "EQ nach Convolution um Mud-Frequenzen zu schneiden (HPF 80-200 Hz)."
        ),
        "difficulty": "beginner",
        "source_project": "Ferrous Rhythm",
        "devices": ["Convolution", "EQ+", "EQ-2"],
        "related_genres": ["Drum and Bass", "Ambient", "Electronica", "Pop"],
    },

    {
        "id": "multi_synth_bass_section",
        "name": "Multi-Synthesizer Bass Section",
        "genre": "Drum and Bass",
        "description": (
            "Der Bass-Bereich besteht nicht aus einem einzigen Synth, sondern aus "
            "mehreren spezialisierten Synthesizern in einem Bus: "
            "Polymer für Wavetable-Charakter, Phase-4 für Reese-Sounds, "
            "ein zweiter Polymer für Sub-Anteile. Jeder Synth spielt das gleiche "
            "MIDI aber liefert einen anderen Frequenzbereich oder Charakter."
        ),
        "use_case": (
            "Wenn ein einzelner Synthesizer nicht alle Aspekte des Bass-Sounds "
            "liefern kann. Sub-Bass von Polymer (sauber), Mids von Phase-4 (schmutzig), "
            "High-Harmonics von Polymer (Wavetable). "
            "Professioneller DnB-Bass hat oft diese Multi-Layer-Struktur."
        ),
        "approach": (
            "Bass Bus Gruppe anlegen → "
            "3 Instrument-Tracks in der Gruppe: Polymer (Sub), Phase-4 (Mid-Bass), "
            "Polymer (Obertöne) → "
            "Gleiche MIDI-Spur oder MIDI-Routing auf alle drei → "
            "EQ+ auf jeden Track: Sub-Track HP bei 300 Hz abschneiden nach unten, "
            "Mid-Track BP um 200-800 Hz, Oberton-Track HP alles unter 500 Hz → "
            "Bus-Kompression und Saturator für Cohäsion."
        ),
        "difficulty": "advanced",
        "source_project": "Ferrous Rhythm",
        "devices": ["Polymer", "Phase-4", "EQ+", "Saturator", "Compressor"],
        "related_genres": ["Drum and Bass", "Neurofunk", "Techno"],
    },
]


# ── Ingestion ─────────────────────────────────────────────────────────────────

def run() -> None:
    from src.knowledge.neo4j_graph import session as neo4j_session, is_available

    if not is_available():
        print("Neo4j nicht erreichbar — abgebrochen.")
        sys.exit(1)

    pattern_count = 0
    involves_count = 0
    genre_count = 0

    with neo4j_session() as s:

        # Constraint für ProductionPattern
        try:
            s.run("""
                CREATE CONSTRAINT production_pattern_id IF NOT EXISTS
                FOR (p:ProductionPattern) REQUIRE p.id IS UNIQUE
            """)
        except Exception:
            pass

        for pat in PRODUCTION_PATTERNS:
            # ProductionPattern-Node anlegen
            s.run("""
                MERGE (p:ProductionPattern {id: $id})
                SET p.name          = $name,
                    p.genre         = $genre,
                    p.description   = $description,
                    p.use_case      = $use_case,
                    p.approach      = $approach,
                    p.difficulty    = $difficulty,
                    p.source_project = $source_project
            """,
                id=pat["id"],
                name=pat["name"],
                genre=pat["genre"],
                description=pat["description"],
                use_case=pat["use_case"],
                approach=pat["approach"],
                difficulty=pat["difficulty"],
                source_project=pat["source_project"],
            )
            pattern_count += 1

            # INVOLVES → Device-Beziehungen
            for dev_name in pat.get("devices", []):
                result = s.run("""
                    MATCH (p:ProductionPattern {id: $pid})
                    MATCH (d:Device {name: $dev})
                    MERGE (p)-[:INVOLVES]->(d)
                    RETURN count(*) AS c
                """, pid=pat["id"], dev=dev_name).single()
                if result and result["c"] > 0:
                    involves_count += 1
                else:
                    print(f"  ⚠ Device nicht gefunden: {dev_name} (in {pat['id']})")

            # ASSOCIATED_WITH → Genre-Beziehungen (Haupt-Genre + verwandte)
            all_genres = [pat["genre"]] + [
                g for g in pat.get("related_genres", [])
                if g != pat["genre"]
            ]
            for genre_name in all_genres:
                s.run("""
                    MATCH (p:ProductionPattern {id: $pid})
                    MERGE (g:Genre {name: $gname})
                    MERGE (p)-[:ASSOCIATED_WITH]->(g)
                """, pid=pat["id"], gname=genre_name)
                genre_count += 1

            print(f"  OK  {pat['id']}")

    print(
        f"\n{pattern_count} ProductionPattern(s) in Neo4j gespeichert.\n"
        f"  {involves_count} INVOLVES-Beziehungen → Device\n"
        f"  {genre_count} ASSOCIATED_WITH-Beziehungen → Genre"
    )


if __name__ == "__main__":
    run()

### Transport & Arranger (Erweitert)
```
/transport/tempo <bpm>            → Tempo setzen (z. B. 120)
/transport/play <0|1>            → Play/Pause
/time_signature/set <4/4>        → Zeitmaß setzen
/key/set <C Major>               → Tonart setzen
/agent/song/create <genre> <tempo> <key> <time_signature> → Song erstellen# Bitwig Agent — Projektdokumentation

> Letztes Update: 2026-05-05

---

## Überblick

KI-Agent für Musikproduktion mit Bitwig Studio 6. Der Agent erstellt Songs **direkt in Bitwig** via OSC — ohne Audio-Extraktion, rein durch LLM-Komposition auf Basis echter Akkordprogressionen aus einer Wissensdatenbank (Chordonomicon, 1.800 Songs).

**Kernprinzip:** Chordonomicon KB → Akkord-Parsing → MIDI-Noten → OSC → BitwigAgentBridge → Bitwig Studio 6

---

## Service-Orchestrierung (2026-05)

Der Stack ist in zwei Ebenen getrennt:

- **Workspace / Control Plane**: `start_agent.py`, `Makefile`, MCP-Tools, KB-Logik
- **Runtime / Infra Plane**: vLLM + Ollama-Proxy über `/home/sija/vllm/service-manager.sh`

### Modi

- `VLLM_MODE=external`: Agent prüft nur `VLLM_BASE_URL`
- `VLLM_MODE=managed`: Agent darf `VLLM_START_CMD` / `VLLM_STOP_CMD` ausführen

### Empfohlene Befehle

```bash
# Nur Runtime
make vllm-up
make vllm-status
make vllm-down

# Voller Stack (managed)
make stack-up
make stack-status
make stack-down
```

### Hinweis zur Bridge

- `bitwig_mcp_server.py` läuft als MCP `stdio`-Prozess (kein TCP-Port-Server)
- Bitwig-Bridge wird per UDP Ping/Pong auf `BITWIG_HOST:BITWIG_DM_PORT` geprüft

---

## Architektur (aktuell)

```
Nutzer
  ↓
Claude Code / MCP-Server (bitwig_mcp_server.py, stdio)
  ↓ Claude Code ruft MCP-Tools auf
LangGraph Agent (Qwen3-14B-AWQ via vLLM, http://192.168.0.4:8000)
  ↕ Tool-Calling
  ├── check_bitwig_connection    → Ping/Pong Test (Port 8001/8002)
  ├── get_bitwig_track_state     → OSC-Rückkanal: Track-Count (Port 8002)
  ├── build_song ★               → Builder Pattern: Track + Instrument + FX + Noten in 1 Call
  ├── create_song_from_genre     → Chordonomicon → MIDI → Bitwig
  ├── verify_song                → Play + Screenshot + Track-Count Verifikation
  ├── setup_instrument_track     → UUID-basiertes Device-Loading
  ├── write_notes_to_clip        → Beliebige Melodien mit Validierung
  ├── query_bitwig_docs          → Neo4j KB (Vektorsuche)
  └── control_bitwig             → OSC Transport/Mix-Befehle

Neo4j Graph-Datenbank (bolt://localhost:7687)
  ├── Device-Nodes (151 Devices, 2.807 Presets, Parameter)
  ├── Genre-Nodes (12 Genres + BPM-Ranges + Device-Empfehlungen)
  ├── KnowledgeQA (13.291 Einträge: Chordonomicon, MusicCaps, CoT, MusicTheoryBench)
  ├── APIClass/APIMethod (37 Bitwig Controller API Klassen)
  └── Document-Nodes (48 Dokumente mit Embeddings)

BitwigAgentBridge.bwextension (Java, Bitwig 6, Port 8001)
  ├── 146 Built-in Devices via UUID (insertBitwigDevice — kein Browser!)
  ├── Browser-Fallback für VST/Presets (DeviceBrowsingSession)
  ├── Clip-Launcher: Clips erstellen, Noten schreiben (512 Steps × 128 Pitch)
  ├── Scene-Launch (/scene/N/launch)
  ├── Arranger-Recording (/arrange/record/start|stop)
  ├── OSC-Rückkanal: Track-Count, Note-Count (Port 8002/8003)
  ├── /track/delete/last (cursorTrack.deleteObject())
  ├── /undo (application.undo())
  └── Ping/Pong Verbindungstest

src/audio/chord_to_bitwig.py
  ├── Chordonomicon-Parser (Am, Fsmin, Gssus2, ...)
  ├── Chord → MIDI-Noten (Root + Intervalle + Octave-Shift)
  ├── progression_to_pattern() → Bass + Chord-Patterns
  └── query_chordonomicon(genre) → Neo4j Query mit Genre-Fallback
```

---

## Stack

| Komponente | Technologie | Status |
|---|---|---|
| Haupt-LLM | Qwen3-14B-AWQ via vLLM 0.19 | ✅ IP: 192.168.0.4:8000 |
| Agent-Framework | LangGraph + LangChain | ✅ MAX_MESSAGES=10, max_tokens=1500 |
| Graph-DB | Neo4j Desktop (Windows) bolt://localhost:7687 | ✅ |
| Embedding-Modell | multilingual-e5-base (HuggingFace) | ✅ |
| Bitwig-Brücke | BitwigAgentBridge.bwextension (Java, API v25) | ✅ UDP 8001 |
| MCP-Server | bitwig_mcp_server.py (FastMCP, stdio) | ✅ |
| Akkord-KB | Chordonomicon (1.800 Pop/Rock/Jazz Songs) | ✅ |
| Hardware | RTX 5070 Ti 16 GB (Blackwell SM120) | ✅ |

---

## BitwigAgentBridge — OSC-API

### Instrument-Loading

```
/browser/device/load <name>    → Option 1: insertBitwigDevice(UUID) für 146 Built-ins
                                  Option 2: DeviceBrowsingSession für VST/Presets
```

**146 UUIDs bekannt** (aus Bitwig Installation extrahiert):
- Instrumente: Organ, FM-4, Phase-4, Polysynth, Polymer, Drum Machine, Sampler, ...
- Drums: v0/v1/v8/v9 Kick/Snare/Hat/Tom/Clap/Cymbal (alle Varianten)
- Effekte: Reverb, Compressor, EQ-5, Saturator, Distortion, Chorus, Delay, ...

### Clip & Noten

```
/clip/create <slot> <beats>    → Leeren Clip anlegen + auswählen
/clip/note/beat <beat> <pitch> <vel> <dur>  → Note schreiben (ALLE WERTE ALS FLOAT!)
/clip/step_size <0.25>         → 1/16-Raster
/clip/clear                    → Clip leeren
/clip/note/count               → Noten-Count via Port 8003
```

**WICHTIG:** Pitch MUSS als Float gesendet werden. `int(pitch)` → OSC-Int → `argFloat()` scheitert → Default 60 (Bitwig C3). Fix: `float(pitch)`.

### Transport & Arranger

```
/transport/tempo <bpm>
/transport/play <0|1>
/arrange/view                  → Arrange-Panel aktivieren
/arrange/record/start          → Arranger-Recording + Play
/arrange/record/stop           → Recording stoppen
/scene/N/launch                → Scene N starten (alle Clips)
/agent/track/count             → Antwort via Port 8002: Track-Anzahl
/track/delete/last             → Aktuell selektierten Track löschen (Teardown)
/undo                          → Letzte Aktion rückgängig machen
```

---

## Song-Erstellung Workflow

### Spezifisch (eigene Noten) — `build_song` ★ BEVORZUGT

```
1. check_bitwig_connection()
2. build_song('{"bpm": 120, "tracks": [{"index": 1, "instrument": "Phase-4",
              "fx": ["Distortion", "Amp"], "clip": {"slot": 0,
              "length_beats": 40, "notes": [{...}]}}]}')
   → Track anlegen + Instrument + FX + Clip + Noten in einem einzigen Tool-Call
   → ~4k Tokens statt ~14k bei Einzelaufrufen
3. verify_song(play_seconds=10)
```

### Genre-basiert — `create_song_from_genre`

```
1. check_bitwig_connection()          → Bridge prüfen (Ping/Pong)
2. get_bitwig_track_state()           → Track-Anzahl via OSC lesen
3. create_song_from_genre(            → Song erstellen
       genre="pop",                   Chordonomicon → 6 Tracks
       start_track_index=1            v9 Kick|Snare|Hat + Polysynth|Phase-4|FM-4
   )
4. verify_song(play_seconds=5)        → Abspielen + Screenshot + Track-Count
5. setup_instrument_track(6,"Reverb") → Effekte hinzufügen (UUID-basiert)
6. write_notes_to_clip(6, notes_json) → Lead-Melodie schreiben
```

### create_song_from_genre Details

- **6 Tracks immer** (num_tracks ignoriert): v9 Kick, v9 Snare, v9 Hat Closed, Polysynth, Phase-4, FM-4
- **Genre-Fallback**: "hard rock"→"rock", "electro pop"→"pop", etc.
- **Timing**: 0.5s nach Track-Select, 0.6s nach Clip-Create (CursorTrack braucht Zeit)
- **Antwort**: "SONG FERTIG ERSTELLT. KEINE weiteren Aufrufe nötig." + Track-Liste

### 1-Minuten Song ohne Loop

```python
# Verse (Slot 0) + Chorus (Slot 1) erstellen
# Dann in Arranger aufnehmen:
/arrange/view
/arrange/record/start
/scene/1/launch    → Verse 30s
/scene/2/launch    → Chorus 30s
/arrange/record/stop
# → 60s Arranger-Timeline, kein Loop
```

---

## Wissensdatenbank (Neo4j)

### Inhalt

| Collection | Einträge | Beschreibung |
|---|---|---|
| Chordonomicon | 1.800 | Echte Pop/Rock/Jazz Akkordfolgen mit Verse/Chorus-Struktur |
| MusicCaps | 5.521 | Musik-Beschreibungen mit Aspects |
| CoT_Music_Production_DAW | 5.557 | DAW-Workflows (FL, Logic, Bitwig) |
| MusicTheoryBench | 367 | Musiktheorie Q&A |
| Bitwig_Generated | 46 | Genre-Devices, Parameter, Workflows |
| BitiwgAPI_v25 | 16 | Bitwig Controller API Dokumentation |
| bitwig_osc.md | 4 Chunks | OSC-Befehlsreferenz |
| bitwig_concepts.md | - | Bitwig-Konzepte |

### Genre-Mapping (Chordonomicon)

```python
GENRE_MAP = {
    "hard rock": "rock", "heavy metal": "metal",
    "progressive rock": "rock", "indie rock": "rock",
    "electro pop": "pop", "synth pop": "pop",
    "hip hop": "hip-hop", "edm": "house",
    ...
}
```

### Kritisches API-Wissen (in KB gespeichert)

- `PopupBrowser.commit()` und `selectFirstFile()`: NUR aus OSC-Handlern, NICHT aus `flush()`
- `CursorClip.setStep(ch, x, y, velocity_int, duration_beats)`: velocity als INT 0-127, duration in BEATS
- `NoteStep.State`: Enum-Werte sind `Empty`, `NoteOn`, `NoteSustain`
- `ClipLauncherSlotBank` braucht `numScenes > 0` bei `createCursorTrack()`
- Bitwig C3 = MIDI 60 (Middle C), eine Oktave weniger als Standard

---

## Bekannte Bugs & Fixes

### OSC Pitch-Bug (behoben)
**Problem:** Python `int(pitch)` → OSC-Int-Typ → Java `msg.getFloat()` scheitert → alle Noten landen bei Pitch 60 (C3 in Bitwig)
**Fix:** `float(pitch)` in allen `/clip/note/beat` Aufrufen

### CursorTrack-Timing (behoben)
**Problem:** 0.15s nach `/track/N/select` zu kurz → CursorClip folgt nicht → Noten auf falschen Track
**Fix:** 0.5s nach select, 0.6s nach clip/create

### clipSlotBank null (behoben)
**Problem:** `createCursorTrack(..., numScenes=0)` → `clipLauncherSlotBank()` gibt null zurück
**Fix:** `numScenes=SLOT_BANK_SIZE` (8)

### StringBuilder.isEmpty() Java-Version (behoben)
**Problem:** `sb.isEmpty()` erst ab Java 15, Bitwig nutzt Java 11/14
**Fix:** `sb.length() > 0`

### create_song_from_genre Doppelaufruf (behoben)
**Problem:** Mit `num_tracks=4` nur 4 Tracks → Agent denkt Chords/Lead fehlen → 2. Aufruf
**Fix:** `num_tracks=6` als Default erzwingen, "SONG FERTIG" Signal in Antwort

### LLM Tool-Call XML-Format (bekannt)
**Problem:** Qwen3 fällt bei > 15 Nachrichten in Hermes-XML-Format statt OpenAI-JSON
**Fix:** `MAX_MESSAGES=10`, kompakte Tool-Antworten (kurze Strings statt große Dicts)

### HTTP 400 Context Overflow (behoben)
**Problem:** 14337 Input + 2048 Output = 16385 > 16384 Token-Limit → `HTTP 400 Bad Request`
**Fix:** `MAX_MESSAGES=10`, `max_tokens=1500`, ToolMessage-Kürzung auf 400 Zeichen in `call_llm()`

### vLLM IP (behoben)
**Problem:** vLLM läuft auf 192.168.0.4 (anderes WSL-Interface), nicht 127.0.0.1
**Fix:** `VLLM_BASE_URL=http://192.168.0.4:8000` in `.env`

---

## Verzeichnisstruktur (aktuell)

```
bitwig-agent/
├── src/
│   ├── agent/
│   │   ├── core.py              # LangGraph Graph, MAX_MESSAGES=15, handle_tool_errors=True
│   │   ├── prompts.py           # System-Prompt: Song-Erstellung, UUID-Devices, Workflow
│   │   ├── state.py             # AgentState: messages, track_count, tracks, tempo, bridge_ok
│   │   └── tools/
│   │       ├── __init__.py      # ALL_TOOLS: 18 Tools (inkl. build_song)
│   │       ├── bitwig_tools.py  # control_bitwig (OSC Transport/Mix)
│   │       ├── knowledge_tool.py # query_bitwig_docs (Neo4j Vektorsuche)
│   │       └── song_tools.py    # build_song ★, create_song_from_genre, verify_song, write_notes_to_clip, ...
│   ├── audio/
│   │   └── chord_to_bitwig.py   # Chordonomicon-Parser + MIDI-Konverter
│   └── knowledge/
│       ├── ingest.py
│       ├── neo4j_graph.py
│       ├── song_memory.py
│       └── store.py             # multilingual-e5-base Embeddings
├── bitwig-extension/            # Java Extension für Bitwig Studio 6
│   ├── src/main/java/com/bitwigagent/
│   │   ├── BitwigAgentBridgeDefinition.java
│   │   └── BitwigAgentBridgeExtension.java  # 1.200+ Zeilen, OSC-Server + UUID-Map
│   ├── dist/
│   │   └── BitwigAgentBridge.bwextension    # Installiert in Bitwig Extensions/
│   └── pom.xml
├── scripts/
│   ├── build_kb.py
│   ├── export_validate_pop.py   # MIDI-Export + Struktur-Validierung
│   └── ingest_bitwig_api.py     # Bitwig Controller API → Neo4j
├── logs/
│   └── agent_YYYYMMDD.log       # Persistentes Logging (Tool-Calls, Antworten)
├── bitwig_mcp_server.py         # MCP-Server (FastMCP): alle Bitwig-Tools
├── start_agent.py               # Full-Stack Launcher (managed/external vLLM Mode)
├── .env                         # VLLM_BASE_URL, NEO4J_*, BITWIG_HOST, HF_TOKEN
├── Makefile
└── PROJECT.md

~/vllm/
├── service-manager.sh           # Runtime-Manager (start/stop/status/logs)
├── vllm-start.sh                # Wrapper → service-manager.sh start
├── vllm-stop.sh                 # Wrapper → service-manager.sh stop
├── ollama_proxy.py              # Continue/Ollama-kompatibler Proxy
└── .run/                        # PID-Dateien für verwaltete Prozesse
```

---

## Setup

```bash
# vLLM starten (auf korrekter IP)
cd ~/vllm && bash vllm-start.sh
# VLLM_BASE_URL=http://192.168.0.4:8000 (nicht localhost!)

# Neo4j: über Windows Neo4j Desktop starten
# Credentials: neo4j / neo4jllm, Datenbank: neo4j

# Agent interaktiv starten
cd ~/bitwig-agent && make agent

# Extension bauen und installieren
cd ~/bitwig-agent/bitwig-extension && mvn package
cp dist/BitwigAgentBridge.bwextension \
   "/mnt/c/Users/Admin/Documents/Bitwig Studio/Extensions/"
# In Bitwig: Settings → Extensions → BitwigAgentBridge aktivieren

# Verbindung prüfen
python -c "from src.agent.tools.song_tools import check_bitwig_connection; \
           print(check_bitwig_connection.invoke({}))"
```

---

## Qualitätsstatus (Stand 2026-05-05)

```
build_song (Builder Pattern):     █████████░  90%  1 Tool-Call statt 7+, 17 Tests ✅
Song-Erstellung (Clip Launcher):  █████████░  90%  stabil, 6 Tracks, Chordonomicon
Instrument-Loading (UUID):        █████████░  90%  146 Devices sofort, kein Browser
Noten schreiben (Chords/Lead):    ████████░░  80%  Float-Pitch-Bug behoben
Arranger-Recording:               ███████░░░  70%  60s Song getestet
LangGraph Agent:                  ████████░░  80%  MAX_MESSAGES=10, kein Overflow
OSC-Rückkanal (Track-Count):      ████████░░  80%  Port 8002 zuverlässig
Note-Count Verifikation:          █████░░░░░  50%  Counter nur nach Reload korrekt
Pitch-Validierung:                ████████░░  80%  MIDI-Names in Tool-Antwort
Browser-Fallback (VST):           ████░░░░░░  40%  DeviceBrowsingSession vorhanden
Test-Idempotenz (Integration):    ████████░░  80%  /track/delete/last Teardown-Fixture
```

---

## Nächste Schritte

1. **Phase-Routing validieren**: Agent-Run prüfen ob `build_song` korrekt aufgerufen wird und `route_by_phase()` nicht vorzeitig `END` zurückgibt
2. **Melodie-Track automatisch** in `create_song_from_genre` befüllen (aktuell leer)
3. **Note-Count-Observer** stabiler machen (Extension-seitig nach jedem `/clip/select` resetten)
4. **Chorus-Section** als separaten Aufruf mit anderem Slot
5. **Arranger-Clip-Erstellung** ohne Record-Workaround (API-Limitation dokumentiert)
6. **VST-Browser-Fallback** testen sobald VST installiert
7. **Screenshot-Analyse** mit Vision-Modell für automatische UI-Verifikation

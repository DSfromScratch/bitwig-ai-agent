# Bitwig AI Agent

KI-gesteuerter Musik-Kompositions-Agent für Bitwig Studio 6. Generiert mehrstimmige Songs direkt in Bitwig via OSC — kein Audio-Export, keine Round-Trips, reines LLM-gesteuertes MIDI-Composing.

## Architektur

```
User-Prompt (Streamlit / CLI / OSC)
        │
        ▼
LangGraph Agent (core.py)
  ├── Router: song | control | launchpad
  ├── LLM: Qwen3-14B-AWQ (vLLM, remote)
  ├── Parser-Chain: OpenAI → QwenXML → TruncatedXML → Markdown
  ├── Policy Guard: halluzinierte Tools herausfiltern
  └── Tool: execute_result(BitwigResult)
              │
              ▼
        bitwig_mcp_server.py
          Step-Executor (Command Pattern)
          ├── UUID-Auflösung: Extension-Cache → Neo4j
          ├── Precondition Auto-Inject (fehlende Tracks)
          └── OSC → BitwigStepPlugin (Port 8002)
                        │
              ┌─────────┴──────────┐
              ▼                    ▼
  BitwigAgentBridge.java    BitwigStepPlugin.java
  Transport, Track, FX      Step-Execution, UUID-Export
  (Port 8001/9001)          (Port 8002/9002)
              │
              ▼
        Bitwig Studio 6
```

**UUID-Sync:** Die Java-Extension ist die einzige Quelle der Gerät-UUIDs. Beim ersten Aufruf holt Python alle UUIDs via `/devices/export` OSC, schreibt sie nach Neo4j und cached sie in-process. Kein doppeltes Pflegen.

**Parser-Chain:** Das LLM (Qwen3) liefert gelegentlich XML-Fragmente statt native Tool-Calls. Die `CompositeToolCallParser`-Kette repariert truncated JSON (Stack-basiert für `{}` und `[]`) und extrahiert `<tool_call>`-Tags automatisch.

## Stack

| Schicht | Technologie |
|---------|-------------|
| LLM | Qwen3-14B-AWQ via vLLM (remote) |
| Agent | LangGraph StateGraph + LangChain Tools |
| MCP | `bitwig_mcp_server.py` (Claude Code Integration) |
| OSC Bridge | `BitwigAgentBridgeExtension.java` (UDP 8001/9001) |
| Step Execution | `BitwigStepPluginExtension.java` (UDP 8002/9002) |
| Knowledge Base | Neo4j + multilingual-e5-base Embeddings |
| UI | Streamlit Dashboard |

## Voraussetzungen

- Python 3.11
- Java 21+ (für Bitwig-Extension-Build, Maven)
- Bitwig Studio 6
- Neo4j (lokal oder Docker)
- vLLM-Server mit Qwen3-14B-AWQ (kann remote sein, via `.env` konfigurierbar)

## VST3 Plugins

Bitwig lädt VST3-Plugins aus `~/.vst3/`. Getestete Plugins (Linux, VST3):

| Plugin | Quelle | Genre / Zweck |
|--------|--------|---------------|
| **MT Power Drum Kit 2** | [powerdrumkit.com](https://www.powerdrumkit.com/linux.php) | Acoustic Drums — Rock, Pop, Jazz |
| **Decent Sampler** | [decentsamples.com](https://www.decentsamples.com/product/decent-sampler-plugin/) | Sampler-Engine für alle Sample-Libraries |
| **Surge XT** | [surge-synthesizer.github.io](https://surge-synthesizer.github.io/) | Synth — Wavetable, 808-Bass, alle elektronischen Genres |
| **Surge XT Effects** | (im Surge-XT-Paket enthalten) | FX-Version von Surge XT |

### Decent Sampler Libraries

Libraries liegen unter `~/Music/DecentSampler/`:

| Library | Quelle | Inhalt |
|---------|--------|--------|
| **VirtualPlayingOrchestra** | [github.com/eodowd](https://github.com/eodowd/VirtualPlayingOrchestra) | 37 Presets: Streicher, Bläser, Chor, Harfe, Pauken |
| **UprightPianoKW** | [freepats.zenvoid.org](https://freepats.zenvoid.org/Piano/acoustic-grand-piano.html) | Echtes Upright-Klavier (26 Velocity-Samples) |
| **808TK** | [github.com/sourc3array](https://github.com/sourc3array/808TK) | Hip-Hop 808 Drums |

```bash
# VST3 Installation (Linux)
mkdir -p ~/.vst3
# Plugin-ZIP/-tar.gz entpacken → Ordner *.vst3 nach ~/.vst3/ kopieren

# Decent Sampler Libraries klonen
mkdir -p ~/Music/DecentSampler
git clone --depth=1 https://github.com/eodowd/VirtualPlayingOrchestra.git ~/Music/DecentSampler/VirtualPlayingOrchestra
git clone --depth=1 https://github.com/sourc3array/808TK.git ~/Music/DecentSampler/808TK
```

Nach der Installation Bitwig neu starten und unter **Settings → Plug-ins → Rescan** den Plugin-Scan auslösen.

## Installation

```bash
git clone https://github.com/DSfromScratch/bitwig-ai-agent.git
cd bitwig-ai-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env ausfüllen: VLLM_BASE_URL, NEO4J_URI, BITWIG_HOST
```

## Konfiguration

```env
# vLLM (kann remote sein)
VLLM_BASE_URL=http://192.168.0.3:8100
VLLM_MODEL=./models/Qwen3-14B-AWQ

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4jllm

# Bitwig OSC Ports
BITWIG_HOST=127.0.0.1
BITWIG_PORT=8001
BITWIG_REPLY_PORT=9001
BITWIG_STEP_PORT=8002
BITWIG_STEP_REPLY_PORT=9002
```

## Starten

```bash
# Agent (interaktiv)
source .venv/bin/activate
python src/agent/core.py

# Streamlit Dashboard
streamlit run dashboard/app.py

# Als MCP-Server für Claude Code (siehe unten)
```

## Bitwig Extensions

Das Projekt verwendet zwei Java-Extensions, die als OSC-Server innerhalb von Bitwig laufen:

### BitwigAgentBridge (Port 8001/9001)
Transport, Tracks, FX-Parameter, Clip-Operationen.

### BitwigStepPlugin (Port 8002/9002)
Step-Execution (Command Pattern), UUID-Export, Note-Counter.

```bash
# Build (erfordert JDK 21+, Maven)
cd bitwig-extension
mvn package -q
# Ausgabe: target/BitwigStepPlugin-*.bwextension
```

Die `.bwextension`-Datei in den Bitwig-Extensions-Ordner kopieren und in Bitwig → Einstellungen → Controller aktivieren.

### Step-Typen (BitwigStepPlugin)

| Step | Beschreibung |
|------|--------------|
| `add_track` | Instrument-Track hinzufügen |
| `select_track` | Track auswählen |
| `load_instrument` | Gerät laden (UUID-direkt wenn bekannt) |
| `append_effect` | FX-Device anhängen |
| `set_param` | Parameter per Index setzen (0.0–1.0) |
| `set_param_named` | Parameter per Name setzen |
| `write_notes` | MIDI-Noten in Clip schreiben |
| `write_drum_pattern` | Drum-Pattern via Neo4j-Lookup |
| `set_tempo` | BPM setzen |

## MCP-Server (Claude Code)

Ermöglicht direktes Bitwig-Controlling aus Claude Code heraus.

`~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "bitwig": {
      "command": "/pfad/zu/bitwig-agent/.venv/bin/python",
      "args": ["/pfad/zu/bitwig-agent/bitwig_mcp_server.py"]
    }
  }
}
```

### Verfügbare MCP-Tools

| Tool | Beschreibung |
|------|--------------|
| `execute_result` | Führt einen BitwigResult-Step-Plan aus (Haupttool) |
| `check_bitwig_connection` | Prüft Verbindung zu beiden Bridges |
| `get_bitwig_track_state` | Track-Namen + Note-Counts aus Bitwig |
| `query_bitwig_docs` | Sucht in der Neo4j-Wissensbasis |
| `bitwig_play` / `bitwig_stop` | Transport starten/stoppen |
| `bitwig_set_tempo` | BPM setzen |
| `bitwig_select_track` | Track auswählen |
| `bitwig_set_track_volume` | Lautstärke (0.0–1.0) |
| `bitwig_launchpad_map` | Launchpad MK2 Pad-Mapping |

### `execute_result` — BitwigResult-Format

```json
{
  "context_type": "song",
  "target": {"bpm": 120, "genre": "rock"},
  "summary": "Rock Drums + Bass",
  "steps": [
    {"type": "add_track",       "args": {},                                      "status": "pending", "note": ""},
    {"type": "load_instrument", "args": {"track_index": 1, "name": "v9 Kick"},   "status": "pending", "note": ""},
    {"type": "write_notes",     "args": {"track_index": 1, "notes": [...]},       "status": "pending", "note": ""}
  ]
}
```

## Tests

```bash
# Unit-Tests (keine externe Abhängigkeit)
.venv/bin/pytest tests/ -m unit -v

# Integration (erfordert Bitwig + OSC-Bridge aktiv)
.venv/bin/pytest tests/ -m integration -v -s

# E2E Guitar Score Loop
.venv/bin/pytest tests/test_e2e_guitar.py -m integration -v -s
```

| Marker | Anforderung |
|--------|-------------|
| `unit` | Keine (alle Deps gemockt) |
| `integration` | Bitwig läuft + BitwigStepPlugin aktiv |
| `neo4j` | Neo4j erreichbar auf bolt://localhost:7687 |

113 Unit-Tests in 10 Dateien, alle ohne externe Abhängigkeiten ausführbar.

## Projektstruktur

```
bitwig-agent/
├── src/agent/
│   ├── core.py                    # LangGraph Agent: Routing, LLM, Recovery, Policy
│   ├── events.py                  # EventBus + JSONL-Logging (logs/generation_events.jsonl)
│   ├── policy.py                  # Halluzinierte Tools erkennen und entfernen
│   ├── project_state.py           # BitwigProjectState: Track/Note-Snapshot
│   ├── prompts.py                 # System-Prompts (song / control / launchpad)
│   ├── state.py                   # AgentState TypedDict
│   ├── tools/
│   │   ├── mcp_bridge.py          # MCP Tool-Registrierung + Whitelist
│   │   ├── song_tools.py          # UUID-Lookup, Device-Sync, OSC-Helpers
│   │   └── bitwig_tools.py        # Transport-, Track-, Parameter-Tools
│   └── parsing/
│       └── tool_call_parsers.py   # CompositeToolCallParser (4 Parser-Strategien)
├── src/knowledge/
│   ├── neo4j_graph.py             # Chordonomicon-Graph-Queries
│   ├── repositories.py            # Device/Pattern-Repositories
│   └── embedding_server.py        # Lokaler Embedding-Service
├── src/audio/                     # Chord-Konvertierung, Style-Rules, MIDI-Utils
├── bitwig-extension/              # Java: BitwigAgentBridge + BitwigStepPlugin (Maven)
├── dashboard/                     # Streamlit-UI
├── bitwig_mcp_server.py           # MCP-Server + execute_result-Implementierung
├── start_agent.py                 # Einstiegspunkt
├── scripts/                       # KB-Build-Scripts, Neo4j-Ingest
├── logs/                          # generation_events.jsonl, agent_YYYYMMDD.log
└── tests/                         # 113 Unit-Tests
```

## Lizenz

MIT

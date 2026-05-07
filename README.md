# Bitwig AI Agent

AI-powered music composition agent for Bitwig Studio 6. Generates multi-track songs directly into Bitwig via OSC — no audio files, no round-trips, pure LLM-driven MIDI composition.

## How It Works

```
User Prompt
    │
    ▼
LangGraph Master Graph
    ├── plan_node          (extracts BPM, key, style, instrument hints)
    ├── instrument_slave ─┐
    ├── harmony_slave    ─┤─ parallel via Send-API
    └── note_slave        │  (waits for both)
         │                │
         ▼                │
    assemble_node ◄───────┘
         │
    execute_build ──► build_song tool ──► OSC ──► BitwigAgentBridge.java
         │                                              │
    verify_node ◄── quality score ◄── verify_song      ▼
    (Observer)       retry if < 0.75          Bitwig Studio 6
         │
    reply_node
```

The **Master Graph** implements an Observer + State Pattern retry loop: `verify_node` scores output quality (note density, track count, warnings) and routes back to `plan_node` if the score falls below the threshold — up to the configured retry budget.

Sources chord progressions from the **Chordonomicon knowledge base** (1,800 songs, Neo4j graph + embeddings).

## Stack

| Layer | Technology |
|-------|-----------|
| LLM | Qwen3-14B-AWQ via vLLM |
| Agent | LangGraph StateGraph + LangChain tools |
| MCP | bitwig_mcp_server.py (Claude Code integration) |
| OSC Bridge | BitwigAgentBridgeExtension.java (UDP 8001/9001) |
| Knowledge Base | Neo4j + multilingual-e5-base embeddings |
| UI | Streamlit dashboard / CLAP plugin |

## Prerequisites

- Python 3.11
- Java 25 (for Bitwig extension build)
- Bitwig Studio 6
- Neo4j Desktop (Windows) or Docker
- vLLM server with Qwen3-14B (can be remote, configured via `.env`)

## Installation

```bash
# 1. Clone and install Python dependencies
git clone https://github.com/DSfromScratch/bitwig-ai-agent.git
cd bitwig-ai-agent
make install

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env: set VLLM_BASE_URL, NEO4J_URI, BITWIG_HOST, HF_TOKEN

# 3. (Optional) Download Music Flamingo model (~16 GB, one-time)
make download-mf
```

## Configuration

`.env` key settings:

```env
VLLM_BASE_URL=http://localhost:8000
VLLM_MODEL=./models/Qwen3-14B-AWQ

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

BITWIG_HOST=127.0.0.1
BITWIG_OSC_PORT=8000
BITWIG_DM_PORT=8001

EMBEDDING_BASE_URL=http://127.0.0.1:8080
KB_EMBED_MODEL=intfloat/multilingual-e5-base

HF_TOKEN=                        # needed for Chordonomicon dataset
```

## Running

```bash
# Full stack (embedding server + MCP + agent)
make start

# Agent CLI only
make agent

# Streamlit dashboard
make dashboard

# As a systemd service (Linux)
make agent-service-install
make agent-service-start
make agent-service-logs
```

## Bitwig Extension

The Java extension runs inside Bitwig Studio as an OSC server. It translates OSC commands to Bitwig API calls.

```bash
# Build (requires JDK 25)
make build-extension

# Install
make install-plugin
```

Copy the generated `.bwextension` file to your Bitwig extensions folder and enable it in Bitwig → Settings → Extensions. The extension listens on **UDP 8001** and replies on **9001**.

Key OSC commands accepted by the extension:

| Command | Description |
|---------|-------------|
| `/track/add/instrument <n>` | Add n instrument tracks |
| `/browser/device/load <name>` | Load a device by name |
| `/transport/tempo <bpm>` | Set project tempo |
| `/clip/notes/add <json>` | Write MIDI notes to clip |
| `/transport/play` | Start playback |
| `/key/set <key> <scale>` | Set project key |

## MCP Server (Claude Code)

Exposes Bitwig control as Model Context Protocol tools directly in Claude Code.

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "bitwig": {
      "command": "/path/to/bitwig-agent/.venv/bin/python",
      "args": ["/path/to/bitwig-agent/bitwig_mcp_server.py"]
    }
  }
}
```

## Testing

```bash
make test                # Unit tests (no external deps)
make test-integration    # Full pipeline, all deps mocked
make test-neo4j          # Requires Neo4j on bolt://localhost:7687
make test-all            # Everything
```

| Marker | Requirement |
|--------|------------|
| `unit` | None |
| `e2e` | None (LLM + OSC mocked) |
| `integration` | Bitwig + OSC bridge (port 8001) |
| `neo4j` | Neo4j running |

589 tests, default run excludes `integration` and `neo4j`.

## Project Structure

```
bitwig-agent/
├── src/agent/
│   ├── core.py              # Main StateGraph + tool routing
│   ├── master_graph.py      # Multi-slave orchestration, Observer retry loop
│   ├── state.py             # AgentState TypedDict, reducers
│   ├── slaves/              # instrument_slave, harmony_slave, note_slave, assemble
│   ├── tools/               # build_song, verify_song, OSC tools
│   ├── policy.py            # Request classification
│   └── prompts.py           # System prompts
├── src/knowledge/
│   ├── neo4j_graph.py       # Chordonomicon graph queries
│   └── embedding_server.py  # Local embedding service
├── src/audio/               # Audio analysis, style rules, MIDI utilities
├── bitwig-extension/        # Java OSC bridge (Bitwig Controller API)
├── agent-plugin/            # CLAP plugin UI
├── dashboard/               # Streamlit UI
├── bitwig_mcp_server.py     # MCP server for Claude Code
├── start_agent.py           # Full-stack launcher
├── scripts/                 # systemd service, KB build scripts
└── tests/                   # 589 tests across 12 files
```

## License

MIT

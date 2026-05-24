# Kommunikationsdiagramm — Bitwig ↔ LLM

## Systemübersicht (Komponentendiagramm)

```mermaid
graph LR
    subgraph WIN ["Windows / WSL"]
        BW["Bitwig Studio\n(DrivenByMoss Extension)"]
        EXT["BitwigAgentBridge.bwextension\nJava / OSC Bridge"]
        BW --- EXT
    end

    subgraph LINUX ["Linux Host"]
        subgraph AGENT ["Python Agent  (Port :9003)"]
            CORE["Agent Core\nLangGraph"]
            TOOLS["Tools Layer\n18 Agent + 39 MCP"]
            MCP["MCP Server\nstdio subprocess"]
            CORE --- TOOLS
            TOOLS --- MCP
        end

        subgraph KB ["Knowledge Base"]
            NEO["Neo4j :7687\nGraph + Vector Search"]
        end

        subgraph INFRA ["Infrastruktur (Podman)"]
            VLLM["vLLM :8100\nQwen3-14B-AWQ\nOpenAI-kompatibel"]
            NEO4J_C["Neo4j Container :7687"]
        end
    end

    EXT  <-->|"OSC UDP\n:8001 → Agent\n:9001 ← Bridge"| TOOLS
    CORE <-->|"HTTP OpenAI API\nPOST /v1/chat/completions"| VLLM
    TOOLS <-->|"Bolt TCP :7687\nCypher + Vector"| NEO
    NEO --- NEO4J_C
```

## Vollständiger Kommunikationsfluss (Sequenzdiagramm)

```mermaid
sequenceDiagram
    autonumber
    participant UI  as Benutzer / Bitwig UI
    participant BW  as Bitwig Studio<br/>(DrivenByMoss)
    participant EXT as BitwigAgentBridge<br/>.bwextension  :8001
    participant AGT as Python Agent<br/>OSC Listener  :9003
    participant LLM as vLLM Server<br/>Qwen3-14B-AWQ  :8100
    participant KB  as Neo4j Graph DB<br/>:7687 Bolt
    participant MCP as MCP Server<br/>(stdio)

    %% ── Schritt 1: Prompt kommt von Bitwig ──────────────────────────────────
    UI  ->> BW : Taste / MIDI-Controller / Chat-Eingabe
    BW  ->> EXT: interner API-Aufruf
    EXT ->> AGT: OSC UDP :9003  →  /agent/ui/prompt "Rock-Riff Em"

    %% ── Schritt 2: Erster LLM-Aufruf ────────────────────────────────────────
    AGT ->> LLM: POST /v1/chat/completions<br/>{ model: "Qwen3-14B-AWQ",<br/>  messages: [system, user],<br/>  tools: [...18+39 Schemas] }
    LLM -->> AGT: { choices: [{ tool_calls: [<br/>  { name: "query_bitwig_docs",<br/>    args: {query: "rock guitar"} }] }] }

    %% ── Schritt 3: Knowledge-Base-Query ─────────────────────────────────────
    AGT ->> KB : Bolt:  MATCH (d:Device)-[:USES]-(g:Genre)<br/>WHERE toLower(g.name) CONTAINS "rock"<br/>RETURN d.name, d.category, r.weight
    KB -->> AGT: [{ name:"Phase-4", category:"synthesizer" },<br/>              { name:"Distortion", category:"audio_fx" }]

    %% ── Schritt 4: Zweiter LLM-Aufruf mit KB-Ergebnis ───────────────────────
    AGT ->> LLM: POST /v1/chat/completions<br/>{ messages: [..., ToolMessage(KB-Ergebnis)],<br/>  tools: [...] }
    LLM -->> AGT: { tool_calls: [<br/>  { name: "build_song",<br/>    args: { project_json: "{bpm:140,\n    tracks:[{instrument:'Phase-4',\n    clip:{notes:[...]}}]}" } }] }

    %% ── Schritt 5: OSC-Nachrichten an Bitwig ─────────────────────────────────
    AGT ->> EXT: OSC UDP :8001  →  /transport/tempo  140
    AGT ->> EXT: OSC UDP :8001  →  /track/add/instrument
    AGT ->> EXT: OSC UDP :8001  →  /browser/device/load  "Phase-4"
    AGT ->> EXT: OSC UDP :8001  →  /clip/create  [0, 16]

    loop Für jede MIDI-Note  (z.B. 48×)
        AGT ->> EXT: OSC UDP :8001  →  /clip/note/beat  [step, pitch, vel, dur]
    end

    AGT ->> EXT: OSC UDP :8001  →  /browser/fx/load  "Distortion"

    %% ── Schritt 6: Verifikation ───────────────────────────────────────────────
    AGT ->> EXT: OSC UDP :8001  →  /agent/track/count  1
    EXT -->> AGT: OSC UDP :9001  →  /agent/track/count  2   (int)

    AGT ->> EXT: OSC UDP :8001  →  /scene/0/launch  1
    Note over AGT,EXT: 3 Sekunden abspielen

    %% ── Schritt 7: Optionaler MCP-Aufruf ────────────────────────────────────
    opt MCP-Tool aufgerufen (z.B. bitwig_load_instrument)
        AGT ->> MCP: stdin  JSON-RPC  {"method":"bitwig_load_instrument",<br/>"params":{...}}
        MCP ->> EXT: OSC UDP :8001  →  /browser/device/load  ...
        EXT -->> MCP: OSC UDP :9001  →  Bestätigung
        MCP -->> AGT: stdout  JSON-RPC  {"result": "ok"}
    end

    %% ── Schritt 8: Abschluß-LLM-Aufruf ──────────────────────────────────────
    AGT ->> LLM: POST /v1/chat/completions<br/>{ messages: [..., ToolMessage(build_result)],<br/>  tools: [...] }
    LLM -->> AGT: { content: "Rock-Riff angelegt:\nPhase-4 · 140 BPM · 48 Noten" }

    %% ── Schritt 9: Antwort zurück an Bitwig ──────────────────────────────────
    AGT ->> EXT: OSC UDP :9003  →  /agent/ui/response  "Rock-Riff angelegt: Phase-4..."
    EXT ->> BW : interner API-Aufruf
    BW  ->> UI : Antwort in Chat / Notification anzeigen
```

## OSC-Nachrichtenprotokoll — Referenz

```mermaid
block-beta
    columns 3

    block:AGENT_TO_BW["Agent → Bitwig  (UDP :8001)"]:3
        T1["/transport/tempo  &lt;float&gt;"]
        T2["/transport/play  0|1"]
        T3["/transport/stop  1"]

        R1["/track/add/instrument  1"]
        R2["/track/{i}/select  1"]
        R3["/track/{i}/remove  1"]
        R4["/track/{i}/volume  &lt;0-1&gt;"]
        R5["/track/{i}/mute  0|1"]
        R6["/track/{i}/solo  0|1"]

        B1["/browser/device/load  &lt;name&gt;"]
        B2["/browser/preset/load  &lt;name&gt;"]
        B3["/browser/fx/load  &lt;name&gt;"]

        C1["/clip/create  [slot, beats]"]
        C2["/clip/note/beat  [step,pitch,vel,dur]"]
        C3["/clip/clear  1"]
        C4["/clip/step_size  0.25"]

        S1["/scene/{i}/launch  1"]
        S2["/arrange/record/start  1"]
        S3["/arrange/record/stop  1"]

        P1["/ping  1"]
        P2["/agent/track/count  1"]
    end

    block:BW_TO_AGENT["Bitwig → Agent  (UDP :9001)"]:3
        R10["/pong  1"]
        R11["/agent/track/count  &lt;int&gt;"]
        R12["/agent/ui/response  &lt;string&gt;"]
    end
```

## Port-Übersicht

| Port | Protokoll | Richtung | Beschreibung |
|------|-----------|----------|--------------|
| **8001** | OSC UDP | Agent → Bitwig | Befehle an DrivenByMoss Extension |
| **9001** | OSC UDP | Bitwig → Agent | Antworten (track count, pong) |
| **9003** | OSC UDP | Bitwig → Agent | User-Prompts, UI-Config |
| **8100** | HTTP (OpenAI API) | Agent → vLLM | LLM-Inferenz (Qwen3-14B-AWQ) |
| **7687** | Bolt TCP | Agent → Neo4j | Wissensbasis-Queries + Vektor-Suche |
| **stdio** | JSON-RPC | Agent ↔ MCP | MCP Tool-Server (subprocess) |

# Kommunikationsdiagramm — Bitwig ↔ LLM

> **Architektur-Update:** Die Kommunikation läuft jetzt über ein **JSON-Step-Protokoll**.
> Der Python-Agent sendet `/step/exec` mit einem JSON-Objekt (`type` + `args`) an die
> Java-Extension. Diese verwaltet eine **Step-Queue** und nutzt Bitwig's
> **`host.scheduleTask()`-Scheduler**, um API-Aufrufe korrekt gestaffelt auszuführen
> (z.B. 80ms nach Track-Add, 200ms nach Device-Load). Nach jedem Step kommt
> `/step/done` als ACK zurück.

---

## Systemübersicht (Komponentendiagramm)

```mermaid
graph TB
    subgraph DAW ["Bitwig Studio  (DAW Host)"]
        BW["Bitwig Studio 6"]
        subgraph EXT ["BitwigStepPluginExtension  (.bwextension)"]
            OSC_IN["OSC Server<br/>UDP :8002"]
            QUEUE["stepQueue<br/>LinkedList<String[]>"]
            DISP["executeStep<br/>Dispatcher"]
            SCHED["host.scheduleTask<br/>Bitwig Task Scheduler"]
            HANDLERS["Step-Handler:<br/>execAddTrack<br/>execLoadInstrument<br/>execAppendEffect<br/>execWriteNotes<br/>execSetParam<br/>…"]
            API["Bitwig Controller API<br/>trackBank, cursorTrack,<br/>cursorDevice, popupBrowser"]

            OSC_IN --> QUEUE
            QUEUE --> DISP
            DISP --> HANDLERS
            HANDLERS --> SCHED
            SCHED --> API
            API -.->|done| OSC_OUT
        end
        OSC_OUT["OSC Reply<br/>UDP :9002<br/>/step/done"]
        BW --- EXT
    end

    subgraph HOST ["Python Agent Host"]
        subgraph AGENT ["Python Agent"]
            LISTENER["osc_listener.py<br/>UDP :9003"]
            CORE["core.py<br/>LangGraph ReAct"]
            EVENTS["events.py<br/>EventBus (Observer)"]
            TOOLS["song_tools.py<br/>+ 56 weitere Tools"]
            CLIENT["osc/client.py<br/>OscClient"]

            LISTENER --> CORE
            CORE --> TOOLS
            CORE -.emit.-> EVENTS
            TOOLS -.emit.-> EVENTS
            TOOLS --> CLIENT
        end

        subgraph INFRA ["Infrastruktur"]
            VLLM["vLLM :8100<br/>Qwen3-14B-AWQ"]
            NEO["Neo4j :7687<br/>Wissensgraph"]
            MCP["MCP Server<br/>(stdio subprocess)"]
        end
    end

    CLIENT <-->|"OSC UDP<br/>:8002 /step/exec<br/>:9002 /step/done"| EXT
    LISTENER <-->|"OSC UDP :9003<br/>/agent/ui/prompt<br/>/agent/ui/response"| EXT
    CORE <-->|"HTTP /v1/chat/completions"| VLLM
    TOOLS <-->|"Bolt :7687"| NEO
    TOOLS <-->|"JSON-RPC stdio"| MCP
```

## Step-Protocol Sequenzdiagramm

```mermaid
sequenceDiagram
    autonumber
    participant U   as User / Bitwig UI
    participant LIS as osc_listener<br/>UDP :9003
    participant CORE as core.py<br/>(LangGraph)
    participant LLM as vLLM :8100<br/>Qwen3-14B-AWQ
    participant KB  as Neo4j :7687
    participant TOOL as song_tools.py
    participant BUS as EventBus
    participant EXT as BitwigStepPlugin<br/>UDP :8002 / :9002
    participant SCH as host.scheduleTask
    participant BW  as Bitwig API

    %% ── 1. Prompt-Eingang ─────────────────────────────────────────────────────
    U   ->> LIS : OSC /agent/ui/prompt "Rock-Riff Em 140 BPM"
    LIS ->> CORE: AgentState{messages:[user]}

    %% ── 2. LLM Iteration 1 ────────────────────────────────────────────────────
    CORE ->> LLM: POST /v1/chat/completions<br/>(system + tools[57])
    LLM -->> CORE: tool_calls=[query_bitwig_docs("rock guitar")]

    CORE ->> KB : MATCH (d:Device)-[:USES]-(g:Genre {name:"rock"})
    KB -->> CORE: [{name:"Phase-4"},{name:"Distortion"}]
    CORE ->> BUS: emit("reasoning",{detected_phase:"song"})

    %% ── 3. LLM Iteration 2 → build_song ──────────────────────────────────────
    CORE ->> LLM: POST /v1/chat/completions  (+ ToolMessage)
    LLM -->> CORE: tool_calls=[build_song({tempo:140, tracks:[…]})]

    %% ── 4. Step-Protocol Loop ────────────────────────────────────────────────
    CORE ->> TOOL: build_song.invoke(project_json)

    rect rgb(240, 248, 255)
        Note over TOOL,EXT: Step-Protocol: Pro Aktion 1× JSON-Step
        loop Für jeden Step (set_tempo, add_track, load_instrument,<br/>append_effect, write_notes, …)
            TOOL ->> EXT: OSC /step/exec  {"type":"add_track","args":{…}}
            alt stepQueue leer
                EXT  ->> EXT : stepExecuting = true
            else stepQueue belegt
                EXT  ->> EXT : stepQueue.add(json) <br/>(serialisiert!)
            end
            EXT  ->> SCH : scheduleTask(execAddTrack, 0ms)
            SCH  ->> BW  : trackBank.scrollIntoView(…)<br/>application.createInstrumentTrack(…)
            BW  -->> SCH : (async API)
            SCH  ->> SCH : scheduleTask(stepDone, 80ms)<br/>(Wartezeit für DAW)
            SCH  ->> EXT : stepDone(src,"add_track")
            EXT -->> TOOL: OSC /step/done "add_track"<br/>(UDP :9002)
            TOOL ->> BUS : emit("result_step_done",{type,index})
            EXT  ->> EXT : nächster Step aus stepQueue.poll()
        end
    end

    TOOL ->> BUS : emit("track_done",{role:"guitar",notes:48})
    TOOL -->> CORE: ToolMessage("OK — 1 Track, 48 Noten")

    %% ── 5. LLM Iteration 3 → Antworttext ─────────────────────────────────────
    CORE ->> LLM: POST /v1/chat/completions  (+ ToolMessage)
    LLM -->> CORE: AIMessage("Rock-Riff angelegt: Phase-4 · 140 BPM · 48 Noten")
    CORE ->> BUS: emit("song_done",{track_count:1})

    %% ── 6. Antwort ────────────────────────────────────────────────────────────
    CORE -->> LIS: AgentState{phase:"done", messages:[…]}
    LIS  ->> EXT: OSC /agent/ui/response "Rock-Riff angelegt: …"
    EXT  ->> U  : UI-Display
```

## Step-Queue State Machine (Java)

```mermaid
stateDiagram-v2
    [*] --> idle           : Extension geladen

    idle --> queued        : /step/exec eingegangen<br/>(stepExecuting=false)
    queued --> executing   : executeStep(json)
    executing --> scheduling: switch(type)→exec*

    scheduling --> waiting : host.scheduleTask(handler, Xms)
    waiting --> api_call   : nach X ms
    api_call --> done      : stepDone(src,type)
    done --> ack_sent      : /step/done OSC reply

    ack_sent --> queued    : stepQueue.poll() — nächster Step
    ack_sent --> idle      : stepQueue.isEmpty()<br/>stepExecuting=false

    state "Parallel Eingang" as parallel {
        [*] --> queue_only : /step/exec während<br/>stepExecuting=true
        queue_only --> [*] : stepQueue.add(json)
    }
```

## Step-Typen Übersicht

| Step-Type           | OSC-Args (JSON)                                              | Handler                  | Delay |
|---------------------|--------------------------------------------------------------|--------------------------|-------|
| `set_tempo`         | `{bpm: 140.0}`                                               | `execSetTempo`           | 0 ms  |
| `add_track`         | `{kind: "instrument" \| "audio" \| "group"}`                 | `execAddTrack`           | 80 ms |
| `select_track`      | `{track_index: 1}`                                           | `execSelectTrack`        | 40 ms |
| `load_instrument`   | `{track_index: 1, device: "Phase-4"}`                        | `execLoadInstrument`     | 200 ms (Browser) |
| `append_effect`     | `{track_index: 1, device: "Distortion"}`                     | `execAppendEffect`       | 200 ms (Browser) |
| `set_param`         | `{track_index: 1, index: 0, value: 0.7}`                     | `execSetParam`           | 0 ms  |
| `set_param_named`   | `{track_index: 1, name: "Cutoff", value: 0.5}`               | `execSetParamNamed`      | 40 ms |
| `write_notes`       | `{track_index: 1, slot: 0, beats: 4, notes: [{…}]}`          | `execWriteNotes`         | varies|
| `clear_tracks`      | `{}`                                                         | `execClearTracks`        | 250 ms / track |
| `play`              | `{}`                                                         | `transport.play()`       | 0 ms  |
| `stop`              | `{}`                                                         | `transport.stop()`       | 0 ms  |

## OSC-Port-Übersicht

| Port      | Protokoll        | Richtung          | Zweck                                                  |
|-----------|------------------|-------------------|--------------------------------------------------------|
| **8002**  | OSC UDP          | Agent → Bitwig    | `/step/exec` — JSON-Step zur Ausführung                |
| **9002**  | OSC UDP          | Bitwig → Agent    | `/step/done` — ACK mit Step-Type                       |
| **8001**  | OSC UDP          | Agent → Bitwig    | Legacy `BitwigAgentBridge` (Track-Count, Ping)         |
| **9001**  | OSC UDP          | Bitwig → Agent    | Legacy Antworten (Track-Count int)                     |
| **9003**  | OSC UDP          | Bitwig → Agent    | `/agent/ui/prompt`, `/agent/ui/config`                 |
| **9003**  | OSC UDP          | Agent → Bitwig    | `/agent/ui/response` (Antworttext)                     |
| **8100**  | HTTP (OpenAI)    | Agent → vLLM      | `POST /v1/chat/completions` — Qwen3-14B-AWQ            |
| **7687**  | Bolt TCP         | Agent → Neo4j     | Cypher-Queries + Vector-Search                         |
| **stdio** | JSON-RPC         | Agent ↔ MCP       | MCP Tool-Server (39 Tools, subprocess)                 |

## Wesentliche Architektur-Eigenschaften

### 1. Sequenzielle Step-Verarbeitung
Die `stepQueue` (synchronized LinkedList) und das `stepExecuting`-Flag garantieren,
dass nur **ein Step zur Zeit** läuft. Eingehende Steps während einer laufenden
Ausführung werden eingereiht und nach `/step/done` automatisch weiterverarbeitet.

### 2. Bitwig-konformes Scheduling
Statt blockierender Waits verwendet die Extension **`host.scheduleTask()`** mit
typischerweise 40–250 ms Verzögerung, damit Bitwig genug Zeit hat, asynchrone
API-Updates (Browser-Population, Device-Load, Bank-Refresh) abzuschließen.

### 3. Observer-Pattern auf Python-Seite
Der **EventBus** (`events.py`) entkoppelt Pipeline-Events von Subscriber-Logik:
- Default-Subscriber: JSONL-Logger (`logs/generation_events.jsonl`) + Python-Logger
- Wildcard `*`-Subscriber für Dashboard/Monitoring
- Synchron, aber Exception-isoliert pro Subscriber

### 4. Reduzierte LangGraph-Topologie
Nur **2 Nodes** (`agent` + `tools`) mit conditional edge `route_by_phase`.
Die alte Master/Slave-Architektur wurde durch die EventBus-getriebene
ReAct-Schleife ersetzt.

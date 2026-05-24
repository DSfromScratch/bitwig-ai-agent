# Ablaufdiagramm — Bitwig AI Agent

## LangGraph Execution Flow

```mermaid
flowchart TD
    A([User Prompt\n/agent/ui/prompt]) --> B{is_concrete_track_task?}

    B -- Ja --> MG_START
    B -- Nein --> SA_START

    subgraph MG ["Master Graph  (parallele Slave-Architektur)"]
        direction TB
        MG_START([Eingang]) --> PLAN["plan_node\nBPM · Scale · beat_count\ninstrument_hint · fx_hint"]
        PLAN --> FAN{fan_out_to_slaves\nLangGraph Send API}

        FAN --> IS["instrument_slave\nDevice aus KB wählen\n(Phase-4 · FM-4 · Sampler …)"]
        FAN --> HS["harmony_slave\nChordonomicon-Query\nAkkord-Progression"]

        IS --> NS["note_slave  ← LLM\nMIDI-Pattern generieren\n(pitch · vel · dur · step)"]
        HS --> NS

        NS --> AS["assemble_node\nJSON zusammenbauen\n{bpm, tracks:[{instrument,\nfx, clip:{notes:[]}}]}"]

        AS --> EB["execute_build_node\nbuild_song Tool\nOSC → Bitwig"]

        EB --> VN["verify_node\nTrack-Count · Screenshot\nQualitäts-Score berechnen"]

        VN --> QC{score ≥ 0.75\noder Budget erschöpft?}
        QC -- "Nein  (retry_signal)" --> PLAN
        QC -- Ja --> RP["reply_node\n'Rock-Riff angelegt:\nPhase-4 · 140 BPM · 24 Noten'"]
    end

    subgraph SA ["Standard Agent  (ReAct Loop)"]
        direction TB
        SA_START([Eingang]) --> LLM["call_llm\nQwen3-14B-AWQ\nSystem-Prompt + Tools binden"]
        LLM --> PH{route_by_phase}

        PH -- "tool_calls vorhanden" --> TN["ToolNode\n18 Agent-Tools +\n39 MCP-Tools"]
        TN -- "ToolMessage" --> LLM

        PH -- "nudge / Phase-Wechsel" --> LLM
        PH -- "done · error · retry-Limit" --> SA_END([Antworttext])
    end

    RP --> OUT([Antwort\n/agent/ui/response])
    SA_END --> OUT
```

## Detaillierter Sequenzfluss (Master Graph — Beispiel: "Rock-Riff Em 140 BPM")

```mermaid
sequenceDiagram
    autonumber
    participant U  as User / Bitwig UI
    participant C  as Agent Core<br/>start_agent.py
    participant PL as plan_node
    participant IS as instrument_slave
    participant HS as harmony_slave
    participant NS as note_slave
    participant AS as assemble_node
    participant EB as execute_build_node
    participant VN as verify_node
    participant RP as reply_node

    U  ->> C : /agent/ui/prompt "Rock-Riff Em 140 BPM"
    C  ->> C : is_concrete_track_task() → True
    C  ->> PL: run_master(user, history)

    PL ->> PL: BPM=140, scale="Em", beat_count=16<br/>instrument_hint="guitar/rock", fx_hint="distortion"
    PL -->> IS: Send(slave_plan)
    PL -->> HS: Send(slave_plan)   [parallel]

    par Parallel Slaves
        IS ->> IS: KB: rock → Phase-4 oder Sampler-Loop
        IS -->> AS: slave_results[0] = {instrument: "Phase-4"}
    and
        HS ->> HS: Chordonomicon: Em - G - D - A
        HS -->> AS: slave_results[1] = {progression: ["Em","G","D","A"]}
    end

    AS ->> NS: note_slave mit harmony + instrument
    NS ->> NS: LLM: MIDI-Noten generieren (48 Noten, 4 Bars)
    NS -->> AS: slave_results[2] = {notes: [...]}

    AS ->> AS: JSON zusammenbauen:<br/>{bpm:140, tracks:[{instrument:"Phase-4",<br/>clip:{notes:[...]}}]}
    AS -->> EB: assembled_json

    EB ->> EB: build_song.invoke(project_json)
    Note over EB: OSC → Bitwig (Details siehe Kommunikationsdiagramm)
    EB -->> VN: build_result "OK — 48/48 Noten"

    VN ->> VN: verify_song: Track-Count, 3s abspielen
    VN ->> VN: _compute_quality: score = 0.88

    alt score ≥ 0.75
        VN -->> RP: phase = "done"
        RP -->> U : /agent/ui/response "Rock-Riff angelegt: Phase-4, 140 BPM, 48 Noten"
    else score < 0.75 und Budget ok
        VN -->> PL: retry_signal = "note_retry"
        Note over PL,NS: Retry-Schleife (max. 3×)
    end
```

## LangGraph Node-Übersicht

| Node | Datei | Funktion |
|------|-------|----------|
| `call_llm` | `src/agent/core.py` | LLM aufrufen, Tool-Calls extrahieren, Phase verwalten |
| `route_by_phase` | `src/agent/core.py` | Routing: tools / nudge / END |
| `plan_node` | `src/agent/master_graph.py` | Prompt parsen → slave_plan |
| `fan_out_to_slaves` | `src/agent/master_graph.py` | Parallele Send-API |
| `instrument_slave` | `src/agent/slaves/` | KB-gestützte Instrument-Auswahl |
| `harmony_slave` | `src/agent/slaves/` | Chordonomicon-Akkordfolgen |
| `note_slave` | `src/agent/slaves/` | MIDI-Pattern via LLM |
| `assemble_node` | `src/agent/slaves/assemble.py` | Slave-Ergebnisse zusammenführen |
| `execute_build_node` | `src/agent/master_graph.py` | `build_song` Tool ausführen |
| `verify_node` | `src/agent/master_graph.py` | Qualitätsprüfung + Retry-Entscheidung |
| `reply_node` | `src/agent/master_graph.py` | Antworttext formatieren |

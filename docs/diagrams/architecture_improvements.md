# Architektur-Verbesserungen — Lösungsansätze

Jedes Finding aus der Architektur-Beurteilung mit konkretem Pattern und Code-Skizze.

> **Implementierungs-Status (Juni 2026):**
>
> | # | Finding | Status | Implementierung |
> |---|---------|--------|-----------------|
> | 1 | OSC ohne Transaktionsgarantie | ✅ | `src/agent/osc/saga.py` + Java `stepQueue` + `host.scheduleTask()` in `BitwigStepPluginExtension.java` |
> | 2 | `song_tools.py` Monolith | 🟡 teilweise | `song_tools.py` jetzt nur 157 Zeilen; `tools/knowledge/{rhythm_tool,instrument_tool}.py` existiert; Tool-Registry/`tools/bitwig/`-Split steht noch aus |
> | 3 | Qualitätsscore misst das Falsche | 🟡 teilweise | `src/agent/quality/specs.py` als Spec-basierter Validator vorhanden |
> | 4 | `is_concrete_track_task()` SPOF | ✅ | Ersetzt durch `src/agent/policy.py` (TaskPolicy) |
> | 5 | Kein Circuit Breaker | ✅ | `src/agent/osc/circuit_breaker.py` aktiv |
> | 6 | `note_slave` Pseudo-Parallelisierung | ✅ | Dualer Graph entfernt; nur noch `note_retry`-Phase im 2-Node-LangGraph (`src/agent/state.py`) |
> | 7 | XML-Recovery Workaround | ✅ | `src/agent/recovery.py` kapselt Recovery-Logik |
> | 8 | Shared State zwischen zwei Graphen | ✅ | Hinfällig — nur noch ein einziger LangGraph (siehe [`agent_flow.md`](agent_flow.md)) |
> | 9 | LLM als Dispatcher statt Reasoning | 🟡 teilweise | `DRUM_PROFILES` entfernt; `rhythm_tool`/`instrument_tool` KB-gestützt; vollständige Strategy-Migration noch offen |
> | 10 | Instrument-Auswahl hardcoded | 🟡 teilweise | `tools/knowledge/instrument_tool.py` LLM-getrieben, aber Fallback-Pfade existieren noch |
> | 11 | Fehlende OSC-ACKs | ✅ | Step-Protocol mit `/step/done`-ACK pro Step (siehe [`bitwig_llm_communication.md`](bitwig_llm_communication.md)) |
> | 12 | Dropdown-UI | ✅ | Dashboard nutzt Freitext-Eingabe (kein Dropdown mehr) |
>
> **Querschnitts-Verbesserungen:**
> - ✅ EventBus (`src/agent/events.py`) für Observer-Pattern (Pipeline-Feedback)
> - ✅ OSC-Client-Abstraktion (`src/agent/osc/client.py`) — eliminiert ~8x Code-Duplikation
>
> Die Code-Skizzen in den einzelnen Findings unten zeigen die ursprünglich vorgeschlagene
> Form. Die tatsächliche Implementierung kann abweichen — siehe jeweils die referenzierte
> Quelldatei für den aktuellen Stand.

---

## Finding 1 — OSC/UDP ohne Transaktionsgarantie

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt
> - **Python-Saga:** [`src/agent/osc/saga.py`](../../src/agent/osc/saga.py) — `BitwigSaga`, `OscCommand`, `SagaStepError` (85 Zeilen)
> - **Java-Queue:** `BitwigStepPluginExtension.java` mit `stepQueue` (LinkedList) + `host.scheduleTask()` für sequentielle, getaktete Ausführung
> - **Step-Protokoll:** Jeder Step liefert `/step/done`-ACK über Port 9002 — siehe [`bitwig_llm_communication.md`](bitwig_llm_communication.md)
>
> Die Code-Skizze unten zeigt das ursprüngliche Design. Die finale Implementierung ist verteilt über Python (Saga) + Java (StepQueue).

**Pattern: Saga + Command Queue**

Eine Song-Erstellung ist eine verteilte Transaktion über ~50 Schritte. Das Saga-Pattern
koordiniert diese Schritte und führt Kompensationsaktionen aus, wenn ein Schritt scheitert.
Die Command Queue serialisiert die OSC-Befehle und wartet auf implizite ACKs (Zustandsabfragen).

```python
# src/agent/osc/saga.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import time

@dataclass
class OscCommand:
    address: str
    args: list
    compensate: OscCommand | None = None   # Rollback-Befehl
    verify:     Callable[[], bool] | None = None  # optionaler Zustandscheck

class BitwigSaga:
    """Führt eine Folge von OSC-Befehlen transaktional aus."""

    def __init__(self, client: "OscClient"):
        self._client   = client
        self._executed: list[OscCommand] = []

    def step(self, cmd: OscCommand, timeout: float = 2.0) -> bool:
        self._client.send(cmd.address, *cmd.args)

        # optionaler Verify-Schritt (Polling auf Zustandsänderung)
        if cmd.verify:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cmd.verify():
                    break
                time.sleep(0.05)
            else:
                self._rollback()
                return False

        self._executed.append(cmd)
        return True

    def _rollback(self) -> None:
        for cmd in reversed(self._executed):
            if cmd.compensate:
                self._client.send(cmd.compensate.address, *cmd.compensate.args)

# Verwendung in build_song:
def _build_track_saga(saga: BitwigSaga, track_idx: int, instrument: str) -> bool:
    return (
        saga.step(OscCommand(
            "/track/add/instrument", [1],
            compensate=OscCommand("/track/remove", [track_idx]),
            verify=lambda: _track_exists(track_idx),
        ))
        and saga.step(OscCommand("/browser/device/load", [instrument]))
    )
```

**Gewinn:** Kein stiller Datenverlust mehr — jeder Fehlschritt löst einen sauberen Rollback aus.

---

## Finding 2 — `song_tools.py` Monolith

> 🟡 **Ist-Stand (Juni 2026):** Teilweise umgesetzt
> - ✅ `song_tools.py` ist von >800 auf **157 Zeilen** geschrumpft
> - ✅ Tool-Verzeichnis aufgesplittet: 22+ Tool-Dateien in `src/agent/tools/` (`bitwig_tools.py`, `pattern_tools.py`, `pattern_generators.py`, `recipe_tool.py`, `freesound_tool.py`, …)
> - ✅ Knowledge-Sub-Package: [`src/agent/tools/knowledge/{rhythm_tool,instrument_tool}.py`](../../src/agent/tools/knowledge/) (KB-gestützte Tools — siehe Finding 9/10)
> - ⏳ Noch offen: zentrale `tools/registry.py` und der ursprünglich vorgesehene `tools/bitwig/` + `tools/music/`-Split. Stattdessen flache Struktur in `tools/`.

**Pattern: Strategy + Tool Registry**

> **Hinweis:** Strategy allein löst nur die Strukturfrage — die Implementierungen
> bleiben sonst weiterhin in Python hardcodiert. Die vollständige Lösung erfordert
> KB-gestützte Strategy-Implementierungen (→ Finding 9). Beide Findings zusammen
> ersetzen `DRUM_PROFILES` vollständig.

Die Datei vereint drei unabhängige Verantwortlichkeiten.
Das Strategy-Pattern isoliert die austauschbare Logik (Drum-Pattern-Generierung je Genre).
Die Tool Registry entkoppelt die Registrierung vom Aufruf.

```
src/agent/tools/
├── registry.py          ← Tool Registry
├── bitwig/
│   ├── transport.py     ← OSC transport/tempo/play
│   ├── tracks.py        ← track add/remove/select
│   └── clips.py         ← clip create/note/clear
├── music/
│   ├── patterns/
│   │   ├── base.py      ← DrumPatternStrategy Protocol + DrumPattern NamedTuple
│   │   ├── kb_strategy.py  ← KBDrumPatternStrategy  (Finding 9 — Neo4j-backed)
│   │   └── fallback.py     ← HardcodedFallbackStrategy (nur wenn KB leer)
│   ├── song_builder.py  ← build_song (ohne Pattern-Logik)
│   └── sections.py      ← create_song_with_sections
└── knowledge/
    ├── kb_tool.py          ← query_bitwig_docs
    ├── rhythm_tool.py      ← get_rhythm_pattern  (Finding 9 — neues Tool)
    └── genre_tool.py       ← get_genre_overview
```

```python
# src/agent/tools/music/patterns/base.py
from typing import Protocol, NamedTuple

class DrumPattern(NamedTuple):
    kick:  list[tuple[float, float]]   # (step, velocity)
    snare: list[tuple[float, float]]
    hat:   list[tuple[float, float]]

class DrumPatternStrategy(Protocol):
    def generate(self, bpm: float, section: str, length_beats: int,
                 genre: str = "pop", energy: float = 0.7) -> DrumPattern: ...

# src/agent/tools/registry.py
from langchain_core.tools import BaseTool

_registry: dict[str, BaseTool] = {}

def register(tool: BaseTool) -> BaseTool:
    _registry[tool.name] = tool
    return tool

def get_all() -> list[BaseTool]:
    return list(_registry.values())
```

**Gewinn:** Jede Datei hat eine Verantwortung. `KBDrumPatternStrategy` (Finding 9) ist
die produktive Implementierung; `HardcodedFallbackStrategy` sichert den Betrieb auch
wenn die KB noch nicht befüllt ist.

---

## Finding 3 — Qualitätsscore misst das Falsche

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt
> - [`src/agent/quality/specs.py`](../../src/agent/quality/specs.py) — alle Specs aus dem Entwurf existieren: `TrackCountSpec`, `NoteCountSpec`, `ScaleConformanceSpec`, `VelocityDistributionSpec`, `DurationVarietySpec`
> - `CompositeQualitySpec` + `DEFAULT_QUALITY_SPEC`-Singleton mit Gewichten 0.20/0.25/0.30/0.15/0.10
> - Zusätzliche Helfer: `scale_pcs_from_hint()` für die ScaleConformanceSpec-Pitch-Class-Berechnung
>
> Code-Skizze unten und tatsächliche Implementierung sind quasi identisch.

**Pattern: Specification (Composite)**

Jedes Qualitätskriterium ist eine eigenständige Spezifikation mit Gewicht.
`CompositeQualitySpec` kombiniert sie zu einem gewichteten Gesamtscore.
Neue Kriterien (z.B. Dynamik-Verteilung) können ohne Änderung am bestehenden Code ergänzt werden.

```python
# src/agent/quality/specs.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass
class SongReport:
    track_count:    int
    expected_tracks: int
    notes:          list[dict]   # [{pitch, velocity, step, duration}]
    scale_pcs:      set[int]     # Pitch-Classes der Tonart (z.B. {0,2,4,5,7,9,11} für Dur)
    bpm:            float
    expected_notes: int

class QualitySpec(Protocol):
    weight: float
    def score(self, report: SongReport) -> float: ...   # 0.0 – 1.0
    def label(self) -> str: ...

class TrackCountSpec:
    weight = 0.20
    def score(self, r: SongReport) -> float:
        return 1.0 if r.track_count >= r.expected_tracks else r.track_count / r.expected_tracks
    def label(self) -> str: return "track_count"

class NoteCountSpec:
    weight = 0.25
    def score(self, r: SongReport) -> float:
        return min(len(r.notes) / max(r.expected_notes, 1), 1.0)
    def label(self) -> str: return "note_count"

class ScaleConformanceSpec:
    weight = 0.30
    def score(self, r: SongReport) -> float:
        if not r.notes or not r.scale_pcs:
            return 1.0
        in_scale = sum(1 for n in r.notes if (n["pitch"] % 12) in r.scale_pcs)
        return in_scale / len(r.notes)
    def label(self) -> str: return "scale_conformance"

class VelocityDistributionSpec:
    """Prüft ob Velocities musikalisch variiert sind (nicht alle gleich)."""
    weight = 0.15
    def score(self, r: SongReport) -> float:
        if len(r.notes) < 4:
            return 1.0
        vels = [n["velocity"] for n in r.notes]
        std  = (sum((v - sum(vels)/len(vels))**2 for v in vels) / len(vels)) ** 0.5
        return min(std / 0.15, 1.0)   # Ziel: stddev ≥ 0.15
    def label(self) -> str: return "velocity_distribution"

class DurationVarietySpec:
    weight = 0.10
    def score(self, r: SongReport) -> float:
        unique_dur = len({round(n["duration"], 2) for n in r.notes})
        return min(unique_dur / 3, 1.0)   # mind. 3 verschiedene Notenlängen
    def label(self) -> str: return "duration_variety"

class CompositeQualitySpec:
    def __init__(self, specs: list[QualitySpec]):
        self._specs = specs
        total_w = sum(s.weight for s in specs)
        self._norm = total_w or 1.0

    def evaluate(self, report: SongReport) -> tuple[float, dict[str, float]]:
        details = {s.label(): s.score(report) for s in self._specs}
        weighted = sum(details[s.label()] * s.weight for s in self._specs)
        return weighted / self._norm, details

# Instanz für verify_node:
DEFAULT_QUALITY_SPEC = CompositeQualitySpec([
    TrackCountSpec(), NoteCountSpec(), ScaleConformanceSpec(),
    VelocityDistributionSpec(), DurationVarietySpec(),
])
```

**Gewinn:** Der Score reflektiert tatsächliche Musikalität. Neue Kriterien kosten 10 Zeilen.

---

## Finding 4 — `is_concrete_track_task()` als Single Point of Failure

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt — abweichend vom Original-Entwurf
> - **Routing:** [`src/agent/router.py`](../../src/agent/router.py) — `_route_request()` klassifiziert in `song` vs. `control` mittels Tool-Name-Sets + Confirmation-Heuristik (kein LLM-Fallback nötig)
> - **Policy-Enforcement:** [`src/agent/policy.py`](../../src/agent/policy.py) — `enforce_policy_on_response()` filtert tote Tool-Calls heraus, extrahiert FX-Hints, klassifiziert Strict-FX und übergibt Kontext an den Agent. `is_concrete_track_task()` ist nicht mehr Single Source — nur eines von mehreren Signalen.
> - Das Chain-of-Responsibility-Pattern aus dem Entwurf wurde nicht 1:1 umgesetzt; statt drei Klassifizierern gibt es zwei Module (Router → Policy), die kombiniert dieselbe Robustheit liefern.

**Pattern: Chain of Responsibility**

Die Routing-Entscheidung läuft durch eine Kette von Klassifizierern.
Jeder Klassifizierer entscheidet oder gibt weiter (`None` = weiterreichen).
Keyword-Matching ist schnell und kostenlos; der LLM-Klassifizierer übernimmt nur bei Unklarheit.

```python
# src/agent/routing.py
from __future__ import annotations
from typing import Protocol

class TaskClassifier(Protocol):
    def classify(self, text: str) -> str | None: ...  # route-name oder None

class KeywordClassifier:
    _MASTER = {"erstell", "bau", "mach", "komponier", "schreib", "erzeug",
               "leg an", "füge hinzu", "riff", "beat", "song", "track"}
    _QUERY  = {"erkläre", "was ist", "zeig", "liste", "wie funktioniert",
               "welche", "gibt es", "beschreib"}

    def classify(self, text: str) -> str | None:
        lower = text.lower()
        if any(k in lower for k in self._MASTER):
            return "master_graph"
        if any(k in lower for k in self._QUERY):
            return "standard_agent"
        return None

class StructureClassifier:
    """Erkennt strukturelle Hinweise: Zahlen + Einheiten → konkreter Task."""
    import re
    _BPM  = re.compile(r"\d+\s*bpm", re.I)
    _BEAT = re.compile(r"\d+\s*(takte?|bars?|beats?)", re.I)

    def classify(self, text: str) -> str | None:
        if self._BPM.search(text) or self._BEAT.search(text):
            return "master_graph"
        return None

class LLMFallbackClassifier:
    """Letztes Mittel: ein schneller LLM-Aufruf mit 1-Token-Antwort."""
    def __init__(self, llm):
        self._llm = llm

    def classify(self, text: str) -> str | None:
        prompt = (
            "Classify the following user request.\n"
            "Reply with exactly one word: master_graph or standard_agent.\n\n"
            f"Request: {text}"
        )
        result = self._llm.invoke(prompt).content.strip().lower()
        return result if result in ("master_graph", "standard_agent") else "standard_agent"

class RouterChain:
    def __init__(self, classifiers: list[TaskClassifier]):
        self._chain = classifiers

    def route(self, text: str) -> str:
        for clf in self._chain:
            if route := clf.classify(text):
                return route
        return "standard_agent"

# Instanz:
# router = RouterChain([KeywordClassifier(), StructureClassifier(), LLMFallbackClassifier(llm)])
# route  = router.route(user_text)
```

**Gewinn:** Kein Single Point of Failure. Jede Stufe ist einzeln testbar und austauschbar.

---

## Finding 5 — Kein Circuit Breaker für Bitwig

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt — Code praktisch identisch zum Entwurf
> - [`src/agent/osc/circuit_breaker.py`](../../src/agent/osc/circuit_breaker.py) — `CircuitBreaker`-Dataclass mit `CLOSED`/`OPEN`/`HALF_OPEN`, `failure_threshold=3`, `recovery_timeout=30.0`
> - Globaler Singleton `get_circuit()` + `send_osc_guarded()`-Helper als Drop-in-Ersatz
> - HALF_OPEN-Übergang nach Recovery-Timeout für Probe-Calls
> - Manuelles `reset()` möglich

**Pattern: Circuit Breaker (Fowler)**

Drei Zustände: `CLOSED` (normal) → `OPEN` (Fehler häufen sich, Calls sofort ablehnen) →
`HALF_OPEN` (nach Timeout einen Probe-Call durchlassen). Verhindert die Retry-Lawine.

```python
# src/agent/osc/circuit_breaker.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
import time

class State(Enum):
    CLOSED    = auto()
    OPEN      = auto()
    HALF_OPEN = auto()

class CircuitOpenError(RuntimeError):
    """Bitwig nicht erreichbar — Circuit ist offen."""

@dataclass
class CircuitBreaker:
    failure_threshold: int   = 3
    recovery_timeout:  float = 30.0
    _state:    State = field(default=State.CLOSED, init=False)
    _failures: int   = field(default=0,            init=False)
    _opened:   float = field(default=0.0,          init=False)

    @property
    def state(self) -> State:
        if self._state is State.OPEN:
            if time.monotonic() - self._opened >= self.recovery_timeout:
                self._state = State.HALF_OPEN
        return self._state

    def call(self, fn, *args, **kwargs):
        if self.state is State.OPEN:
            raise CircuitOpenError("Bitwig-Circuit offen — bitte Verbindung prüfen")
        try:
            result = fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        self._failures = 0
        self._state    = State.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._state  = State.OPEN
            self._opened = time.monotonic()

# Globale Instanz — wird von allen Tools geteilt:
_bitwig_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

def send_osc_guarded(client, address: str, *args):
    """Drop-in-Ersatz für direkten client.send_message."""
    return _bitwig_circuit.call(client.send_message, address, list(args))
```

Integration in `build_song`:

```python
# Vor dem Saga-Start:
if _bitwig_circuit.state is State.OPEN:
    return "ERROR: Bitwig nicht erreichbar (Circuit offen). Bitte Verbindung prüfen."
```

**Gewinn:** Nach 3 aufeinanderfolgenden Fehlern werden keine weiteren 50 OSC-Pakete
ins Leere geschickt. Automatische Erholung nach 30 s.

---

## Finding 6 — `note_slave` ist keine echte Parallelisierung

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt — komplett anderer Lösungsweg
> - **Der duale Master-Graph wurde entfernt.** Es gibt nur noch *einen* schlanken LangGraph mit zwei Nodes (`agent` + `tools`) — siehe [`agent_flow.md`](agent_flow.md).
> - Das ursprüngliche Slave-Modell (instrument_slave/harmony_slave/note_slave) existiert nicht mehr.
> - Statt Pipeline-Parallelisierung steuert das LLM ReAct-style den Ablauf; lange Operationen werden auf Java-Seite per `stepQueue` getaktet — das eliminiert das Latenzproblem an der Wurzel.
> - Phase-Tracking via `generation_phase` in [`src/agent/state.py`](../../src/agent/state.py) (z.B. `note_retry`).
>
> Die Pipeline-Skizze unten ist **historisch** und beschreibt eine Architektur, die heute nicht mehr existiert.

**Pattern: Pipeline mit Partial-Fan-Out**

Drum-Pattern sind harmonisch unabhängig — sie können *parallel* zu `harmony_slave` starten.
Nur Melodie und Bass brauchen die Harmonie. Die Pipeline wird umstrukturiert:

```
                     ┌─ instrument_slave  ──────────────────────┐
fan_out ─────────────┤                                           ├─► assemble
                     ├─ harmony_slave  ──┬─► melody_note_slave ─┤
                     │                  └─► bass_note_slave   ──┤
                     └─ drum_slave  (harmonisch unabhängig) ────┘
```

```python
# src/agent/master_graph.py  (angepasster Graph-Aufbau)

from langgraph.types import Send

def fan_out_to_slaves(state: AgentState) -> list[Send]:
    return [
        Send("instrument_slave", state),
        Send("harmony_slave",    state),
        Send("drum_slave",       state),   # NEU — kein LLM, reine Pattern-Logik
    ]

def fan_out_melody_bass(state: AgentState) -> list[Send]:
    """Startet nach harmony_slave mit den nun bekannten Akkorden."""
    return [
        Send("melody_note_slave", state),
        Send("bass_note_slave",   state),
    ]

# Graph-Kanten:
builder.add_conditional_edges("fan_out_to_slaves", fan_out_to_slaves)
builder.add_edge("harmony_slave",  "fan_out_melody_bass")
builder.add_conditional_edges("fan_out_melody_bass", fan_out_melody_bass)

# drum_slave: reine Strategy-Auswahl, kein LLM-Aufruf
def drum_slave_node(state: AgentState) -> dict:
    strategy = _get_drum_strategy(state["slave_plan"]["genre"])  # Strategy-Pattern
    pattern  = strategy.generate(
        bpm=state["slave_plan"]["bpm"],
        section=state["slave_plan"].get("section", "verse"),
        length_beats=state["slave_plan"]["beat_count"],
    )
    return {"slave_results": [{"type": "drums", "pattern": pattern._asdict()}]}
```

**Gewinn:** `drum_slave` braucht keinen LLM-Call und ist damit sofort fertig.
Melody- und Bass-Slaves laufen danach parallel. Gesamtlatenz sinkt bei typischen
Requests um ~40 % (ein LLM-Call entfällt aus dem kritischen Pfad).

---

## Finding 7 — Qwen3 XML-Recovery als Workaround

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt
> - [`src/agent/parsing/tool_call_parsers.py`](../../src/agent/parsing/tool_call_parsers.py) — `CompositeToolCallParser` mit:
>   - `OpenAIFormatParser` (Standard-Tool-Calls)
>   - `QwenXMLParser` (vollständiges `<tool_call>...</tool_call>`)
>   - `TruncatedXMLParser` (NEU — repariert abgeschnittene XML-Fragmente, im Original-Entwurf nicht vorgesehen)
>   - `MarkdownCodeBlockParser` (\`\`\`json-Blöcke)
> - Globale Instanz `TOOL_CALL_PARSER` + `patch_message()` werden von [`src/agent/recovery.py`](../../src/agent/recovery.py) genutzt
> - `recovery.py` enthält zusätzlich Klassifikation (`_classify_invalid_output`) und einen LLM-Re-Prompt-Fallback (`_recover_xml_fragment_once`)

**Pattern: Adapter + Strategy (Parser-Chain)**

Die Parsing-Logik wird als austauschbare Strategie-Kette modelliert.
Jeder Parser versucht es; bei Misserfolg gibt er `None` zurück.
Das eliminiert die verstreuten `_recover_*`-Funktionen in `core.py`.

```python
# src/agent/parsing/tool_call_parsers.py
from __future__ import annotations
import json, re
from typing import Protocol
from langchain_core.messages import AIMessage

class ToolCallParser(Protocol):
    def parse(self, message: AIMessage) -> list[dict] | None: ...

class OpenAIFormatParser:
    """Standardfall: tool_calls direkt im AIMessage-Objekt."""
    def parse(self, msg: AIMessage) -> list[dict] | None:
        if msg.tool_calls:
            return [tc for tc in msg.tool_calls]
        return None

class QwenXMLParser:
    """Qwen3 gibt manchmal <tool_call>{...}</tool_call> als Fließtext."""
    _RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if not isinstance(msg.content, str):
            return None
        matches = self._RE.findall(msg.content)
        if not matches:
            return None
        result = []
        for raw in matches:
            try:
                data = json.loads(raw)
                result.append({"name": data["name"], "args": data.get("arguments", {})})
            except (json.JSONDecodeError, KeyError):
                continue
        return result or None

class MarkdownCodeBlockParser:
    """Fallback: JSON in ```json ... ``` Block."""
    _RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)

    def parse(self, msg: AIMessage) -> list[dict] | None:
        if not isinstance(msg.content, str):
            return None
        m = self._RE.search(msg.content)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
            return [{"name": data["name"], "args": data.get("arguments", {})}]
        except (json.JSONDecodeError, KeyError):
            return None

class CompositeToolCallParser:
    def __init__(self, parsers: list[ToolCallParser]):
        self._parsers = parsers

    def extract(self, msg: AIMessage) -> list[dict]:
        for parser in self._parsers:
            if result := parser.parse(msg):
                return result
        return []

# Instanz ersetzt alle _recover_*-Funktionen in core.py:
TOOL_CALL_PARSER = CompositeToolCallParser([
    OpenAIFormatParser(),
    QwenXMLParser(),
    MarkdownCodeBlockParser(),
])
```

**Gewinn:** `core.py` verliert ~80 Zeilen Workaround-Code.
Ein neues Modell erfordert nur einen neuen Parser, keine Änderung am Graphen.

---

## Finding 8 — Shared State zwischen zwei Graphen

> ✅ **Ist-Stand (Juni 2026):** Hinfällig durch Architektur-Vereinfachung
> - **Es gibt nur noch einen Graphen** → das geteilte State-Problem existiert nicht mehr.
> - [`src/agent/state.py`](../../src/agent/state.py) hat eine *einzige* `AgentState`-TypedDict mit klar dokumentierten Feldern (`messages`, `generation_phase`, `retry_count`, `ui_song_config`, `last_blueprint`, …).
> - Der vorgeschlagene `StateBuilder` mit zwei Subklassen wurde nicht benötigt — ein Graph braucht keine Trennung.
>
> Die Lösung unten beschreibt einen Zustand, den die Codebase nicht mehr hat.

**Pattern: State Object mit Typed Subclasses + Builder**

Felder für Standard Agent und Master Graph werden in separate TypedDicts getrennt.
Gemeinsame Basis in `BaseState`. Ein `StateBuilder` erzeugt den korrekten Typ je Route.

```python
# src/agent/state.py  (refaktoriert)
from __future__ import annotations
from typing import Annotated, Optional, TypedDict
from langgraph.graph.message import add_messages
from src.agent.state_types import GenerationPhase

class BaseState(TypedDict):
    """Felder, die beide Graphen brauchen."""
    messages:          Annotated[list, add_messages]
    generation_phase:  GenerationPhase
    retry_count:       int

class StandardAgentState(BaseState):
    """Nur für den Standard-ReAct-Agent."""
    ui_song_config:    Optional[dict]

class MasterGraphState(BaseState):
    """Nur für den parallelen Master-Graphen."""
    slave_plan:        Optional[dict]
    slave_results:     Annotated[list, _merge_slave_results]
    assembled_json:    Optional[str]
    retry_signal:      Optional[str]
    phase_quality_score: float
    retry_budget:      dict

# Builder verhindert, dass der falsche Graph falsche Felder sieht:
class StateBuilder:
    @staticmethod
    def standard(user_text: str, history: list) -> StandardAgentState:
        from langchain_core.messages import HumanMessage
        return StandardAgentState(
            messages=[*history, HumanMessage(content=user_text)],
            generation_phase=GenerationPhase.IDLE,
            retry_count=0,
            ui_song_config=None,
        )

    @staticmethod
    def master(user_text: str, history: list,
               ui_config: Optional[dict] = None) -> MasterGraphState:
        from langchain_core.messages import HumanMessage
        return MasterGraphState(
            messages=[*history, HumanMessage(content=user_text)],
            generation_phase=GenerationPhase.PLANNING,
            retry_count=0,
            slave_plan=None,
            slave_results=[],
            assembled_json=None,
            retry_signal=None,
            phase_quality_score=0.0,
            retry_budget={"instrument": 2, "harmony": 2, "notes": 3},
        )
```

**Gewinn:** Typ-Checker (`mypy`/Pylance) warnt sofort, wenn ein Master-Graph-Node
auf `ui_song_config` zugreift oder ein Standard-Agent-Node `slave_plan` liest.

---

---

## Finding 9 — LLM als Dispatcher statt Reasoning-Engine

> 🟡 **Ist-Stand (Juni 2026):** Größtenteils umgesetzt
> - ✅ **Repositories:** [`src/knowledge/repositories.py`](../../src/knowledge/repositories.py) — `DrumPatternRepository`, `DrumSoundRepository`, `GenrePatternRepository` (sowie `ProjectSnapshotRepository`, `ProjectTemplateRepository`, `WorkflowRepository`)
> - ✅ **LLM-Tool:** [`src/agent/tools/knowledge/rhythm_tool.py`](../../src/agent/tools/knowledge/rhythm_tool.py) — `get_rhythm_pattern(genre, section, energy, mood)`
> - ✅ **KB befüllt:** Neo4j enthält 4722 Nodes, davon 168 `DIATONIC_CHORD`-Beziehungen und Genre/Pattern-Daten (siehe [`project_overview.md`](project_overview.md))
> - ✅ **`DRUM_PROFILES`-Dict entfernt** aus dem Produktivpfad
> - ⏳ **Noch offen:** Vollständige Strategy-Klasse (`KBDrumPatternStrategy` in `tools/music/patterns/`) — die `pattern_generators.py` enthält noch Hardcoded-Fallbacks für den KB-Lückenfall.
> - ⏳ **Retrieve-Then-Reason im System-Prompt:** Teilweise umgesetzt in [`src/agent/prompts.py`](../../src/agent/prompts.py); explizite `<think>`-Beispiele wie im Entwurf fehlen aber.

**Pattern: Repository + Retrieve-Then-Reason**

### Das Problem

Alle musikalischen Entscheidungen (Drum-Pattern, MIDI-Pitches, Velocities, Genre-Mapping)
sind in Python-Dicts hardcodiert. Das LLM extrahiert nur Genre und BPM aus dem User-Prompt
und wählt dann ein vordefiniertes Template — es *denkt* nicht über Musik nach.

```python
# Heute: LLM routet nur, Python entscheidet
genre = llm.extract("rock")             # einzige LLM-Arbeit
pattern = DRUM_PROFILES["rock"]["verse"] # Python-Dict, immer gleich
```

Das `<think>`-Token von Qwen3 bleibt ungenutzt, weil es keine Entscheidung zu treffen gibt.

### Lösung Teil A — Neo4j-Schema für musikalisches Wissen

```cypher
// Statt DRUM_PROFILES-Dict — in KB-Migration-Skript anlegen:
CREATE (:DrumPattern {
    genre:       "rock",
    section:     "verse",
    kick_beats:  [0.0, 2.0, 4.0, 6.0],
    snare_beats: [2.0, 6.0],
    hat_step:    0.5,
    hat_vel_on:  0.52,
    hat_vel_off: 0.38,
    kick_vel:    0.88,
    snare_vel:   0.82,
    energy:      0.70,
    mood:        "driving",
    description: "Straight rock beat, moderate energy, 8th-note hat"
});

CREATE (:DrumPattern {
    genre: "rock", section: "chorus",
    kick_beats:  "4floor",
    snare_beats: [2.0, 6.0],
    hat_step:    0.25,
    kick_vel:    0.95, snare_vel: 0.92,
    energy:      0.92,
    mood:        "energetic",
    description: "4-on-the-floor kick, 16th-note hat — peak energy"
});

// Statt Magic Numbers (36/38/42/46/49):
CREATE (:DrumSound {name: "kick",       gm_pitch: 36, description: "Bass Drum 1"});
CREATE (:DrumSound {name: "snare",      gm_pitch: 38, description: "Acoustic Snare"});
CREATE (:DrumSound {name: "closed_hat", gm_pitch: 42, description: "Closed Hi-Hat"});
CREATE (:DrumSound {name: "open_hat",   gm_pitch: 46, description: "Open Hi-Hat"});
CREATE (:DrumSound {name: "crash",      gm_pitch: 49, description: "Crash Cymbal 1"});

// Velocity-Profile — statt hardcodierter Floats:
CREATE (:VelocityProfile {
    context:     "aggressive_chorus",
    kick_vel:    0.95,
    snare_vel:   0.92,
    ghost_ratio: 0.48,
    description: "High energy, punchy — metal/hard rock chorus"
});
CREATE (:VelocityProfile {
    context:     "mellow_verse",
    kick_vel:    0.65,
    snare_vel:   0.60,
    ghost_ratio: 0.70,
    description: "Soft, organic — acoustic/introspective"
});
```

### Lösung Teil B — Repository Pattern (KB-Zugriff)

```python
# src/knowledge/repositories.py
from __future__ import annotations
from dataclasses import dataclass
from src.knowledge.neo4j_graph import session

@dataclass
class DrumPatternRecord:
    kick_beats:  list[float] | str   # float-Liste oder "4floor"/"double"
    snare_beats: list[float]
    hat_step:    float
    hat_vel_on:  float
    hat_vel_off: float
    kick_vel:    float
    snare_vel:   float
    energy:      float
    description: str

class DrumPatternRepository:
    def find(self, genre: str, section: str,
             energy_max: float = 1.0, mood: str = "") -> DrumPatternRecord | None:
        with session() as s:
            result = s.run("""
                MATCH (p:DrumPattern)
                WHERE toLower(p.genre)   = toLower($genre)
                  AND toLower(p.section) = toLower($section)
                  AND p.energy           <= $energy_max
                  AND ($mood = '' OR toLower(p.mood) CONTAINS toLower($mood))
                RETURN p
                ORDER BY abs(p.energy - $energy_max)
                LIMIT 1
            """, genre=genre, section=section, energy_max=energy_max, mood=mood)
            row = result.single()
            if row is None:
                return None
            p = row["p"]
            return DrumPatternRecord(**{k: p[k] for k in DrumPatternRecord.__dataclass_fields__})

class DrumSoundRepository:
    _cache: dict[str, int] = {}

    def pitch(self, sound_name: str) -> int:
        if sound_name not in self._cache:
            with session() as s:
                row = s.run(
                    "MATCH (d:DrumSound {name: $n}) RETURN d.gm_pitch AS p",
                    n=sound_name,
                ).single()
                self._cache[sound_name] = row["p"] if row else {"kick":36,"snare":38}.get(sound_name, 38)
        return self._cache[sound_name]
```

### Lösung Teil C — KB-backed Strategy (verbindet Finding 2 + 9)

```python
# src/agent/tools/music/patterns/kb_strategy.py
from src.knowledge.repositories import DrumPatternRepository, DrumSoundRepository
from src.agent.tools.music.patterns.base import DrumPattern, DrumPatternStrategy
from src.agent.tools.music.patterns.fallback import HardcodedFallbackStrategy

class KBDrumPatternStrategy:
    """Liest Pattern aus Neo4j — kein hardcodierter Wert mehr im Produktivpfad."""

    def __init__(self):
        self._patterns = DrumPatternRepository()
        self._sounds   = DrumSoundRepository()
        self._fallback = HardcodedFallbackStrategy()   # nur wenn KB leer

    def generate(self, bpm: float, section: str, length_beats: int,
                 genre: str = "pop", energy: float = 0.7) -> DrumPattern:
        rec = self._patterns.find(genre=genre, section=section, energy_max=energy)
        if rec is None:
            return self._fallback.generate(bpm, section, length_beats, genre=genre)

        kick_p  = self._sounds.pitch("kick")
        snare_p = self._sounds.pitch("snare")
        hat_p   = self._sounds.pitch("closed_hat")

        kick_beats = (
            [b for b in range(int(length_beats))]           # "4floor"
            if rec.kick_beats == "4floor"
            else [b * 0.5 for b in range(int(length_beats * 2))]  # "double"
            if rec.kick_beats == "double"
            else rec.kick_beats
        )

        kick  = [(b, rec.kick_vel)  for b in kick_beats  if b < length_beats]
        snare = [(b, rec.snare_vel) for b in rec.snare_beats if b < length_beats]
        hat   = [(round(i * rec.hat_step, 4),
                  rec.hat_vel_on if i % 2 == 0 else rec.hat_vel_off)
                 for i in range(int(length_beats / rec.hat_step))]

        return DrumPattern(
            kick  =[(b, v, kick_p)  for b, v in kick],
            snare =[(b, v, snare_p) for b, v in snare],
            hat   =[(b, v, hat_p)   for b, v in hat],
        )
```

### Lösung Teil D — Neues LLM-Tool `get_rhythm_pattern`

```python
# src/agent/tools/knowledge/rhythm_tool.py
import json
from langchain_core.tools import tool
from src.knowledge.repositories import DrumPatternRepository, DrumSoundRepository

@tool
def get_rhythm_pattern(genre: str, section: str,
                       energy: float = 0.7, mood: str = "") -> str:
    """
    Liest ein Drum-Pattern aus der Wissensdatenbank.
    Immer aufrufen bevor Drum-Noten geschrieben werden — nie hardcodierte Werte verwenden.

    Args:
        genre:   Musikgenre (rock, metal, jazz, pop, blues ...)
        section: Song-Abschnitt (intro, verse, chorus, solo, outro)
        energy:  Energie-Level 0.0–1.0 (0.3 = ruhig, 0.9 = aggressiv)
        mood:    Optionale Stimmung (introspective, aggressive, driving ...)
    """
    repo = DrumPatternRepository()
    sounds = DrumSoundRepository()
    rec = repo.find(genre=genre, section=section, energy_max=energy, mood=mood)

    if rec is None:
        return (f"Kein Pattern für genre='{genre}' section='{section}' in KB. "
                f"Bitte energy oder genre anpassen oder get_genre_overview aufrufen.")

    return json.dumps({
        "description":  rec.description,
        "energy":       rec.energy,
        "kick_beats":   rec.kick_beats,
        "snare_beats":  rec.snare_beats,
        "hat_step":     rec.hat_step,
        "velocities": {
            "kick":  rec.kick_vel,
            "snare": rec.snare_vel,
            "hat_on":  rec.hat_vel_on,
            "hat_off": rec.hat_vel_off,
        },
        "midi_pitches": {
            "kick":       sounds.pitch("kick"),
            "snare":      sounds.pitch("snare"),
            "closed_hat": sounds.pitch("closed_hat"),
            "open_hat":   sounds.pitch("open_hat"),
            "crash":      sounds.pitch("crash"),
        },
    }, indent=2)
```

### Lösung Teil E — System-Prompt: Retrieve-Then-Reason

Der Prompt muss das LLM anweisen, KB-Daten **vor** Entscheidungen abzufragen und
sein `<think>`-Block für musikalische Begründungen zu nutzen:

```python
# src/agent/prompts.py — ergänzende Sektion
RHYTHM_REASONING_INSTRUCTION = """
## Drum-Pattern-Regel (immer befolgen)

Bevor du Drum-Noten schreibst:
1. Rufe `get_rhythm_pattern(genre=..., section=..., energy=...)` auf
2. Nutze den <think>-Block um zu begründen:
   - Warum passt dieser energy-Wert zur Nutzeranfrage?
   - Entspricht die KB-Beschreibung der gewünschten Stimmung?
   - Muss ich das Pattern für diesen spezifischen Song anpassen?
3. Verwende ausschließlich die midi_pitches aus der KB-Antwort — niemals 36/38/42 hardcoden

Beispiel-Thinking für "introspektiver Rock-Song":
<think>
Der Nutzer möchte introspektiv/nachdenklich. Standardmäßig würde rock/verse
energy=0.7 liefern (driving). Ich frage mit energy=0.4 und mood="introspective"
um ein ruhigeres Pattern zu bekommen. Die KB gibt hat_step=1.0 zurück —
halbe Noten statt Achtel, das erzeugt den gewünschten Atem-Raum.
</think>
"""
```

### Abdeckung durch bisherige Findings

| Finding | Unterstützt F9? | Lücke ohne F9 |
|---------|-----------------|----------------|
| F2 Strategy | Schnittstelle ✓ | Implementations bleiben hardcodiert |
| F3 Quality Spec | `scale_pcs` braucht KB | `ScaleRepository` fehlt noch |
| F6 Pipeline | `drum_slave` nutzt Strategy | Strategy-Impl. noch nicht KB-backed |
| F1–F8 sonst | Nicht relevant | — |

> **F9 löst Drum-Pattern + MIDI-Pitches + Velocities.**
> Die Instrument-Auswahl (welches Bitwig-Device für welche Rolle) bleibt
> weiterhin hardcodiert — das adressiert Finding 10.

---

## Finding 10 — Instrument-Auswahl hardcodiert statt LLM-gesteuert

> 🟡 **Ist-Stand (Juni 2026):** Größtenteils umgesetzt
> - ✅ **Repository:** `InstrumentRepository` + `InstrumentRecord` in [`src/knowledge/repositories.py`](../../src/knowledge/repositories.py) mit `find()` + `find_best()`
> - ✅ **LLM-Tool:** [`src/agent/tools/knowledge/instrument_tool.py`](../../src/agent/tools/knowledge/instrument_tool.py) — `get_instruments_for_song(genre, roles, mood, energy)`
> - ✅ **KB-Schema:** `InstrumentTemplate`-Nodes in Neo4j mit `role`, `device_name`, `uuid`, `genres`, `not_for`, `moods`, `description` (389 Devices gescannt)
> - ✅ **VST-Scanner:** [`src/knowledge/vst_scanner.py`](../../src/knowledge/vst_scanner.py) erweitert die KB um VST3-Devices
> - ⏳ **Noch offen:** Restliche `INSTRUMENT_MAP`-Fallbacks im Code; vollständiger LLM-`<think>`-Begründungs-Prompt im System-Prompt.

**Pattern: Repository + Retrieve-Then-Reason (Instrument-Ebene)**

### Das Problem

Das LLM entscheidet nicht, welche Instrumente verwendet werden — Python entscheidet:

```python
# master_graph.py:57–68 — statisches Dict, keine Reasoning-Möglichkeit
INSTRUMENT_MAP = {
    "phase-4":  "Phase-4",
    "guitar":   "Phase-4",    # ← falsch: Phase-4 ist kein Gitarren-Synth
    "gitarre":  "Phase-4",    # ← falsch
    "organ":    "Phase-4",    # ← falsch
    "lead":     "FM-4",
    "sampler":  "Sampler",
}

# instrument_registry.py — 6 Rollen, 10 Devices, alles fest verdrahtet
# Polymer und Surge XT sind in der KB, werden aber nie ausgewählt
# E-Kick/Snare/HiHat sind in der KB, v9-Serie wird immer bevorzugt
# Bitwig-Bibliothek (100+ Devices) ist dem Agent vollständig unbekannt
```

### Lösung Teil A — Neo4j-Schema: InstrumentTemplate-Nodes

```cypher
// Migration aus instrument_registry.py + Erweiterung
// Jedes Device bekommt: Rolle, Genre-Eignung, Stimmungs-Tags, Suitability

CREATE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Phase-4",
    uuid:             "252723bf-68a6-4ee6-81f8-95ba4d0fb467",
    midi_low:         48,   midi_high:  84,
    default_velocity: 0.65,
    genres:           ["pop", "rock", "electronic", "metal", "trap"],
    not_for:          ["jazz", "classical", "acoustic", "bossa nova"],
    moods:            ["driving", "energetic", "dark", "modern"],
    description:      "Phase modulation synth — suits electronic and rock contexts"
});

CREATE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Piano",
    uuid:             null,           // Browser-Load
    midi_low:         36,   midi_high: 96,
    default_velocity: 0.60,
    genres:           ["jazz", "classical", "bossa nova", "blues", "soul", "acoustic"],
    not_for:          ["metal", "trap", "dubstep"],
    moods:            ["mellow", "introspective", "warm", "organic"],
    description:      "Acoustic piano — natürlicher Klang für organische Genres"
});

CREATE (:InstrumentTemplate {
    role:             "chords",
    device_name:      "Polymer",
    uuid:             null,
    midi_low:         48,   midi_high: 84,
    default_velocity: 0.62,
    genres:           ["ambient", "cinematic", "new age", "electronic"],
    moods:            ["atmospheric", "evolving", "spacious"],
    description:      "Wavetable synth — breite Pads und atmosphärische Sounds"
});

CREATE (:InstrumentTemplate {
    role:             "lead",
    device_name:      "FM-4",
    uuid:             "7a0a94df-3aa4-4bb5-8e24-2511999871ad",
    midi_low:         55,   midi_high: 88,
    default_velocity: 0.72,
    genres:           ["electronic", "metal", "dubstep", "jazz", "rock"],
    moods:            ["bright", "aggressive", "metallic", "funky"],
    description:      "FM synthesis — charakteristischer metallischer Sound"
});

CREATE (:InstrumentTemplate {
    role:             "lead",
    device_name:      "Surge XT",
    uuid:             null,
    midi_low:         48,   midi_high: 96,
    default_velocity: 0.68,
    genres:           ["rock", "metal", "cinematic", "electronic"],
    moods:            ["powerful", "rich", "complex"],
    description:      "Hybrid synth — vielseitig für Lead und Pad-Sounds"
});

// Drum-Devices: E-Serie vs v9-Serie — LLM wählt nach Genre
CREATE (:InstrumentTemplate {
    role:        "kick",
    device_name: "v9 Kick",
    uuid:        "32a4c607-039a-4998-be9c-578468f25454",
    midi_low: 36, midi_high: 36, default_velocity: 0.88,
    genres:      ["pop", "rock", "metal", "trap", "electronic"],
    moods:       ["punchy", "modern", "tight"],
    description: "Elektronischer Kick — modern und präzise"
});

CREATE (:InstrumentTemplate {
    role:        "kick",
    device_name: "E-Kick",
    uuid:        null,
    midi_low: 36, midi_high: 36, default_velocity: 0.80,
    genres:      ["jazz", "blues", "soul", "acoustic", "bossa nova"],
    moods:       ["organic", "warm", "natural"],
    description: "Akustischer Kick — natürlicher Vintage-Sound"
});

// Vollständige Migration aller Einträge aus instrument_registry.py analog...
```

### Lösung Teil B — InstrumentRepository

```python
# src/knowledge/repositories.py  (Erweiterung)
from dataclasses import dataclass
from typing import Optional

@dataclass
class InstrumentRecord:
    role:             str
    device_name:      str
    uuid:             Optional[str]
    midi_low:         int
    midi_high:        int
    default_velocity: float
    description:      str

class InstrumentRepository:
    def find(self, role: str, genre: str,
             mood: str = "", limit: int = 3) -> list[InstrumentRecord]:
        """Gibt bis zu `limit` passende Devices für Rolle + Genre zurück."""
        with session() as s:
            result = s.run("""
                MATCH (t:InstrumentTemplate {role: $role})
                WHERE ($genre = '' OR $genre IN t.genres)
                  AND NOT ($genre IN coalesce(t.not_for, []))
                  AND ($mood = '' OR $mood IN coalesce(t.moods, []))
                RETURN t
                ORDER BY
                    CASE WHEN $genre IN t.genres THEN 0 ELSE 1 END,
                    t.default_velocity DESC
                LIMIT $limit
            """, role=role, genre=genre.lower(),
                 mood=mood.lower(), limit=limit)
            return [
                InstrumentRecord(
                    role=row["t"]["role"],
                    device_name=row["t"]["device_name"],
                    uuid=row["t"].get("uuid"),
                    midi_low=row["t"]["midi_low"],
                    midi_high=row["t"]["midi_high"],
                    default_velocity=row["t"]["default_velocity"],
                    description=row["t"]["description"],
                )
                for row in result
            ]

    def find_best(self, role: str, genre: str, mood: str = "") -> InstrumentRecord | None:
        results = self.find(role, genre, mood, limit=1)
        return results[0] if results else None
```

### Lösung Teil C — Neues LLM-Tool `get_instruments_for_song`

```python
# src/agent/tools/knowledge/instrument_tool.py
import json
from langchain_core.tools import tool
from src.knowledge.repositories import InstrumentRepository

@tool
def get_instruments_for_song(
    genre: str,
    roles: list[str],
    mood: str = "",
    energy: float = 0.7,
) -> str:
    """
    Wählt die passenden Bitwig-Devices für jeden Track aus der Wissensdatenbank.

    Immer aufrufen bevor Tracks angelegt werden — niemals Device-Namen hardcoden
    oder aus internen Mappings (INSTRUMENT_MAP) nehmen.

    Das LLM soll anhand der zurückgegebenen Optionen und Beschreibungen
    begründet entscheiden, welches Device am besten zur Anfrage passt.

    Args:
        genre:  Musikgenre (rock, metal, jazz, pop, blues, electronic ...)
        roles:  Benötigte Rollen z.B. ["kick","snare","hihat","bass","chords","lead"]
        mood:   Stimmung der Anfrage (introspective, aggressive, warm, dark ...)
        energy: Energie-Level 0.0–1.0 — beeinflusst default_velocity-Gewichtung
    """
    repo = InstrumentRepository()
    result = {}

    for role in roles:
        options = repo.find(role=role, genre=genre, mood=mood, limit=3)
        if not options:
            result[role] = {"error": f"Kein Device für role='{role}' genre='{genre}' in KB"}
        else:
            result[role] = [
                {
                    "device_name":      opt.device_name,
                    "uuid":             opt.uuid,
                    "midi_range":       [opt.midi_low, opt.midi_high],
                    "default_velocity": opt.default_velocity,
                    "description":      opt.description,
                }
                for opt in options
            ]

    return json.dumps(result, indent=2, ensure_ascii=False)
```

### Lösung Teil D — Prompt: LLM trifft die Instrument-Entscheidung

```python
# src/agent/prompts.py — ergänzende Sektion
INSTRUMENT_REASONING_INSTRUCTION = """
## Instrument-Auswahl-Regel (immer befolgen)

Bevor du einen Song oder Tracks aufbaust:
1. Rufe `get_instruments_for_song(genre=..., roles=[...], mood=..., energy=...)` auf
2. Die KB liefert bis zu 3 Optionen pro Rolle mit Beschreibung
3. Nutze den <think>-Block um für jede Rolle zu begründen:
   - Welche Option passt am besten zur Nutzeranfrage und warum?
   - Gibt es Widersprüche zwischen Genre-Default und der konkreten Anfrage?
   - Soll ein ungewöhnlicheres Device gewählt werden (z.B. Polymer statt Phase-4)?
4. Verwende device_name und uuid aus der KB-Antwort — niemals eigene Device-Namen erfinden

Beispiel-Thinking für "melancholischer Jazz-Ballad":
<think>
Genre = jazz, mood = melancholic, energy = 0.35.
KB gibt für role="chords": [Piano (warm/organic), Phase-4 (modern/driving)].
Piano passt deutlich besser — "warm" und "organic" treffen die Stimmung.
Phase-4 ist für Jazz als "not_for" markiert.

Für role="lead": FM-4 (metallic/bright) vs. FM-4 nochmal mit Jazz-Preset.
KB gibt nur FM-4 zurück — ich wähle es mit niedrigerer velocity (0.55 statt 0.72)
um den melancholischen Charakter zu verstärken.

Für role="kick": E-Kick (organic/warm) ist für Jazz besser als v9 Kick (punchy/modern).
KB bestätigt: v9 Kick ist für Jazz als "not_for" markiert.
</think>
```

### Lösung Teil E — `scan_bitwig_devices.py` in KB-Migration einbinden

Das Script muss einmalig gegen laufendes Bitwig ausgeführt werden und die
gescannten Devices als `InstrumentTemplate`-Nodes in Neo4j anlegen — mit
automatischer Kategorisierung über die bestehende `categorize()`-Funktion:

```python
# scripts/scan_bitwig_devices.py — ingest_devices() erweitern
def ingest_devices(catalog: list[dict]) -> int:
    from src.knowledge.neo4j_graph import session
    count = 0
    with session() as s:
        for entry in catalog:
            name = entry.get("name", "").strip()
            if not name:
                continue
            dtype, cat, bpath = categorize(name)

            # Gerät als Device-Node (bisheriges Verhalten)
            s.run(
                "MERGE (d:Device {name: $name}) "
                "SET d.type=$type, d.category=$category, d.browser_path=$bpath",
                name=name, type=dtype, category=cat, bpath=bpath,
            )

            # NEU: Gerät auch als InstrumentTemplate anlegen (wählbar durch LLM)
            role = _infer_role(name, cat)
            if role:
                s.run("""
                    MERGE (t:InstrumentTemplate {device_name: $name, role: $role})
                    SET t.category     = $cat,
                        t.browser_path = $bpath,
                        t.source       = 'bitwig_scan',
                        t.scanned_at   = datetime()
                """, name=name, role=role, cat=cat, bpath=bpath)
            count += 1
    return count

def _infer_role(name: str, category: str) -> str | None:
    key = name.lower()
    if category == "drum_synth":
        if "kick" in key: return "kick"
        if "snare" in key: return "snare"
        if "hat" in key: return "hihat"
        if "clap" in key: return "snare"
    if category == "synthesizer": return "lead"
    if category == "sampler":     return "bass"
    return None
```

### Was das LLM danach kann

```
User: "Gitarren-lastiger Rock-Song, aggressiv"

<think>
genre=rock, mood=aggressive, energy=0.85
→ get_instruments_for_song(genre="rock", roles=["chords","lead","bass"], mood="aggressive")

KB gibt zurück:
  chords: [Phase-4 (driving/modern ✓), Polymer (atmospheric — passt nicht)]
  lead:   [FM-4 (aggressive ✓), Surge XT (powerful ✓)]
  bass:   [Polysynth (standard), Polysynth mit low MIDI-Range für Drop-Tuning]

Entscheidung:
  chords → Phase-4 mit Distortion-FX (KB: "Phase-4 RECOMMENDED_WITH Distortion")
  lead   → FM-4 (aggressive, metallic — passt zur Anfrage)
  bass   → Polysynth, midi_low=28 (Drop-D Stimmung für aggressiven Rock)

NICHT: guitar → Phase-4 aus hardcodiertem Dict
SONDERN: Phase-4, weil KB "rock + aggressive" bestätigt und Distortion empfiehlt
</think>
```

### Abdeckung: F9 + F10 zusammen

| Problem | F9 | F10 |
|---------|:--:|:---:|
| DRUM_PROFILES hardcodiert | ✓ | — |
| MIDI-Pitches als Magic Numbers | ✓ | — |
| Velocity-Werte hardcodiert | ✓ | — |
| `guitar → Phase-4` falsches Mapping | — | ✓ |
| Polymer/Surge XT nie gewählt | — | ✓ |
| E-Kick vs. v9 Kick — LLM entscheidet | — | ✓ |
| `instrument_registry.py` hardcodiert | — | ✓ |
| Bitwig-Scan → InstrumentTemplates | — | ✓ |
| LLM begründet Instrument-Wahl | — | ✓ |

---

## Finding 11 — OSC-Protokoll: Fehlende ACKs und Browser-Polling

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt — durch das neue Step-Protokoll
> - **Step-Protokoll** ersetzt einzelne ACK-Endpoints: jeder Step in der `BitwigStepPluginExtension`-Queue meldet `/step/done` an Python (Port 9002) zurück. Siehe [`bitwig_llm_communication.md`](bitwig_llm_communication.md) für Sequenz und Step-Typen-Tabelle.
> - **Browser-Observer:** Statt Countdown wird auf Bitwig-Browser-Status gewartet, bevor der nächste Step ausgeführt wird (`host.scheduleTask` mit Polling-Pause).
> - **Batch-Notes:** Steps vom Typ `note`/`pattern` werden vom Java-Code in einem Durchgang in den Clip geschrieben — kein 50-fach-OSC mehr.
> - **Status-Check:** Step-Typ `status_check` liefert `trackCount`, `tempo`, `playing` zurück — Python kann am Anfang von `build_song` querien.
>
> Die Code-Skizzen unten beschreiben einen früheren OSC-Reply-basierten Ansatz; die Endlösung ist abstrakter (jeder Step liefert ACK, kein endpoint-spezifisches Reply-Schema).

**Pattern: Observer + ACK-Reply + Batch-Command**

### Revidierte Bewertung

> OSC über Loopback (`127.0.0.1`) ist für dieses Projekt **vertretbar** — auf demselben
> Rechner gibt es keinen UDP-Paketverlust und keine Reihenfolgeprobleme.
> Das ist kein Netzwerk, sondern Kernel-IPC.
>
> Die Extension ist **keine Drittanbieter-Lösung** (DrivenByMoss o.ä.) sondern
> vollständig eigener Code mit direktem Zugriff auf die Bitwig Extension API.
> Sie enthält bereits 146 Built-in UUIDs für direktes `insertBitwigDevice()` —
> das ist der richtige Weg und funktioniert zuverlässig.
>
> **Die eigentlichen Probleme sind drei gezielte Lücken in der Extension selbst,
> kein Protokollproblem.**

### Problem 1 — Browser-Polling mit Countdown statt Observer

```java
// BitwigAgentBridgeExtension.java:1166-1169 — fragiler Guess
if (loadWaitLeft > 0) {
    loadWaitLeft--;   // "warte 3 Frames" ohne Zustandscheck
    return;
}
```

Für VST-Plugins und Presets, die nicht in den 146 UUIDs sind, wartet `flush()`
eine feste Anzahl von Zyklen — unabhängig davon ob der Browser tatsächlich bereit ist.

**Lösung: Observer auf `popupBrowser.exists()`**

```java
// In init() einmalig registrieren:
popupBrowser.exists().addValueObserver(isOpen -> {
    if (!isOpen && pendingLoadName != null) {
        // Browser hat sich geschlossen → Load abgeschlossen oder abgebrochen
        boolean ok = lastCommittedName != null &&
                     lastCommittedName.contains(pendingLoadName);
        sendReply(replyConn, "/browser/device/loaded",
                  pendingLoadName, ok ? 1 : 0);
        pendingLoadName    = null;
        lastCommittedName  = null;
    }
});

// cursorResult-Name beobachten um lastCommittedName zu setzen:
cursorResult.name().addValueObserver(name -> lastCommittedName = name);
```

Damit kann Python auf `/browser/device/loaded` warten statt blind zu schlafen.

### Problem 2 — Write-Operationen ohne ACK

Python schreibt 50 Noten via `/clip/note/beat` und bekommt keine Bestätigung.
Der Note-Counter (`noteCountMap`) existiert, wird aber nie aktiv zurückgemeldet.

**Lösung: ACK nach Batch-Schreiben**

```java
// Neuer Endpoint: /clip/notes/write <json_array>
// Schreibt alle Noten in einem Call und antwortet mit Anzahl
space.registerMethod("/clip/notes/write", "*", "Batch write notes + ACK",
    (src, msg) -> {
        String json = argStr(msg, 0);
        if (json == null || json.isBlank()) return;

        int written = 0;
        try {
            // Minimaler JSON-Parser: [{step,pitch,vel,dur}, ...]
            written = parseAndWriteNoteBatch(json);
        } catch (Exception e) {
            host.println("[BitwigAgent] Batch-Fehler: " + e.getMessage());
            sendReply(src, "/clip/notes/written", 0, "error: " + e.getMessage());
            return;
        }

        // Track-Name für noteCountMap
        String tn = cursorTrack.name().get();
        if (tn != null && !tn.isEmpty()) {
            noteCountMap.merge(tn, written, Integer::sum);
        }
        sendReply(src, "/clip/notes/written", written, tn != null ? tn : "");
        host.println("[BitwigAgent] Batch: " + written + " Noten auf '" + tn + "'");
    });

private int parseAndWriteNoteBatch(String json) {
    // Format: [{"step":0.0,"pitch":36,"vel":0.88,"dur":0.25}, ...]
    int count = 0;
    // einfacher Regex-freier Parser für das feste Format:
    for (String entry : json.replace("[","").replace("]","").split("\\},\\{")) {
        entry = entry.replace("{","").replace("}","").trim();
        if (entry.isBlank()) continue;
        Map<String, Double> fields = parseSimpleJsonObject(entry);
        int   step  = (int) Math.round(fields.getOrDefault("step",  0.0) / 0.25);
        int   pitch = fields.getOrDefault("pitch", 60.0).intValue();
        float vel   = fields.getOrDefault("vel",   0.8).floatValue();
        float dur   = fields.getOrDefault("dur",   0.25).floatValue();
        if (step < 0 || step >= CLIP_STEPS || pitch < 0 || pitch >= 128) continue;
        int velInt = Math.max(1, Math.min(127, (int)(vel * 127)));
        cursorClip.setStep(0, step, pitch, velInt, (double) dur);
        count++;
    }
    return count;
}
```

**Python-Seite — statt 50 einzelner OSC-Nachrichten:**

```python
# src/agent/tools/bitwig/clips.py
import json, time
from pythonosc import udp_client

def write_notes_batch(notes: list[dict], timeout: float = 5.0) -> int:
    """
    Schreibt alle Noten in einem einzigen OSC-Call und wartet auf ACK.
    Gibt die Anzahl tatsächlich geschriebener Noten zurück.
    """
    payload = json.dumps(notes)
    _osc_client.send_message("/clip/notes/write", payload)

    # Auf /clip/notes/written warten (OSC reply listener)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (count := _reply_buffer.pop("/clip/notes/written", None)) is not None:
            return count
        time.sleep(0.02)
    raise TimeoutError(f"Kein ACK für {len(notes)} Noten nach {timeout}s")
```

### Problem 3 — Fehlende Zustandsabfrage vor `build_song`

`/agent/status` existiert bereits und gibt `trackCount`, `isPlaying`, `tempo` zurück —
wird aber in `build_song` nie aufgerufen. Der Circuit Breaker (F5) ist die Python-Seite;
der Extension-Status-Check ist die Bitwig-Seite.

**Lösung: Python ruft `/agent/status` am Anfang jedes `build_song`-Calls ab**

```python
# src/agent/tools/music/song_builder.py
def build_song(project_json: str) -> str:
    # Schritt 0: Zustand prüfen bevor irgendwas passiert
    status = _query_bitwig_status(timeout=2.0)
    if status is None:
        return "ERROR: Bitwig nicht erreichbar — /agent/status timeout"

    if status["playing"]:
        _osc.send_message("/transport/stop", 1)
        time.sleep(0.2)

    # Jetzt erst: Saga starten
    ...
```

### Was die Extension NICHT braucht

| Idee | Bewertung |
|------|-----------|
| OSC durch WebSocket/HTTP ersetzen | ✗ Overengineering — loopback UDP ist zuverlässig |
| JSON-RPC Server in Java implementieren | ✗ Unnötig — OSC + ACK-Replies reichen |
| Protokollwechsel für Transaktionen | ✗ Saga-Pattern (F1) löst das auf Python-Seite |

### Abdeckung durch bisherige Findings

| Problem | F1 (Saga) | F5 (Circuit) | F11 (Extension) |
|---------|:---------:|:------------:|:---------------:|
| UDP-Paketverlust | — | — | ✗ kein echtes Problem |
| Browser-Polling fragil | — | — | ✓ Observer |
| Keine Noten-ACKs | ✓ (Kompensation) | — | ✓ Batch + ACK |
| Bitwig-Status vor Operationen | — | ✓ (Python-Seite) | ✓ Extension liefert Status |
| 50 Einzel-Nachrichten pro Song | — | — | ✓ Batch-Endpoint |

**F1 und F11 ergänzen sich:** F1 definiert was bei Fehlern passiert (Rollback),
F11 stellt sicher dass Fehler überhaupt gemeldet werden.

---

## Finding 12 — Dropdown-UI entfernen, Freitext als primärer Eingang

> ✅ **Ist-Stand (Juni 2026):** Umgesetzt
> - **Bitwig-Extension:** Die 9 `SettableEnumValue`-Dropdowns (Genre/Key/Technique/Rhythm/StringRegister/FX/Tracks/Length/Dynamics) wurden entfernt. Übrig bleiben Freitext-Prompt + BPM-Slider + Send/Play/Stop/Status — wie im Entwurf vorgeschlagen.
> - **Dashboard:** Das separate Streamlit-Dashboard (`dashboard/`) bietet ebenfalls Freitext-Eingabe.
> - **Python:** `_prompt_from_config()` und die 10-Felder-Rekonstruktion in `core.py` sind weg; der `/agent/ui/config`-Handler nimmt das schlanke `{prompt, bpm}`-JSON entgegen.
> - **State:** [`src/agent/state.py`](../../src/agent/state.py) — `ui_song_config` ist jetzt ein optionales Dict mit `prompt` + `bpm` statt 10 Pflichtfeldern.

**Pattern: Thin Client / Natural Language Interface**

### Was entfernt wird — und warum

Die Bitwig-Preferences-UI hat aktuell 9 Dropdown-Felder die das LLM **umgehen**:

| Feld | Problem |
|------|---------|
| Genre (8 Werte) | Kein "Nu-Jazz", "Doom Metal", "Afrobeat" möglich |
| Key (7 Werte) | 17 von 24 Tonarten fehlen |
| Technique: Palm Mute, Gallop, Chug Pattern | Gitarren-Vokabular für alle Genres |
| String Register: Low/Mid/Lead | Nur für Gitarre sinnvoll |
| Rhythm Pattern: 5 Werte | Kein Shuffle, kein Swing, kein Polyrhythmus |
| FX Preset: 4 Werte | Alle gitarrenorientiert |
| Track Count: 1/2/4/6 | Kein 3, 5, 7, 8 |
| Length: 8/16/32/64 Beats | Keine ungeraden Längen |
| Dynamics: Flat/Crescendo/... | 4 Optionen statt kontinuierliches Spektrum |

Der Python-Code rekonstruiert diese Werte zu einem Prompt
(`"Erstelle einen Rock-Song mit 120 BPM in E minor, Technik Palm Mute..."`)
den das LLM ohne Reasoning abarbeitet — `<think>` ist leer.

### Java-Extension — was bleibt, was wird neu

**Entfernen:** 9 `SettableEnumValue`-Felder + alle `prefs.getEnumSetting()`-Aufrufe

```java
// ENTFERNEN — alles aus setupAgentUi():
private SettableEnumValue  cfgGenre, cfgTracks, cfgKey, cfgLength;
private SettableEnumValue  cfgTechnique, cfgRhythm, cfgStringRegister;
private SettableEnumValue  cfgDynamics, cfgFx;

// und alle prefs.getEnumSetting()-Aufrufe
// und die 10-Felder JSON-Konstruktion
```

**Neu: ein Freitext-Feld + optionaler BPM-Slider**

```java
// setupAgentUi() — nach dem Umbau:
private SettableStringValue cfgPrompt;
private SettableRangedValue cfgBpm;      // bleibt — Slider ist gute UX

private void setupAgentUi() {
    Preferences prefs = host.getPreferences();

    // Primärer Eingang: Freitext
    cfgPrompt = prefs.getStringSetting(
        "Prompt",         // Label in Bitwig UI
        "Agent",          // Kategorie (neuer, schlankerer Name)
        400,              // max. Zeichen
        ""
    );

    // Optionaler BPM-Anker (Slider ist präziser als Tippen)
    cfgBpm = prefs.getNumberSetting(
        "BPM (optional)", "Agent", 60.0, 200.0, 1.0, " bpm", 0.0
        // Default 0 = "nicht gesetzt" → LLM entscheidet aus Prompt
    );

    // Send-Button — schickt Prompt + optionales BPM
    Signal sendPrompt = prefs.getSignalSetting(
        "▶ Send", "Agent", "Prompt an Agent senden"
    );
    sendPrompt.addSignalObserver(() -> {
        String text = cfgPrompt != null ? cfgPrompt.get().trim() : "";
        if (text.isEmpty()) {
            host.showPopupNotification("Bitte Prompt eingeben");
            return;
        }
        double bpm = cfgBpm != null ? cfgBpm.get() : 0.0;

        // Minimales JSON — kein Dropdown-Ballast mehr
        String payload = bpm > 0
            ? "{\"prompt\":\"" + escapeJson(text) + "\",\"bpm\":" + (int)bpm + "}"
            : "{\"prompt\":\"" + escapeJson(text) + "\"}";

        boolean ok = sendAgentUiPromptWithRetries(payload, 8, 350L);
        host.showPopupNotification(ok ? "Gesendet: " + text.substring(0, Math.min(40, text.length())) + "…"
                                      : "Agent nicht erreichbar");
    });

    // Transport-Steuerung bleibt unverändert
    Signal playNow = prefs.getSignalSetting("Play",  "Agent", "Transport starten");
    playNow.addSignalObserver(() -> { transport.play(); });

    Signal stopNow = prefs.getSignalSetting("Stop",  "Agent", "Transport stoppen");
    stopNow.addSignalObserver(() -> { transport.stop(); });

    Signal status  = prefs.getSignalSetting("Status","Agent", "Status anzeigen");
    status.addSignalObserver(() -> {
        int n = 0;
        for (int i = 0; i < TRACK_BANK_SIZE; i++)
            if (((Channel)trackBank.getItemAt(i)).exists().get()) n++;
        host.showPopupNotification("Tracks=" + n
            + " | BPM=" + Math.round(transport.tempo().get())
            + " | " + (transport.isPlaying().get() ? "▶" : "■"));
    });
}
```

**Ergebnis in Bitwig:** Das Preferences-Panel hat nur noch 4 Elemente:

```
[Agent]
  Prompt:  [________________________]   ← free-text, 400 Zeichen
  BPM:     [___60_____120____180___]   ← Slider, 0 = "auto"
  [▶ Send]   [Play]   [Stop]   [Status]
```

### Python-Seite — was entfernt und vereinfacht wird

**Entfernen in `core.py`:**

```python
# ENTFERNEN — core.py:763-779
def _prompt_from_config(cfg: dict[str, Any]) -> str:
    genre     = str(cfg.get("genre", "Rock"))
    bpm       = int(float(cfg.get("bpm", 120)))
    technique = str(cfg.get("technique", "Standard"))
    rhythm    = str(cfg.get("rhythm_pattern", "Straight Eighths"))
    # ... 10 Felder → rekonstruierter Prompt-String
```

**Vereinfachen — neuer Handler:**

```python
# core.py — /agent/ui/config Handler (vorher ~30 Zeilen, jetzt 8)
def _handle_config(address: str, raw: str) -> None:
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        return
    prompt = cfg.get("prompt", "").strip()
    if not prompt:
        return
    bpm = cfg.get("bpm")   # optional int oder None
    _set_latest_ui_config({"prompt": prompt, "bpm": bpm})
    log.info("Agent UI Prompt: %s (bpm=%s)", prompt[:80], bpm)
```

**Entfernen in `master_graph.py` — `plan_node`:**

```python
# ENTFERNEN — master_graph.py:110-155
cfg_genre     = str(ui_cfg.get("genre", "")).strip()
cfg_technique = str(ui_cfg.get("technique", "")).strip()
cfg_rhythm    = str(ui_cfg.get("rhythm_pattern", "")).strip()
cfg_register  = str(ui_cfg.get("string_register", "")).strip()
cfg_dynamics  = str(ui_cfg.get("dynamics_shape", "")).strip()
cfg_fx        = str(ui_cfg.get("fx_preset", "")).strip()
# ...cfg_text = f"Genre {cfg_genre}, Technik {cfg_technique}..."

# ERSETZEN DURCH:
def plan_node(state: MasterGraphState) -> dict:
    ui_cfg    = state.get("ui_song_config") or {}
    user_text = state["messages"][-1].content
    ui_bpm    = ui_cfg.get("bpm")          # einziger strukturierter Wert

    bpm        = float(ui_bpm) if ui_bpm else _extract_bpm(user_text, 120.0)
    beat_count = _extract_beats(user_text) or _beats_from_time(bpm, user_text) or 16.0
    scale      = _extract_scale_hint(user_text)   # LLM-Extraktion aus Freitext
    fx_hint    = _extract_explicit_fx(user_text)  # LLM-Extraktion aus Freitext

    # slave_plan: nur noch was wirklich objektiv ist
    slave_plan = {
        "bpm":        bpm,
        "beat_count": beat_count,
        "scale":      scale,
        "fx_hint":    fx_hint,
        # genre/mood/technique: LLM entscheidet über KB-Queries
    }
```

**Entfernen aus `state.py`:**

```python
# state.py — ui_song_config vereinfachen
# VORHER:
ui_song_config: Optional[dict]  # 10 Felder

# NACHHER:
ui_prompt: Optional[str]        # der rohe Freitext
ui_bpm:    Optional[float]      # einziger strukturierter Hint
```

### Der neue Datenfluss

```
Vorher:
User wählt Dropdowns → JSON (10 Felder) → _prompt_from_config() → LLM (kein Reasoning)

Nachher:
User tippt "düsterer Progressive-Metal, Drop-D, Tool-artig, 5/4 Takt"
    + BPM-Slider: 160
    → JSON: {"prompt": "...", "bpm": 160}
    → Python: prompt direkt ans LLM
    → LLM <think>:
        "Progressive Metal, Tool → dunkel, komplex, polyrhythmisch
         Drop-D → midi_low=26 (D2), Tuning-Hinweis an Instrument-KB
         5/4 Takt → beat_count=20 (5×4), hat_step=5/4-Feeling
         BPM=160 aus Slider übernehmen
         → get_instruments_for_song(genre='progressive metal', mood='dark')
         → get_rhythm_pattern(genre='progressive metal', section='verse', energy=0.85)"
```

### Gelöschte Zeilen — Übersicht

| Datei | Entfernt | Bleibt |
|-------|----------|--------|
| `BitwigAgentBridgeExtension.java` | 9 Enum-Felder, 9 `getEnumSetting`, JSON-Builder (40 Zeilen) | BPM-Slider, Send/Play/Stop/Status |
| `core.py` | `_prompt_from_config()` (~20 Zeilen) | `/agent/ui/config`-Handler (8 Zeilen) |
| `master_graph.py` | 10 `cfg_*`-Variablen, `cfg_text`-Block (~25 Zeilen) | BPM-Extraktion, `slave_plan` |
| `state.py` | `ui_song_config: dict` | `ui_prompt: str`, `ui_bpm: float` |

**~85 Zeilen Code entfernt, ~40 neue — und das LLM kann endlich frei denken.**

---

## Umsetzungsreihenfolge — Status (Juni 2026)

| # | Finding | Status | Quelle |
|---|---------|:------:|--------|
| 1 | Extension: Step-ACK-Protokoll (F11) | ✅ | `BitwigStepPluginExtension.java` |
| 2 | Extension: Batch-Note-Steps (F11) | ✅ | Step-Typen `pattern`/`note` |
| 3 | Circuit Breaker Python-Seite (F5) | ✅ | `src/agent/osc/circuit_breaker.py` |
| 4 | Saga + Command Queue (F1) | ✅ | `src/agent/osc/saga.py` + `stepQueue` |
| 5 | KB-Schema: DrumPattern + DrumSound (F9) | ✅ | Neo4j; `DrumPatternRepository` |
| 6 | KB-Schema: InstrumentTemplate (F10) | ✅ | Neo4j; `InstrumentRepository` |
| 7 | Tools: `get_rhythm_pattern` (F9) | ✅ | `tools/knowledge/rhythm_tool.py` |
| 8 | Tools: `get_instruments_for_song` (F10) | ✅ | `tools/knowledge/instrument_tool.py` |
| 9 | Prompt: Retrieve-Then-Reason (F9+F10) | 🟡 | `src/agent/prompts.py` (Beispiele fehlen) |
| 10 | `scan_bitwig_devices.py` ausgeführt (F10) | ✅ | 389 Devices in KB |
| 11 | Composite Quality Spec (F3) | ✅ | `src/agent/quality/specs.py` |
| 12 | Parser-Chain / Adapter (F7) | ✅ | `src/agent/parsing/tool_call_parsers.py` |
| 13 | Router/Policy (F4) | ✅ | `src/agent/router.py` + `policy.py` |
| 14 | Strategy → KB-backed (F2+F9) | 🟡 | KB ja, dedizierte Strategy-Klasse fehlt |
| 15 | Single-Graph statt Subclasses (F8) | ✅ | nur ein `AgentState` |
| 16 | Latenzreduktion (F6) | ✅ | dualer Graph entfernt; Java-StepQueue taktet |
| 17 | Tool-Registry Refactor (F2) | ⏳ | flache `tools/`-Struktur statt Registry |

**Bilanz:** 14 ✅ / 2 🟡 / 1 ⏳ — die Architektur-Beurteilung von 2024/25 ist im Wesentlichen umgesetzt.

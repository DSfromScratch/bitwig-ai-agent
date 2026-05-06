"""InstrumentSlave — fokussierter LLM-Call nur für Instrument + FX-Chain.

Produziert bewusst ein kleines JSON (~80 Token Output) um xml_fragment zu vermeiden.
Output wird in slave_results Liste gesammelt (Fan-in via operator.add Reducer).
"""
from __future__ import annotations

import json
import logging
import os
import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState

log = logging.getLogger("bitwig-agent.instrument-slave")

_SYSTEM_PROMPT = """\
Du bist ein Instrument-Spezialist für Bitwig Studio.
Deine einzige Aufgabe: Wähle das richtige Bitwig-Instrument und die FX-Chain für den gegebenen Prompt.

Antworte NUR mit einem validen JSON-Objekt — kein Text, keine Erklärung, kein Markdown.

Format:
{
  "instrument": "<Bitwig-Instrument-Name>",
  "preset": "<Instrument-Preset oder leer>",
  "fx_preset": "<Audioeffekte-Guitar-Chain-Preset oder leer>",
  "fx": ["<FX-1>", "<FX-2>"]
}

Bekannte Bitwig-Instrumente: Phase-4, FM-4, Polysynth, Surge XT, Organ, Sampler, Drum Machine, E-Piano
Bekannte FX: Distortion, Amp, Reverb, Delay, Chorus, Flanger, Phaser, EQ-5, Compressor, Bit-8

Für Gitarren-Sounds: Setze fx_preset auf einen der Guitar-FX-Chain-Presets aus Bitwigs "Audioeffekte > Guitar" Kategorie:
  "Guitar Crunchy" — mittlere Verzerrung, Crunch-Sound
  "Lead Guitar 1"  — Lead-Gitarre mit Sustain
  "Lead Guitar 2"  — Lead-Gitarre Variation
  "Clean Guitar"   — cleaner, unverzerrter Gitarrenklang
  "Faulty Distortion" — starke Verzerrung, Heavy Sound
  "A Little Crunch"   — leichte Verzerrung, Blues/Rock
  "Almost Clean"      — fast clean mit leichtem Drive
  Wenn fx_preset gesetzt ist, lasse fx leer (die FX-Chain ist im Preset enthalten).

Falls KB-Kontext unten vorhanden ist: nutze die empfohlenen Devices und Sounds aus der Wissensbasis.
preset-Feld: Instrument-Preset (leer lassen für Gitarren — stattdessen fx_preset nutzen).

Kein <think>-Block, keine Erklärung. Nur JSON.
"""

_JSON_RE = re.compile(r'\{[^{}]+\}', re.DOTALL)


def _kb_lookup(user_text: str, instrument_hint: str) -> str:
    """Sucht in Neo4j nach passenden Devices/Sounds für den Prompt. Gibt '' zurück wenn KB unavailable."""
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session, is_available
        if not is_available():
            return ""
    except Exception:
        return ""

    # Schlüsselwörter aus Prompt extrahieren
    combined = f"{user_text} {instrument_hint}".lower()
    words = [w for w in re.findall(r'\b\w{3,}\b', combined)
             if w not in ("das","die","der","ein","mit","und","oder","für","bitte",
                          "erstelle","lege","track","noten","bpm","beats","einen","eine")][:6]
    if not words:
        return ""

    lines: list[str] = []
    try:
        with neo4j_session() as s:
            # Genre-Empfehlungen
            genres = s.run("""
                MATCH (g:Genre)
                WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w
                       OR toLower(coalesce(g.description,'')) CONTAINS w)
                WITH g LIMIT 2
                MATCH (g)-[r:USES]->(d:Device)
                RETURN g.name AS genre, d.name AS device, r.role AS role, r.weight AS w
                ORDER BY r.weight DESC LIMIT 10
            """, words=words).data()

            if genres:
                genre_name = genres[0]["genre"]
                devs = ", ".join(f"{r['device']} ({r['role']})" for r in genres[:6])
                lines.append(f"Genre '{genre_name}' → Empfohlene Devices: {devs}")

            # Sound-Typen
            sounds = s.run("""
                MATCH (snd:Sound)
                WHERE any(w IN $words WHERE toLower(snd.name) CONTAINS w
                       OR toLower(coalesce(snd.description,'')) CONTAINS w)
                OPTIONAL MATCH (snd)-[:CREATED_BY]->(dev:Device)
                RETURN snd.name AS name, dev.name AS device,
                       snd.description AS desc, snd.settings AS settings
                LIMIT 3
            """, words=words).data()

            for snd in sounds:
                line = f"Sound '{snd['name']}' → Instrument: {snd['device']}"
                if snd.get("settings"):
                    line += f", Settings: {snd['settings']}"
                lines.append(line)

            # Direkte Device-Matches
            devices = s.run("""
                MATCH (d:Device)
                WHERE any(w IN $words WHERE toLower(d.name) CONTAINS w
                       OR toLower(coalesce(d.description,'')) CONTAINS w)
                WITH d LIMIT 3
                OPTIONAL MATCH (d)-[r:RECOMMENDED_WITH]->(fx:Device)
                RETURN d.name AS name, d.category AS cat,
                       collect(fx.name)[..4] AS fx_chain
            """, words=words).data()

            for dev in devices:
                line = f"Device '{dev['name']}' [{dev['cat']}]"
                if dev.get("fx_chain"):
                    line += f" → empfohlene FX: {', '.join(dev['fx_chain'])}"
                lines.append(line)

    except Exception as e:
        log.debug("KB-Lookup Fehler: %s", e)
        return ""

    if not lines:
        return ""
    return "KB-Kontext:\n" + "\n".join(lines)


def _get_llm() -> ChatOpenAI:
    base = os.getenv("VLLM_BASE_URL", "http://192.168.0.4:8000") + "/v1"
    model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
    return ChatOpenAI(
        base_url=base,
        api_key="vllm",
        model=model,
        temperature=0.3,
        max_tokens=200,   # Instrument-JSON braucht max 150 Token
        timeout=60,
    )


def _parse_instrument_json(text: str) -> dict | None:
    """Extrahiert {instrument, fx} aus dem LLM-Output."""
    # <think>-Blocks entfernen
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    # Direkt JSON parsen
    try:
        data = json.loads(text)
        if "instrument" in data and "fx" in data:
            return data
    except json.JSONDecodeError:
        pass
    # JSON-Fragment aus Text extrahieren
    for match in _JSON_RE.finditer(text):
        try:
            data = json.loads(match.group())
            if "instrument" in data and "fx" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None


def run_instrument_slave(state: AgentState) -> dict:
    """Node-Funktion für den Master-Graph.

    Liest slave_plan aus dem State, ruft LLM mit fokussiertem Prompt auf,
    gibt {"slave_results": [result_dict], "slave_retry_counts": {"instrument": n}}
    zurück.
    """
    plan = state.get("slave_plan") or {}
    retry = (state.get("slave_retry_counts") or {}).get("instrument", 0)
    user_text = plan.get("user_text", "")
    instrument_hint = plan.get("instrument_hint", "")
    fx_hint = plan.get("fx_hint", "")

    hint_parts = []
    if instrument_hint:
        hint_parts.append(f"Instrument-Hinweis aus Prompt: {instrument_hint}")
    if fx_hint:
        hint_parts.append(f"FX-Hinweis aus Prompt: {fx_hint}")

    # Neo4j KB-Lookup
    kb_context = _kb_lookup(user_text, instrument_hint)
    if kb_context:
        hint_parts.append(kb_context)
        log.debug("InstrumentSlave — KB-Kontext: %s", kb_context[:120])

    user_msg = f"{user_text}\n\n{chr(10).join(hint_parts)}".strip()

    log.info("InstrumentSlave — LLM-Call (retry=%d)", retry)
    llm = _get_llm()
    response: AIMessage = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])

    raw = response.content or ""
    parsed = _parse_instrument_json(raw)

    if parsed:
        preset    = parsed.get("preset", "") or ""
        fx_preset = parsed.get("fx_preset", "") or ""
        log.info("InstrumentSlave — OK: instrument=%s, preset=%s, fx_preset=%s, fx=%s",
                 parsed["instrument"], preset or "(none)", fx_preset or "(none)", parsed.get("fx", []))
        return {
            "slave_results": [{
                "type": "instrument",
                "instrument": parsed["instrument"],
                "preset": preset,
                "fx_preset": fx_preset,
                "fx": parsed.get("fx", []),
            }],
            "slave_retry_counts": {"instrument": retry},
        }

    # Parse-Fehler → Retry-Signal
    log.warning("InstrumentSlave — Parse-Fehler (retry=%d): %s", retry, raw[:100])
    return {
        "slave_results": [{"type": "instrument", "error": "parse_failed", "raw": raw[:200], "retry": True}],
        "slave_retry_counts": {"instrument": retry + 1},
    }

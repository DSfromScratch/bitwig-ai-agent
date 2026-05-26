"""InstrumentSlave — LLM entscheidet welche Tracks/Rollen benötigt werden
und wählt passende Instrumente für jeden Track.

Output: vollständige Track-Manifest-Liste [{role, instrument, fx}, ...]
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
Du bist ein Musik-Arrangeur für Bitwig Studio.
Deine Aufgabe: Entscheide welche Tracks für den Prompt benötigt werden und wähle passende Instrumente.

Antworte NUR mit einem validen JSON-Objekt — kein Text, keine Erklärung, kein Markdown, kein <think>.

Format:
{
  "tracks": [
    {"role": "<rolle>", "instrument": "<Bitwig-Device>", "preset": "", "fx_preset": "", "fx": ["<FX>"]},
    ...
  ]
}

Mögliche Rollen (nur nehmen was gebraucht wird):
  kick, snare, hihat          — Schlagzeug-Stimmen
  bass                         — Bassline
  chords                       — Akkord-Track
  lead                         — Lead-Melodie
  pad                          — Flächen/Atmosphäre
  melody                       — Haupt-Melodie

Beispiele:
  "drum solo" / "schlagzeug" → nur kick + snare + hihat
  "bassline" / "nur bass"    → nur bass
  "chord progression"        → chords (+ evtl. bass)
  "full band" / "ganzer Song"→ kick + snare + hihat + bass + chords + lead
  "ambient" / "fläche"       → pad
  "melodie"                  → lead oder melody

Bekannte Bitwig-Drum-Instrumente (immer UUID-geladen, sofort verfügbar):
  v9 Kick, v9 Snare, v9 Hat Closed, v9 Hat Open, v9 Ride
  v8 Kick, v8 Snare, v8 Hat, v1 Kick, v1 Snare

Bekannte Bitwig-Synth-Instrumente:
  Phase-4, FM-4, Polysynth, Surge XT, Organ, E-Piano, Sampler

Bekannte FX:
  Distortion, Amp, Reverb, Delay, Chorus, Flanger, EQ-5, Compressor, Bit-8

Für Gitarren-Sounds: fx_preset auf einen Guitar-FX-Chain-Preset setzen:
  "Guitar Crunchy", "Lead Guitar 1", "Lead Guitar 2", "Clean Guitar",
  "Faulty Distortion", "A Little Crunch", "Almost Clean"
  Wenn fx_preset gesetzt → fx leer lassen.

Kein <think>-Block. Nur JSON.
"""

_TRACKS_RE = re.compile(r'"tracks"\s*:\s*\[', re.DOTALL)

# Maps wrong/hallucinated device names → correct Bitwig internal names
_DEVICE_NAME_MAP: dict[str, str] = {
    # Drum aliases
    "e-kick":           "v9 Kick",
    "e-snare":          "v9 Snare",
    "e-hihat":          "v9 Hat Closed",
    "e-hat":            "v9 Hat Closed",
    "e-clap":           "v9 Clap",
    "e-tom":            "v9 Tom",
    "hihat":            "v9 Hat Closed",
    "kick drum":        "v9 Kick",
    "snare drum":       "v9 Snare",
    # Synth/melodic aliases (LLM hallucinations)
    "pad":              "Phase-4",
    "synth pad":        "Phase-4",
    "atmosphere":       "Phase-4",
    "atmosphäre":       "Phase-4",
    "lead synth":       "FM-4",
    "bass synth":       "FM-4",
    "reese bass":       "FM-4",
    "sub bass":         "FM-4",
    "electric piano":   "E-Piano",
    "e-piano":          "E-Piano",
    "keys":             "Polysynth",
    "synth":            "Phase-4",
}


def _normalize_instrument(name: str) -> str:
    return _DEVICE_NAME_MAP.get(name.strip().lower(), name)


def _kb_lookup(user_text: str, genre: str) -> str:
    try:
        from src.knowledge.neo4j_graph import session as neo4j_session, is_available
        if not is_available():
            return ""
    except Exception:
        return ""

    combined = f"{user_text} {genre}".lower()
    words = [w for w in re.findall(r'\b\w{3,}\b', combined)
             if w not in ("das","die","der","ein","mit","und","oder","für","bitte",
                          "erstelle","lege","track","noten","bpm","beats","einen","eine")][:6]
    if not words:
        return ""

    lines: list[str] = []
    try:
        with neo4j_session() as s:
            # Genre → empfohlene Devices
            genres = s.run("""
                MATCH (g:Genre)
                WHERE any(w IN $words WHERE toLower(g.name) CONTAINS w
                       OR toLower(coalesce(g.description,'')) CONTAINS w)
                WITH g LIMIT 2
                MATCH (g)-[r:USES]->(d:Device)
                RETURN g.name AS genre, d.name AS device, r.role AS role, r.weight AS w
                ORDER BY r.weight DESC LIMIT 8
            """, words=words).data()

            if genres:
                genre_name = genres[0]["genre"]
                devs = ", ".join(f"{r['device']} ({r['role']})" for r in genres[:5])
                lines.append(f"Genre '{genre_name}' → Empfohlene Devices: {devs}")

            # Device-Details + empfohlene FX
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

            # Workflow-Kontext: passende Sound-Design-Rezepte
            workflows = s.run("""
                MATCH (w:Workflow)
                WHERE any(word IN $words WHERE toLower(w.name) CONTAINS word
                       OR toLower(coalesce(w.description,'')) CONTAINS word)
                RETURN w.name AS name, w.description AS desc,
                       w.osc_steps AS osc_steps
                LIMIT 2
            """, words=words).data()

            for wf in workflows:
                line = f"Workflow '{wf['name']}': {wf['desc'] or ''}"
                if wf.get("osc_steps"):
                    import json as _json
                    try:
                        steps = _json.loads(wf["osc_steps"])
                        cmds = [s["cmd"] for s in steps if "cmd" in s][:5]
                        if cmds:
                            line += f" → OSC: {', '.join(cmds)}"
                    except Exception:
                        pass
                lines.append(line)

    except Exception as e:
        log.debug("KB-Lookup Fehler: %s", e)
        return ""

    return ("KB-Kontext:\n" + "\n".join(lines)) if lines else ""


def _get_llm() -> ChatOpenAI:
    base = os.getenv("VLLM_BASE_URL", "http://192.168.0.4:8000") + "/v1"
    model = os.getenv("VLLM_MODEL", "./models/Qwen3-14B-AWQ")
    return ChatOpenAI(
        base_url=base,
        api_key="vllm",
        model=model,
        temperature=0.3,
        max_tokens=400,
        timeout=60,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def _parse_manifest(text: str) -> list[dict] | None:
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "tracks" in data:
            return _validate_tracks(data["tracks"])
    except json.JSONDecodeError:
        pass
    # JSON aus Text extrahieren
    m = re.search(r'\{.*?"tracks".*?\}', text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if "tracks" in data:
                return _validate_tracks(data["tracks"])
        except json.JSONDecodeError:
            pass
    return None


def _validate_tracks(tracks: list) -> list[dict] | None:
    if not isinstance(tracks, list) or not tracks:
        return None
    result = []
    valid_roles = {"kick","snare","hihat","bass","chords","lead","pad","melody"}
    for t in tracks:
        if not isinstance(t, dict) or "role" not in t or "instrument" not in t:
            continue
        role = str(t["role"]).lower().strip()
        if role not in valid_roles:
            continue
        result.append({
            "role":      role,
            "instrument": _normalize_instrument(str(t["instrument"])),
            "preset":    str(t.get("preset", "") or ""),
            "fx_preset": str(t.get("fx_preset", "") or ""),
            "fx":        [str(f) for f in t.get("fx", []) if f],
        })
    return result if result else None


def run_instrument_slave(state: AgentState) -> dict:
    plan = state.get("slave_plan") or {}
    retry = (state.get("slave_retry_counts") or {}).get("instrument", 0)
    user_text = plan.get("user_text", "")
    genre = plan.get("genre", "")
    fx_hint = plan.get("fx_hint", "")

    hint_parts = []
    if genre:
        hint_parts.append(f"Genre: {genre}")
    if fx_hint:
        hint_parts.append(f"FX-Hinweis: {fx_hint}")

    kb_context = _kb_lookup(user_text, genre)
    if kb_context:
        hint_parts.append(kb_context)

    user_msg = f"{user_text}\n\n{chr(10).join(hint_parts)}".strip()

    log.info("InstrumentSlave — LLM-Call (retry=%d)", retry)
    llm = _get_llm()
    response: AIMessage = llm.invoke([
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_msg),
    ])

    raw = response.content or ""
    tracks = _parse_manifest(raw)

    if tracks:
        roles = [t["role"] for t in tracks]
        log.info("InstrumentSlave — OK: %d Tracks: %s", len(tracks), roles)
        return {
            "slave_results": [{"type": "instrument", "tracks": tracks}],
            "slave_retry_counts": {"instrument": retry},
        }

    log.warning("InstrumentSlave — Parse-Fehler (retry=%d): %s", retry, raw[:200])
    return {
        "slave_results": [{"type": "instrument", "error": "parse_failed", "raw": raw[:200], "retry": True}],
        "slave_retry_counts": {"instrument": retry + 1},
    }

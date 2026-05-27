"""
Bitwig Audio Agent — Dashboard v3
Drei Tabs analog zu Bitwigs Bereichen: Chat | Browser | Analyse
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

st.set_page_config(
    page_title="Bitwig Audio Agent",
    page_icon="🎛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Nav-Radio: Circles entfernen, Bitwig-Browser-Stil */
div[data-testid="stRadio"] > label { display: none; }
div[data-testid="stRadio"] > div   { gap: 2px !important; }
div[data-testid="stRadio"] > div > label {
    background: #181825; border-radius: 5px;
    padding: 8px 12px !important; cursor: pointer;
    font-size: 0.92em; color: #cdd6f4;
    border: 1px solid transparent;
    transition: background 0.15s;
    display: flex; align-items: center; gap: 6px;
}
div[data-testid="stRadio"] > div > label:hover { background: #313244 !important; }
div[data-testid="stRadio"] > div > label[data-checked="true"],
div[data-testid="stRadio"] > div > label[aria-checked="true"] {
    background: #1e3a5f !important;
    border-color: #4c9be8 !important;
    color: #89b4fa !important;
}
/* Tile Grid */
.tile {
    background: #1e1e2e; border-radius: 6px; padding: 10px 12px;
    border-left: 3px solid #313244; margin-bottom: 6px; cursor: pointer;
}
.tile:hover { border-left-color: #4c9be8; background: #252535; }
.tile-icon  { font-size: 1.4em; float: left; margin-right: 8px; margin-top: 2px; }
.tile-name  { font-weight: bold; font-size: 0.95em; color: #cdd6f4; }
.tile-meta  { font-size: 0.75em; color: #6c7086; margin-top: 2px; }
.tile-tag   { background: #313244; border-radius: 3px; padding: 1px 5px;
              font-size: 0.72em; color: #89b4fa; margin-right: 3px; }
/* Compact expander */
div[data-testid="stExpander"] > div:first-child {
    background: #1e1e2e; border-radius: 6px;
}
/* Status badges */
.badge-ok  { color: #a6e3a1; font-weight: bold; }
.badge-err { color: #f38ba8; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ── Session State ─────────────────────────────────────────────────────────────
_DEFAULTS = {
    "chat_history":    [],
    "selected_item":   None,
    "browser_cat":     "Devices",
    "browser_subtype": "Alle",
    "browser_search":  "",
    "analyse_result":  None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── Service / Status Checks ───────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _check_neo4j() -> bool:
    try:
        from src.knowledge.neo4j_graph import is_available
        return is_available()
    except Exception:
        return False

@st.cache_data(ttl=15, show_spinner=False)
def _check_llm() -> tuple[bool, str]:
    import urllib.request, os
    url = os.getenv("VLLM_BASE_URL", "http://localhost:8100")
    try:
        urllib.request.urlopen(f"{url}/v1/models", timeout=2)
        return True, url
    except Exception:
        return False, url

@st.cache_data(ttl=10, show_spinner=False)
def _check_embed() -> bool:
    import urllib.request, os
    url = os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:8080")
    try:
        urllib.request.urlopen(f"{url}/health", timeout=2)
        return True
    except Exception:
        return False

@st.cache_data(ttl=300, show_spinner=False)
def _neo4j_stats() -> dict:
    try:
        from src.knowledge.neo4j_graph import session
        with session() as s:
            rows = s.run(
                "MATCH (n) RETURN labels(n)[0] AS l, count(*) AS c ORDER BY c DESC"
            ).data()
        return {r["l"]: r["c"] for r in rows if r["l"]}
    except Exception:
        return {}

@st.cache_data(ttl=600, show_spinner=False)
def _get_device_subtypes() -> list[str]:
    """Lädt Device-Typen für den Browser-Filter aus Neo4j."""
    try:
        from src.knowledge.neo4j_graph import session
        with session() as s:
            rows = s.run(
                "MATCH (d:Device) WHERE d.device_type IS NOT NULL "
                "RETURN DISTINCT d.device_type AS t, count(*) AS c "
                "ORDER BY c DESC"
            ).data()
        # Schönere Labels
        LABELS = {
            "instrument": "🎹 Instruments",
            "fx":          "🎛️ Effects",
            "modulation":  "🌊 Modulators",
            "device":      "🔲 Devices / Grid",
            "mixing":      "🎚️ Mixing",
            "data":        "📊 Data",
            "pitch":       "🎵 Pitch",
            "hardware":    "🔌 Hardware",
            "MIDI":        "🎹 MIDI",
            "Note FX":     "🎵 Note FX",
            "display":     "👁 Display",
            "oscillator":  "〜 Oscillators",
        }
        return [LABELS.get(r["t"], r["t"]) for r in rows]
    except Exception:
        return []

def _vllm_state() -> str:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", "vllm@agent.service"],
            capture_output=True, text=True, timeout=3,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🎛️ Bitwig Agent")
    st.divider()

    neo4j_ok        = _check_neo4j()
    llm_ok, llm_url = _check_llm()
    embed_ok        = _check_embed()
    stats           = _neo4j_stats() if neo4j_ok else {}
    svc_state       = _vllm_state()

    # OSC-Verbindung zu Bitwig prüfen
    def _bitwig_osc_ok() -> bool:
        try:
            from src.agent.tools.song_tools import check_bitwig_connection
            r = check_bitwig_connection.invoke({})
            return r.get("connected", False)
        except Exception:
            return False

    bitwig_ok = _bitwig_osc_ok()

    # Status-Zeile
    def _badge(ok: bool, label: str) -> str:
        cls = "badge-ok" if ok else "badge-err"
        sym = "●" if ok else "✗"
        return f"<span class='{cls}'>{sym} {label}</span>"

    st.markdown(
        _badge(bitwig_ok, "Bitwig") + "  " +
        _badge(llm_ok, "LLM") + "  " +
        _badge(neo4j_ok, "DB"),
        unsafe_allow_html=True,
    )
    st.markdown(
        _badge(embed_ok, "Embed"),
        unsafe_allow_html=True,
    )

    # vLLM service controls
    st.caption(f"vllm@agent: `{svc_state}`")
    llm_c1, llm_c2 = st.columns(2)
    with llm_c1:
        if st.button("▶ LLM", use_container_width=True,
                     disabled=(svc_state == "active"),
                     help="systemctl --user start vllm@agent.service"):
            try:
                subprocess.run(["systemctl", "--user", "start", "vllm@agent.service"],
                               check=True, timeout=10)
                st.toast("vllm@agent gestartet")
            except Exception as e:
                st.toast(f"Fehler: {e}", icon="❌")
            _check_llm.clear()
            st.rerun()
    with llm_c2:
        if st.button("■ LLM", use_container_width=True,
                     disabled=(svc_state != "active"),
                     help="systemctl --user stop vllm@agent.service"):
            try:
                subprocess.run(["systemctl", "--user", "stop", "vllm@agent.service"],
                               check=True, timeout=10)
                st.toast("vllm@agent gestoppt")
            except Exception as e:
                st.toast(f"Fehler: {e}", icon="❌")
            _check_llm.clear()
            st.rerun()

    # Embedding server
    emb_c1, emb_c2 = st.columns(2)
    with emb_c1:
        if st.button("▶ Embed", use_container_width=True, disabled=embed_ok,
                     help="Startet lokalen Embedding-Server"):
            try:
                subprocess.Popen(
                    [".venv/bin/python", "src/knowledge/embedding_server.py"],
                    cwd=str(Path(__file__).parent.parent),
                    stdout=open("/tmp/embed_server.log", "w"),
                    stderr=open("/tmp/embed_server.log", "a"),
                )
                st.toast("Embedding-Server gestartet")
            except Exception as e:
                st.toast(f"Fehler: {e}", icon="❌")
            _check_embed.clear()
            st.rerun()
    with emb_c2:
        if not embed_ok:
            st.caption("⚠ Vektorsuche offline")

    st.divider()

    # Bitwig Transport
    st.subheader("▶ Transport")
    tc1, tc2, tc3 = st.columns(3)
    for col, lbl, action in [(tc1,"▶","play"), (tc2,"■","stop"), (tc3,"⟳","rewind")]:
        with col:
            if st.button(lbl, use_container_width=True, key=f"t_{action}"):
                try:
                    from src.agent.tools.bitwig_tools import control_bitwig
                    control_bitwig.invoke({"action": action})
                    st.toast(lbl)
                except Exception as e:
                    st.toast(str(e), icon="❌")

    bpm_val = st.number_input("BPM", 20, 300, 120, step=1)
    if st.button("BPM setzen", use_container_width=True):
        try:
            from src.agent.tools.bitwig_tools import control_bitwig
            control_bitwig.invoke({"action": "tempo", "bpm": float(bpm_val)})
            st.toast(f"BPM → {bpm_val}")
        except Exception as e:
            st.toast(str(e), icon="❌")

    st.divider()
    if st.button("Chat leeren", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

    if stats:
        with st.expander("Graph", expanded=False):
            ICONS = {"Device":"📦","Genre":"🎵","Workflow":"🔄","ProductionPattern":"🎛️",
                     "Concept":"💡","Parameter":"🎚️","Document":"📄","Pattern":"🥁"}
            for label, count in list(stats.items())[:10]:
                st.caption(f"{ICONS.get(label,'•')} {label}: **{count}**")


def _do_chat(prompt: str) -> None:
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.spinner("Agent denkt …"):
        try:
            from src.agent.core import chat as agent_chat
            from langchain_core.messages import HumanMessage, AIMessage

            # Letzte 10 Nachrichten als History mitgeben (ohne die aktuelle)
            history_msgs = []
            for msg in st.session_state.chat_history[:-1][-10:]:
                if msg["role"] == "user":
                    history_msgs.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    history_msgs.append(AIMessage(content=msg["content"]))

            response = agent_chat(prompt, history=history_msgs)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": response}
            )
        except Exception as e:
            st.session_state.chat_history.append(
                {"role": "assistant", "content": f"⚠ {e}"}
            )
    st.rerun()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_chat, tab_browser, tab_analyse = st.tabs(["💬 Chat", "🔍 Browser", "📊 Analyse"])


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  Tab 1 — Chat
# ╚══════════════════════════════════════════════════════════════════════════════
with tab_chat:
    chat_col, quick_col = st.columns([3, 1])

    with chat_col:
        if not llm_ok:
            st.warning(
                f"**LLM nicht erreichbar** (`{llm_url}`)  \n"
                "Starte den Server über die Sidebar oder warte auf Modell-Load.",
                icon="⚠️",
            )

        chat_box = st.container(height=500)
        with chat_box:
            if not st.session_state.chat_history:
                st.markdown(
                    "<div style='color:#45475a;margin-top:60px;text-align:center;font-size:1.1em'>"
                    "Stelle eine Frage zu Bitwig, Devices, Produktionstechniken …"
                    "</div>", unsafe_allow_html=True,
                )
            for msg in st.session_state.chat_history:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        if prompt := st.chat_input(
            "Frage stellen …" if llm_ok else "LLM nicht verfügbar",
            disabled=not llm_ok,
        ):
            _do_chat(prompt)

    with quick_col:
        st.caption("Schnell-Fragen")
        QUICK = [
            "Welches Device für warmen Analog-Bass?",
            "Wie baut man Sidechain-Kompression auf?",
            "Reverb-Sends für DnB erklären",
            "SVF Filter erklären",
            "Poly Grid vs. Note Grid",
            "Workflow: Reese-Bass in Bitwig",
            "DnB Production Patterns zeigen",
            "Phase-4 Tipps",
        ]
        for q in QUICK:
            if st.button(q, use_container_width=True, key=f"q_{q[:18]}",
                         disabled=not llm_ok):
                _do_chat(q)


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  Tab 2 — Browser (Bitwig-Browser-Style)
# ╚══════════════════════════════════════════════════════════════════════════════

# ── Device-Type-Labels ↔ raw DB-Werte ─────────────────────────────────────────
_SUBTYPE_TO_DB = {
    "🎹 Instruments": "instrument",
    "🎛️ Effects":     "fx",
    "🌊 Modulators":  "modulation",
    "🔲 Devices / Grid": "device",
    "🎚️ Mixing":      "mixing",
    "📊 Data":        "data",
    "🎵 Pitch":       "pitch",
    "🔌 Hardware":    "hardware",
    "🎹 MIDI":        "MIDI",
    "🎵 Note FX":     "Note FX",
    "👁 Display":     "display",
    "〜 Oscillators": "oscillator",
}

# Icons per main category
_CAT_ICONS = {
    "Devices":          "📦",
    "Genres":           "🎵",
    "Workflows":        "🔄",
    "Production Patterns": "🎛️",
    "Concepts":         "💡",
}


@st.cache_data(ttl=30, show_spinner=False)
def _browser_query(cat: str, subtype: str, search: str, limit: int = 60) -> list[dict]:
    """Hauptsuche für den Browser-Tab — direkte Neo4j-Abfragen."""
    if not _check_neo4j():
        return []
    try:
        from src.knowledge.neo4j_graph import session
    except Exception:
        return []

    words = [w.lower() for w in search.split() if len(w) >= 2] if search.strip() else []
    results: list[dict] = []

    def _where(field_exprs: list[str]) -> str:
        if not words:
            return ""
        clauses = " OR ".join(
            f"any(w IN $words WHERE {fe} CONTAINS w)"
            for fe in field_exprs
        )
        return f"WHERE {clauses}"

    with session() as s:
        if cat == "Devices":
            db_type = _SUBTYPE_TO_DB.get(subtype)
            # WHERE-Klausel korrekt aufbauen
            filter_parts: list[str] = []
            if words:
                filter_parts.append(
                    "any(w IN $words WHERE toLower(d.name) CONTAINS w "
                    "OR toLower(coalesce(d.description,'')) CONTAINS w "
                    "OR toLower(coalesce(d.category,'')) CONTAINS w)"
                )
            if db_type:
                filter_parts.append(f"d.device_type = '{db_type}'")
            where = ("WHERE " + " AND ".join(filter_parts)) if filter_parts else ""
            rows = s.run(f"""
                MATCH (d:Device) {where}
                WITH d,
                     CASE WHEN any(w IN $words WHERE toLower(d.name) CONTAINS w)
                          THEN 2 ELSE 1 END AS rel
                ORDER BY rel DESC, d.name
                LIMIT $lim
                RETURN d.name AS name, d.description AS desc,
                       d.device_type AS dtype, d.category AS category,
                       d.use_case AS use_case, d.ui_path AS path,
                       d.browser_tab AS tab, d.tips AS tips
            """, words=words, lim=limit).data()

            for r in rows:
                params = s.run("""
                    MATCH (d:Device {name:$n})-[:HAS_PARAMETER]->(p:Parameter)
                    RETURN p.name AS name, p.description AS desc,
                           p.low_means AS low, p.high_means AS high, p.tip AS tip
                    LIMIT 8
                """, n=r["name"]).data()
                similar = s.run("""
                    MATCH (d:Device {name:$n})-[:SIMILAR_TO]->(s:Device)
                    RETURN s.name AS n LIMIT 5
                """, n=r["name"]).data()
                results.append({
                    "kind": "Device", "name": r["name"], "desc": r["desc"] or "",
                    "dtype": r["dtype"] or "", "category": r["category"] or "",
                    "use_case": r["use_case"] or "", "path": r["path"] or "",
                    "tab": r["tab"] or "", "tips": r["tips"],
                    "params": params, "similar": [x["n"] for x in similar],
                })

        elif cat == "Genres":
            where = _where(["toLower(g.name)", "toLower(coalesce(g.description,''))"])
            rows = s.run(f"""
                MATCH (g:Genre) {where}
                ORDER BY g.name LIMIT $lim
                RETURN g.name AS name, g.description AS desc,
                       g.bpm_min AS bpm_min, g.bpm_max AS bpm_max
            """, words=words, lim=limit).data()
            for r in rows:
                devs = s.run("""
                    MATCH (g:Genre {name:$n})-[rel:USES]->(d:Device)
                    RETURN d.name AS n, rel.role AS role
                    ORDER BY rel.weight DESC LIMIT 10
                """, n=r["name"]).data()
                results.append({
                    "kind": "Genre", "name": r["name"], "desc": r["desc"] or "",
                    "bpm_min": r["bpm_min"], "bpm_max": r["bpm_max"], "devices": devs,
                })

        elif cat == "Workflows":
            where = _where(["toLower(w.name)", "toLower(coalesce(w.description,''))"])
            rows = s.run(f"""
                MATCH (w:Workflow) {where}
                ORDER BY w.name LIMIT $lim
                RETURN w.name AS name, w.description AS desc,
                       w.use_case AS use_case, w.steps AS steps
            """, words=words, lim=limit).data()
            for r in rows:
                devs = s.run("""
                    MATCH (w:Workflow {name:$n})-[:REQUIRES]->(d:Device)
                    RETURN d.name AS n LIMIT 6
                """, n=r["name"]).data()
                results.append({
                    "kind": "Workflow", "name": r["name"], "desc": r["desc"] or "",
                    "use_case": r["use_case"] or "", "steps": r["steps"] or "",
                    "devices": [x["n"] for x in devs],
                })

        elif cat == "Production Patterns":
            where = _where(["toLower(p.name)", "toLower(coalesce(p.description,''))",
                             "toLower(coalesce(p.genre,''))", "toLower(coalesce(p.use_case,''))"])
            rows = s.run(f"""
                MATCH (p:ProductionPattern) {where}
                ORDER BY p.name LIMIT $lim
                RETURN p.name AS name, p.description AS desc,
                       p.genre AS genre, p.use_case AS use_case,
                       p.approach AS approach, p.difficulty AS difficulty,
                       p.source_project AS source
            """, words=words, lim=limit).data()
            for r in rows:
                devs = s.run("""
                    MATCH (p:ProductionPattern {name:$n})-[:INVOLVES]->(d:Device)
                    RETURN d.name AS n LIMIT 6
                """, n=r["name"]).data()
                results.append({
                    "kind": "ProductionPattern", "name": r["name"], "desc": r["desc"] or "",
                    "genre": r["genre"] or "", "use_case": r["use_case"] or "",
                    "approach": r["approach"] or "", "difficulty": r["difficulty"] or "",
                    "source": r["source"] or "", "devices": [x["n"] for x in devs],
                })

        elif cat == "Concepts":
            where = _where(["toLower(c.name)", "toLower(coalesce(c.description,''))"])
            rows = s.run(f"""
                MATCH (c:Concept) {where}
                ORDER BY c.name LIMIT $lim
                RETURN c.name AS name, c.description AS desc,
                       c.category AS category, c.use_case AS use_case
            """, words=words, lim=limit).data()
            for r in rows:
                results.append({
                    "kind": "Concept", "name": r["name"], "desc": r["desc"] or "",
                    "category": r["category"] or "", "use_case": r["use_case"] or "",
                })

    return results


def _dtype_icon(dtype: str) -> str:
    return {
        "instrument": "🎹", "fx": "🎛️", "modulation": "🌊",
        "device": "🔲", "mixing": "🎚️", "data": "📊",
        "pitch": "🎵", "hardware": "🔌", "MIDI": "🎹",
        "Note FX": "🎵", "display": "👁", "oscillator": "〜",
    }.get(dtype, "📦")


def _render_browser_tile(r: dict, idx: int = 0) -> None:
    kind = r["kind"]
    name = r["name"]
    desc = (r["desc"] or "")[:120]

    if kind == "Device":
        icon = _dtype_icon(r.get("dtype",""))
        meta = " · ".join(p for p in [r.get("dtype",""), r.get("category",""), r.get("tab","")] if p)
        border = "#4c9be8"
    elif kind == "Genre":
        icon = "🎵"
        bmin, bmax = r.get("bpm_min"), r.get("bpm_max")
        meta = f"{bmin}–{bmax} BPM" if bmin else ""
        border = "#fab387"
    elif kind == "Workflow":
        icon = "🔄"
        meta = r.get("use_case","")[:60]
        border = "#cba6f7"
    elif kind == "ProductionPattern":
        icon = "🎛️"
        meta = " · ".join(p for p in [r.get("genre",""), r.get("difficulty",""), r.get("source","")] if p)
        border = "#a6e3a1"
    else:  # Concept
        icon = "💡"
        meta = r.get("category","")
        border = "#f9e2af"

    label = f"{icon} **{name}**"
    if meta:
        label += f"  \n<small style='color:#6c7086'>{meta}</small>"

    with st.expander(f"{icon} **{name}**", expanded=False):
        if meta:
            st.caption(meta)
        if desc:
            st.markdown(desc + ("…" if len(r["desc"]) > 120 else ""))

        if kind == "Device":
            if r.get("use_case"):
                st.markdown(f"**Wann:** {r['use_case'][:250]}")
            if r.get("path"):
                st.caption(f"📍 {r['path']}")
            if r.get("params"):
                with st.container():
                    for p in r["params"][:6]:
                        pd = p.get("desc") or ""
                        lo, hi = p.get("low",""), p.get("high","")
                        line = f"• **{p['name']}**"
                        if pd:  line += f" — {pd[:80]}"
                        if lo and hi: line += f" _(↓{lo} / ↑{hi})_"
                        st.caption(line)
            if r.get("similar"):
                st.markdown("**Ähnlich:** " + " ".join(f"`{s}`" for s in r["similar"]))
            if r.get("tips"):
                try:
                    tips = json.loads(r["tips"]) if isinstance(r["tips"], str) else r["tips"]
                    if tips:
                        st.markdown("**Tipps:**")
                        for t in tips[:3]:
                            st.caption(f"→ {t}")
                except Exception:
                    pass

        elif kind == "Genre":
            devs = r.get("devices", [])
            if devs:
                st.markdown("**Typische Devices:**")
                for d in devs:
                    role = d.get("role","")
                    st.caption(f"• {d['n']}" + (f" _({role})_" if role else ""))

        elif kind == "Workflow":
            if r.get("use_case"):
                st.markdown(f"**Wann:** {r['use_case'][:200]}")
            steps_raw = r.get("steps","")
            if steps_raw:
                try:
                    steps = json.loads(steps_raw) if steps_raw.startswith("[") else steps_raw.split("\n")
                except Exception:
                    steps = steps_raw.split("\n")
                for i, step in enumerate(steps[:8], 1):
                    if str(step).strip():
                        st.caption(f"{i}. {step}")
            if r.get("devices"):
                st.markdown("**Devices:** " + " ".join(f"`{d}`" for d in r["devices"]))

        elif kind == "ProductionPattern":
            if r.get("use_case"):
                st.markdown(f"**Wann:** {r['use_case'][:200]}")
            if r.get("approach"):
                st.markdown(f"**Vorgehen:**\n{r['approach'][:500]}")
            if r.get("devices"):
                st.markdown("**Devices:** " + " ".join(f"`{d}`" for d in r["devices"]))

        elif kind == "Concept":
            if r.get("use_case"):
                st.markdown(f"**Wann:** {r['use_case'][:200]}")

        # Aktions-Buttons
        btn_col1, btn_col2 = st.columns(2)
        q = (f"Erkläre {name}" if kind in ("Device","Genre","Concept")
             else f"Zeige das Muster: {name}" if kind == "ProductionPattern"
             else f"Erkläre den Workflow: {name}")
        with btn_col1:
            if st.button("💬 Chat", key=f"ask_{idx}_{kind}_{name[:28]}",
                         use_container_width=True, disabled=not llm_ok):
                _do_chat(q)
        with btn_col2:
            # Für Devices: direkt in Bitwig laden via Agent
            if kind == "Device":
                if st.button("⚡ Laden", key=f"load_{idx}_{name[:28]}",
                             use_container_width=True, disabled=not llm_ok):
                    _do_chat(
                        f"Füge das Bitwig-Device '{name}' zum aktuellen Track hinzu. "
                        "Erstelle falls nötig einen neuen Instrument-Track."
                    )


with tab_browser:
    if not neo4j_ok:
        st.info("Neo4j nicht verbunden.")
        st.stop()

    # Bitwig-Status-Zeile im Browser
    if bitwig_ok:
        bw_c1, bw_c2, bw_c3, bw_c4 = st.columns(4)
        with bw_c1:
            if st.button("▶", use_container_width=True, help="Play"):
                try:
                    from src.agent.tools.bitwig_tools import control_bitwig
                    control_bitwig.invoke({"action": "play"})
                    st.toast("▶ Play")
                except Exception as e:
                    st.toast(str(e), icon="❌")
        with bw_c2:
            if st.button("■", use_container_width=True, help="Stop"):
                try:
                    from src.agent.tools.bitwig_tools import control_bitwig
                    control_bitwig.invoke({"action": "stop"})
                    st.toast("■ Stop")
                except Exception as e:
                    st.toast(str(e), icon="❌")
        with bw_c3:
            if st.button("⟳", use_container_width=True, help="Rewind"):
                try:
                    from src.agent.tools.bitwig_tools import control_bitwig
                    control_bitwig.invoke({"action": "rewind"})
                    st.toast("⟳")
                except Exception as e:
                    st.toast(str(e), icon="❌")
        with bw_c4:
            st.markdown("<span class='badge-ok'>● Bitwig</span>", unsafe_allow_html=True)
    else:
        st.warning("Bitwig nicht verbunden — DrivenByMoss OSC prüfen (Port 8001)", icon="🎛️")

    nav_col, main_col = st.columns([1, 4], gap="medium")

    # ── Linke Navigations-Spalte ──────────────────────────────────────────────
    with nav_col:
        st.markdown("**Kategorie**")
        cat = st.radio(
            "Kategorie",
            list(_CAT_ICONS.keys()),
            index=list(_CAT_ICONS.keys()).index(
                st.session_state.get("browser_cat", "Devices")
            ),
            label_visibility="collapsed",
            key="browser_cat_radio",
            format_func=lambda c: f"{_CAT_ICONS[c]} {c}",
        )
        st.session_state.browser_cat = cat

        # Sub-Typ-Filter (nur für Devices)
        if cat == "Devices":
            st.markdown("**Typ**")
            subtypes = _get_device_subtypes()
            subtype = st.radio(
                "Typ",
                ["Alle"] + subtypes,
                index=0,
                label_visibility="collapsed",
                key="browser_sub_radio",
            )
        else:
            subtype = "Alle"

    # ── Haupt-Content-Bereich ─────────────────────────────────────────────────
    with main_col:
        # Suchleiste
        search = st.text_input(
            "",
            placeholder=f"🔍  {cat} durchsuchen …",
            key="browser_search_input",
            label_visibility="collapsed",
        )

        # Ergebnisse laden
        results = _browser_query(cat, subtype, search, limit=60)

        # Stats-Zeile
        n = len(results)
        if search:
            suffix = f" · Typ: {subtype}" if subtype != "Alle" else ""
            st.caption(f"**{n}** Ergebnisse für \"{search}\"{suffix}")
        elif subtype != "Alle":
            st.caption(f"**{n}** {cat} · {subtype}")
        else:
            st.caption(f"**{n}** {cat}")

        if not results:
            st.info("Keine Ergebnisse — andere Suche oder Kategorie wählen.")
        else:
            # 3-spaltige Tile-Grid
            cols = st.columns(3, gap="small")
            for i, r in enumerate(results):
                with cols[i % 3]:
                    _render_browser_tile(r, idx=i)


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  Tab 3 — Analyse
# ╚══════════════════════════════════════════════════════════════════════════════
with tab_analyse:
    st.subheader("Audio-Analyse")

    a_col, b_col = st.columns([2, 1])
    with a_col:
        file_path  = st.text_input("Pfad zur Audiodatei", placeholder="/home/…/song.mp3")
        output_dir = st.text_input("Ausgabeordner (optional)")
    with b_col:
        separate_stems = st.checkbox("Stems trennen", value=True)
        extract_midi   = st.checkbox("MIDI extrahieren", value=True)
        send_osc       = st.checkbox("→ Bitwig OSC", value=True)

    if st.button("▶ Analysieren", type="primary") and file_path:
        fp = file_path
        if not Path(fp).exists():
            fp = file_path.replace("\\","/").replace("C:","/mnt/c").replace("c:","/mnt/c")
        with st.spinner("Analysiere … (Stems: 1–3 Min)"):
            try:
                from src.agent.tools.analyse import analyse_audio
                st.session_state.analyse_result = analyse_audio.invoke({
                    "file_path": fp, "output_dir": output_dir or "",
                    "separate_stems": separate_stems,
                    "extract_midi": extract_midi, "send_osc": send_osc,
                })
            except Exception as e:
                st.error(f"Fehler: {e}")

    r = st.session_state.analyse_result
    if r and "error" not in r:
        st.divider()
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("BPM",    f"{r.get('bpm', '?'):.2f}" if r.get("bpm") else "?")
        mc2.metric("Tonart",  r.get("key","?"))
        mc3.metric("Dauer",  f"{r.get('duration_s',0)/60:.1f} min")
        mc4.metric("Takt",    r.get("time_sig","4/4"))

        if r.get("osc",{}).get("status") == "ok":
            st.success(f"✓ BPM {r['bpm']:.2f} via OSC an Bitwig")

        stems_tab, midi_tab = st.tabs(["🎚️ Stems", "🎵 MIDI"])

        with stems_tab:
            if r.get("quality"):
                try:
                    import plotly.graph_objects as go
                    quality = r["quality"]
                    names   = [q["stem"].capitalize() for q in quality]
                    scores  = [q["score"] for q in quality]
                    bleeds  = [q["bleed_pct"] for q in quality]
                    colors  = ["#a6e3a1" if s >= 0.6 else "#f9e2af" if s >= 0.4 else "#f38ba8"
                               for s in scores]
                    fig = go.Figure()
                    fig.add_bar(name="Score", x=names, y=scores,
                                marker_color=colors, text=[f"{s:.2f}" for s in scores],
                                textposition="outside")
                    fig.add_scatter(name="Bleed %", x=names, y=[b/100 for b in bleeds],
                                    mode="markers+lines", yaxis="y2",
                                    marker=dict(size=10, color="#f9e2af"))
                    fig.update_layout(
                        yaxis=dict(title="Score", range=[0,1.1]),
                        yaxis2=dict(title="Bleed %", overlaying="y", side="right",
                                    range=[0,1.1], tickformat=".0%"),
                        height=300, margin=dict(t=10), paper_bgcolor="#1e1e2e",
                        plot_bgcolor="#1e1e2e", font=dict(color="#cdd6f4"),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except Exception:
                    pass
            else:
                st.info("Keine Stem-Daten.")

        with midi_tab:
            if r.get("midi"):
                st.code(r["midi"])
            else:
                st.info("Keine MIDI-Datei.")

    elif r and "error" in r:
        st.error(r["error"])

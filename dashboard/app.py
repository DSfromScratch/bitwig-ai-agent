"""
Bitwig Audio Agent — Streamlit Companion Dashboard
Läuft neben Bitwig Studio und kommuniziert via OSC.
"""

import json
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

# ── Session State ─────────────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []


# ── Sidebar: Datei + Einstellungen ────────────────────────────────────────────

with st.sidebar:
    st.title("🎛️ Bitwig Audio Agent")
    st.divider()

    st.subheader("Audiodatei")
    file_path = st.text_input(
        "Pfad zur Audiodatei",
        placeholder="C:\\Users\\...\\song.mp3",
        help="MP3, WAV oder FLAC"
    )
    output_dir = st.text_input(
        "Ausgabeordner (optional)",
        placeholder="Standard: <datei>_bitwig/",
    )

    col1, col2 = st.columns(2)
    with col1:
        separate_stems = st.checkbox("Stems trennen", value=True)
        extract_midi   = st.checkbox("MIDI extrahieren", value=True)
    with col2:
        send_osc = st.checkbox("→ Bitwig OSC", value=True)

    analyse_btn = st.button("▶ Analysieren", type="primary", use_container_width=True)

    st.divider()
    st.subheader("Bitwig OSC-Steuerung")
    osc_col1, osc_col2, osc_col3 = st.columns(3)
    with osc_col1:
        if st.button("▶ Play", use_container_width=True):
            from src.agent.tools.bitwig_tools import control_bitwig
            control_bitwig.invoke({"action": "play"})
            st.success("Play")
    with osc_col2:
        if st.button("■ Stop", use_container_width=True):
            from src.agent.tools.bitwig_tools import control_bitwig
            control_bitwig.invoke({"action": "stop"})
            st.success("Stop")
    with osc_col3:
        bpm_val = st.number_input("BPM", min_value=20, max_value=300, value=120, step=1, label_visibility="collapsed")
    if st.button("BPM setzen", use_container_width=True):
        from src.agent.tools.bitwig_tools import control_bitwig
        control_bitwig.invoke({"action": "tempo", "bpm": float(bpm_val)})
        st.success(f"BPM → {bpm_val}")

    st.divider()
    st.subheader("MIDI Validierung")
    ref_midi = st.text_input("Referenz-MIDI (Bitwig-Export)", placeholder="C:\\...\\song.mid")
    if st.button("Validieren", use_container_width=True) and st.session_state.last_result:
        r = st.session_state.last_result
        gen_midi = r.get("midi") or ""
        if gen_midi and ref_midi:
            from src.audio.midi_validate import validate
            val = validate(gen_midi, ref_midi)
            st.session_state.validation = val
        else:
            st.warning("Erst Analyse ausführen und Referenz-MIDI angeben.")


# ── Analyse ausführen ─────────────────────────────────────────────────────────

if analyse_btn and file_path:
    # Windows-Pfad → WSL
    wsl_path = file_path.replace("\\", "/").replace("C:", "/mnt/c").replace("c:", "/mnt/c")
    if not Path(wsl_path).exists() and Path(file_path).exists():
        wsl_path = file_path

    with st.spinner("Analysiere… (Stems-Trennung dauert 1–3 Min)"):
        from src.agent.tools.analyse import analyse_audio
        result = analyse_audio.invoke({
            "file_path":       wsl_path,
            "output_dir":      output_dir or "",
            "separate_stems":  separate_stems,
            "extract_midi":    extract_midi,
            "send_osc":        send_osc,
        })
        st.session_state.last_result = result


# ── Hauptbereich: Tabs ────────────────────────────────────────────────────────

tab_analyse, tab_stems, tab_midi, tab_dawproject, tab_chat = st.tabs([
    "📊 Analyse", "🎚️ Stems", "🎵 MIDI", "📁 DAWproject", "💬 Agent Chat"
])


# ── Tab 1: Analyse ────────────────────────────────────────────────────────────

with tab_analyse:
    r = st.session_state.last_result
    if not r:
        st.info("Wähle eine Audiodatei und klicke **Analysieren**.")
    elif "error" in r:
        st.error(r["error"])
    else:
        st.subheader("Ergebnis")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("BPM",      f"{r.get('bpm', '?'):.2f}")
        c2.metric("Tonart",    r.get("key", "?"))
        c3.metric("Dauer",    f"{r.get('duration_s', 0)/60:.1f} min")
        c4.metric("Taktart",   r.get("time_sig", "4/4"))

        if r.get("osc"):
            osc = r["osc"]
            if osc.get("status") == "ok":
                st.success(f"✓ BPM {r['bpm']:.2f} via OSC an Bitwig gesendet")

        if r.get("dawproject"):
            daw = r["dawproject"]
            st.success(f"✓ DAWproject erstellt: `{Path(daw).name}`")
            st.code(daw)

        if r.get("pipeline_error"):
            st.warning(f"Pipeline-Fehler: {r['pipeline_error']}")


# ── Tab 2: Stems ─────────────────────────────────────────────────────────────

with tab_stems:
    r = st.session_state.last_result
    if not r or not r.get("quality"):
        st.info("Stems werden nach der Analyse angezeigt.")
    else:
        st.subheader("Stem-Qualität")
        import plotly.graph_objects as go

        quality = r["quality"]
        names  = [q["stem"].capitalize() for q in quality]
        scores = [q["score"] for q in quality]
        bleeds = [q["bleed_pct"] for q in quality]
        colors = ["#4CAF50" if s >= 0.6 else "#FF9800" if s >= 0.4 else "#F44336"
                  for s in scores]

        fig = go.Figure()
        fig.add_bar(name="Score", x=names, y=scores,
                    marker_color=colors, text=[f"{s:.2f}" for s in scores],
                    textposition="outside")
        fig.add_scatter(name="Bleed %", x=names, y=[b/100 for b in bleeds],
                        mode="markers+lines", yaxis="y2",
                        marker=dict(size=10, color="#E8C152"))
        fig.update_layout(
            yaxis=dict(title="Score (0–1)", range=[0, 1.1]),
            yaxis2=dict(title="Bleed %", overlaying="y", side="right",
                        range=[0, 1.1], tickformat=".0%"),
            legend=dict(orientation="h", y=-0.2),
            height=350, margin=dict(t=20),
        )
        st.plotly_chart(fig, use_container_width=True)

        for q in quality:
            with st.expander(f"{q['stem'].capitalize()} — {q['quality']}"):
                cc1, cc2, cc3, cc4 = st.columns(4)
                cc1.metric("Score",    f"{q['score']:.2f}")
                cc2.metric("RMS",      f"{q['rms_db']:.1f} dB")
                cc3.metric("Bleed",    f"{q['bleed_pct']:.1f}%")
                cc4.metric("Stille",   f"{q['silence_pct']:.1f}%")

        if r.get("stems") and isinstance(r["stems"], dict) and "error" not in r["stems"]:
            st.subheader("Stem-Dateien")
            for name, path in r["stems"].items():
                st.code(f"{name}: {path}")


# ── Tab 3: MIDI ───────────────────────────────────────────────────────────────

with tab_midi:
    r = st.session_state.last_result
    if not r or not r.get("midi"):
        st.info("MIDI wird nach der Analyse angezeigt.")
    else:
        st.subheader("Extrahierte Melodie")
        midi_path = r["midi"]
        st.code(midi_path)

        if r.get("stems_used"):
            st.caption(f"Generiert aus: {', '.join(r['stems_used'])}"
                       + (" + Piano" if r.get("piano_used") else ""))

        # Piano Roll Visualisierung
        try:
            import mido
            import plotly.graph_objects as go

            mid = mido.MidiFile(midi_path)
            tpb = mid.ticks_per_beat
            tempo_us = 500_000
            notes_data = []
            for track in mid.tracks:
                active = {}
                t_s = 0.0
                for msg in track:
                    if msg.type == "set_tempo":
                        tempo_us = msg.tempo
                    spb = (tempo_us / 1_000_000) / tpb
                    t_s += msg.time * spb
                    if msg.type == "note_on" and msg.velocity > 0:
                        active[msg.note] = t_s
                    elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                        if msg.note in active:
                            notes_data.append((active.pop(msg.note), t_s, msg.note))

            if notes_data:
                max_t = min(max(e for _, e, _ in notes_data), 60.0)
                fig = go.Figure()
                for start, end, pitch in notes_data:
                    if start > max_t:
                        continue
                    fig.add_shape(type="rect",
                                  x0=start, x1=min(end, max_t),
                                  y0=pitch - 0.4, y1=pitch + 0.4,
                                  fillcolor="#4C9BE8", line_width=0, opacity=0.7)
                fig.update_layout(
                    title="Piano Roll (erste 60s)",
                    xaxis_title="Zeit (s)", yaxis_title="MIDI-Note",
                    xaxis=dict(range=[0, max_t]),
                    yaxis=dict(range=[45, 90]),
                    height=300, margin=dict(t=40),
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.warning(f"Piano Roll konnte nicht geladen werden: {e}")

        # Beat-Grid
        if r.get("beat_grid") and Path(r["beat_grid"]).exists():
            with st.expander("Beat-Grid"):
                bg = json.loads(Path(r["beat_grid"]).read_text())
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Beats",  bg.get("beat_count", 0))
                cc2.metric("Takte",  bg.get("bar_count", 0))
                cc3.metric("Taktart", bg.get("time_signature", "4/4"))

        # Validierung
        if "validation" in st.session_state:
            v = st.session_state.validation
            st.subheader("Validierung vs. Referenz")
            vc1, vc2, vc3 = st.columns(3)
            vc1.metric("Overlap exakt",   f"{v.get('overlap_strict', 0):.1%}")
            vc2.metric("Overlap ±1HT",    f"{v.get('overlap_loose', 0):.1%}")
            vc3.metric("Pitch-Abweichung", f"{v.get('pitch_mean_diff', 0):+.1f} HT")
            for hint in v.get("hints", []):
                st.info(hint)


# ── Tab 4: DAWproject ─────────────────────────────────────────────────────────

with tab_dawproject:
    r = st.session_state.last_result
    if not r or not r.get("dawproject"):
        st.info("DAWproject wird nach der Analyse erstellt.")
    else:
        daw_path = r["dawproject"]
        st.subheader("Bitwig Projekt-Import")
        st.success(f"✓ Fertig: `{Path(daw_path).name}`")

        st.markdown("""
**In Bitwig Studio 6 öffnen:**
1. Menü **Datei → Öffnen** (oder Drag & Drop)
2. Datei `{name}` auswählen
3. Das Projekt öffnet sich mit:
   - Allen Stems auf eigenen Tracks
   - Melodie-MIDI auf einem Instrument-Track
   - Korrektem Tempo ({bpm:.0f} BPM) und Taktart ({tsig})
   - Bar-Markern für alle Takte
        """.format(
            name=Path(daw_path).name,
            bpm=r.get("bpm", 0),
            tsig=r.get("time_sig", "4/4"),
        ))

        st.code(daw_path, language=None)

        import zipfile
        if Path(daw_path).exists():
            with zipfile.ZipFile(daw_path) as z:
                files = z.namelist()
                st.caption(f"Enthält {len(files)} Dateien: {', '.join(files[:8])}")

        if r.get("import_guide"):
            guide_path = Path(r["import_guide"])
            if guide_path.exists():
                with st.expander("Import-Anleitung"):
                    st.text(guide_path.read_text(encoding="utf-8"))


# ── Tab 5: Agent Chat ─────────────────────────────────────────────────────────

with tab_chat:
    st.subheader("💬 Chat mit dem Bitwig Audio Agent")
    st.caption("Der Agent kann Fragen zur Analyse beantworten, Tools aufrufen und Bitwig steuern.")

    chat_container = st.container(height=450)
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    if prompt := st.chat_input("Frage stellen oder Befehl geben…"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})

        # Kontext aus letzter Analyse anhängen
        ctx = ""
        if st.session_state.last_result:
            r = st.session_state.last_result
            ctx = (f"\n\n[Letztes Analyse-Ergebnis: BPM={r.get('bpm')}, "
                   f"Tonart={r.get('key')}, Datei={r.get('output_dir')}]")

        with st.spinner("Agent denkt…"):
            try:
                from src.agent.core import chat as agent_chat
                from langchain_core.messages import HumanMessage

                lc_history = []
                for m in st.session_state.chat_history[:-1]:
                    if m["role"] == "user":
                        lc_history.append(HumanMessage(content=m["content"]))

                response = agent_chat(prompt + ctx, history=lc_history)
                st.session_state.chat_history.append({"role": "assistant", "content": response})
            except Exception as e:
                err = f"Agent-Fehler: {e}"
                st.session_state.chat_history.append({"role": "assistant", "content": err})

        st.rerun()

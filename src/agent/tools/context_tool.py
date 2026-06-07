"""
Tool: get_song_context

Gibt den musikalischen Kontext eines Bitwig-Projekts zurück:
Tempo, Tonart, Szenen/Energie, Track-Rollen, MIDI-Infos, Arranger-Struktur,
Device-Ketten und Parameter-Zusammenfassung.
"""
from __future__ import annotations

import json

from langchain_core.tools import tool

_PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _midi_name(pitch: int) -> str:
    return _PITCH_NAMES[pitch % 12] + str(pitch // 12 - 1)


def _format_notes(notes_json: str, max_events: int = 24) -> str:
    """Konvertiert notes_json zu kompakter Noten-Sequenz.

    Polyphonie-bewusst: Noten am gleichen Step werden als Akkord zusammengefasst.
    Gleiche aufeinanderfolgende Akkorde werden zu einem Event mit Gesamtdauer.
    Format: 'C#5+A3+A2(s0,d16) F#5(s16,d3) ...'
    Steps sind relativ zum ersten Step normalisiert.
    """
    try:
        notes = json.loads(notes_json)
    except Exception:
        return "?"
    if not notes:
        return "–"

    notes = sorted(notes, key=lambda n: n['step'])
    offset = notes[0]['step']

    # Step → frozenset(pitches) gruppieren
    from collections import defaultdict
    step_chords: dict[int, set] = defaultdict(set)
    for n in notes:
        step_chords[n['step'] - offset].add(n['pitch'])

    sorted_steps = sorted(step_chords)

    # Aufeinanderfolgende identische Akkorde zu Events zusammenfassen
    events: list[tuple[int, frozenset, int]] = []  # (start_step, chord, duration)
    cur_start = sorted_steps[0]
    cur_chord = frozenset(step_chords[sorted_steps[0]])
    cur_len   = 1
    for step in sorted_steps[1:]:
        chord = frozenset(step_chords[step])
        if chord == cur_chord and step == cur_start + cur_len:
            cur_len += 1
        else:
            events.append((cur_start, cur_chord, cur_len))
            cur_start = step
            cur_chord = chord
            cur_len   = 1
    events.append((cur_start, cur_chord, cur_len))

    def fmt_chord(pitches: frozenset) -> str:
        return "+".join(_midi_name(p) for p in sorted(pitches, reverse=True))

    parts = [f"{fmt_chord(c)}(s{s},d{d})" for s, c, d in events[:max_events]]
    suffix = f" … +{len(events) - max_events} weitere" if len(events) > max_events else ""
    return " ".join(parts) + suffix


def _classify_role(track_name: str, device: str | None) -> str:
    name = track_name.lower()
    dev  = (device or "").lower()
    if any(k in name for k in ("kick", "bass drum", "bd")):               return "kick"
    if any(k in name for k in ("snare", "clap", "rimshot")):              return "snare"
    if any(k in name for k in ("hat", "perc", "cymbal")):                 return "hats"
    if any(k in name for k in ("drum", "percussion")):                    return "drums"
    if any(k in name for k in ("bass",)):                                 return "bass"
    if any(k in name for k in ("arp", "stringer")):                       return "arp"
    if any(k in name for k in ("pad", "ambient", "texture", "atmo",
                                "loopy", "swarm")):                       return "pad"
    if any(k in name for k in ("lead", "melody", "pluck", "sine",
                                "sawtooth")):                             return "lead"
    if any(k in name for k in ("chord", "stab", "keys", "piano")):       return "chord"
    if any(k in name for k in ("vox", "vocal", "voice")):                return "vocal"
    if any(k in name for k in ("fx", "effect", "noise")):                return "fx"
    if any(k in name for k in ("body", "synth")):                         return "synth"
    if "poly grid" in dev or "fx grid" in dev:                           return "synth"
    return "synth"


@tool
def get_song_context(project_name: str = "") -> str:
    """Gibt den vollständigen musikalischen Song-Kontext aus der Wissensdatenbank zurück.

    Zeigt: Tempo, Tonart, Arranger-Struktur, Szenen-Energie, Track-Rollen,
    Device-Ketten, MIDI-Clip-Infos (Tonart, Notenanzahl) und Parameter.

    Vor dem Schreiben von Patterns oder dem Einfügen von Tracks aufrufen,
    um den Song musikalisch vollständig zu verstehen.

    Args:
        project_name: Name des Projekts (z.B. "Chee - Hey Now").
                      Leer lassen — dann wird das aktuell in Bitwig geöffnete Projekt gelesen.
    """
    try:
        from src.knowledge.neo4j_graph import is_available, session
        if not is_available():
            return "❌ Neo4j nicht erreichbar."
    except Exception as e:
        return f"❌ Neo4j-Fehler: {e}"

    # Projektname aus Bitwig holen wenn nicht angegeben
    if not project_name:
        try:
            from src.agent.osc.project_scan import get_project_name
            project_name = get_project_name() or ""
        except Exception:
            pass

    with session() as s:
        # Projekt-Basis
        proj = None
        if project_name:
            proj = s.run("""
                MATCH (p:BitwigProject {name: $name})
                RETURN p.tempo AS tempo, p.name AS name
            """, name=project_name).single()

        if not proj and project_name:
            proj = s.run("""
                MATCH (p:BitwigProject)
                WHERE toLower(p.name) CONTAINS toLower($name)
                   OR toLower($name) CONTAINS toLower(p.name)
                RETURN p.tempo AS tempo, p.name AS name
                LIMIT 1
            """, name=project_name).single()

        # Fallback: neuestes Projekt in DB
        if not proj:
            proj = s.run("""
                MATCH (p:BitwigProject)
                RETURN p.tempo AS tempo, p.name AS name
                ORDER BY p.updated_at DESC
                LIMIT 1
            """).single()

        if not proj:
            return ("❌ Kein Projekt in der Wissensdatenbank.\n"
                    "Rufe erst scan_and_learn_project() auf.")

        actual_name = proj["name"]
        _t = proj["tempo"] or 0
        tempo = round(20 + _t * 646) if 0 < _t <= 2 else round(_t)

        # Szenen mit Energie-Level
        scenes = s.run("""
            MATCH (sc:Scene {project: $proj})
            RETURN sc.idx AS idx, sc.name AS name,
                   sc.clip_count AS clip_count, sc.active_tracks AS active,
                   sc.total_tracks AS total, sc.energy_level AS energy
            ORDER BY sc.idx
        """, proj=actual_name).data()

        # Tracks mit Rollen + aktiven Szenen + Device-Kette
        # Dedupliziert nach track_name: bevorzuge das Recipe mit device_chain
        recipes_raw = s.run("""
            MATCH (sr:SoundRecipe {project: $proj})
            OPTIONAL MATCH (sr)-[:HAS_CLIP_IN_SCENE]->(sc:Scene)
            WITH sr, collect(sc.name) AS active_scenes
            RETURN sr.track_name    AS name,
                   sr.role          AS role,
                   sr.primary_device AS device,
                   sr.device_chain  AS chain,
                   sr.track_index   AS idx,
                   sr.params_json   AS params,
                   active_scenes
            ORDER BY sr.track_index
        """, proj=actual_name).data()

        # Deduplizierung: pro track_name das mit device_chain behalten
        seen_names: dict = {}
        for r in recipes_raw:
            name = r["name"]
            if name not in seen_names:
                seen_names[name] = r
            else:
                existing = seen_names[name]
                # Bevorzuge das mit device_chain und aktiven Szenen
                existing_score = bool(existing["chain"]) + len(existing["active_scenes"])
                new_score = bool(r["chain"]) + len(r["active_scenes"])
                if new_score > existing_score:
                    seen_names[name] = r
        recipes = sorted(seen_names.values(), key=lambda r: r["idx"] or 0)

        # Tonart aus MidiClips (häufigster Wert)
        key_row = s.run("""
            MATCH (mc:MidiClip {project: $proj})
            WHERE mc.full_key IS NOT NULL
            RETURN mc.full_key AS k, count(*) AS n
            ORDER BY n DESC LIMIT 1
        """, proj=actual_name).single()
        key = key_row["k"] if key_row else "unbekannt"

        # MidiClip-Details pro Track (inkl. Noten)
        midi_clips = s.run("""
            MATCH (mc:MidiClip {project: $proj})
            RETURN mc.track_name AS track, mc.full_key AS key,
                   mc.note_count AS notes, mc.scene_name AS scene,
                   mc.notes_json AS notes_json, mc.loop_beats AS loop_beats,
                   mc.quantization AS quantization, mc.rhythm_pattern AS rhythm
            ORDER BY mc.track_name
        """, proj=actual_name).data()

        # Arranger-Struktur (TimelineSections mit Position)
        sections = s.run("""
            MATCH (ts:TimelineSection {project: $proj})
            RETURN ts.name AS name, ts.beat AS beat, ts.bar AS bar,
                   ts.length_bars AS length_bars
            ORDER BY ts.beat
        """, proj=actual_name).data()

        # AudioSamples
        audio_samples = s.run("""
            MATCH (a:AudioSample {project: $proj})
            RETURN a.filename AS file, a.category AS cat,
                   a.key_note AS key, a.tempo_bpm AS bpm,
                   a.duration_s AS dur, a.rms AS rms
            ORDER BY a.category, a.filename
        """, proj=actual_name).data()

        # TrackGroups (nur Top-Level mit Children)
        track_groups = s.run("""
            MATCH (tg:TrackGroup {project: $proj})
            WHERE tg.children IS NOT NULL
            RETURN tg.name AS name, tg.role AS role,
                   tg.children AS children, tg.group_fx AS fx
            ORDER BY tg.track_index
        """, proj=actual_name).data()

    # ── Ausgabe aufbauen ──────────────────────────────────────────────────────
    lines = [
        f"🎵 **{actual_name}**",
        f"   Tempo: {tempo} BPM | Tonart: {key}",
        "",
    ]

    # Arranger-Struktur mit Beat-Positionen
    if sections:
        lines.append("**Arranger-Struktur (Beat-Position | Takte | Länge):**")
        # Duplikate nach Beat deduplizieren (manche Sections überlappen)
        seen_beats: set = set()
        for sec in sections:
            beat = sec["beat"]
            if beat in seen_beats:
                continue
            seen_beats.add(beat)
            bar  = int(sec["bar"] or 0)
            lb   = int(sec["length_bars"] or 0)
            lines.append(f"  Takt {bar:>3}  (Beat {int(beat):>4})  {lb:>2} Takte — {sec['name']}")
        lines.append("")

    # Szenen
    if scenes:
        lines.append("**Szenen (Energie 0.0=leer → 1.0=voll):**")
        max_clip = max((sc["clip_count"] or 0 for sc in scenes), default=1)
        for sc in scenes:
            energy = sc["energy"] if sc["energy"] is not None else (sc["clip_count"] or 0) / max(max_clip, 1)
            bar    = "█" * int(energy * 10) + "░" * (10 - int(energy * 10))
            active = sc["active"] or sc["clip_count"] or 0
            total  = sc["total"] or "?"
            lines.append(f"  {sc['name']:<10} [{bar}] {energy:.0%}  ({active}/{total} Tracks)")
        lines.append("")

    # Tracks mit Device-Kette + aktive Szenen
    lines.append("**Tracks — Rolle | Device-Kette | aktive Szenen:**")
    for r in recipes:
        role       = r["role"] or _classify_role(r["name"], r["device"])
        scenes_str = ", ".join(sorted(set(r["active_scenes"]))) if r["active_scenes"] else "–"
        chain      = r["chain"] or r["device"] or "–"
        # chain kürzen
        if len(chain) > 50:
            chain = chain[:47] + "…"
        lines.append(f"  [{role:<6}] {r['name']:<22} | {chain}")
        lines.append(f"           {'':22}   Szenen: {scenes_str}")

    # Track-Gruppen-Hierarchie
    if track_groups:
        lines.append("")
        lines.append("**Track-Gruppen (Hierarchie | Gruppen-FX):**")
        for g in track_groups:
            children = ", ".join(g["children"]) if g["children"] else "–"
            fx = " → ".join(g["fx"][:3]) if g["fx"] else "–"
            lines.append(f"  {g['name']:<20} → [{children}]")
            if g["fx"]:
                lines.append(f"  {'':20}   Gruppen-FX: {fx}")

    # MIDI-Clip Details mit Noten-Sequenz
    if midi_clips:
        lines.append("")
        lines.append("**MIDI-Clips (Tonart / Quantisierung / Noten-Sequenz):**")
        for mc in midi_clips:
            scene  = f" [{mc['scene']}]" if mc.get("scene") else ""
            q      = mc.get("quantization") or "1/16"
            rhythm = mc.get("rhythm") or ""
            beats  = mc.get("loop_beats") or 0
            lines.append(
                f"  {mc['track']:<22} {mc['key'] or '?':<15} "
                f"{mc['notes'] or 0} Noten | {beats:.0f} Beats | {q}{scene}"
            )
            if rhythm:
                lines.append(f"    Rhythmus: {rhythm}")
            if mc.get("notes_json"):
                seq = _format_notes(mc["notes_json"])
                # Zeile umbrechen wenn zu lang
                if len(seq) > 100:
                    words = seq.split()
                    cur_line = "    "
                    for w in words:
                        if len(cur_line) + len(w) + 1 > 100:
                            lines.append(cur_line)
                            cur_line = "    " + w
                        else:
                            cur_line += (" " if cur_line.strip() else "") + w
                    if cur_line.strip():
                        lines.append(cur_line)
                else:
                    lines.append(f"    {seq}")

    # Audio-Samples
    if audio_samples:
        lines.append("")
        lines.append("**Audio-Samples (Kategorie | Key | Dauer | RMS):**")
        cur_cat = None
        for a in audio_samples:
            cat = a["cat"] or "Sonstige"
            if cat != cur_cat:
                cur_cat = cat
                lines.append(f"  [{cat}]")
            fname = (a["file"] or "?")
            if len(fname) > 40:
                fname = fname[:37] + "…"
            bpm_s = f" ~{a['bpm']:.0f}bpm" if a.get("bpm") and a["bpm"] > 10 else ""
            lines.append(f"    {fname:<42} {a['key'] or '?':<4}  {a['dur']:.1f}s  rms={a['rms']:.3f}{bpm_s}")

    lines.append("")
    lines.append("💡 Nutze diese Info um musikalisch passende Patterns zu schreiben.")
    lines.append("   Intro=spärlich, Peak/Break=alle Tracks aktiv.")

    return "\n".join(lines)

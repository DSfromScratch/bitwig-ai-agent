# 📋 Aufgabenliste — Bitwig AI Agent

> **Stand: 7. Juni 2026** — generiert aus Test-Run + [`docs/diagrams/architecture_improvements.md`](docs/diagrams/architecture_improvements.md)
> Kombinierte Liste fehlgeschlagener Tests und noch offener Architektur-Findings.

---

## 0 · Aktuelle Phase — Woche 2: Live-Härtung

> **Woche 1 ✅ abgeschlossen** — Unit 257/257, Bridge 7/7, Neo4j 16/16 (Commits `20f32ec`, `3f398bb`, `d3a80d7`).
> Java-Extensions neu deployed: `BitwigStepPlugin.bwextension`, `LaunchpadController.bwextension`.

### 0.1 · Song-Lern-Pipeline ✅ (neu)
Implementiert in dieser Phase, um echte Beispiel-Songs als Trainingsmaterial zu sammeln:

| Tool | Zweck | Lizenz-Anforderung |
|------|-------|--------------------|
| `search_artist_song(artist, title)` | MusicBrainz + AcousticBrainz + Last.fm Metadaten (BPM, Key, Genre, Mood) | öffentlich, kein Audio |
| `learn_song_from_youtube(artist, title, url, transcribe_midi=False)` | yt-dlp Download → librosa-Features → Neo4j Persist; Audio-Datei wird nach Analyse gelöscht | **nur privat** |
| `scripts/learn_songs_batch.py list.txt` | Batch-Lerner für `artist\|title\|url`-Listen | wie oben |

Smoke-Test ✅: Kevin MacLeod "Brittle Rille" → BPM 89.1 / Key E / 230s in 26s persistiert.

### 0.2 · RL-/DPO-Trainings-Pipeline ✅ (Woche 3)
Geschlossener Lern-Loop, der den fine-getunten Composer gegen den deterministischen
Validator (`score_completion`) laufen lässt und schwache Antworten als DPO-Paare zurückspielt.

| Schritt | Script | Zweck |
|---------|--------|-------|
| 1. Genre-Daten harvesten | `scripts/harvest_freesound.py` | Freesound-Loops → BPM/Key/Energy/Onset-Skelett → `GenrePattern` in Neo4j + `training_data/freesound_genres.json` |
| 2. DPO-Paare bauen | `scripts/generate_dpo_pairs.py` | Genre-Ground-Truth (finite `write_pattern_raw`-Drums) + note_plan-Paare → `training_data/dpo_*.jsonl` |
| 3. LoRA-Retrain | `scripts/rl_train_loop.py` | LaunchAgent unload → `mlx_lm lora` (resume) → reload (Kernel-Panic-Schutz) |
| 4. Trial-Loop | `scripts/trial_compose_validate.py` | Composer↔Validator Closed-Loop, iteratives Self-Refine, Neo4j-Referenzen (`--with-kb`/`--no-kb`) |
| 5. Auswertung | `scripts/analyze_trials.py` | Solve-Rate, mean best-score, Konvergenz-Kurve, KB-Effekt, PNG-Plot |

**Ergebnis:** Drum-Runaway-Problem gelöst (Trap/Techno/House 0.00 → 0.88–0.95, alle `finish=stop`).
Trial-Läufe: with-kb & no-kb je 4/4 gelöst, mean best-score 0.92.
Doku zum Ausführen: [`README.md` §11 · RL-/DPO-Training](README.md#11--rl-dpo-training-genre-loop).

### Vorgehen (Live-Härtung)
1. **Bitwig neu starten** → neue Extensions laden.
2. Pro Session `./scripts/live_capture.sh "<kurztitel>"` ausführen — Snapshot landet in `BitwigTracks/sessions/`.
3. Findings strukturiert in [`LIVE_LOG.md`](./LIVE_LOG.md) eintragen (Vorlage dort).
4. Wiederkehrende Bugs → als P1/P2 in Abschnitt **G · Live-Findings** unten anhängen.
5. Nach ca. 5 Sessions: Findings auswerten, Severity sortieren, Sprint planen.

### Test-Szenarien (Mindest-Coverage Woche 2)
- [ ] Rock-Song (Drums + Bass + Lead), 4 Patterns, 120 BPM
- [ ] Jazz-Stück (Swing-Drums + Comping + Walking-Bass), 8 Bars
- [ ] Elektronik (Kick-Pattern + Bass-Sequence + Pad), Grid-Modulation
- [ ] Korrektur-Loop: bewusst kaputten Prompt → prüfen, ob Agent sich erholt
- [ ] Lange Session (>10 Tool-Calls) → Context-Limit-Verhalten beobachten
- [ ] **Song-Lern-Run** (10-20 Referenz-Songs aus eigener Library) → KB-Boost

### Watchpoints (basierend auf Woche-1-Bugs)
- Launchpad-Stabilität (war: `IOException → Crash`)
- `write_notes`-Track-Targeting (war: Sprung auf Track 1)
- Embedding-Server-Routing (war: Fallback auf Qwen-Port 8080)
- Räumung zwischen Runden (war: 2. Runde startete, bevor Tracks gelöscht)

---

## A · Tests reparieren — ✅ erledigt

**Ergebnis des letzten Laufs** (`pytest -m unit`):

```
250 passed · 58 deselected (0 failed)
```

### A.1 — Snapshot-Tests scheitern: `syrupy` fehlt ✅

**Symptom:** `fixture 'snapshot' not found` bei 4 Tests in `tests/test_advanced_strategies.py`.

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| `syrupy` als Test-Dependency in `requirements-ci.txt` ergänzen | `requirements-ci.txt` | XS |
| Im venv installieren: `pip install syrupy` | — | XS |
| Initiale Snapshots mit `pytest --snapshot-update` erzeugen | — | XS |

**Betroffene Tests:**
- `TestSnapshots::test_rock_drum_prompt_snapshot`
- `TestSnapshots::test_jazz_drum_prompt_snapshot`
- `TestSnapshots::test_melody_prompt_no_drum_criteria_snapshot`
- `TestSnapshots::test_error_pattern_prompt_snapshot`

### A.2 — Neo4j-RAG Mock-Tests scheitern (9 Tests) ✅

**Symptom:** Alle Tests landen im `except Exception`-Branch von
`src/agent/tools/knowledge_tool.py:614` und liefern
`[Vektorsuche nicht verfügbar: 'c']` bzw. `'NoneType' object is not subscriptable`.

**Ursache:** Die Mock-Reihenfolge in `tests/test_neo4j_rag.py::TestScoreThreshold._invoke()`
und der tatsächliche Cypher-Aufruf-Pfad in `query_bitwig_docs` driften auseinander
(zusätzlicher DB-Aufruf nicht vom Mock vorhergesehen).

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| Aktuellen Aufruf-Reihenfolgen-Pfad in `query_bitwig_docs` dokumentieren | `src/agent/tools/knowledge_tool.py` | S |
| Mock-Helper `_make_neo4j_run` an aktuelle Aufruf-Reihenfolge anpassen | `tests/test_neo4j_rag.py` | S |
| Erwartete Call-Counts in den 2 `TestKnowledgeQAGuard`-Tests aktualisieren (3→4 / 2→3) | `tests/test_neo4j_rag.py` | XS |
| Sicherstellen, dass `'c'`-Key bei COUNT-Result vorhanden ist | `tests/test_neo4j_rag.py` | XS |

**Betroffene Tests:**
- `TestScoreThreshold::test_youtube_at_075_passes`
- `TestScoreThreshold::test_structured_doc_at_070_passes`
- `TestScoreThreshold::test_mixed_results_only_above_threshold`
- `TestContextChunk::test_neighbor_chunk_appended`
- `TestContextChunk::test_no_duplicate_if_neighbor_already_in_results`
- `TestContextChunk::test_no_neighbor_query_for_non_youtube_hit`
- `TestVideoUrlLinks::test_video_url_rendered_as_link`
- `TestKnowledgeQAGuard::test_kq_query_skipped_when_zero_nodes`
- `TestKnowledgeQAGuard::test_kq_query_runs_when_nodes_present`

### A.3 — Test-Dependencies konsolidieren ✅

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| `hypothesis` (war ebenfalls fehlend) und `syrupy` zur CI-Requirements ergänzen | `requirements-ci.txt` | XS |
| CI-Workflow läuft mit `pip install -r requirements-ci.txt` — verifizieren | `.github/workflows/test.yml` | XS |

---

## B · Offene Architektur-Findings

Aus [`docs/diagrams/architecture_improvements.md`](docs/diagrams/architecture_improvements.md) — die noch nicht ✅ markierten Punkte.

### B.1 — F9 Retrieve-Then-Reason im System-Prompt ✅

**Status:** KB-Tools (`rhythm_tool`, `instrument_tool`) existieren, aber der System-Prompt
enthält noch keine konkreten `<think>`-Beispiele, die das LLM zur Begründung anhalten.

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| `RHYTHM_REASONING_INSTRUCTION` mit `<think>`-Beispielen in den System-Prompt einbauen | `src/agent/prompts.py` | S |
| `INSTRUMENT_REASONING_INSTRUCTION` analog ergänzen | `src/agent/prompts.py` | S |
| Trainingsdaten-Pair für Drum/Instrument-Reasoning im Mac-Native LoRA-Datensatz | `~/mlx-training/train.jsonl` | M |

### B.2 — F2 + F9 KB-backed Strategy-Klasse ✅

**Status:** Repositories und KB-Tools existieren, aber `pattern_generators.py` enthält
noch hardcodierte Drum-Pattern als Fallback im Produktivpfad.

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| `KBDrumPatternStrategy` als dedizierte Strategy-Klasse erstellen (Protocol-Implementierung) | `src/agent/tools/music/patterns/kb_strategy.py` (neu) | M |
| Hardcoded-Pattern in `pattern_generators.py` in `HardcodedFallbackStrategy` extrahieren | `src/agent/tools/music/patterns/fallback.py` (neu) | M |
| Aufrufer auf Strategy-Pattern umstellen | `src/agent/tools/song_tools.py`, `pattern_generators.py` | M |

### B.3 — F10 Restliche Hardcoded-Mappings entfernen ✅

**Status:** `InstrumentRepository` + `instrument_tool.py` aktiv, aber Fallback-Pfade
referenzieren noch `INSTRUMENT_MAP`.

| Aufgabe | Datei | Aufwand |
|---------|-------|---------|
| Verbliebene `INSTRUMENT_MAP`-Lookups durch `InstrumentRepository.find_best()` ersetzen | suchen mit `grep -r INSTRUMENT_MAP src/` | M |
| `_infer_role()`-Heuristik überprüfen — ggf. KB-Query statt String-Matching | `scripts/scan_bitwig_devices.py` | S |

### B.4 — F2 Tool-Registry-Refactor 🟡

**Status:** Zentrale `registry.py` ✅ eingeführt — die manuell gepflegte `ALL_TOOLS`-Liste
wird jetzt über `registry.register(tool, domain=...)` mit Domänen-Tags
(`bitwig`/`music`/`knowledge`/`meta`) gespeist. Der **Verzeichnis-Split**
(`tools/bitwig/`, `tools/music/`) ist bewusst aufgeschoben (hoher Import-Churn, niedriger Nutzen).

| Aufgabe | Datei | Aufwand | Status |
|---------|-------|---------|--------|
| Zentrale `ToolRegistry` mit `register()`/`by_domain()`/`domain_of()` | `src/agent/tools/registry.py` (neu) | M | ✅ |
| `ALL_TOOLS` über Registry mit Domänen-Tags speisen | `src/agent/tools/__init__.py` | S | ✅ |
| Unit-Tests für Registry + Domänen-Integrität | `tests/test_tool_registry.py` (neu) | S | ✅ |
| **Entscheidung Verzeichnis-Split:** `bitwig/`+`music/`-Umzug oder flache Struktur akzeptieren? | — | XS | ⏳ Diskussion |
| Falls Split: Tools nach `bitwig/`, `music/`, `knowledge/` umziehen (~30 Import-Pfade) | mehrere | L | ⏳ |

---

## C · Roadmap-Items aus `project_overview.md`

(Höchste Priorität laut [`project_overview.md`](docs/diagrams/project_overview.md#nächste-roadmap-schritte))

| # | Aufgabe | Datei | Aufwand |
|---|---------|-------|---------|
| 1 | Return-Track-Unterstützung in Java (`/track/add/return`, `/track/{n}/send_to`) | `bitwig-extension/.../BitwigStepPluginExtension.java` | M |
| 2 | Track-Gruppen-Endpoint (`/track/add/group`) | dito | S |
| 3 | Drum-Machine Multi-Pad-Setup | dito | M |
| 4 | `call_llm()` (214 Zeilen) in `_invoke_with_retry()` + `_apply_nudge()` aufteilen | `src/agent/core.py` | M |
| 5 | Jazz-Trainingsdaten erweitern (Ride statt HiHat, Offbeat-Snare, Walking Bass) | `~/mlx-training/train.jsonl` | L |
| 6 | `_query_neo4j()` (300 Zeilen) in 6 separate Query-Funktionen splitten | `src/agent/tools/knowledge_tool.py` | M |
| 7 | ✅ **MidiClip → Scene** als echte Neo4j-Relation (statt String-Feld) — Fix in `scripts/ingest_midi_clips.py` (persistiert `track_index`/`scene_idx`), Backfill-Migration `src/knowledge/migrations/link_midiclips_to_scenes.cypher` (37/37 MidiClips verknüpft) | KB-Migration + Ingest | M |
| 8 | **AudioSample → SoundRecipe** verknüpfen | KB-Migration + `repositories.py` | M |
| 9 | **Artist-Node** + `get_artist_context()` Tool | `tools/knowledge/`, KB-Migration | M |
| 10 | ✅ SIMILAR_TO-Kanten zwischen Song-Embeddings (Vektor-Ähnlichkeit) — Migration `src/knowledge/migrations/link_similar_songs.cypher` (top-3 NN je Song über `song_embedding`-Index, 21 Kanten), Runner `scripts/link_similar_songs.py` | KB-Migration | L |

---

## D · Empfohlene Reihenfolge

| Phase | Aufgaben | Begründung |
|-------|----------|------------|
| **1. Sofort (Test-Hygiene)** | A.1, A.2, A.3 | CI muss grün laufen, bevor Features gebaut werden |
| **2. Quick Wins** | B.1 (Prompt-Beispiele), C.2 (Track-Gruppen) | Kleiner Aufwand, hoher Nutzen |
| **3. Architektur-Komplettierung** | B.2, B.3 | Letzte 🟡 Findings auf ✅ |
| **4. Java-Erweiterungen** | C.1, C.3 | Java-Arbeit blockt Python-seitige Features |
| **5. Code-Größe reduzieren** | C.4, C.6 | 214/300-Zeilen-Funktionen sind Wartungsschulden |
| **6. KB-Erweiterung** | C.7, C.8, C.9, C.10 | Tieferes Reasoning für Lern-Features |
| **7. Optional** | B.4 | Bewusste Entscheidung, keine technische Notwendigkeit |

---

## E · Status-Legende

- ✅ **Erledigt** — kein Handlungsbedarf
- 🟡 **Teilweise** — Kern steht, Detail fehlt
- ⏳ **Offen** — noch nicht begonnen
- 💬 **Diskussion** — Architektur-Entscheidung steht aus

---

## F · Pflege

Diese Datei wird **manuell** aktualisiert:
- Nach jedem Test-Run mit Failures
- Nach jeder Architektur-Entscheidung
- Bei Sprint-Übergängen

Quelle für Architektur-Findings: [`docs/diagrams/architecture_improvements.md`](docs/diagrams/architecture_improvements.md)
Quelle für Roadmap: [`docs/diagrams/project_overview.md`](docs/diagrams/project_overview.md#nächste-roadmap-schritte)

---

## G · Live-Findings (Woche 2 ff.)

> Anhang für reproduzierbare Bugs/UX-Probleme aus echten Sessions.
> Roh-Notizen gehören in [`LIVE_LOG.md`](./LIVE_LOG.md); hier landen nur **konsolidierte, actionable Tasks**.

| # | Datum | Symptom | Hypothese | Komponente | Severity | Status |
|---|-------|---------|-----------|------------|----------|--------|
| — | —     | _noch keine_ | — | — | — | — |


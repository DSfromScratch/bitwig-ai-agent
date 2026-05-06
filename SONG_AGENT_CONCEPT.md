# Bitwig Song Agent — Roadmap

> **Zuletzt aktualisiert:** 05. Mai 2026  
> **Version:** 0.5  
> **Fokus:** Von Konzept zu robustem, testbarem Song- und Track-Agent

---

## 1. Zielbild

Der Agent soll aus einer knappen musikalischen Beschreibung zuverlässig einen Bitwig-Track oder einen einfachen Song erzeugen, ohne dass der User Instrument, FX, MIDI-Bereich und Tool-Reihenfolge vollständig ausschreiben muss.

**Kurzfristiges Produktziel:**
- offene Prompts robust in einen funktionierenden `build_song`-Aufruf übersetzen
- den erzeugten Track vollständig ausführen statt vorzeitig zu enden
- musikalische Defaults für Rock/Pop/Jazz stabil aus vorhandenem Wissen ableiten

**Nicht das unmittelbare Ziel:**
- ein vollautonomer Multi-Section-Arrangement-Agent mit ausgefeiltem Quality-Gate-System
- datensatzgetriebene Musiktheorie-Optimierung vor Stabilisierung des aktuellen Agentenlaufs

---

## 2. Aktueller Stand

### Was bereits belastbar funktioniert

- `build_song` existiert als Single-Call-Pfad für Track + Instrument + FX + Clip + Noten
- Kontext-Overflow wurde durch `MAX_MESSAGES=10`, `max_tokens=1500` und Tool-Message-Kürzung entschärft
- `build_song` ist mit Unit- und Integration-Tests abgedeckt
- die Bitwig-Bridge kann Tracks anlegen, Devices laden, Clips schreiben und den letzten Test-Track wieder löschen

### Was in realen Agent-Runs noch instabil ist

- der Agent wählt für spezifische Aufgaben oft nicht `build_song`, sondern mehrere Einzel-Tool-Calls
- `generation_phase` kippt teils zu früh auf `done`, bevor der letzte Tool-Call ausgeführt wurde
- bei offeneren Prompts werden Range, Struktur und FX-Treue noch nicht konsistent abgeleitet
- der Agent ergänzt teils unnötige Extra-FX wie `Compressor` oder `EQ-5`

---

## 3. Roadmap-Phasen

### Phase 1 — Agent-Lauf stabilisieren

**Ziel:** Der aktuelle Agent soll eine konkrete Musikaufgabe zuverlässig bis zum Ende ausführen.

**Lieferobjekte:**
- deterministische Wahl von `build_song` bei spezifischen Prompts
- sauberes Routing in `src/agent/core.py` ohne vorzeitiges `done`
- reproduzierbare Agent-Runs für einen einzelnen Rock-Riff-Track

**Arbeitspakete:**
- Prompt schärfen: `build_song` nicht nur bevorzugen, sondern für konkrete Track-Aufgaben erzwingen
- `route_by_phase()` und Phase-Signale so nachziehen, dass Tool-Calls immer Vorrang behalten
- Logging um klaren Nachweis ergänzen: geplant, aufgerufen, ausgeführt, verifiziert
- offene Prompt-Sets testen: konservativ, ausgewogen, maximal offen

**Definition of Done:**
- derselbe Rock-Riff-Prompt erzeugt in mindestens 3 Läufen denselben Tool-Pfad
- `build_song` wird für die spezifische Track-Aufgabe tatsächlich aufgerufen
- der finale Note-Write wird ausgeführt, nicht nur im LLM-Text erzeugt
- `verify_song` oder ein gleichwertiger Abschluss-Check läuft danach erfolgreich

### Phase 2 — Musikalische Defaults ausbauen

**Ziel:** Der User muss weniger musikalische Details vorgeben, ohne dass der Agent unplausibel wird.

**Lieferobjekte:**
- stabile Genre-Defaults für Instrument, FX-Kette, BPM und Register
- kleine Heuristiken für Dauer → Beats und Phrase-Struktur
- weniger Bedarf an expliziten MIDI-Zahlen im Prompt

**Arbeitspakete:**
- Genre- und Register-Heuristiken aus vorhandenem Repo-Wissen und Neo4j vereinheitlichen
- `get_pattern_context` gezielter vor Note-Generierung nutzen
- Standard-Strukturen hinterlegen, z. B. 20 Sekunden bei 120 BPM → 40 Beats
- unerwünschte Zusatz-FX unterbinden, wenn der Prompt eine enge Kette vorgibt

**Definition of Done:**
- ein kurzer Prompt wie „rockiger Gitarrenriff-Sound in E-Moll für 20 Sekunden" liefert konsistent einen tiefen, plausiblen Riff-Track
- der Agent bleibt bei der geforderten FX-Kette oder begründet Abweichungen explizit
- Range-Fehler wie Sprünge in hohe MIDI-Lagen treten in den Standardfällen nicht mehr auf

### Phase 3 — Verifikation und gezielte Reparatur

**Ziel:** Fehler sollen nicht nur erkannt, sondern deterministisch nachgebessert werden.

**Lieferobjekte:**
- `verify_song` als stabiler, maschinenlesbarer Prüfpunkt
- Projekt-Snapshots für Tracks, Clips und Noten
- Retry-Mechanik für nur die defekten Teile

**Arbeitspakete:**
- Snapshot-Sammlung aus Bitwig ausbauen
- Quality-Gates als reine Python-Validatoren kapseln
- Retry-Controller für `failed_tracks` und `failed_sections`
- Telemetrie unter `logs/quality_gates/` ergänzen

**Definition of Done:**
- Verifikation liefert strukturierte Fehler statt nur Freitext
- bei Fail wird nur der defekte Teil neu erzeugt
- maximal 3 Versuche, danach sauberer Diagnoseabbruch

### Phase 4 — Vom Track-Agent zum einfachen Song-Agent

**Ziel:** Auf Basis eines stabilen Single-Track-Agenten wieder kontrolliert in Richtung Arrangement gehen.

**Lieferobjekte:**
- klarer Wechsel zwischen `build_song` für spezifische Tracks und `create_song_from_genre` für einfache Mehrspur-Songs
- einfache Formlogik für Verse/Chorus/Outro
- gezielter Einsatz der KB für Harmonik und Struktur statt harter Defaults

**Arbeitspakete:**
- Prompt- und Tool-Grenzen zwischen Track-Agent und Song-Agent explizit trennen
- Section-Proposals und Genre-Workflow vereinfachen
- Knowledge-Graph gezielt nur dort anbinden, wo er die Entscheidung wirklich verbessert

**Definition of Done:**
- der Agent wählt je nach Anfrage robust den richtigen Pfad: Track oder Song
- einfache Mehrspur-Songs laufen ohne redundante Tool-Schleifen durch

---

## 4. Priorisierte Tickets

| Ticket | Priorität | Aufgabe | Abhängigkeit |
|--------|-----------|---------|--------------|
| R1 | hoch | `build_song`-Pfad für spezifische Prompts im System-Prompt und Routing absichern | — |
| R2 | hoch | Phase-Routing gegen vorzeitiges `done` härten | R1 parallel möglich |
| R3 | hoch | reproduzierbare Agent-Run-Tests mit 3 Prompt-Stufen dokumentieren | R1, R2 |
| R4 | mittel | Genre-/Register-Heuristiken zentralisieren | R1 |
| R5 | mittel | `verify_song`-Snapshot und Gate-Basis erweitern | R2 |
| R6 | mittel | Retry-Controller für fehlerhafte Tracks/Sections | R5 |
| R7 | niedrig | Song-Agent mit vereinfachter Section-Logik wieder ausbauen | R4, R5 |

---

## 5. Mapping auf bestehende Dateien

| Bereich | Hauptdatei | Rolle in der Roadmap |
|--------|------------|----------------------|
| Routing | `src/agent/core.py` | `generation_phase`, Tool-Recovery, Priorität von Tool-Calls, Retry-Loop |
| Prompting | `src/agent/prompts.py` | Pfadwahl zwischen `build_song`, `write_notes_to_clip` und `create_song_from_genre` |
| Track-/Song-Erzeugung | `src/agent/tools/song_tools.py` | `build_song`, `verify_song`, Genre-Logik, Note-Generierung |
| Musik-Wissen | `src/audio/chord_to_bitwig.py` | Skalen, Progressionen, Pattern- und Melodie-Logik |
| Wissensgraph | `src/knowledge/neo4j_graph.py` | optionale Genre- und Kontextanreicherung |
| Bitwig-Bridge | `bitwig-extension/src/main/java/com/bitwigagent/BitwigAgentBridgeExtension.java` | OSC-Kommandos, Device-Loading, Teardown-Operationen |

---

## 6. Erfolgsmetriken

### Für Phase 1

- `build_song`-Nutzung bei spezifischen Track-Prompts: Ziel ≥ 90 %
- vollständige Ausführung ohne vorzeitiges `END`: Ziel ≥ 95 % in Testläufen
- keine Kontext-Overflow-Fehler im Standard-Workflow

### Für Phase 2

- verkürzter Prompt ohne MIDI-Zahlen führt in Standardfällen zu plausiblen Registern
- keine unnötigen Zusatz-FX in engen Prompt-Vorgaben

### Für Phase 3

- jeder Verifikations-Fail liefert maschinenlesbare Diagnose
- Retry verbessert nur die fehlerhaften Artefakte statt den ganzen Song neu zu bauen

---

## 7. Außerhalb des aktuellen Scopes

- großer MIDI-Datensatz-Ingest als kurzfristiger Schwerpunkt
- vollautomatische Arrangement-AI mit frei generierter Section-Reihenfolge
- komplexe ästhetische Bewertung jenseits von Struktur, Range, Rhythmik und offensichtlichen Harmoniefehlern
- Vision-Modell-basierte UI-Prüfung vor Stabilisierung des Kernpfads

---

## 8. Entscheidungslog

| Entscheidung | Begründung | Datum |
|-------------|-----------|-------|
| `build_song` ist der bevorzugte Pfad für spezifische Track-Aufgaben | spart Tokens und reduziert Tool-Ketten | Mai 2026 |
| Agent-Stabilität vor Ausbau des Song-Agenten | aktueller Engpass ist Control-Flow, nicht Feature-Fläche | Mai 2026 |
| kurze offene Prompts sind das Ziel, aber erst nach Stabilisierung der musikalischen Defaults | sonst bleiben Range- und FX-Fehler zu hoch | Mai 2026 |
| Quality Gates bleiben wichtig, aber nach Routing- und Tool-Wahl-Stabilisierung | Diagnose bringt wenig, wenn der Hauptpfad noch nicht sauber durchläuft | Mai 2026 |

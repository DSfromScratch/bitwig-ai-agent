"""
Smoke Tests: Workflow → Template → WorkflowPlan

Testet die vollständige Pipeline ohne Bitwig:
  1. BitwigProjectSnapshot aus Neo4j aufbauen
  2. ProjectTemplate via from_snapshot() erzeugen
  3. WorkflowPlan (Steps) ableiten
  4. Template in Neo4j speichern + zurückladen
  5. ProjectTemplateRepository.find_best_match() via HNSW

Marker:
  @pytest.mark.unit   — kein Neo4j, kein Bitwig (reines Objekt-Modell)
  @pytest.mark.neo4j  — benötigt laufende Neo4j-Instanz
"""
from __future__ import annotations

import json
import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

CHEE_RAW_JSON = json.dumps({
    "tracks": [
        {"idx": 1,  "name": "Drums",           "is_group": True,  "devices": [],                    "slots": [False]*8},
        {"idx": 2,  "name": "Kicks",            "is_group": False, "devices": ["Poly Grid"],         "slots": [True, False, True, True, True, False, False, False]},
        {"idx": 3,  "name": "Clap/Snare",       "is_group": False, "devices": ["Poly Grid"],         "slots": [False, False, False, True, True, False, False, False]},
        {"idx": 4,  "name": "Hats & Percs",     "is_group": False, "devices": ["E-Hat", "Reverb"],   "slots": [True]*8},
        {"idx": 5,  "name": "Body",             "is_group": True,  "devices": [],                    "slots": [False]*8},
        {"idx": 6,  "name": "Bass",             "is_group": False, "devices": ["FM-4", "EQ-5"],      "slots": [False, False, True, True, True, False, False, False]},
        {"idx": 9,  "name": "Stringer",         "is_group": False, "devices": ["Phase-4", "Reverb"], "slots": [False, False, True, True, True, True, False, False]},
        {"idx": 14, "name": "Dissonant Pad",    "is_group": False, "devices": ["Phase-4"],           "slots": [False, False, False, False, True, False, False, True]},
        {"idx": 16, "name": "Sharp Arp",        "is_group": False, "devices": ["Polysynth"],         "slots": [False, False, False, False, True, False, True, False]},
    ],
    "scenes": [
        {"idx": 1, "name": "Intro",  "clip_count": 3},
        {"idx": 2, "name": "Raise",  "clip_count": 2},
        {"idx": 3, "name": "Garage", "clip_count": 4},
        {"idx": 4, "name": "Peak",   "clip_count": 5},
        {"idx": 5, "name": "Break",  "clip_count": 6},
        {"idx": 6, "name": "Trap",   "clip_count": 3},
        {"idx": 7, "name": "Impro",  "clip_count": 2},
        {"idx": 8, "name": "Outro",  "clip_count": 2},
    ],
    "groups": [
        {"idx": 1, "name": "Drums"},
        {"idx": 5, "name": "Body"},
    ],
    "tempo": 140.0,
    "total_tracks": 9,
})


@pytest.fixture
def chee_snapshot():
    from src.agent.models.project_snapshot import BitwigProjectSnapshot
    return BitwigProjectSnapshot.from_raw("Chee - Hey Now", CHEE_RAW_JSON)


# ── Unit Tests: Snapshot ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_snapshot_parst_szenen(chee_snapshot):
    snap = chee_snapshot
    assert len(snap.scenes) == 8
    assert snap.scenes[0].name == "Intro"
    assert snap.scenes[4].name == "Break"


@pytest.mark.unit
def test_snapshot_szene_by_name(chee_snapshot):
    sc = chee_snapshot.scene_by_name("Garage")
    assert sc is not None
    assert sc.idx == 3


@pytest.mark.unit
def test_snapshot_clip_content_matrix(chee_snapshot):
    snap = chee_snapshot
    kicks = snap.get_track(2)
    assert kicks is not None
    # Kicks hat Content in Intro (1), Garage (3), Peak (4), Break (5)
    clips_with_notes = kicks.clips_with_notes()
    assert 1 in clips_with_notes  # Intro
    assert 3 in clips_with_notes  # Garage
    assert 2 not in clips_with_notes  # Raise leer


@pytest.mark.unit
def test_snapshot_first_clip_o1(chee_snapshot):
    dissonant = chee_snapshot.get_track(14)
    assert dissonant is not None
    first = dissonant.first_clip_with_notes()
    assert first == 5  # Break (scene_idx=5)


@pytest.mark.unit
def test_snapshot_group_tracks(chee_snapshot):
    groups = chee_snapshot.group_tracks()
    names = [g.name for g in groups]
    assert "Drums" in names
    assert "Body" in names


@pytest.mark.unit
def test_snapshot_tracks_in_group(chee_snapshot):
    drums = chee_snapshot.tracks_in_group("Drums")
    names = [t.name for t in drums]
    assert "Kicks" in names
    assert "Clap/Snare" in names
    assert "Hats & Percs" in names


@pytest.mark.unit
def test_snapshot_instrument_property(chee_snapshot):
    bass = chee_snapshot.get_track(6)
    assert bass.instrument == "FM-4"
    assert bass.fx == ["EQ-5"]


# ── Unit Tests: Template ──────────────────────────────────────────────────────

@pytest.mark.unit
def test_template_from_snapshot(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    tmpl = ProjectTemplate.from_snapshot(chee_snapshot, genre="deep house")

    assert tmpl.name == "Chee - Hey Now"
    assert tmpl.tempo == 140.0
    assert tmpl.genre == "deep house"
    assert len(tmpl.scenes) == 8


@pytest.mark.unit
def test_template_szenen_namen(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    names = tmpl.scene_names()
    assert "Intro" in names
    assert "Break" in names
    assert "Outro" in names


@pytest.mark.unit
def test_template_gruppen_struktur(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    assert "Drums" in tmpl.groups
    drums_tracks = [t.name for t in tmpl.groups["Drums"]]
    assert "Kicks" in drums_tracks


@pytest.mark.unit
def test_template_alle_tracks(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    all_tracks = tmpl.all_tracks()
    names = [t.name for t in all_tracks]
    assert "Bass" in names
    assert "Dissonant Pad" in names
    assert "Sharp Arp" in names


@pytest.mark.unit
def test_template_serialisierung(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    d = tmpl.to_dict()
    assert d["tempo"] == 140.0
    assert len(d["scenes"]) == 8

    # Roundtrip: dict → Template → dict
    tmpl2 = ProjectTemplate.from_dict(d)
    assert tmpl2.name == tmpl.name
    assert tmpl2.tempo == tmpl.tempo
    assert tmpl2.scene_names() == tmpl.scene_names()


# ── Unit Tests: Plugin System + WorkflowPlan ─────────────────────────────────

@pytest.mark.unit
def test_plugin_instrument_steps():
    from src.agent.models.track_plugins import InstrumentTrackPlugin
    from src.agent.models.project_template import TemplateTrack

    plugin = InstrumentTrackPlugin()
    track = TemplateTrack(
        name="Bass", track_type="instrument", role="Bass",
        instrument="FM-4", fx=["EQ-5", "Compressor"]
    )
    steps = plugin.build_steps(track, track_idx=3)
    types = [s.type for s in steps]

    assert "add_track" in types
    assert "load_instrument" in types
    assert types.count("append_effect") == 2


@pytest.mark.unit
def test_plugin_audio_steps():
    from src.agent.models.track_plugins import AudioTrackPlugin
    from src.agent.models.project_template import TemplateTrack

    plugin = AudioTrackPlugin()
    track = TemplateTrack(
        name="VOX", track_type="audio", role="Vocals",
        instrument=None, fx=["Reverb"]
    )
    steps = plugin.build_steps(track, track_idx=5)
    types = [s.type for s in steps]

    assert steps[0].type == "add_track"
    assert steps[0].track_type == "audio"  # type: ignore
    assert "append_effect" in types
    assert "load_instrument" not in types


@pytest.mark.unit
def test_workflow_plan_from_template(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.workflow_plan import WorkflowPlan

    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    plan = WorkflowPlan.from_template(tmpl, context="Smoke Test")

    assert len(plan.steps) > 0
    assert plan.steps[0].type == "set_tempo"
    assert plan.steps[0].bpm == 140  # type: ignore


@pytest.mark.unit
def test_workflow_plan_diff_nur_fehlende_tracks(chee_snapshot):
    """Wenn Tracks bereits existieren → nur Delta-Steps."""
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.workflow_plan import WorkflowPlan
    from src.agent.models.project_snapshot import BitwigProjectSnapshot

    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    total_steps_ohne_diff = len(WorkflowPlan.from_template(tmpl).steps)

    # Simuliere: Kicks (Poly Grid) und Bass (FM-4) existieren bereits
    existing_raw = json.dumps({
        "tracks": [
            {"idx": 2, "name": "Kicks",  "is_group": False, "devices": ["Poly Grid"], "slots": [False]*8},
            {"idx": 6, "name": "Bass",   "is_group": False, "devices": ["FM-4"],      "slots": [False]*8},
        ],
        "scenes": [], "groups": [], "tempo": 140.0, "total_tracks": 2,
    })
    current = BitwigProjectSnapshot.from_raw("Chee - Hey Now", existing_raw)
    plan = WorkflowPlan.from_template(tmpl, current=current)

    load_steps = [s for s in plan.steps if s.type == "load_instrument"]
    load_names = [s.name for s in load_steps]  # type: ignore

    # FM-4 (Bass-Instrument) darf NICHT mehr geladen werden — Bass existiert bereits
    assert "FM-4" not in load_names, f"FM-4 sollte nicht in Steps sein, da Bass existiert. Steps: {load_names}"

    # Weniger Steps als ohne Diff (2 Tracks weniger → mind. 2 weniger add_track)
    assert len(plan.steps) < total_steps_ohne_diff, "Diff-Plan sollte kürzer sein als vollständiger Plan"

    # Andere Tracks müssen noch hinzugefügt werden
    add_track_steps = [s for s in plan.steps if s.type == "add_track"]
    assert len(add_track_steps) > 0, "Restliche Tracks müssen noch angelegt werden"


@pytest.mark.unit
def test_workflow_plan_to_result(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.workflow_plan import WorkflowPlan

    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    plan = WorkflowPlan.from_template(tmpl)
    result = plan.to_result()

    assert result["context_type"] == "song"
    assert isinstance(result["steps"], list)
    assert result["steps"][0]["type"] == "set_tempo"


@pytest.mark.unit
def test_workflow_validation_context(chee_snapshot):
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.workflow_plan import WorkflowPlan

    tmpl = ProjectTemplate.from_snapshot(chee_snapshot)
    plan = WorkflowPlan.from_template(tmpl)
    ctx = plan.validation_context(snapshot=chee_snapshot)

    assert ctx["tempo"] == 140.0
    assert "Break" in ctx["scenes"]
    assert isinstance(ctx["tracks"], list)


# ── Neo4j Integration Tests ───────────────────────────────────────────────────

@pytest.mark.neo4j
def test_template_neo4j_save_und_laden(chee_snapshot, neo4j_available):
    if not neo4j_available:
        pytest.skip("Neo4j nicht verfügbar")

    from src.agent.models.project_template import ProjectTemplate
    from src.knowledge.repositories import ProjectTemplateRepository

    tmpl = ProjectTemplate.from_snapshot(chee_snapshot, genre="deep house")
    tmpl.name = "Chee - Hey Now [Test]"  # eigener Name damit echte Daten safe sind

    repo = ProjectTemplateRepository()
    repo.save(tmpl)

    # Zurückladen
    loaded = repo.load("Chee - Hey Now [Test]")
    assert loaded is not None
    assert loaded.tempo == 140.0
    assert "Break" in loaded.scene_names()

    # Aufräumen
    from src.knowledge.neo4j_graph import session
    with session() as s:
        s.run("MATCH (pt:ProjectTemplate {name: 'Chee - Hey Now [Test]'}) DETACH DELETE pt")


@pytest.mark.neo4j
def test_template_hnsw_find_best_match(neo4j_available):
    """Findet bestehendes Chee-Hey-Now Template per Vektorsuche."""
    if not neo4j_available:
        pytest.skip("Neo4j nicht verfügbar")

    from src.knowledge.repositories import ProjectTemplateRepository

    repo = ProjectTemplateRepository()
    result = repo.find_best_match(
        context_text="techno project 140 bpm with drums bass synth layers",
        genre="deep house",
    )
    # Kann None sein wenn kein Template gespeichert — kein Fehler
    if result is not None:
        assert result.tempo > 0
        assert len(result.scenes) > 0


@pytest.mark.neo4j
def test_neo4j_graph_vollständig(neo4j_available):
    """Prüft ob der Chee-Hey-Now Graph in Neo4j vollständig verbunden ist."""
    if not neo4j_available:
        pytest.skip("Neo4j nicht verfügbar")

    from src.knowledge.neo4j_graph import session

    with session() as s:
        # Szenen vorhanden
        sc = s.run(
            "MATCH (sc:Scene {project: 'Chee - Hey Now'}) RETURN count(sc) AS n"
        ).single()["n"]
        assert sc == 8, f"Erwartet 8 Szenen, gefunden: {sc}"

        # MidiClips mit Szenen verknüpft
        mc = s.run(
            "MATCH (mc:MidiClip {project: 'Chee - Hey Now'})-[:IN_SCENE]->() RETURN count(mc) AS n"
        ).single()["n"]
        assert mc >= 6, f"Erwartet ≥6 MidiClip→Scene, gefunden: {mc}"

        # AudioSamples mit SoundRecipes verknüpft
        audio = s.run(
            "MATCH (a:AudioSample {project: 'Chee - Hey Now'})-[:SAMPLED_IN]->() RETURN count(a) AS n"
        ).single()["n"]
        assert audio >= 10, f"Erwartet ≥10 AudioSample→SoundRecipe, gefunden: {audio}"

        # BitwigProject Kern-Verknüpfungen
        bp = s.run("""
            MATCH (p:BitwigProject {name: 'Chee - Hey Now'})
            RETURN
              size([(p)-[:HAS_SCENE]->() | 1]) AS scenes,
              size([(p)-[:HAS_GROUP]->() | 1]) AS groups
        """).single()
        assert bp["scenes"] == 8
        assert bp["groups"] == 2  # Drums + Body

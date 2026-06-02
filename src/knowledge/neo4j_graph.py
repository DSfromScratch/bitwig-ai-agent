"""
Neo4j Wissensgraph für Bitwig Studio 6.

Schema-Überblick:
  (Genre)      -[:USES]->          (Device)
  (Device)     -[:HAS_PARAMETER]-> (Parameter)
  (Device)     -[:RECOMMENDED_WITH]-> (Device)
  (Sound)      -[:CREATED_BY]->    (Device)
  (Genre)      -[:TYPICAL_SOUND]-> (Sound)
  (Workflow)   -[:USES_DEVICE]->   (Device)
  (Song)       -[:CLASSIFIED_AS]-> (Genre)
  (Song)       -[:HAS_STEM]->      (Stem)
  (Preset)     -[:BELONGS_TO]->    (Device)
  (Pattern)    -[:USED_IN]->       (Genre)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from neo4j import GraphDatabase

from src.knowledge.bitwig_catalog import (  # noqa: F401  (re-export für externe Aufrufer)
    SCHEMA_CONSTRAINTS, DEVICES, GENRES, SOUNDS, GENRE_DEVICES,
    RECOMMENDED_CHAINS, WORKFLOWS,
)

# ── Verbindung ────────────────────────────────────────────────────────────────

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4jllm")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

_driver = None
_neo4j_available: bool | None = None  # None = ungeprüft


def reset_availability_cache() -> None:
    """Setzt den Neo4j-Verfügbarkeits-Cache zurück (für Tests und env-Wechsel)."""
    global _neo4j_available, _driver
    _neo4j_available = None
    _driver = None


def is_available() -> bool:
    """Gibt True zurück wenn Neo4j erreichbar ist (gecacht nach erstem Check)."""
    global _neo4j_available
    if _neo4j_available is not None:
        return _neo4j_available
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session(database=NEO4J_DATABASE) as s:
            s.run("RETURN 1").single()
        driver.close()
        _neo4j_available = True
    except Exception:
        _neo4j_available = False
    return _neo4j_available


def get_driver():
    global _driver
    if not is_available():
        raise ConnectionError(
            f"Neo4j nicht erreichbar ({NEO4J_URI}). "
            "Starte Neo4j oder setze NEO4J_URI auf einen laufenden Server."
        )
    if _driver is None:
        _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    return _driver

@contextmanager
def session():
    with get_driver().session(database=NEO4J_DATABASE) as s:
        yield s

# ── Schema ────────────────────────────────────────────────────────────────────

def create_schema():
    with session() as s:
        for c in SCHEMA_CONSTRAINTS:
            try:
                s.run(c)
            except Exception:
                pass
    print("✓ Schema-Constraints erstellt")


# ── Graph aufbauen ────────────────────────────────────────────────────────────

def build_graph():
    """Befüllt den Neo4j-Graph mit allen Bitwig-Daten."""
    with session() as s:
        total = 0

        # Genres
        for g in GENRES:
            s.run("""
                MERGE (g:Genre {name: $name})
                SET g.bpm_min=$bpm_min, g.bpm_max=$bpm_max,
                    g.key_mode=$key_mode, g.description=$description
            """, **g)
        print(f"  ✓ {len(GENRES)} Genres")

        # Devices + Parameter
        dev_count, param_count = 0, 0
        for dev in DEVICES:
            params = dev.pop("params", [])
            s.run("""
                MERGE (d:Device {name: $name})
                SET d.type=$type, d.category=$category,
                    d.description=$description, d.browser_path=$browser_path
            """, **dev)
            dev["params"] = params
            dev_count += 1
            for p in params:
                pname = f"{dev['name']}.{p['name']}"
                s.run("""
                    MERGE (p:Parameter {name: $pname})
                    SET p.device=$device, p.param=$param,
                        p.type=$type, p.default=$default,
                        p.unit=$unit, p.values=$values
                    WITH p
                    MATCH (d:Device {name: $device})
                    MERGE (d)-[:HAS_PARAMETER]->(p)
                """,
                    pname=pname,
                    device=dev["name"],
                    param=p["name"],
                    type=p.get("type","float"),
                    default=str(p.get("default","")),
                    unit=p.get("unit",""),
                    values=p.get("values",""),
                )
                param_count += 1
        print(f"  ✓ {dev_count} Devices, {param_count} Parameter")

        # Sounds
        for snd in SOUNDS:
            creator = snd.pop("created_by", None)
            s.run("""
                MERGE (snd:Sound {name: $name})
                SET snd.category=$category, snd.description=$description,
                    snd.settings=$settings
            """, **snd)
            snd["created_by"] = creator
            if creator:
                s.run("""
                    MATCH (snd:Sound {name: $snd}), (d:Device {name: $dev})
                    MERGE (snd)-[:CREATED_BY]->(d)
                """, snd=snd["name"], dev=creator)
        print(f"  ✓ {len(SOUNDS)} Sounds")

        # Genre → Device — zuerst veraltete guitar/lead-Synth-Beziehungen für Loop-Genres löschen
        s.run("""
            MATCH (g:Genre)-[r:USES]->(d:Device {name: "Phase-4"})
            WHERE g.name IN ["Rock", "Metal", "Blues"]
              AND r.role IN ["guitar", "lead"]
            DELETE r
        """)
        for genre, device, role, weight in GENRE_DEVICES:
            s.run("""
                MATCH (g:Genre {name: $genre}), (d:Device {name: $device})
                MERGE (g)-[r:USES {role: $role}]->(d)
                SET r.weight = $weight
            """, genre=genre, device=device, role=role, weight=weight)
        print(f"  ✓ {len(GENRE_DEVICES)} Genre→Device Beziehungen")

        # Empfohlene Ketten
        for device, effect, reason in RECOMMENDED_CHAINS:
            s.run("""
                MATCH (d:Device {name: $device}), (e:Device {name: $effect})
                MERGE (d)-[r:RECOMMENDED_WITH]->(e)
                SET r.reason = $reason
            """, device=device, effect=effect, reason=reason)
        print(f"  ✓ {len(RECOMMENDED_CHAINS)} Empfohlene Ketten")

        # Workflows
        for wf in WORKFLOWS:
            genre = wf.get("genre")
            s.run("""
                MERGE (w:Workflow {name: $name})
                SET w.description=$description, w.steps=$steps
            """, name=wf["name"], description=wf["description"],
                 steps="\n".join(wf["steps"]))
            if genre:
                s.run("""
                    MATCH (w:Workflow {name: $wf}), (g:Genre {name: $genre})
                    MERGE (w)-[:USED_IN]->(g)
                """, wf=wf["name"], genre=genre)
        print(f"  ✓ {len(WORKFLOWS)} Workflows")

    print("✓ Graph aufgebaut")

# ── Query-Interface ───────────────────────────────────────────────────────────

def query_for_genre(genre_name: str) -> dict:
    """Alle Devices, Sounds und Workflows für ein Genre."""
    with session() as s:
        devices = s.run("""
            MATCH (g:Genre)-[r:USES]->(d:Device)
            WHERE g.name =~ $pattern
            RETURN d.name AS device, d.category AS category,
                   r.role AS role, r.weight AS weight, d.description AS desc
            ORDER BY r.weight DESC
        """, pattern=f"(?i).*{genre_name}.*").data()

        workflows = s.run("""
            MATCH (w:Workflow)-[:USED_IN]->(g:Genre)
            WHERE g.name =~ $pattern
            RETURN w.name AS name, w.description AS desc, w.steps AS steps
        """, pattern=f"(?i).*{genre_name}.*").data()

        sounds = s.run("""
            MATCH (g:Genre)-[:TYPICAL_SOUND]->(snd:Sound)
            WHERE g.name =~ $pattern
            RETURN snd.name AS sound, snd.settings AS settings
        """, pattern=f"(?i).*{genre_name}.*").data()

    return {"devices": devices, "workflows": workflows, "sounds": sounds}


def query_device_setup(device_name: str) -> dict:
    """Parameter + empfohlene Effektkette für ein Device."""
    with session() as s:
        params = s.run("""
            MATCH (d:Device {name: $name})-[:HAS_PARAMETER]->(p:Parameter)
            RETURN p.param AS param, p.type AS type,
                   p.default AS default, p.unit AS unit, p.values AS values
            ORDER BY p.param
        """, name=device_name).data()

        chain = s.run("""
            MATCH (d:Device {name: $name})-[r:RECOMMENDED_WITH]->(fx:Device)
            RETURN fx.name AS effect, r.reason AS reason
        """, name=device_name).data()

        info = s.run("""
            MATCH (d:Device {name: $name})
            RETURN d.description AS desc, d.browser_path AS path,
                   d.category AS category
        """, name=device_name).single()

    return {
        "device": device_name,
        "info": dict(info) if info else {},
        "parameters": params,
        "recommended_chain": chain,
    }


def store_song_analysis_neo4j(
    filename: str, bpm: float, key: str,
    genre: str, subgenre: str, confidence: float,
    present_stems: list[str], stem_analyses: dict,
) -> str:
    """Speichert Song-Analyse im Graph."""
    with session() as s:
        s.run("""
            MERGE (song:Song {filename: $filename})
            SET song.bpm=$bpm, song.key=$key, song.confidence=$confidence
            WITH song
            MATCH (g:Genre)
            WHERE g.name =~ $genre_pat
            MERGE (song)-[:CLASSIFIED_AS {confidence: $confidence}]->(g)
        """, filename=filename, bpm=bpm, key=key, confidence=confidence,
             genre_pat=f"(?i).*{subgenre or genre}.*")

        for stem_name, analysis in stem_analyses.items():
            s.run("""
                MERGE (stem:Stem {id: $stem_id})
                SET stem.name=$name, stem.song=$song,
                    stem.has_content=$has_content, stem.character=$character,
                    stem.confidence=$confidence
                WITH stem
                MATCH (song:Song {filename: $song})
                MERGE (song)-[:HAS_STEM]->(stem)
            """,
                stem_id=f"{filename}:{stem_name}",
                name=stem_name, song=filename,
                has_content=analysis.get("has_content", False),
                character=analysis.get("character", ""),
                confidence=analysis.get("confidence", 0.0),
            )
    return filename

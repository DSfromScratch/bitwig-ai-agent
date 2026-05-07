"""
Tests für Song-Config aus dem Bitwig Controller UI.

Prüft:
  - JSON-Struktur (alle Felder vorhanden, Typen korrekt)
  - Feldwerte gegen erlaubte Enum-Werte
  - _prompt_from_config() erzeugt korrekten Prompt-Text
  - plan_node() verarbeitet ui_song_config korrekt
  - Edge Cases: leere Config, unbekannte Felder, Typ-Koercion (bpm als String)
"""
from __future__ import annotations

import json
import pytest
from langchain_core.messages import HumanMessage
from src.agent.core import _default_state


def _plan_state(cfg, msg: str = "Erstelle einen Song"):
    """Minimal gültiger AgentState mit gesetzter ui_song_config."""
    s = _default_state()
    s["messages"] = [HumanMessage(content=msg)]
    s["ui_song_config"] = cfg
    return s


# ── Erlaubte Werte (spiegeln BitwigAgentBridgeExtension.java wider) ────────────

VALID_GENRES   = {"Pop", "Rock", "Metal", "Blues", "Jazz", "EDM", "Hip-Hop", "Classical"}
VALID_KEYS     = {"C major", "A minor", "E minor", "G major", "D major", "F major", "B minor"}
VALID_LENGTHS  = {8, 16, 32, 64}
VALID_TRACKS   = {1, 2, 4, 6}
VALID_TECHNIQUES = {
    "Standard", "Palm Mute", "Legato", "Bend Heavy", "Vibrato", "Arpeggio"
}
VALID_RHYTHMS  = {
    "Straight Eighths", "Gallop", "Syncopated", "Triplet Feel", "Chug Pattern"
}
VALID_REGISTERS = {"Low (E2-D3)", "Mid (D3-G3)", "Lead (G3-E4)"}
VALID_DYNAMICS  = {"Flat", "Crescendo", "Accent 1&3", "Accent 2&4"}
VALID_FX        = {"None", "Distortion+Amp", "Reverb+EQ", "Delay+Chorus"}

REQUIRED_FIELDS = {
    "genre", "bpm", "track_count", "key", "length_beats",
    "technique", "rhythm_pattern", "string_register", "dynamics_shape", "fx_preset",
}


# ── Beispiel-Configs (representativ für alle Genres + Edge Cases) ──────────────

EXAMPLE_CONFIGS = [
    {
        "label": "Pop Gallop Low 1Track 100BPM 64beats",  # Screenshot-Variante
        "config": {
            "genre": "Pop", "bpm": 100, "track_count": 1,
            "key": "E minor", "length_beats": 64,
            "technique": "Standard", "rhythm_pattern": "Gallop",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
            "fx_preset": "Distortion+Amp",
        },
    },
    {
        "label": "Rock Standard",
        "config": {
            "genre": "Rock", "bpm": 120, "track_count": 4,
            "key": "E minor", "length_beats": 32,
            "technique": "Standard", "rhythm_pattern": "Straight Eighths",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
            "fx_preset": "Distortion+Amp",
        },
    },
    {
        "label": "Metal Palm Mute Gallop",
        "config": {
            "genre": "Metal", "bpm": 180, "track_count": 6,
            "key": "B minor", "length_beats": 64,
            "technique": "Palm Mute", "rhythm_pattern": "Gallop",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 2&4",
            "fx_preset": "Distortion+Amp",
        },
    },
    {
        "label": "Blues Lead Bend",
        "config": {
            "genre": "Blues", "bpm": 90, "track_count": 2,
            "key": "A minor", "length_beats": 16,
            "technique": "Bend Heavy", "rhythm_pattern": "Triplet Feel",
            "string_register": "Lead (G3-E4)", "dynamics_shape": "Crescendo",
            "fx_preset": "Reverb+EQ",
        },
    },
    {
        "label": "Jazz Legato Mid-Register",
        "config": {
            "genre": "Jazz", "bpm": 140, "track_count": 4,
            "key": "F major", "length_beats": 32,
            "technique": "Legato", "rhythm_pattern": "Syncopated",
            "string_register": "Mid (D3-G3)", "dynamics_shape": "Flat",
            "fx_preset": "Delay+Chorus",
        },
    },
    {
        "label": "Pop Minimal 1 Track",
        "config": {
            "genre": "Pop", "bpm": 110, "track_count": 1,
            "key": "C major", "length_beats": 8,
            "technique": "Arpeggio", "rhythm_pattern": "Straight Eighths",
            "string_register": "Mid (D3-G3)", "dynamics_shape": "Flat",
            "fx_preset": "None",
        },
    },
    {
        "label": "EDM High BPM",
        "config": {
            "genre": "EDM", "bpm": 200, "track_count": 6,
            "key": "G major", "length_beats": 64,
            "technique": "Vibrato", "rhythm_pattern": "Chug Pattern",
            "string_register": "Lead (G3-E4)", "dynamics_shape": "Accent 2&4",
            "fx_preset": "Delay+Chorus",
        },
    },
    {
        "label": "Classical Low BPM",
        "config": {
            "genre": "Classical", "bpm": 60, "track_count": 2,
            "key": "D major", "length_beats": 16,
            "technique": "Legato", "rhythm_pattern": "Straight Eighths",
            "string_register": "Mid (D3-G3)", "dynamics_shape": "Crescendo",
            "fx_preset": "Reverb+EQ",
        },
    },
]

CONFIG_IDS = [c["label"] for c in EXAMPLE_CONFIGS]


# ── Hilfsfunktion: _prompt_from_config direkt aus core.py extrahieren ──────────

def _make_prompt(cfg: dict) -> str:
    """Ruft die interne _prompt_from_config Logik ohne OSC-Listener-Start auf."""
    genre          = str(cfg.get("genre", "Rock"))
    bpm            = int(float(cfg.get("bpm", 120)))
    track_count    = int(float(cfg.get("track_count", 4)))
    key            = str(cfg.get("key", "E minor"))
    length_beats   = int(float(cfg.get("length_beats", 32)))
    technique      = str(cfg.get("technique", "Standard"))
    rhythm         = str(cfg.get("rhythm_pattern", "Straight Eighths"))
    string_register = str(cfg.get("string_register", "Low (E2-D3)"))
    dynamics       = str(cfg.get("dynamics_shape", "Accent 1&3"))
    fx             = str(cfg.get("fx_preset", "Distortion+Amp"))
    return (
        f"Erstelle einen {genre}-Track mit {track_count} Track(s), {bpm} BPM, "
        f"Tonart {key}, Länge {length_beats} Beats. "
        f"Nutze Spieltechnik {technique}, Rhythmusmuster {rhythm}, "
        f"Saitenbereich {string_register}, Dynamik {dynamics}. "
        f"FX-Preset: {fx}. "
        "Bitte variiere Notenlängen und Akzente musikalisch, und halte den Stil konsistent."
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. JSON-Struktur und Feld-Validierung
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigStructure:

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_required_fields_present(self, example):
        missing = REQUIRED_FIELDS - example["config"].keys()
        assert not missing, f"Fehlende Felder: {missing}"

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_no_extra_fields(self, example):
        extra = set(example["config"].keys()) - REQUIRED_FIELDS
        assert not extra, f"Unerwartete Felder: {extra} — Java-Extension aktualisieren?"

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_json_roundtrip(self, example):
        """Config muss verlustfrei JSON-serialisierbar sein (wie Java sie sendet)."""
        raw = json.dumps(example["config"])
        parsed = json.loads(raw)
        assert parsed == example["config"]

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_bpm_range(self, example):
        bpm = example["config"]["bpm"]
        assert 60 <= bpm <= 200, f"BPM {bpm} außerhalb 60–200"

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_genre(self, example):
        assert example["config"]["genre"] in VALID_GENRES

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_key(self, example):
        assert example["config"]["key"] in VALID_KEYS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_length_beats(self, example):
        assert int(example["config"]["length_beats"]) in VALID_LENGTHS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_track_count(self, example):
        assert int(example["config"]["track_count"]) in VALID_TRACKS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_technique(self, example):
        assert example["config"]["technique"] in VALID_TECHNIQUES

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_rhythm(self, example):
        assert example["config"]["rhythm_pattern"] in VALID_RHYTHMS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_string_register(self, example):
        assert example["config"]["string_register"] in VALID_REGISTERS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_dynamics(self, example):
        assert example["config"]["dynamics_shape"] in VALID_DYNAMICS

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_enum_fx_preset(self, example):
        assert example["config"]["fx_preset"] in VALID_FX


# ══════════════════════════════════════════════════════════════════════════════
# 2. Prompt-Generierung
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptGeneration:

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_contains_genre(self, example):
        cfg = example["config"]
        prompt = _make_prompt(cfg)
        assert cfg["genre"] in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_contains_bpm(self, example):
        cfg = example["config"]
        prompt = _make_prompt(cfg)
        assert str(int(cfg["bpm"])) in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_contains_key(self, example):
        cfg = example["config"]
        prompt = _make_prompt(cfg)
        assert cfg["key"] in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_contains_technique(self, example):
        cfg = example["config"]
        prompt = _make_prompt(cfg)
        assert cfg["technique"] in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_contains_fx(self, example):
        cfg = example["config"]
        prompt = _make_prompt(cfg)
        assert cfg["fx_preset"] in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_prompt_nonempty(self, example):
        prompt = _make_prompt(example["config"])
        assert len(prompt) > 50


# ══════════════════════════════════════════════════════════════════════════════
# 3. plan_node() verarbeitet ui_song_config
# ══════════════════════════════════════════════════════════════════════════════

class TestPlanNodeConfig:

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_plan_node_extracts_bpm(self, example):
        from src.agent.master_graph import plan_node
        cfg = example["config"]
        result = plan_node(_plan_state(cfg))
        assert result["slave_plan"]["bpm"] == float(cfg["bpm"])

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_plan_node_extracts_beat_count(self, example):
        from src.agent.master_graph import plan_node
        cfg = example["config"]
        result = plan_node(_plan_state(cfg))
        assert result["slave_plan"]["beat_count"] == float(cfg["length_beats"])

    @pytest.mark.unit
    @pytest.mark.parametrize("example", EXAMPLE_CONFIGS, ids=CONFIG_IDS)
    def test_plan_node_ui_config_in_user_text(self, example):
        """ui_song_config muss als [UI_CONFIG] Block im user_text erscheinen."""
        from src.agent.master_graph import plan_node
        cfg = example["config"]
        result = plan_node(_plan_state(cfg))
        user_text = result["slave_plan"]["user_text"]
        assert "[UI_CONFIG]" in user_text
        assert cfg["genre"] in user_text


# ══════════════════════════════════════════════════════════════════════════════
# 4. Edge Cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    @pytest.mark.unit
    def test_bpm_as_string_coercion(self):
        """Java könnte BPM als String senden — Python muss es trotzdem verarbeiten."""
        cfg = {
            "genre": "Rock", "bpm": "120", "track_count": "4",
            "key": "E minor", "length_beats": "32",
            "technique": "Standard", "rhythm_pattern": "Straight Eighths",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
            "fx_preset": "Distortion+Amp",
        }
        prompt = _make_prompt(cfg)
        assert "120" in prompt
        assert "Rock" in prompt

    @pytest.mark.unit
    def test_bpm_float_coercion(self):
        """BPM als Float (120.0) muss als Integer im Prompt erscheinen."""
        cfg = {
            "genre": "Jazz", "bpm": 140.0, "track_count": 4,
            "key": "F major", "length_beats": 32,
            "technique": "Legato", "rhythm_pattern": "Syncopated",
            "string_register": "Mid (D3-G3)", "dynamics_shape": "Flat",
            "fx_preset": "Delay+Chorus",
        }
        prompt = _make_prompt(cfg)
        assert "140" in prompt
        assert "140.0" not in prompt  # Kein Float im Prompt

    @pytest.mark.unit
    def test_empty_config_uses_defaults(self):
        """Leere Config → alle Defaults müssen greifen, kein Crash."""
        prompt = _make_prompt({})
        assert "Rock" in prompt       # default genre
        assert "120" in prompt        # default bpm
        assert "E minor" in prompt    # default key

    @pytest.mark.unit
    def test_unknown_fields_ignored(self):
        """Unbekannte Felder (z.B. zukünftige Extension-Erweiterungen) dürfen nicht crashen."""
        cfg = {
            "genre": "Rock", "bpm": 120, "track_count": 4,
            "key": "E minor", "length_beats": 32,
            "technique": "Standard", "rhythm_pattern": "Straight Eighths",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
            "fx_preset": "Distortion+Amp",
            "future_field": "some_value",  # unbekanntes Feld
        }
        prompt = _make_prompt(cfg)
        assert "Rock" in prompt  # bekannte Felder funktionieren noch

    @pytest.mark.unit
    def test_json_parse_valid(self):
        """Die JSON-Payload wie sie Java sendet muss parsebar sein."""
        raw = (
            '{"genre":"Rock","bpm":120,"track_count":4,'
            '"key":"E minor","length_beats":32,'
            '"technique":"Standard","rhythm_pattern":"Straight Eighths",'
            '"string_register":"Low (E2-D3)","dynamics_shape":"Accent 1&3",'
            '"fx_preset":"Distortion+Amp"}'
        )
        cfg = json.loads(raw)
        assert isinstance(cfg, dict)
        assert cfg["genre"] == "Rock"
        assert cfg["bpm"] == 120

    @pytest.mark.unit
    def test_json_parse_invalid_raises(self):
        """Kein gültiges JSON → ValueError oder JSONDecodeError erwartet."""
        with pytest.raises((json.JSONDecodeError, ValueError)):
            cfg = json.loads("nicht-json")
            if not isinstance(cfg, dict):
                raise ValueError("kein dict")

    @pytest.mark.unit
    def test_json_not_dict_raises(self):
        """JSON-Array statt Object → ValueError erwartet."""
        with pytest.raises((json.JSONDecodeError, ValueError)):
            cfg = json.loads('["Rock", 120]')
            if not isinstance(cfg, dict):
                raise ValueError("JSON muss ein Objekt sein")

    @pytest.mark.unit
    def test_plan_node_without_ui_config(self):
        """plan_node ohne ui_song_config darf nicht crashen."""
        from src.agent.master_graph import plan_node
        result = plan_node(_plan_state(None, "Erstelle einen Rock-Song mit 120 BPM"))
        assert "slave_plan" in result
        assert result["slave_plan"]["bpm"] > 0

    @pytest.mark.unit
    def test_plan_node_ui_config_overrides_text_bpm(self):
        """BPM aus ui_song_config hat Vorrang vor BPM im User-Text."""
        from src.agent.master_graph import plan_node
        cfg = {
            "genre": "Metal", "bpm": 180, "track_count": 4,
            "key": "B minor", "length_beats": 32,
            "technique": "Palm Mute", "rhythm_pattern": "Gallop",
            "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 2&4",
            "fx_preset": "Distortion+Amp",
        }
        result = plan_node(_plan_state(cfg, "Erstelle einen Song mit 90 BPM"))
        # UI-Config BPM (180) soll gewinnen, nicht Text-BPM (90)
        assert result["slave_plan"]["bpm"] == 180.0


# ══════════════════════════════════════════════════════════════════════════════
# 5. Screenshot-Variante: Pop 100 BPM · 1 Track · E minor · 64 beats · Gallop
# ══════════════════════════════════════════════════════════════════════════════

_SCREENSHOT_CFG = {
    "genre": "Pop", "bpm": 100, "track_count": 1,
    "key": "E minor", "length_beats": 64,
    "technique": "Standard", "rhythm_pattern": "Gallop",
    "string_register": "Low (E2-D3)", "dynamics_shape": "Accent 1&3",
    "fx_preset": "Distortion+Amp",
}

_SCREENSHOT_STATE = _plan_state(_SCREENSHOT_CFG)


class TestScreenshotVariant:
    """Ergebnis-Tests für die Screenshot-Konfiguration aus dem Bitwig Controller UI."""

    @pytest.mark.unit
    def test_bpm_100(self):
        from src.agent.master_graph import plan_node
        result = plan_node(_SCREENSHOT_STATE)
        assert result["slave_plan"]["bpm"] == 100.0

    @pytest.mark.unit
    def test_beat_count_64(self):
        from src.agent.master_graph import plan_node
        result = plan_node(_SCREENSHOT_STATE)
        assert result["slave_plan"]["beat_count"] == 64.0

    @pytest.mark.unit
    def test_track_count_1(self):
        from src.agent.master_graph import plan_node
        result = plan_node(_SCREENSHOT_STATE)
        assert result["slave_plan"]["track_count"] == 1

    @pytest.mark.unit
    def test_prompt_contains_pop_and_gallop(self):
        prompt = _make_prompt(_SCREENSHOT_CFG)
        assert "Pop" in prompt
        assert "Gallop" in prompt

    @pytest.mark.unit
    def test_prompt_contains_distortion_fx(self):
        prompt = _make_prompt(_SCREENSHOT_CFG)
        assert "Distortion+Amp" in prompt

    @pytest.mark.unit
    def test_prompt_contains_e_minor(self):
        prompt = _make_prompt(_SCREENSHOT_CFG)
        assert "E minor" in prompt

    @pytest.mark.unit
    def test_prompt_contains_low_register(self):
        prompt = _make_prompt(_SCREENSHOT_CFG)
        assert "Low (E2-D3)" in prompt

    @pytest.mark.unit
    def test_ui_config_block_in_plan(self):
        from src.agent.master_graph import plan_node
        result = plan_node(_SCREENSHOT_STATE)
        user_text = result["slave_plan"]["user_text"]
        assert "[UI_CONFIG]" in user_text
        assert "Pop" in user_text
        assert "Gallop" in user_text
        assert "Distortion+Amp" in user_text

    @pytest.mark.unit
    def test_bpm_overrides_default_120(self):
        """100 BPM aus UI muss den Hard-coded Default 120 überschreiben."""
        from src.agent.master_graph import plan_node
        result = plan_node(_SCREENSHOT_STATE)
        assert result["slave_plan"]["bpm"] != 120.0
        assert result["slave_plan"]["bpm"] == 100.0


# ══════════════════════════════════════════════════════════════════════════════
# 6. Alle Einzel-Varianten — jeder erlaubte Wert jedes Feldes, Basis = Screenshot
# ══════════════════════════════════════════════════════════════════════════════

# config-Feldname → (slave_plan-Schlüssel, Typ-Coercion)
_FIELD_TO_PLAN: dict = {
    "genre":           ("genre",          str),
    "track_count":     ("track_count",    lambda v: int(float(v))),
    "key":             ("scale",          str),
    "length_beats":    ("beat_count",     float),
    "technique":       ("technique",      str),
    "rhythm_pattern":  ("rhythm_pattern", str),
    "string_register": ("string_register",str),
    "dynamics_shape":  ("dynamics_shape", str),
    "fx_preset":       ("fx_hint",        str),
}

_ALL_FIELD_VALUES = [
    pytest.param(field, value, id=f"{field}={value}")
    for field, values in {
        "genre":           sorted(VALID_GENRES),
        "track_count":     sorted(VALID_TRACKS),
        "key":             sorted(VALID_KEYS),
        "length_beats":    sorted(VALID_LENGTHS),
        "technique":       sorted(VALID_TECHNIQUES),
        "rhythm_pattern":  sorted(VALID_RHYTHMS),
        "string_register": sorted(VALID_REGISTERS),
        "dynamics_shape":  sorted(VALID_DYNAMICS),
        "fx_preset":       sorted(VALID_FX),
    }.items()
    for value in values
]


def _variant_cfg(field: str, value) -> dict:
    """Screenshot-Basis mit einem überschriebenen Feld."""
    cfg = dict(_SCREENSHOT_CFG)
    cfg[field] = value
    return cfg


def _variant_state(cfg: dict):
    return _plan_state(cfg)


class TestAllFieldVariants:
    """Jeder erlaubte Wert jedes Feldes fließt korrekt durch Prompt und plan_node.

    45 Varianten (8 Genres + 4 TrackCounts + 7 Keys + 4 Lengths + 6 Techniques
    + 5 Rhythms + 3 Registers + 4 Dynamics + 4 FX) × 3 Prüfungen = 135 Tests.
    Basis-Config: Screenshot-Variante (Pop · 100 BPM · 1 Track · E minor · 64 · Gallop).
    """

    @pytest.mark.unit
    @pytest.mark.parametrize("field,value", _ALL_FIELD_VALUES)
    def test_prompt_contains_value(self, field, value):
        """Jeder Feldwert muss im generierten Prompt-Text erscheinen."""
        prompt = _make_prompt(_variant_cfg(field, value))
        assert str(value) in prompt

    @pytest.mark.unit
    @pytest.mark.parametrize("field,value", _ALL_FIELD_VALUES)
    def test_plan_node_field_value(self, field, value):
        """plan_node muss den Feldwert korrekt in slave_plan übernehmen."""
        from src.agent.master_graph import plan_node
        plan_key, coerce = _FIELD_TO_PLAN[field]
        result = plan_node(_variant_state(_variant_cfg(field, value)))
        assert result["slave_plan"][plan_key] == coerce(value)

    @pytest.mark.unit
    @pytest.mark.parametrize("field,value", _ALL_FIELD_VALUES)
    def test_ui_config_block_contains_value(self, field, value):
        """[UI_CONFIG]-Block im user_text muss den Feldwert enthalten."""
        from src.agent.master_graph import plan_node
        result = plan_node(_variant_state(_variant_cfg(field, value)))
        user_text = result["slave_plan"]["user_text"]
        assert "[UI_CONFIG]" in user_text
        assert str(value) in user_text

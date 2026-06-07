from src.agent.tools.knowledge.knowledge_tool import query_bitwig_docs
from src.agent.tools.knowledge.kb_store_tool import store_result_in_kb
from src.agent.tools.knowledge.project_learning_tool import scan_and_learn_project
from src.agent.tools.knowledge.reconstruct_tool import reconstruct_project
from src.agent.tools.bitwig.recipe_tool import create_track_from_recipe
from src.agent.tools.bitwig.bitwig_tools import control_bitwig
from src.agent.tools.bitwig.song_tools import (
    check_bitwig_connection,
    get_bitwig_track_state,
)
from src.agent.tools.bitwig.suggest_tools import suggest_notes, get_launchpad_mode, listen_played_notes, play_notes, arm_track
from src.agent.tools.music.pattern_tools import write_pattern
from src.agent.tools.music.pattern_raw_tool import write_pattern_raw
from src.agent.tools.music.context_tool import get_song_context
from src.agent.tools.knowledge.artist_tool import get_artist_context
from src.agent.tools.knowledge.web_search_tool import web_search
from src.agent.tools.knowledge.freesound_tool import find_audio_example
from src.agent.tools.music.music_validator import validate_music
from src.agent.tools.music.audio_llm_tool import analyze_song
from src.agent.tools.knowledge.song_metadata_tool import search_artist_song
from src.agent.tools.knowledge.song_learn_tool import learn_song_from_youtube
from src.agent.tools.knowledge.music_learning import validate_and_learn
from src.agent.tools.meta.mlx_export import export_mlx_training_data
from src.bitwig_executor import execute_setup, compose_notes
from langchain_core.tools import StructuredTool, tool as _tool
from pydantic import BaseModel, model_validator
from src.knowledge.vst_scanner import scan_and_store as _scan_fn
from src.agent.tools.registry import registry


class _BitwigResultInput(BaseModel):
    """Flexibles Schema: akzeptiert sowohl result={...} als auch flache kwargs."""
    result: dict = {}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: dict) -> dict:
        if isinstance(data, dict) and "result" not in data:
            return {"result": data}
        return data


def _make_tool(fn, name: str | None = None) -> StructuredTool:
    return StructuredTool(
        name=name or fn.__name__,
        func=fn,
        description=(fn.__doc__ or "").strip(),
        args_schema=_BitwigResultInput,
        return_direct=False,
    )


@_tool
def scan_vst_plugins() -> str:
    """Scannt alle installierten VST3-Plugins in Bitwig und speichert sie in Neo4j.
    Danach gibt query_bitwig_docs die aktuell installierten Plugins zurück.
    Aufrufen wenn neue VSTs installiert wurden oder der Agent die Plugin-Liste nicht kennt.
    """
    return _scan_fn()


ALL_TOOLS = [
    registry.register(query_bitwig_docs, domain="knowledge"),
    registry.register(store_result_in_kb, domain="knowledge"),
    registry.register(web_search, domain="knowledge"),
    registry.register(find_audio_example, domain="knowledge"),
    registry.register(scan_and_learn_project, domain="knowledge"),
    registry.register(reconstruct_project, domain="knowledge"),
    registry.register(create_track_from_recipe, domain="bitwig"),
    registry.register(control_bitwig, domain="bitwig"),
    registry.register(check_bitwig_connection, domain="bitwig"),
    registry.register(get_bitwig_track_state, domain="bitwig"),
    registry.register(_make_tool(execute_setup), domain="bitwig"),
    registry.register(_make_tool(compose_notes), domain="music"),
    registry.register(write_pattern, domain="music"),
    registry.register(write_pattern_raw, domain="music"),
    registry.register(get_song_context, domain="music"),
    registry.register(get_artist_context, domain="knowledge"),
    registry.register(validate_music, domain="music"),
    registry.register(validate_and_learn, domain="knowledge"),
    registry.register(analyze_song, domain="music"),
    registry.register(search_artist_song, domain="knowledge"),
    registry.register(learn_song_from_youtube, domain="knowledge"),
    registry.register(export_mlx_training_data, domain="meta"),
    registry.register(scan_vst_plugins, domain="bitwig"),
    registry.register(StructuredTool.from_function(suggest_notes), domain="music"),
    registry.register(StructuredTool.from_function(get_launchpad_mode), domain="bitwig"),
    registry.register(StructuredTool.from_function(listen_played_notes), domain="bitwig"),
    registry.register(StructuredTool.from_function(play_notes), domain="bitwig"),
    registry.register(StructuredTool.from_function(arm_track), domain="bitwig"),
]

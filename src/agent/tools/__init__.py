from src.agent.tools.knowledge_tool import query_bitwig_docs
from src.agent.tools.project_learning_tool import scan_and_learn_project
from src.agent.tools.reconstruct_tool import reconstruct_project
from src.agent.tools.recipe_tool import create_track_from_recipe
from src.agent.tools.bitwig_tools import control_bitwig
from src.agent.tools.song_tools import (
    check_bitwig_connection,
    get_bitwig_track_state,
)
from src.agent.tools.suggest_tools import suggest_notes, get_launchpad_mode, listen_played_notes, play_notes, arm_track
from src.agent.tools.pattern_tools import write_pattern
from src.agent.tools.context_tool import get_song_context
from src.agent.tools.web_search_tool import web_search
from src.agent.tools.freesound_tool import find_audio_example
from src.agent.tools.music_validator import validate_music
from src.agent.tools.audio_llm_tool import analyze_song
from src.agent.tools.music_learning import validate_and_learn
from src.agent.tools.mlx_export import export_mlx_training_data
from src.bitwig_executor import execute_setup, compose_notes
from langchain_core.tools import StructuredTool, tool as _tool
from pydantic import BaseModel, model_validator
from src.knowledge.vst_scanner import scan_and_store as _scan_fn


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
    query_bitwig_docs,
    web_search,
    find_audio_example,
    scan_and_learn_project,
    reconstruct_project,
    create_track_from_recipe,
    control_bitwig,
    check_bitwig_connection,
    get_bitwig_track_state,
    _make_tool(execute_setup),
    _make_tool(compose_notes),
    write_pattern,
    get_song_context,
    validate_music,
    validate_and_learn,
    analyze_song,
    export_mlx_training_data,
    scan_vst_plugins,
    StructuredTool.from_function(suggest_notes),
    StructuredTool.from_function(get_launchpad_mode),
    StructuredTool.from_function(listen_played_notes),
    StructuredTool.from_function(play_notes),
    StructuredTool.from_function(arm_track),
]

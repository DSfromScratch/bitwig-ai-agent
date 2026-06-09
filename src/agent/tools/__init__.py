from src.agent.tools.knowledge.knowledge_tool import query_knowledge
from src.agent.tools.knowledge.kb_store_tool import store_result_in_kb
from src.agent.tools.knowledge.project_learning_tool import scan_and_learn_project
from src.agent.tools.knowledge.reconstruct_tool import reconstruct_project
from src.agent.tools.bitwig.recipe_tool import create_track_from_recipe
from src.agent.tools.bitwig.bitwig_tools import control_bitwig
from src.agent.tools.bitwig.song_tools import get_bitwig_state
from src.agent.tools.bitwig.suggest_tools import launchpad
from src.agent.tools.knowledge.web_search_tool import web_search
from src.agent.tools.knowledge.song_learn_tool import learn_song_from_youtube
from src.agent.tools.music.pattern_raw_tool import write_pattern_raw
from src.agent.tools.music.pattern_llm_tool import generate_pattern
from src.agent.tools.registry import registry
from src.bitwig_executor import execute_setup
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, model_validator


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


ALL_TOOLS = [
    registry.register(query_knowledge, domain="knowledge"),
    registry.register(store_result_in_kb, domain="knowledge"),
    registry.register(web_search, domain="knowledge"),
    registry.register(scan_and_learn_project, domain="knowledge"),
    registry.register(reconstruct_project, domain="knowledge"),
    registry.register(create_track_from_recipe, domain="bitwig"),
    registry.register(control_bitwig, domain="bitwig"),
    registry.register(get_bitwig_state, domain="bitwig"),
    registry.register(_make_tool(execute_setup), domain="bitwig"),
    registry.register(write_pattern_raw, domain="music"),
    registry.register(generate_pattern, domain="music"),
    registry.register(launchpad, domain="music"),
    registry.register(learn_song_from_youtube, domain="knowledge"),
]

from src.agent.tools.knowledge_tool import query_bitwig_docs
from src.agent.tools.bitwig_tools import control_bitwig
from src.agent.tools.song_tools import (
    check_bitwig_connection,
    get_bitwig_track_state,
)
from src.agent.tools.launchpad_tools import (
    bitwig_launchpad_map,
    bitwig_launchpad_led,
    bitwig_launchpad_clear,
)
from src.bitwig_executor import execute_setup, execute_result
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
    query_bitwig_docs,
    control_bitwig,
    check_bitwig_connection,
    get_bitwig_track_state,
    _make_tool(execute_setup),
    _make_tool(execute_result),
    StructuredTool.from_function(bitwig_launchpad_map),
    StructuredTool.from_function(bitwig_launchpad_led),
    StructuredTool.from_function(bitwig_launchpad_clear),
]

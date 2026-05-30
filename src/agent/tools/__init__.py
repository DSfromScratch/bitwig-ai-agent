from src.agent.tools.knowledge_tool import query_bitwig_docs
from src.agent.tools.bitwig_tools import control_bitwig
from src.agent.tools.song_tools import (
    check_bitwig_connection,
    get_bitwig_track_state,
)

ALL_TOOLS = [
    query_bitwig_docs,
    control_bitwig,
    check_bitwig_connection,
    get_bitwig_track_state,
]

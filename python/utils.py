"""
facade module for backward compatibility.
"""

from python.core import WEEKDAY_NAMES, get_time_parts, get_time_string, is_market_open  # noqa: F401
from python.prompting import (  # noqa: F401
    build_messages,
    call_server,
    estimate_prompt_tokens,
    manage_slot,
    render_prompt,
)


def get_weekday_name(sim_time: float) -> str:
    p = get_time_parts(sim_time)
    return WEEKDAY_NAMES[p.weekday_idx]

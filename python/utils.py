"""
Facade module for backward compatibility.

Old code imported from python/utils.py:
  - build_messages
  - call_server
  - estimate_prompt_tokens
  - get_time_string
  - is_market_open

After modularization:
  - prompting.py owns prompt building + server calls
  - core.py owns time utilities (market hours, clock formatting)

This facade keeps the old import paths stable.
"""

from core import WEEKDAY_NAMES, get_time_parts, get_time_string, is_market_open  # noqa: F401
from prompting import (  # noqa: F401
    build_messages,
    call_server,
    estimate_prompt_tokens,
    manage_slot,
    render_prompt,
)


def get_weekday_name(sim_time: float) -> str:
    p = get_time_parts(sim_time)
    return WEEKDAY_NAMES[p.weekday_idx]
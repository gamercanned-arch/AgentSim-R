"""
Facade module for backward compatibility.

Old code imported from python/tools.py:
  - execute_tool, parse_tool_call, try_auto_collect_loot
  - ITEM_CATALOG, WORKPLACE_BY_JOB, EDUCATION_LOCATIONS
  - _kill_agent

After modularization, the real implementations live in python/tooling/*.
This facade preserves the old import paths so the rest of the simulation
(scheduler, utils/prompting, etc.) does not need to change all at once.
"""

from tooling.execute import execute_tool  # noqa: F401
from tooling.parsing import parse_tool_call  # noqa: F401

from tooling.catalogs import (  # noqa: F401
    EDUCATION_LOCATIONS,
    HOBBY_ITEMS,
    ITEM_CATALOG,
    VEHICLE_CATALOG,
    WORKPLACE_BY_JOB,
)

from tooling.handlers.inventory_loot import try_auto_collect_loot  # noqa: F401
from tooling.death import kill_agent as _kill_agent  # noqa: F401

# Optional: provide non-underscored name too (nice for new code)
kill_agent = _kill_agent
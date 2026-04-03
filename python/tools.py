"""
facade module for backward compatibility.
"""

from python.tooling.execute import execute_tool  # noqa: F401
from python.tooling.parsing import parse_tool_call, parse_tool_calls  # noqa: F401

from python.tooling.catalogs import (  # noqa: F401
    EDUCATION_LOCATIONS,
    HOBBY_ITEMS,
    ITEM_CATALOG,
    VEHICLE_CATALOG,
    WORKPLACE_BY_JOB,
)

from python.tooling.handlers.inventory_loot import try_auto_collect_loot  # noqa: F401
from python.tooling.death import kill_agent as _kill_agent  # noqa: F401

kill_agent = _kill_agent

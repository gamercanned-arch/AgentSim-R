from __future__ import annotations


# Parameters that handlers intentionally default or treat as optional.
OPTIONAL_TOOL_PARAMS: dict[str, set[str]] = {
    "change_status": {"person", "type", "value"},
    "do_hobby": {"description", "item"},
    "drop_item": {"item_name"},
    "get_education": {"type", "hours"},
    "sleep": {"hours"},
    "wait": {"minutes"},
    "work_job": {"jobname", "hours"},
}

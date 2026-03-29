from __future__ import annotations

import re
from typing import Dict, Tuple

_TOOL_BLOCK_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FUNC_RE = re.compile(r"<function=([^>\n]+)>(.*?)</function>", re.DOTALL)
_PARAM_RE = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Optional: strip accidental markdown fences (common failure mode)
_FENCE_RE = re.compile(r"```.*?$", re.DOTALL)


def parse_tool_call(tool_call_str: str) -> Tuple[str, Dict[str, str]]:
    """
    Parses the <tool_call> block in the assistant output.
    Enforces EXACTLY ONE tool_call (otherwise returns Parse error).
    """
    try:
        s = tool_call_str or ""
        s = re.sub(_THINK_RE, "", s)
        s = re.sub(_FENCE_RE, "", s).strip()

        matches = list(re.finditer(_TOOL_BLOCK_RE, s))
        if not matches:
            return "Parse error: No <tool_call> tags found.", {}
        if len(matches) != 1:
            return f"Parse error: Expected exactly 1 <tool_call>, found {len(matches)}.", {}

        block = matches[0].group(1)
        func_match = re.search(_FUNC_RE, block)
        if not func_match:
            return "Parse error: No <function=name> tag found.", {}

        name = func_match.group(1).strip()
        params_block = func_match.group(2)

        args: Dict[str, str] = {}
        for p in re.finditer(_PARAM_RE, params_block):
            key = p.group(1).strip()
            val = p.group(2).strip()
            args[key] = val

        return name, args
    except Exception as e:
        return f"Parse error: {e}", {}
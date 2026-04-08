from __future__ import annotations

import re
from typing import Dict, List, Tuple

_OUTER_FENCE_RE = re.compile(r"```(?:xml)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_PARAM_RE = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)
_FUNC_RE = re.compile(r"<function=([^>\n]+)>(.*?)</function>", re.DOTALL)


def _unwrap_outer_fence(text: str) -> str:
    s = str(text or "").strip()
    blocks = _OUTER_FENCE_RE.findall(s)
    for block in blocks:
        if "<tool_call>" in block and "</tool_call>" in block:
            return block.strip()
    return s


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _parse_tool_block(block: str) -> Tuple[Tuple[str, Dict[str, str]] | None, str | None]:
    stripped = str(block or "").strip()
    if not stripped:
        return None, "Parse error: Empty <tool_call> block."

    func_match = re.fullmatch(_FUNC_RE, stripped)
    if not func_match:
        return None, "Parse error: <tool_call> must contain exactly one <function=...></function> block and no extra text."

    name = func_match.group(1).strip()
    if not name:
        return None, "Parse error: Empty function name."

    params_block = func_match.group(2)
    args: Dict[str, str] = {}
    pos = 0

    while True:
        pos = _skip_ws(params_block, pos)
        if pos >= len(params_block):
            break

        p = _PARAM_RE.match(params_block, pos)
        if not p:
            return None, "Parse error: Unexpected text inside <function> block."

        key = p.group(1).strip()
        val = p.group(2).strip()

        if not key:
            return None, "Parse error: Empty parameter name."
        if key in args:
            return None, f"Parse error: Duplicate parameter '{key}'."

        args[key] = val
        pos = p.end()

    return (name, args), None


def parse_tool_calls(tool_call_str: str) -> Tuple[List[Tuple[str, Dict[str, str]]], str | None]:
    try:
        s = _unwrap_outer_fence(tool_call_str or "").strip()
        if not s:
            return[], "Parse error: Empty assistant output."

        # Completely strip out all <think> blocks to avoid confusing the strict parser
        s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()

        pos = 0
        calls: List[Tuple[str, Dict[str, str]]] =[]

        while True:
            start = s.find("<tool_call>", pos)
            if start == -1:
                break
            end = s.find("</tool_call>", start)
            if end == -1:
                return[], "Parse error: Unbalanced <tool_call> tags."

            inner = s[start + len("<tool_call>"):end]
            parsed, err = _parse_tool_block(inner)
            if err:
                return[], err
            calls.append(parsed)

            pos = end + len("</tool_call>")

        if not calls:
            return[], "Parse error: No <tool_call> tags found."

        return calls, None
    except Exception as e:
        return[], f"Parse error: {e}"


def parse_tool_call(tool_call_str: str) -> Tuple[str, Dict[str, str]]:
    calls, err = parse_tool_calls(tool_call_str)
    if err:
        return err, {}
    if len(calls) != 1:
        return f"Parse error: Expected exactly 1 <tool_call>, found {len(calls)}.", {}
    return calls[0]
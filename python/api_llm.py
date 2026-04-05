from __future__ import annotations

import json
import os
import random
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

from python.config import CHARS_PER_TOKEN
from python.prompting import GLOBAL_TOOLS_LIST

from groq import Groq  # type: ignore
from cerebras.cloud.sdk import Cerebras  # type: ignore


def _approx_tokens_from_messages(messages: List[dict]) -> int:
    total_chars = 0
    for m in messages:
        total_chars += len(str(m.get("role", ""))) + 2
        total_chars += len(str(m.get("content", ""))) + 1
    return max(1, total_chars // CHARS_PER_TOKEN)


def _is_rate_limit_error(status_code: Optional[int], exc_text: str) -> bool:
    if status_code == 429:
        return True
    s = (exc_text or "").lower()
    return ("429" in s) or ("rate limit" in s) or ("ratelimit" in s)


def _tools_system_prefix(tools: List[dict]) -> str:
    lines = []
    lines.append("# Tools")
    lines.append("")
    lines.append("You have access to the following functions:")
    lines.append("")
    lines.append("<tools>")
    for t in tools:
        lines.append(json.dumps(t, ensure_ascii=False))
    lines.append("</tools>")
    lines.append("")
    lines.append("If you choose to call a function ONLY reply in the following format with NO suffix:")
    lines.append("")
    lines.append("<tool_call>")
    lines.append("<function=example_function_name>")
    lines.append("<parameter=example_parameter_1>")
    lines.append("value_1")
    lines.append("</parameter>")
    lines.append("<parameter=example_parameter_2>")
    lines.append("This is the value for the second parameter")
    lines.append("that can span")
    lines.append("multiple lines")
    lines.append("</parameter>")
    lines.append("</function>")
    lines.append("</tool_call>")
    lines.append("")
    lines.append("<IMPORTANT>")
    lines.append("Reminder:")
    lines.append(
        "- Function calls MUST follow the specified format: an inner <function=...></function> block must be nested within <tool_call></tool_call> XML tags"
    )
    lines.append("- Required parameters MUST be specified")
    lines.append(
        "- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after"
    )
    lines.append(
        "- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls"
    )
    lines.append("</IMPORTANT>")
    return "\n".join(lines)


@dataclass
class ProviderConfig:
    name: str  # "openrouter" | "groq" | "cerebras"
    models: List[str]
    temperature: float = 0.7
    top_p: float = 0.9
    timeout_s: float = 90.0
    max_output_tokens: Optional[int] = None  # override per provider call


class APIKeyRing:
    def __init__(self, keys: List[str]):
        self.keys = [k for k in keys if k]
        self.idx = 0

    def __len__(self) -> int:
        return len(self.keys)

    def next_key(self) -> str:
        if not self.keys:
            return ""
        k = self.keys[self.idx % len(self.keys)]
        self.idx = (self.idx + 1) % len(self.keys)
        return k

    def iter_once_rotating(self):
        if not self.keys:
            return
        for _ in range(len(self.keys)):
            yield self.next_key()


def _sanitize_openai_messages(messages: List[dict]) -> List[dict]:
    """
    Allowed keys:
      - system/user: role, content
      - assistant: role, content, tool_calls
      - tool: role, content, tool_call_id
    """
    out: List[dict] = []
    for m in messages or []:
        role = str(m.get("role", "") or "")
        content = "" if m.get("content") is None else str(m.get("content"))

        if role in ("system", "user"):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            nm = {"role": "assistant", "content": content}
            if "tool_calls" in m and m.get("tool_calls") is not None:
                nm["tool_calls"] = m.get("tool_calls")
            out.append(nm)
        elif role == "tool":
            tcid = m.get("tool_call_id", None)
            nm = {"role": "tool", "content": content}
            if tcid is not None:
                nm["tool_call_id"] = str(tcid)
            out.append(nm)
        else:
            out.append({"role": "user", "content": f"[{role}]\n{content}"})
    return out


class LLMRouter:
    """
    Enforces OpenAI-style tool handshake:
    - tool messages must have tool_call_id
    - tool_call_id must match a PRIOR assistant.tool_calls[].id
    """

    def __init__(
        self,
        provider_order: List[str],
        provider_configs: Dict[str, ProviderConfig],
        max_output_tokens: int = 16384,
        mode: str = "ordered",
        openrouter_headers: Optional[Dict[str, str]] = None,
        tool_role_mode: str = "tool",
    ):
        load_dotenv()
        self.provider_order = list(provider_order)
        self.provider_configs = dict(provider_configs)
        self.max_output_tokens = int(max_output_tokens)
        self.mode = mode
        self.openrouter_headers = openrouter_headers or {}
        self.tool_role_mode = (tool_role_mode or "tool").strip().lower()

        self.openrouter_keys = APIKeyRing(self._load_keys("OPENROUTER_API_KEY"))
        self.groq_keys = APIKeyRing(self._load_keys("GROQ_API_KEY"))
        self.cerebras_keys = APIKeyRing(self._load_keys("CEREBRAS_API_KEY"))

        if self.tool_role_mode != "tool":
            raise ValueError("This build enforces TOOL_ROLE_MODE=tool for stability.")

    @staticmethod
    def _load_keys(prefix: str, n: int = 5) -> List[str]:
        keys = []
        for i in range(1, n + 1):
            k = (os.environ.get(f"{prefix}_{i}", "") or "").strip()
            if k:
                keys.append(k)
        k0 = (os.environ.get(prefix, "") or "").strip()
        if k0 and k0 not in keys:
            keys.append(k0)
        return keys

    def _provider_sequence(self) -> List[str]:
        if self.mode == "random_provider":
            seq = list(self.provider_order)
            random.shuffle(seq)
            return seq
        return list(self.provider_order)

    def _inject_tools_into_system(self, messages: List[dict]) -> List[dict]:
        msgs = deepcopy(messages)
        if not msgs or msgs[0].get("role") != "system":
            msgs.insert(0, {"role": "system", "content": ""})
        base = str(msgs[0].get("content", "") or "")
        msgs[0]["content"] = _tools_system_prefix(GLOBAL_TOOLS_LIST) + "\n\n" + base
        return msgs

    @staticmethod
    def _attach_and_validate_tool_calls(messages: List[dict]) -> List[dict]:
        msgs = deepcopy(messages)

        valid_ids: set[str] = set()
        prior_ids: set[str] = set()

        # Convert internal assistant.api_tool_calls -> assistant.tool_calls
        for m in msgs:
            if m.get("role") == "assistant" and "api_tool_calls" in m:
                api_calls = m.get("api_tool_calls") or []
                tool_calls = []
                for c in api_calls:
                    cid = str(c.get("id", "") or "").strip()
                    name = str(c.get("name", "") or "").strip() or "unknown"
                    args = c.get("args", {}) or {}
                    if not cid:
                        continue
                    valid_ids.add(cid)
                    tool_calls.append(
                        {
                            "id": cid,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(args, ensure_ascii=False),
                            },
                        }
                    )
                m["tool_calls"] = tool_calls

        # Validate handshake ordering
        for m in msgs:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        prior_ids.add(str(tc["id"]))

            if m.get("role") == "tool":
                tcid = m.get("tool_call_id", None)
                if not tcid or not str(tcid).strip():
                    raise ValueError("tool message missing tool_call_id.")
                tcid_s = str(tcid)
                if tcid_s not in valid_ids:
                    raise ValueError(
                        f"tool_call_id '{tcid_s}' not present in any assistant.api_tool_calls."
                    )
                if tcid_s not in prior_ids:
                    raise ValueError(
                        f"tool_call_id '{tcid_s}' has no PRIOR assistant.tool_calls."
                    )

        return _sanitize_openai_messages(msgs)

    def __call__(self, messages: List[dict], agent_id: int, prompt_text=None) -> Tuple[str, int, int]:
        msgs = self._inject_tools_into_system(messages)
        msgs = self._attach_and_validate_tool_calls(msgs)

        prompt_tokens = _approx_tokens_from_messages(msgs)
        out = self._route_call(msgs, provider=None, model=None)
        gen_tokens = max(1, len(out) // CHARS_PER_TOKEN)
        return out, prompt_tokens, gen_tokens

    def call_specific_raw(
        self,
        provider: str,
        model: str,
        messages: List[dict],
        *,
        temperature: float = 0.2,
        top_p: float = 0.8,
        max_output_tokens: int = 2048,
    ) -> str:
        """
        Call exactly one provider/model without tool schema injection and without tool validation.
        (Use for summarizer.)
        """
        provider = (provider or "").strip().lower()
        if not provider:
            raise ValueError("provider required")
        if not model:
            raise ValueError("model required")

        msgs = _sanitize_openai_messages(messages)
        cfg = ProviderConfig(
            name=provider,
            models=[model],
            temperature=float(temperature),
            top_p=float(top_p),
            max_output_tokens=int(max_output_tokens),
        )
        return self._call_provider_model(provider, model, cfg, msgs)

    def _route_call(self, messages: List[dict], provider: Optional[str], model: Optional[str]) -> str:
        if provider and model:
            cfg = self.provider_configs.get(provider)
            if not cfg:
                raise RuntimeError(f"Provider not configured: {provider}")
            cfg2 = ProviderConfig(
                name=provider,
                models=[model],
                temperature=cfg.temperature,
                top_p=cfg.top_p,
                timeout_s=cfg.timeout_s,
                max_output_tokens=cfg.max_output_tokens,
            )
            return self._call_provider_model(provider, model, cfg2, messages)

        seq = self._provider_sequence()
        last_err = None
        for provider_name in seq:
            cfg = self.provider_configs.get(provider_name)
            if not cfg or not cfg.models:
                continue
            try:
                return self._call_provider(cfg, messages)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    def _call_provider(self, cfg: ProviderConfig, messages: List[dict]) -> str:
        last_err = None
        for model in cfg.models:
            try:
                return self._call_provider_model(cfg.name, model, cfg, messages)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Provider {cfg.name} failed for all models. Last error: {last_err}")

    def _call_provider_model(self, provider: str, model: str, cfg: ProviderConfig, messages: List[dict]) -> str:
        provider = provider.lower()
        if provider == "openrouter":
            return self._call_openrouter(model, cfg, messages)
        if provider == "groq":
            return self._call_groq(model, cfg, messages)
        if provider == "cerebras":
            return self._call_cerebras(model, cfg, messages)
        raise ValueError(f"Unknown provider: {provider}")

    def _call_openrouter(self, model: str, cfg: ProviderConfig, messages: List[dict]) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        if len(self.openrouter_keys) == 0:
            raise RuntimeError("No OpenRouter keys found (OPENROUTER_API_KEY_1..5).")

        max_tokens = int(cfg.max_output_tokens or self.max_output_tokens)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(cfg.temperature),
            "top_p": float(cfg.top_p),
            "max_tokens": max_tokens,
            "stream": False,
        }

        last_err_text = ""
        for k in self.openrouter_keys.iter_once_rotating():
            headers = {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}
            headers.update(self.openrouter_headers)
            r = None
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout_s)
                if r.status_code == 429:
                    continue
                if r.status_code >= 400:
                    last_err_text = r.text or ""
                    r.raise_for_status()
                data = r.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
            except requests.HTTPError as e:
                if _is_rate_limit_error(getattr(r, "status_code", None) if r else None, str(e)):
                    continue
                raise
        raise RuntimeError(f"OpenRouter failed. Last error: {last_err_text[:4000]}")

    def _call_groq(self, model: str, cfg: ProviderConfig, messages: List[dict]) -> str:
        if len(self.groq_keys) == 0:
            raise RuntimeError("No Groq keys found (GROQ_API_KEY_1..5).")

        max_tokens = int(cfg.max_output_tokens or self.max_output_tokens)
        last_err_txt = ""
        for k in self.groq_keys.iter_once_rotating():
            try:
                client = Groq(api_key=k)
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=float(cfg.temperature),
                    top_p=float(cfg.top_p),
                    max_completion_tokens=max_tokens,
                    stream=False,
                )
                return (completion.choices[0].message.content or "").strip()
            except Exception as e:
                last_err_txt = str(e)
                if _is_rate_limit_error(None, last_err_txt):
                    continue
                raise
        raise RuntimeError(f"Groq failed. Last error: {last_err_txt[:4000]}")

    def _call_cerebras(self, model: str, cfg: ProviderConfig, messages: List[dict]) -> str:
        if len(self.cerebras_keys) == 0:
            raise RuntimeError("No Cerebras keys found (CEREBRAS_API_KEY_1..5).")

        max_tokens = int(cfg.max_output_tokens or self.max_output_tokens)
        last_err_txt = ""
        for k in self.cerebras_keys.iter_once_rotating():
            try:
                client = Cerebras(api_key=k)
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    stream=False,
                    max_completion_tokens=max_tokens,
                    temperature=float(cfg.temperature),
                    top_p=float(cfg.top_p),
                )
                return (completion.choices[0].message.content or "").strip()
            except Exception as e:
                last_err_txt = str(e)
                if _is_rate_limit_error(None, last_err_txt):
                    continue
                raise
        raise RuntimeError(f"Cerebras failed. Last error: {last_err_txt[:4000]}")


class Summarizer:
    """
    Editable summarizer user prompt:
      - SUMMARY_USER_PROMPT_PATH (preferred)
      - SUMMARY_USER_PROMPT (inline)
    Placeholders:
      {existing_summary}
      {chunk_text}
    """

    DEFAULT_SYSTEM_PROMPT = (
        "You are a summarization engine for a multi-agent village simulation.\n"
        "Write a dense, factual summary.\n"
        "Do NOT include tool-call XML.\n"
        "Return ONLY the updated summary text."
    )

    DEFAULT_USER_TEMPLATE = (
        "Existing summary (may be empty):\n"
        "{existing_summary}\n\n"
        "New turns to incorporate:\n"
        "{chunk_text}\n"
    )

    def __init__(
        self,
        router: LLMRouter,
        provider: str,
        model: str,
        *,
        max_output_tokens: int = 2048,
        temperature: float = 0.2,
        top_p: float = 0.8,
        user_template: str | None = None,
        user_template_path: str | None = None,
        system_prompt: str | None = None,
    ):
        self.router = router
        self.provider = (provider or "openrouter").strip().lower()
        self.model = model
        self.max_output_tokens = int(max_output_tokens)
        self.temperature = float(temperature)
        self.top_p = float(top_p)

        self.system_prompt = (system_prompt or self.DEFAULT_SYSTEM_PROMPT).strip()

        tmpl = user_template
        if user_template_path:
            try:
                with open(user_template_path, "r", encoding="utf-8") as f:
                    tmpl = f.read()
            except OSError:
                pass
        self.user_template = (tmpl or self.DEFAULT_USER_TEMPLATE).strip() + "\n"

        if "{chunk_text}" not in self.user_template:
            raise ValueError("Summarizer user template must include {chunk_text}.")
        if "{existing_summary}" not in self.user_template:
            raise ValueError("Summarizer user template must include {existing_summary}.")

    def summarize(self, existing_summary: str, chunk_text: str) -> str:
        user = self.user_template.format(
            existing_summary=(existing_summary or "").strip(),
            chunk_text=(chunk_text or "").strip(),
        )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]
        out = self.router.call_specific_raw(
            self.provider,
            self.model,
            messages,
            temperature=self.temperature,
            top_p=self.top_p,
            max_output_tokens=self.max_output_tokens,
        )
        return (out or "").strip()
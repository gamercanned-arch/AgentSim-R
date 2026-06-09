from __future__ import annotations

import os
import random
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from google import genai
from google.genai import types
from python.config import CHARS_PER_TOKEN
from python.prompting import GLOBAL_TOOLS_LIST
from python.tooling.schema import OPTIONAL_TOOL_PARAMS


_STRING_PARAM_HINTS = {
    "action",
    "description",
    "direction",
    "item",
    "item_name",
    "jobname",
    "message",
    "person",
    "person_or_object",
    "place",
    "type",
    "value",
}
_NUMBER_PARAM_HINTS = {"amount", "hours", "minutes"}
_INTEGER_PARAM_HINTS = {"shares"}

def _approx_tokens_from_messages(messages: List[dict]) -> int:
    total_chars = 0
    for m in messages:
        total_chars += len(str(m.get("role", ""))) + 2
        total_chars += len(str(m.get("content", ""))) + 1
    return max(1, total_chars // CHARS_PER_TOKEN)

def _schema_for_tool_param(param_name: str) -> types.Schema:
    key = str(param_name or "").strip().lower()
    if key in _INTEGER_PARAM_HINTS:
        return types.Schema(type=types.Type.INTEGER)
    if key in _NUMBER_PARAM_HINTS:
        return types.Schema(type=types.Type.NUMBER)
    if key in _STRING_PARAM_HINTS:
        return types.Schema(type=types.Type.STRING)
    return types.Schema(type=types.Type.STRING)


def _tool_function_declarations(tools: List[dict]) -> List[types.FunctionDeclaration]:
    declarations: List[types.FunctionDeclaration] = []
    for tool in tools or []:
        name = str(tool.get("name", "") or "").strip()
        if not name:
            continue

        raw_params = tool.get("params", None)
        if raw_params is None:
            raw_params = tool.get("parameters", [])

        if isinstance(raw_params, dict):
            raw_params = list((raw_params.get("properties") or {}).keys())

        params = [str(p).strip() for p in (raw_params or []) if str(p).strip()]
        declaration = types.FunctionDeclaration(
            name=name,
            description=str(tool.get("description", "") or "").strip() or None,
        )
        required_params = [
            p for p in params if p not in OPTIONAL_TOOL_PARAMS.get(name, set())
        ]
        if params:
            declaration.parameters = types.Schema(
                type=types.Type.OBJECT,
                properties={p: _schema_for_tool_param(p) for p in params},
                required=required_params,
                property_ordering=params,
            )
        declarations.append(declaration)
    return declarations


def _tool_config_for_declarations(
    declarations: List[types.FunctionDeclaration],
) -> types.ToolConfig | None:
    if not declarations:
        return None
    return types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowed_function_names=[str(d.name) for d in declarations if d.name],
        )
    )


def _escape_xml_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _function_call_to_xml(function_call: Any) -> str:
    name = str(getattr(function_call, "name", "") or "").strip()
    args = getattr(function_call, "args", None) or {}
    if not isinstance(args, dict):
        args = {}

    lines = ["<tool_call>", f"<function={name}>"]
    for key, value in args.items():
        key = str(key).strip()
        if not key:
            continue
        lines.extend([
            f"<parameter={key}>",
            _escape_xml_text(value),
            "</parameter>",
        ])
    lines.extend(["</function>", "</tool_call>"])
    return "\n".join(lines)


def _extract_function_calls(response: Any) -> List[Any]:
    direct_calls = getattr(response, "function_calls", None)
    if direct_calls:
        return list(direct_calls)

    calls = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            function_call = getattr(part, "function_call", None)
            if function_call is not None:
                calls.append(function_call)
    return calls


from python.prompting import _normalize_assistant_output as _normalize_assistant_output_xml


@dataclass
class ProviderConfig:
    name: str  
    models: List[str]
    temperature: float = 0.7
    top_p: float = 0.9
    timeout_s: float = 90.0
    max_output_tokens: Optional[int] = None 


@dataclass
class RawLLMResponse:
    provider: str
    model: str
    content: str
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


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


def _sanitize_provider_messages(messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    for m in messages or []:
        role = str(m.get("role", "") or "")
        content = "" if m.get("content") is None else str(m.get("content"))

        if role in ("system", "user"):
            out.append({"role": role, "content": content})
        elif role == "assistant":
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            out.append({"role": "user", "content": content})
        else:
            out.append({"role": "user", "content": f"[{role}]\n{content}"})
    return out


_NATIVE_TOOL_RULES = """[Native Tool Calling]
- You MUST choose at least one provided function tool every turn.
- Use only the function tools provided by the API request.
- Return function calls through the model's native function-calling mechanism; do not write XML tags or tool schemas in text.
- Multiple function calls are allowed when the actions naturally belong together."""


def _strip_legacy_tool_prompt(text: str) -> str:
    s = str(text or "")
    s = re.sub(
        r"# Tools\s+You have access to the following functions:.*?</IMPORTANT>\s*",
        "",
        s,
        flags=re.DOTALL | re.IGNORECASE,
    )
    s = re.sub(r"<tools>.*?</tools>\s*", "", s, flags=re.DOTALL | re.IGNORECASE)

    cleaned = []
    skip_example = False
    for line in s.splitlines():
        stripped = line.strip()
        lower = stripped.lower()

        if stripped.startswith("TOOL CALLING FORMAT"):
            skip_example = True
            continue
        if skip_example:
            if (
                not stripped
                or stripped.startswith("Clarifications:")
                or stripped.startswith("[")
                or stripped.startswith("- ")
            ):
                skip_example = False
            else:
                continue
        if not stripped:
            cleaned.append(line)
            continue

        if stripped == "You MUST reply with one or more tool calls.":
            cleaned.append("You MUST choose one or more provided function tools.")
            continue
        if stripped == "- Use only the tools listed in your system instructions.":
            cleaned.append("- Use only the function tools provided by the API request.")
            continue
        if stripped == "- Make at least one tool call every turn. Multiple tool calls are allowed when the actions naturally belong together.":
            cleaned.append("- Choose at least one function tool every turn. Multiple function calls are allowed when the actions naturally belong together.")
            continue

        if any(
            marker in stripped
            for marker in (
                "<tool_call",
                "</tool_call",
                "<function=",
                "</function>",
                "<parameter=",
                "</parameter>",
                "<think>",
                "</think>",
            )
        ):
            continue
        if (
            "xml" in lower
            or "after the final" in lower
            or "before the <tool_call>" in lower
            or "text before <tool_call>" in lower
            or "do not output any text after" in lower
            or "must think" in lower
            or "place your reason" in lower
        ):
            continue

        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _prepare_messages_for_native_tools(messages: List[dict]) -> List[dict]:
    msgs = deepcopy(messages)
    if not msgs or msgs[0].get("role") != "system":
        msgs.insert(0, {"role": "system", "content": ""})

    native_rules_added = any(
        msg.get("role") == "system"
        and "[Native Tool Calling]" in str(msg.get("content", "") or "")
        for msg in msgs
    )
    for msg in msgs:
        if msg.get("role") != "system":
            continue
        content = _strip_legacy_tool_prompt(str(msg.get("content", "") or ""))
        if not native_rules_added:
            content = "\n\n".join(s for s in (_NATIVE_TOOL_RULES, content) if s)
            native_rules_added = True
        msg["content"] = content

    return msgs


class LLMRouter:
    def __init__(
        self,
        provider_order: List[str],
        provider_configs: Dict[str, ProviderConfig],
        max_output_tokens: int = 16384,
        mode: str = "ordered",
        openrouter_headers: Optional[Dict[str, str]] = None,
    ):
        load_dotenv()
        self.provider_order = list(provider_order)
        self.provider_configs = dict(provider_configs)
        self.max_output_tokens = int(max_output_tokens)
        self.mode = mode
        self.openrouter_headers = openrouter_headers or {}
        self.token_usage_registry = {}
        self.gemini_tpm_limit = int(os.environ.get("GEMINI_TPM_LIMIT", "250000").strip())
        self.gemini_calls = []

        self.gemini_keys = APIKeyRing(self._load_keys("GEMINI_API_KEY"))
        self.last_raw: Dict[int, Dict[str, str]] = {}
        self._clients: Dict[str, genai.Client] = {}

        n_keys = len(self.gemini_keys.keys)
        if n_keys > 0:
            from python.quota import DEFAULT_STATE_PATH, QuotaManager
            initial_models = []
            for cfg in provider_configs.values():
                if cfg.models:
                    initial_models.extend(cfg.models)
            self.quota = QuotaManager(
                n_keys,
                list(set(initial_models)),
                key_fingerprints=QuotaManager.fingerprints_from_keys(
                    self.gemini_keys.keys
                ),
                state_path=os.environ.get(
                    "GEMINI_QUOTA_STATE_PATH", DEFAULT_STATE_PATH
                ).strip() or DEFAULT_STATE_PATH,
                rpm_limit=int(os.environ.get("GEMINI_RPM_LIMIT", "15").strip()),
                flash_lite_tpm_limit=int(
                    os.environ.get("GEMINI_FLASH_LITE_TPM_LIMIT", "250000").strip()
                ),
            )
        else:
            self.quota = None

    def set_quota(self, quota: 'QuotaManager'):
        self.quota = quota

    @staticmethod
    def _load_keys(prefix: str) -> List[str]:
        keys = []
        i = 1
        consecutive_misses = 0
        
        while consecutive_misses < 20:
            k = (os.environ.get(f"{prefix}_{i}", "") or "").strip()
            if k:
                if k not in keys:
                    keys.append(k)
                consecutive_misses = 0
            else:
                consecutive_misses += 1
            i += 1
            
        k0 = (os.environ.get(prefix, "") or "").strip()
        if k0 and k0 not in keys:
            keys.insert(0, k0)
            
        return keys

    def get_last_raw(self, agent_id: int) -> Dict[str, str]:
        return dict(self.last_raw.get(int(agent_id), {}) or {})

    def get_context_limit(self) -> int:
        has_gemma = False
        for provider_cfg in self.provider_configs.values():
            for model in provider_cfg.models:
                if "gemma" in model.lower():
                    has_gemma = True
                    break
        return 120000 if has_gemma else 1000000

    def _wait_for_tpm_limit(self, prompt_tokens: int, max_tokens: int):
        # Backward-compatible fallback for callers that do not use QuotaManager.
        import time
        needed = prompt_tokens + max_tokens
        if needed > self.gemini_tpm_limit:
            needed = self.gemini_tpm_limit
        
        while True:
            now = time.time()
            self.gemini_calls = [c for c in self.gemini_calls if now - c[0] < 60.0]
            current_sum = sum(c[1] for c in self.gemini_calls)
            if current_sum + needed <= self.gemini_tpm_limit:
                self.gemini_calls.append((now, needed))
                break
            time.sleep(0.5)

    @staticmethod
    def _looks_like_quota_or_rate_error(err: Exception) -> bool:
        s = str(err or "").lower()
        return any(
            marker in s
            for marker in (
                "quota",
                "rate",
                "429",
                "resource_exhausted",
                "too many requests",
                "exceeded",
            )
        )

    def _key_attempt_order(
        self, preferred_idx: int, model: str, estimated_tokens: int = 0
    ) -> List[int]:
        n_keys = len(self.gemini_keys.keys)
        raw = [(preferred_idx + off) % n_keys for off in range(n_keys)]
        quota = getattr(self, "quota", None)
        if not quota:
            return raw
        with_quota = [
            idx
            for idx in raw
            if quota.key_available(idx, model) and quota.has_daily_quota(idx, model)
        ]
        if with_quota:
            return sorted(
                with_quota,
                key=lambda idx: quota.seconds_until_request_slot(
                    idx, model, estimated_tokens=estimated_tokens
                ),
            )
        available = [idx for idx in raw if quota.key_available(idx, model)]
        fallback = available or raw
        return sorted(
            fallback,
            key=lambda idx: quota.seconds_until_request_slot(
                idx, model, estimated_tokens=estimated_tokens
            ),
        )

    def _provider_sequence(self) -> List[str]:
        if self.mode == "random_provider":
            seq = list(self.provider_order)
            random.shuffle(seq)
            return seq
        return list(self.provider_order)

    def __call__(self, messages: List[dict], agent_id: int, prompt_text=None) -> Tuple[str, int, int]:
        messages = _prepare_messages_for_native_tools(messages)
        msgs = _sanitize_provider_messages(messages)

        raw = self._route_call_rich(
            msgs,
            provider=None,
            model=None,
            agent_id=agent_id,
            use_tools=True,
        )
        self.last_raw[int(agent_id)] = {
            "provider": raw.provider,
            "model": raw.model,
            "content": raw.content,
            "reasoning": raw.reasoning,
        }

        processed = raw.content if raw.content.lstrip().startswith("<tool_call>") else _normalize_assistant_output_xml(raw.content)
        return processed, raw.prompt_tokens, raw.completion_tokens

    def call_specific_raw(
        self,
        provider: str,
        model: str,
        messages: List[dict],
        *,
        agent_id: Optional[int] = None,
        temperature: float = 0.2,
        top_p: float = 0.8,
        max_output_tokens: int = 2048,
    ) -> str:
        provider = (provider or "").strip().lower()
        if not provider:
            raise ValueError("provider required")
        if not model:
            raise ValueError("model required")

        msgs = _sanitize_provider_messages(messages)
        cfg = ProviderConfig(
            name=provider,
            models=[model],
            temperature=float(temperature),
            top_p=float(top_p),
            max_output_tokens=int(max_output_tokens),
        )

        raw = self._call_provider_model_rich(
            provider,
            model,
            cfg,
            msgs,
            agent_id=agent_id,
            use_tools=False,
        )
        return (raw.content or "").strip()

    def _route_call_rich(
        self,
        messages: List[dict],
        provider: Optional[str],
        model: Optional[str],
        agent_id: Optional[int] = None,
        *,
        use_tools: bool = False,
    ) -> RawLLMResponse:
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
            return self._call_provider_model_rich(
                provider,
                model,
                cfg2,
                messages,
                agent_id=agent_id,
                use_tools=use_tools,
            )

        seq = self._provider_sequence()
        last_err = None
        for provider_name in seq:
            cfg = self.provider_configs.get(provider_name)
            if not cfg or not cfg.models:
                continue
            try:
                return self._call_provider_rich(
                    cfg,
                    messages,
                    agent_id=agent_id,
                    use_tools=use_tools,
                )
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    def _call_provider_rich(
        self,
        cfg: ProviderConfig,
        messages: List[dict],
        agent_id: Optional[int] = None,
        *,
        use_tools: bool = False,
    ) -> RawLLMResponse:
        last_err = None
        for model in cfg.models:
            try:
                return self._call_provider_model_rich(
                    cfg.name,
                    model,
                    cfg,
                    messages,
                    agent_id=agent_id,
                    use_tools=use_tools,
                )
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Provider {cfg.name} failed for all models. Last error: {last_err}")

    def _call_provider_model_rich(
        self,
        provider: str,
        model: str,
        cfg: ProviderConfig,
        messages: List[dict],
        agent_id: Optional[int] = None,
        *,
        use_tools: bool = False,
    ) -> RawLLMResponse:
        provider = provider.lower()
        if provider == "gemini":
            return self._call_gemini_rich(
                model,
                cfg,
                messages,
                agent_id=agent_id,
                use_tools=use_tools,
            )
        raise ValueError(f"Unknown provider: {provider}")

    def _call_gemini_rich(
        self,
        model: str,
        cfg: ProviderConfig,
        messages: List[dict],
        agent_id: Optional[int] = None,
        *,
        use_tools: bool = False,
    ) -> RawLLMResponse:
        if len(self.gemini_keys) == 0:
            raise RuntimeError("No Gemini keys found (GEMINI_API_KEY_1..N).")

        max_tokens = int(cfg.max_output_tokens or self.max_output_tokens)
        
        system_msgs = [m["content"] for m in messages if m["role"] == "system"]
        system_msg = "\n\n".join(system_msgs) if system_msgs else ""
        chat_msgs = [m for m in messages if m["role"] != "system"]

        is_gemma = "gemma" in model.lower()

        if is_gemma and system_msg:
            # Gemma models reject native system instructions.
            # Hence, merge system into the first user message.
            if chat_msgs and chat_msgs[0]["role"] == "user":
                chat_msgs[0]["content"] = f"{system_msg}\n\n{chat_msgs[0]['content']}"
            else:
                chat_msgs.insert(0, {"role": "user", "content": system_msg})
            system_instruction = None
        else:
            system_instruction = system_msg if system_msg else None

        merged_contents = []
        for m in chat_msgs:
            role = "model" if m["role"] == "assistant" else "user"
            content = str(m["content"])
            if merged_contents and merged_contents[-1].role == role:
                existing = merged_contents[-1].parts[0].text
                merged_contents[-1] = types.Content(
                    role=role, 
                    parts=[types.Part.from_text(text=existing + "\n\n" + content)]
                )
            else:
                merged_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))

        tool_declarations = _tool_function_declarations(GLOBAL_TOOLS_LIST) if use_tools else []
        genai_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=float(cfg.temperature),
            top_p=float(cfg.top_p),
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_level="high"),
            tools=(
                [types.Tool(function_declarations=tool_declarations)]
                if tool_declarations
                else None
            ),
            tool_config=_tool_config_for_declarations(tool_declarations),
            automatic_function_calling=(
                types.AutomaticFunctionCallingConfig(disable=True)
                if tool_declarations
                else None
            ),
        )

        n_keys = len(self.gemini_keys.keys)
        preferred_idx = (agent_id - 1) % n_keys if agent_id is not None else 0

        est_prompt = _approx_tokens_from_messages(messages)
        estimated_total_tokens = est_prompt + max_tokens
        attempts = 0
        max_attempts = max(n_keys, n_keys * 3)
        last_err = None

        while attempts < max_attempts:
            order = self._key_attempt_order(
                preferred_idx + attempts,
                model,
                estimated_tokens=estimated_total_tokens,
            )
            if not order:
                time.sleep(1.0)
                attempts += 1
                continue

            current_key_idx = order[0]

            k = self.gemini_keys.keys[current_key_idx]

            if self.quota:
                self.quota.wait_for_rpm_slot(
                    current_key_idx,
                    model,
                    estimated_tokens=estimated_total_tokens,
                )
            else:
                self._wait_for_tpm_limit(est_prompt, max_tokens)

            try:
                if k not in self._clients:
                    self._clients[k] = genai.Client(api_key=k)
                client = self._clients[k]
                
                response = client.models.generate_content(
                    model=model,
                    contents=merged_contents,
                    config=genai_config
                )
                # Safe response text extraction
                content = ""
                reasoning = ""
                function_calls = _extract_function_calls(response) if use_tools else []
                if response.candidates:
                    candidate = response.candidates[0]
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if getattr(part, "function_call", None) is not None:
                                continue
                            if getattr(part, "thought", False):
                                reasoning += (part.text or "")
                            else:
                                content += (part.text or "")
                if function_calls:
                    content = "\n".join(_function_call_to_xml(fc) for fc in function_calls)
                elif use_tools:
                    content = content.strip() or "[NO FUNCTION CALL RETURNED]"

                # Extract actual token counts
                prompt_tokens = 0
                completion_tokens = 0
                if response.usage_metadata:
                    prompt_tokens = response.usage_metadata.prompt_token_count or 0
                    completion_tokens = response.usage_metadata.candidates_token_count or 0

                actual_total = prompt_tokens + completion_tokens
                if not self.quota and self.gemini_calls:
                    self.gemini_calls[-1] = (self.gemini_calls[-1][0], actual_total)
                if self.quota:
                    self.quota.record_request(
                        current_key_idx,
                        model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )

                # Update token registry
                if model not in self.token_usage_registry:
                    self.token_usage_registry[model] = {"prompt": 0, "completion": 0, "total": 0}
                self.token_usage_registry[model]["prompt"] += prompt_tokens
                self.token_usage_registry[model]["completion"] += completion_tokens
                self.token_usage_registry[model]["total"] += actual_total

                return RawLLMResponse(
                    provider="gemini",
                    model=model,
                    content=content,
                    reasoning=reasoning,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            except Exception as e:
                if not self.quota and self.gemini_calls:
                    self.gemini_calls.pop()

                last_err = e
                if self.quota:
                    self.quota.record_error(current_key_idx, model, e)
                err_str = str(e)
                quotaish = self._looks_like_quota_or_rate_error(e)
                suffix = " Cooldown recorded." if quotaish else ""
                print(
                    f"    [API ERROR] {err_str[:150]}... on key "
                    f"{current_key_idx+1}. Rotating key.{suffix}"
                )
                attempts += 1
                continue
        raise RuntimeError(
            f"Worker {agent_id} all gemini keys failed for model {model} "
            f"after {attempts} attempts. Last error: {last_err}"
        )


class Summarizer:
    DEFAULT_SYSTEM_PROMPT = (
        "You are an expert summarization engine for an agent in a life-simulation.\n"
        "Your task is to merge the provided recent logs into the agent's existing running summary "
        "to create a single, cohesive, chronological narrative.\n"
        "Crucial requirements:\n"
        "- Focus on the long-term activities, achievements, relationships, and important events that occurred.\n"
        "- You MUST write the summary in the first person (using 'I', 'my', 'me').\n"
        "- The summary MUST start with the exact prefix: '[THIS IS A SUMMARY OF WHAT YOU HAVE DONE TILL NOW]'.\n"
        "- DO NOT include or output XML tool tags.\n"
        "- Return ONLY the updated summary text."
    )

    def __init__(
        self,
        router: LLMRouter,
        provider: str,
        model: str,
        *,
        max_output_tokens: int = 8192,
        temperature: float = 0.8,
        top_p: float = 0.8,
        system_prompt: str | None = None,
        user_prompt_template: str | None = None,
        **kwargs
    ):
        self.router = router
        self.provider = (provider or "gemini").strip().lower()
        self.model = model
        self.max_output_tokens = int(max_output_tokens)
        self.temperature = float(temperature)
        self.top_p = float(top_p)
        self.system_prompt = (system_prompt or self.DEFAULT_SYSTEM_PROMPT).strip()
        self.user_prompt_template = user_prompt_template
        self.max_retries = kwargs.get("max_retries", None)

    def summarize(self, existing_summary: str, prompt_text: str, agent_id: Optional[int] = None) -> str:
        if self.user_prompt_template:
            try:
                user_msg = self.user_prompt_template.format(
                    existing_summary=existing_summary,
                    text_chunk=prompt_text,
                    prompt_text=prompt_text
                )
            except Exception:
                user_msg = self.user_prompt_template.replace(
                    "{existing_summary}", existing_summary
                ).replace(
                    "{text_chunk}", prompt_text
                ).replace(
                    "{prompt_text}", prompt_text
                )
        else:
            if existing_summary.strip():
                user_msg = (
                    f"EXISTING FIRST-PERSON SUMMARY:\n{existing_summary}\n\n"
                    f"NEW LOG EVENTS TO INTEGRATE:\n{prompt_text}\n\n"
                    f"Task: Update and rewrite the existing first-person summary to integrate the new events. "
                    f"Keep it in first-person. Ensure the summary starts with "
                    f"'[THIS IS A SUMMARY OF WHAT YOU HAVE DONE TILL NOW]'."
                )
            else:
                user_msg = (
                    f"LOG EVENTS TO SUMMARIZE:\n{prompt_text}\n\n"
                    f"Task: Create a first-person summary of these events focusing on long-term activities. "
                    f"The summary MUST start with '[THIS IS A SUMMARY OF WHAT YOU HAVE DONE TILL NOW]'."
                )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_msg},
        ]
        
        out = self.router.call_specific_raw(
            self.provider,
            self.model,
            messages,
            agent_id=agent_id,
            temperature=self.temperature,
            top_p=self.top_p,
            max_output_tokens=self.max_output_tokens,
        )
        return (out or "").strip()

from __future__ import annotations

import json
import os
import random
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from google import genai
from google.genai import types
from google.genai.errors import APIError

from python.config import CHARS_PER_TOKEN
from python.prompting import GLOBAL_TOOLS_LIST

def _approx_tokens_from_messages(messages: List[dict]) -> int:
    total_chars = 0
    for m in messages:
        total_chars += len(str(m.get("role", ""))) + 2
        total_chars += len(str(m.get("content", ""))) + 1
    return max(1, total_chars // CHARS_PER_TOKEN)

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
    lines.append("- Function calls MUST follow the specified format: an inner <function=...></function> block must be nested within <tool_call></tool_call> XML tags")
    lines.append("- Required parameters MUST be specified")
    lines.append("- You may provide optional reasoning for your function call in natural language BEFORE the function call, but NOT after")
    lines.append("- If your model/provider supports a separate reasoning trace field, put reasoning there and keep assistant content focused on the tool call.")
    lines.append("- If there is no function call available, answer the question like normal with your current knowledge and do not tell the user about function calls")
    lines.append("</IMPORTANT>")
    return "\n".join(lines)


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
        self.gemini_tpm_limit = int(os.environ.get("GEMINI_TPM_LIMIT", "220000").strip())
        self.gemini_calls = []

        self.gemini_keys = APIKeyRing(self._load_keys("GEMINI_API_KEY"))
        self.last_raw: Dict[int, Dict[str, str]] = {}
        self._clients: Dict[str, genai.Client] = {}

        n_keys = len(self.gemini_keys.keys)
        if n_keys > 0:
            from python.quota import QuotaManager
            initial_models = []
            for cfg in provider_configs.values():
                if cfg.models:
                    initial_models.extend(cfg.models)
            self.quota = QuotaManager(n_keys, list(set(initial_models)))
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
        if "<tools>" in base:
            return msgs
        msgs[0]["content"] = _tools_system_prefix(GLOBAL_TOOLS_LIST) + "\n\n" + base
        return msgs

    def __call__(self, messages: List[dict], agent_id: int, prompt_text=None) -> Tuple[str, int, int]:
        msgs = self._inject_tools_into_system(messages)
        msgs = _sanitize_provider_messages(msgs)

        raw = self._route_call_rich(msgs, provider=None, model=None, agent_id=agent_id)
        self.last_raw[int(agent_id)] = {
            "provider": raw.provider,
            "model": raw.model,
            "content": raw.content,
            "reasoning": raw.reasoning,
        }

        processed = _normalize_assistant_output_xml(raw.content)
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

        raw = self._call_provider_model_rich(provider, model, cfg, msgs, agent_id=agent_id)
        return (raw.content or "").strip()

    def _route_call_rich(self, messages: List[dict], provider: Optional[str], model: Optional[str], agent_id: Optional[int] = None) -> RawLLMResponse:
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
            return self._call_provider_model_rich(provider, model, cfg2, messages, agent_id=agent_id)

        seq = self._provider_sequence()
        last_err = None
        for provider_name in seq:
            cfg = self.provider_configs.get(provider_name)
            if not cfg or not cfg.models:
                continue
            try:
                return self._call_provider_rich(cfg, messages, agent_id=agent_id)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"All providers failed. Last error: {last_err}")

    def _call_provider_rich(self, cfg: ProviderConfig, messages: List[dict], agent_id: Optional[int] = None) -> RawLLMResponse:
        last_err = None
        for model in cfg.models:
            try:
                return self._call_provider_model_rich(cfg.name, model, cfg, messages, agent_id=agent_id)
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Provider {cfg.name} failed for all models. Last error: {last_err}")

    def _call_provider_model_rich(self, provider: str, model: str, cfg: ProviderConfig, messages: List[dict], agent_id: Optional[int] = None) -> RawLLMResponse:
        provider = provider.lower()
        if provider == "gemini":
            return self._call_gemini_rich(model, cfg, messages, agent_id=agent_id)
        raise ValueError(f"Unknown provider: {provider}")

    def _call_gemini_rich(self, model: str, cfg: ProviderConfig, messages: List[dict], agent_id: Optional[int] = None) -> RawLLMResponse:
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

        genai_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=float(cfg.temperature),
            top_p=float(cfg.top_p),
            max_output_tokens=max_tokens,
        )

        n_keys = len(self.gemini_keys.keys)
        preferred_idx = (agent_id - 1) % n_keys if agent_id is not None else 0
        attempts = 0
        backoff = 5.0

        est_prompt = _approx_tokens_from_messages(messages)
        self._wait_for_tpm_limit(est_prompt, max_tokens)
        reserved_added = True

        while True:
            # Check if all keys are out of daily quota
            if self.quota and not self.quota.any_key_has_quota(model):
                if reserved_added and self.gemini_calls:
                    self.gemini_calls.pop()
                    reserved_added = False
                self.quota.wait_until_quota_reset()
                if not reserved_added:
                    self._wait_for_tpm_limit(est_prompt, max_tokens)
                    reserved_added = True
                continue

            current_key_idx = (preferred_idx + attempts) % n_keys
            if self.quota and not self.quota.has_daily_quota(current_key_idx, model):
                # Try the next key since this key is out of daily quota
                attempts += 1
                if attempts > 3 * n_keys:
                    time.sleep(1.0)
                continue

            k = self.gemini_keys.keys[current_key_idx]

            if self.quota:
                self.quota.wait_for_rpm_slot(current_key_idx, model)

            try:
                if k not in self._clients:
                    self._clients[k] = genai.Client(api_key=k)
                client = self._clients[k]
                
                response = client.models.generate_content(
                    model=model,
                    contents=merged_contents,
                    config=genai_config
                )
                # Record quota after successful request
                if self.quota:
                    self.quota.record_request(current_key_idx, model)
                
                # Safe response text extraction
                content = ""
                if response.candidates:
                    candidate = response.candidates[0]
                    if candidate.content and candidate.content.parts:
                        content = candidate.content.parts[0].text or ""

                # Extract actual token counts
                prompt_tokens = 0
                completion_tokens = 0
                if response.usage_metadata:
                    prompt_tokens = response.usage_metadata.prompt_token_count or 0
                    completion_tokens = response.usage_metadata.candidates_token_count or 0

                actual_total = prompt_tokens + completion_tokens
                if reserved_added and self.gemini_calls:
                    self.gemini_calls[-1] = (self.gemini_calls[-1][0], actual_total)

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
                    reasoning="",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            except Exception as e:
                if reserved_added and self.gemini_calls:
                    self.gemini_calls.pop()
                    reserved_added = False

                if isinstance(e, ValueError):
                    # safety block: return empty response
                    return RawLLMResponse(provider="gemini", model=model, content="", reasoning="")
                
                # Record quota for errors that likely reached Google (HTTP 4xx/5xx)
                if self.quota:
                    self.quota.record_request(current_key_idx, model)
                err_str = str(e)
                print(f"    [API ERROR] {err_str[:150]}... on key {current_key_idx+1}. Rotating key. Backoff {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(60.0, backoff * 2)
                
                attempts += 1
                if attempts >= n_keys * 3:
                    raise RuntimeError(f"Worker {agent_id} all gemini keys failed after {attempts} rotating attempts. Last error: {err_str}")
                
                if not reserved_added:
                    self._wait_for_tpm_limit(est_prompt, max_tokens)
                    reserved_added = True
                continue


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
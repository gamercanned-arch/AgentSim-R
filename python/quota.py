"""
Persistent quota and rate-limit bookkeeping for Google AI Studio keys.

This manager is intentionally conservative about *waiting* and cautious about
*blocking*. Local counters are useful for spacing requests and debugging across
short runs, but they are not treated as proof that remote daily quota is gone.
Provider errors drive temporary cooldowns; remaining keys/models continue to be
tried before the caller gives up.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

from python.config import CACHE_DIR

IST = timezone(timedelta(hours=5, minutes=30))
RESET_HOUR, RESET_MINUTE = 13, 30
STATE_VERSION = 3
DEFAULT_STATE_PATH = os.path.join(CACHE_DIR, "quota_state.json")

DEFAULT_RPM = 15
DEFAULT_DAILY_LIMIT = 500
DEFAULT_FLASH_LITE_TPM = 250_000

MODEL_DAILY_LIMITS = {
    "gemma-4-31b-it": 1500,
    "gemma-4-26b-it": 1500,
    "gemma-4-26b-a4b-it": 1500,
    "gemini-3.1-flash-lite": 500,
    "gemini-3.1-flash-lite-preview": 500,
}


def _now_wall() -> float:
    return time.time()


def _now_mono() -> float:
    return time.monotonic()


def _model_key(model: str) -> str:
    return str(model or "").strip()


def _daily_limit_for_model(model: str) -> int:
    return int(MODEL_DAILY_LIMITS.get(_model_key(model), DEFAULT_DAILY_LIMIT))


def _is_flash_lite(model: str) -> bool:
    return "gemini-3.1-flash-lite" in _model_key(model).lower()


def _empty_model_usage() -> Dict[str, int]:
    return {
        "requests": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }


def _reset_period(now: datetime | None = None) -> str:
    now_ist = now or datetime.now(IST)
    reset_today = now_ist.replace(
        hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0
    )
    if now_ist < reset_today:
        now_ist = now_ist - timedelta(days=1)
    return now_ist.date().isoformat()


def _next_reset_epoch() -> float:
    now_ist = datetime.now(IST)
    reset_today = now_ist.replace(
        hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0
    )
    target = reset_today + timedelta(days=1) if now_ist >= reset_today else reset_today
    return target.timestamp()


class QuotaManager:
    def __init__(
        self,
        n_keys: int,
        models: list[str],
        *,
        key_fingerprints: list[str] | None = None,
        state_path: str = DEFAULT_STATE_PATH,
        rpm_limit: int = DEFAULT_RPM,
        flash_lite_tpm_limit: int = DEFAULT_FLASH_LITE_TPM,
    ):
        self.n_keys = int(n_keys)
        self.models = []
        for model in models or []:
            self.add_model(model)
        self.key_fingerprints = list(key_fingerprints or [f"key_{i}" for i in range(self.n_keys)])
        self.state_path = state_path
        self.rpm_limit = int(rpm_limit)
        self.flash_lite_tpm_limit = int(flash_lite_tpm_limit)
        self.run_total_requests = 0
        self.run_start_time = _now_wall()
        self._lock = threading.RLock()
        self._period = _reset_period()
        self._usage: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._errors: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._rpm_windows: Dict[int, deque[float]] = {}
        self._tpm_windows: Dict[int, deque[tuple[float, int]]] = {}
        self._load()
        self._ensure_shape_locked()

    @staticmethod
    def fingerprint_key(key: str) -> str:
        return hashlib.sha256(str(key or "").encode("utf-8", errors="ignore")).hexdigest()[:16]

    @classmethod
    def fingerprints_from_keys(cls, keys: Iterable[str]) -> list[str]:
        return [cls.fingerprint_key(k) for k in keys]

    def add_model(self, model: str) -> None:
        model = _model_key(model)
        if model and model not in self.models:
            self.models.append(model)

    def _key_id(self, key_idx: int) -> str:
        if 0 <= int(key_idx) < len(self.key_fingerprints):
            return self.key_fingerprints[int(key_idx)]
        return f"key_{int(key_idx)}"

    def _key_idx_from_id(self, key_id: str) -> int | None:
        try:
            return self.key_fingerprints.index(str(key_id))
        except ValueError:
            return None

    def _ensure_shape_locked(self) -> None:
        current = _reset_period()
        if current != self._period:
            self._period = current
            self._usage = {}
            self._errors = {}
        for idx in range(self.n_keys):
            key_id = self._key_id(idx)
            self._usage.setdefault(key_id, {})
            self._errors.setdefault(key_id, {})
            for model in self.models:
                self._usage[key_id].setdefault(
                    model,
                    _empty_model_usage(),
                )
                self._errors[key_id].setdefault(
                    model,
                    {"cooldown_until": 0.0, "last_error": "", "last_error_at": 0.0, "consecutive_errors": 0},
                )
            self._rpm_windows.setdefault(idx, deque())
            self._tpm_windows.setdefault(idx, deque())

    def _load(self) -> None:
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f) or {}
        except (OSError, json.JSONDecodeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        if payload.get("version") not in (2, STATE_VERSION):
            return
        self._period = str(payload.get("period") or self._period)
        usage = payload.get("usage", {})
        errors = payload.get("errors", {})
        if isinstance(usage, dict):
            self._usage = usage
        if isinstance(errors, dict):
            self._errors = errors

        now_wall = _now_wall()
        now_mono = _now_mono()
        rpm_windows = payload.get("rpm_windows", {})
        if isinstance(rpm_windows, dict):
            for key_id, values in rpm_windows.items():
                key_idx = self._key_idx_from_id(str(key_id))
                if key_idx is None:
                    continue
                dq: deque[float] = deque()
                for ts in values or []:
                    try:
                        age = max(0.0, now_wall - float(ts))
                    except (TypeError, ValueError):
                        continue
                    if age < 60.0:
                        dq.append(now_mono - age)
                self._rpm_windows[key_idx] = dq

        tpm_windows = payload.get("flash_lite_tpm_windows", {})
        if isinstance(tpm_windows, dict):
            for key_id, values in tpm_windows.items():
                key_idx = self._key_idx_from_id(str(key_id))
                if key_idx is None:
                    continue
                dq: deque[tuple[float, int]] = deque()
                for row in values or []:
                    if not isinstance(row, (list, tuple)) or len(row) != 2:
                        continue
                    try:
                        age = max(0.0, now_wall - float(row[0]))
                        tokens = max(1, int(row[1]))
                    except (TypeError, ValueError):
                        continue
                    if age < 60.0:
                        dq.append((now_mono - age, tokens))
                self._tpm_windows[key_idx] = dq

    def _wall_windows_locked(self) -> tuple[dict[str, list[float]], dict[str, list[list[int | float]]]]:
        now_wall = _now_wall()
        now_mono = _now_mono()
        rpm_out: dict[str, list[float]] = {}
        tpm_out: dict[str, list[list[int | float]]] = {}
        for idx in range(self.n_keys):
            self._prune_windows_locked(idx)
            key_id = self._key_id(idx)
            rpm_out[key_id] = [
                now_wall - max(0.0, now_mono - ts)
                for ts in self._rpm_windows.get(idx, ())
            ]
            tpm_out[key_id] = [
                [now_wall - max(0.0, now_mono - ts), int(tokens)]
                for ts, tokens in self._tpm_windows.get(idx, ())
            ]
        return rpm_out, tpm_out

    def _save_locked(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
        rpm_windows, tpm_windows = self._wall_windows_locked()
        payload = {
            "version": STATE_VERSION,
            "period": self._period,
            "reset_hour_ist": RESET_HOUR,
            "reset_minute_ist": RESET_MINUTE,
            "key_fingerprints": self.key_fingerprints,
            "models": self.models,
            "rpm_limit_per_key": self.rpm_limit,
            "flash_lite_tpm_limit_per_key": self.flash_lite_tpm_limit,
            "usage": self._usage,
            "errors": self._errors,
            "rpm_windows": rpm_windows,
            "flash_lite_tpm_windows": tpm_windows,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp_path = self.state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, self.state_path)

    def _prune_windows_locked(self, key_idx: int) -> None:
        now = _now_mono()
        rpm = self._rpm_windows.setdefault(int(key_idx), deque())
        while rpm and rpm[0] <= now - 60.0:
            rpm.popleft()
        tpm = self._tpm_windows.setdefault(int(key_idx), deque())
        while tpm and tpm[0][0] <= now - 60.0:
            tpm.popleft()

    def seconds_until_request_slot(self, key_idx: int, model: str, estimated_tokens: int = 0) -> float:
        with self._lock:
            self._ensure_shape_locked()
            self._prune_windows_locked(key_idx)
            now = _now_mono()
            waits = []
            rpm = self._rpm_windows.setdefault(int(key_idx), deque())
            if len(rpm) >= self.rpm_limit:
                waits.append(max(0.0, rpm[0] - (now - 60.0)))
            if _is_flash_lite(model):
                tpm = self._tpm_windows.setdefault(int(key_idx), deque())
                used = sum(tokens for _, tokens in tpm)
                need = max(1, min(int(estimated_tokens or 1), self.flash_lite_tpm_limit))
                if used + need > self.flash_lite_tpm_limit and tpm:
                    waits.append(max(0.0, tpm[0][0] - (now - 60.0)))
            return max(waits) if waits else 0.0

    def reserve_request(self, key_idx: int, model: str, estimated_tokens: int = 0) -> None:
        with self._lock:
            self._ensure_shape_locked()
            self._prune_windows_locked(key_idx)
            now = _now_mono()
            self._rpm_windows.setdefault(int(key_idx), deque()).append(now)
            if _is_flash_lite(model):
                tokens = max(1, min(int(estimated_tokens or 1), self.flash_lite_tpm_limit))
                self._tpm_windows.setdefault(int(key_idx), deque()).append((now, tokens))
            self._save_locked()

    def wait_for_rpm_slot(self, key_idx: int, model: str = "", estimated_tokens: int = 0) -> None:
        while True:
            wait = self.seconds_until_request_slot(key_idx, model, estimated_tokens)
            if wait <= 0:
                self.reserve_request(key_idx, model, estimated_tokens)
                return
            time.sleep(min(wait + 0.05, 60.0))

    def has_daily_quota(self, key_idx: int, model: str) -> bool:
        with self._lock:
            self._ensure_shape_locked()
            key_id = self._key_id(key_idx)
            usage = self._usage.get(key_id, {}).get(_model_key(model), {})
            return int(usage.get("requests", 0)) < _daily_limit_for_model(model)

    def any_key_has_quota(self, model: str) -> bool:
        with self._lock:
            self._ensure_shape_locked()
            return any(self.has_daily_quota(idx, model) for idx in range(self.n_keys))

    def key_available(self, key_idx: int, model: str) -> bool:
        with self._lock:
            self._ensure_shape_locked()
            err = self._errors.get(self._key_id(key_idx), {}).get(_model_key(model), {})
            return float(err.get("cooldown_until", 0.0) or 0.0) <= _now_wall()

    def record_request(
        self,
        key_idx: int,
        model: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        reached_provider: bool = True,
    ) -> None:
        if not reached_provider:
            return
        with self._lock:
            self._ensure_shape_locked()
            model = _model_key(model)
            key_id = self._key_id(key_idx)
            bucket = self._usage[key_id].setdefault(
                model,
                {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
            pt = max(0, int(prompt_tokens or 0))
            ct = max(0, int(completion_tokens or 0))
            actual_total = pt + ct
            bucket["requests"] = int(bucket.get("requests", 0)) + 1
            bucket["prompt_tokens"] = int(bucket.get("prompt_tokens", 0)) + pt
            bucket["completion_tokens"] = int(bucket.get("completion_tokens", 0)) + ct
            bucket["total_tokens"] = int(bucket.get("total_tokens", 0)) + actual_total
            if actual_total > 0 and _is_flash_lite(model):
                tpm = self._tpm_windows.setdefault(int(key_idx), deque())
                if tpm:
                    ts, _reserved_tokens = tpm[-1]
                    tpm[-1] = (ts, max(1, min(actual_total, self.flash_lite_tpm_limit)))
            self.run_total_requests += 1
            err = self._errors[key_id].setdefault(model, {})
            err["consecutive_errors"] = 0
            err["cooldown_until"] = 0.0
            self._save_locked()

    def record_error(self, key_idx: int, model: str, error: Exception | str) -> None:
        err_text = str(error or "")
        lower = err_text.lower()
        quotaish = any(
            marker in lower
            for marker in (
                "quota",
                "rate",
                "429",
                "resource_exhausted",
                "exceeded",
                "too many requests",
            )
        )
        with self._lock:
            self._ensure_shape_locked()
            key_id = self._key_id(key_idx)
            model = _model_key(model)
            bucket = self._errors[key_id].setdefault(model, {})
            consecutive = int(bucket.get("consecutive_errors", 0) or 0) + 1
            bucket["consecutive_errors"] = consecutive
            bucket["last_error"] = err_text[:500]
            bucket["last_error_at"] = _now_wall()
            if quotaish:
                cooldown = min(300.0, 15.0 * (2 ** min(consecutive - 1, 4)))
                bucket["cooldown_until"] = _now_wall() + cooldown
            self._save_locked()

    def reset_all_daily(self) -> None:
        with self._lock:
            self._period = _reset_period()
            self._usage = {}
            self._errors = {}
            self._ensure_shape_locked()
            self._save_locked()

    def wait_until_quota_reset(self) -> None:
        wait = max(0.0, _next_reset_epoch() - _now_wall())
        raise RuntimeError(
            "Local quota ledger shows no remaining daily requests. "
            f"Next reset is in {wait / 3600.0:.1f}h, but the runner should rotate "
            "to another key/model before waiting."
        )

    def status_line(self) -> str:
        with self._lock:
            self._ensure_shape_locked()
            parts = []
            for model in self.models:
                used = 0
                limit = 0
                for idx in range(self.n_keys):
                    key_id = self._key_id(idx)
                    used += int(self._usage.get(key_id, {}).get(model, {}).get("requests", 0))
                    limit += _daily_limit_for_model(model)
                parts.append(f"{model.split('/')[-1]}: {used}/{limit}")
            return f"Requests this run: {self.run_total_requests} | " + " | ".join(parts)

    def debug_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_shape_locked()
            return {
                "period": self._period,
                "models": list(self.models),
                "run_total_requests": self.run_total_requests,
                "usage": json.loads(json.dumps(self._usage)),
                "errors": json.loads(json.dumps(self._errors)),
            }

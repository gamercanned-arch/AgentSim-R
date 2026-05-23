"""
Rate-limit and daily-quota management for Google AI Studio API keys.

Tracks per-key, per-model request counts with:
- Sliding-window RPM enforcement (15 req/min)
- Daily limit enforcement (model-specific)
- Auto-pause + auto-resume at 1:30 PM IST when daily quota exhausted
- Per-run request counter for observability
"""

import time
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple, Optional

IST = timezone(timedelta(hours=5, minutes=30))
RESET_HOUR, RESET_MINUTE = 13, 30  # 1:30 PM IST

# Model-specific daily limits (per key)
MODEL_DAILY_LIMITS = {
    "gemma-4-31b-it":              1500,
    "gemma-4-26b-it":              1500,
    "gemma-4-26b-a4b-it":          1500,   # alias
    "gemini-3.1-flash-lite":       500,
    "gemini-3.1-flash-lite-preview": 500,  # alias
}
DEFAULT_DAILY_LIMIT = 500  # conservative fallback for unknown models
DEFAULT_RPM = 15


class _KeyModelCounter:
    """Tracks requests for one (key_index, model) pair."""
    def __init__(self, daily_limit: int, rpm_limit: int):
        self.daily_limit = daily_limit
        self.rpm_limit = rpm_limit
        self.daily_count = 0
        self.minute_window: deque[float] = deque()  # timestamps of recent requests

    def has_daily_quota(self) -> bool:
        return self.daily_count < self.daily_limit

    def seconds_until_rpm_slot(self) -> float:
        """Returns 0.0 if a slot is available, else seconds to wait."""
        now = time.monotonic()
        # Purge entries older than 60s
        while self.minute_window and self.minute_window[0] <= now - 60.0:
            self.minute_window.popleft()
        if len(self.minute_window) < self.rpm_limit:
            return 0.0
        # Must wait until the oldest entry expires
        return max(0.0, self.minute_window[0] - (now - 60.0))

    def record(self):
        self.daily_count += 1

    def reserve_rpm_slot(self):
        self.minute_window.append(time.monotonic())

    def reset_daily(self):
        self.daily_count = 0


class QuotaManager:
    def __init__(self, n_keys: int, models: list[str]):
        self.n_keys = n_keys
        self.models = list(models)
        self.run_total_requests = 0
        self.run_start_time = time.time()
        self._counters: Dict[Tuple[int, str], _KeyModelCounter] = {}
        self._paused = False
        self._lock = threading.RLock()
        self._reset_period = self._current_reset_period()

        for ki in range(n_keys):
            for model in models:
                daily = MODEL_DAILY_LIMITS.get(model, DEFAULT_DAILY_LIMIT)
                self._counters[(ki, model)] = _KeyModelCounter(daily, DEFAULT_RPM)

    def _current_reset_period(self) -> str:
        now_ist = datetime.now(IST)
        reset_today = now_ist.replace(
            hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0
        )
        if now_ist < reset_today:
            now_ist = now_ist - timedelta(days=1)
        return now_ist.date().isoformat()

    def _reset_if_new_period_locked(self) -> None:
        period = self._current_reset_period()
        if period != self._reset_period:
            for counter in self._counters.values():
                counter.reset_daily()
            self._reset_period = period
            print("[QUOTA] Daily counters reset for new quota period.")

    def _get_counter(self, key_idx: int, model: str) -> _KeyModelCounter:
        key = (key_idx, model)
        if key not in self._counters:
            daily = MODEL_DAILY_LIMITS.get(model, DEFAULT_DAILY_LIMIT)
            self._counters[key] = _KeyModelCounter(daily, DEFAULT_RPM)
        return self._counters[key]

    def wait_for_rpm_slot(self, key_idx: int, model: str):
        """Block until an RPM slot is available for this key+model."""
        while True:
            with self._lock:
                self._reset_if_new_period_locked()
                counter = self._get_counter(key_idx, model)
                wait = counter.seconds_until_rpm_slot()
                if wait <= 0:
                    counter.reserve_rpm_slot()
                    break
            print(f"    [QUOTA] RPM limit for key {key_idx+1}, waiting {wait:.1f}s")
            time.sleep(wait + 0.1)  # small buffer

    def has_daily_quota(self, key_idx: int, model: str) -> bool:
        with self._lock:
            self._reset_if_new_period_locked()
            return self._get_counter(key_idx, model).has_daily_quota()

    def any_key_has_quota(self, model: str) -> bool:
        """Check if ANY key still has daily quota for this model."""
        with self._lock:
            self._reset_if_new_period_locked()
            return any(
                self._get_counter(ki, model).has_daily_quota()
                for ki in range(self.n_keys)
            )

    def any_model_has_quota(self) -> bool:
        """Check if ANY key+model combination has daily quota remaining."""
        with self._lock:
            self._reset_if_new_period_locked()
            return any(counter.has_daily_quota() for counter in self._counters.values())

    def record_request(self, key_idx: int, model: str):
        with self._lock:
            self._reset_if_new_period_locked()
            self._get_counter(key_idx, model).record()
            self.run_total_requests += 1

    def reset_all_daily(self):
        with self._lock:
            period = self._current_reset_period()
            if self._reset_period != period:
                for counter in self._counters.values():
                    counter.reset_daily()
                self._reset_period = period
                print("[QUOTA] All daily counters reset.")

    def wait_until_quota_reset(self):
        """Sleep until next 1:30 PM IST, then reset all daily counters."""
        now_ist = datetime.now(IST)
        reset_today = now_ist.replace(
            hour=RESET_HOUR, minute=RESET_MINUTE, second=0, microsecond=0
        )
        if now_ist >= reset_today:
            # Already past 1:30 PM today, wait until tomorrow 1:30 PM
            reset_target = reset_today + timedelta(days=1)
        else:
            reset_target = reset_today

        wait_seconds = (reset_target - now_ist).total_seconds()
        hrs = int(wait_seconds // 3600)
        mins = int((wait_seconds % 3600) // 60)

        print(f"\n[QUOTA] ⏸  ALL daily quotas exhausted.")
        print(f"[QUOTA] Pausing until {reset_target.strftime('%Y-%m-%d %H:%M IST')} ({hrs}h {mins}m)")
        print(f"[QUOTA] Requests this run: {self.run_total_requests}")

        self._paused = True
        time.sleep(wait_seconds)
        self._paused = False
        self.reset_all_daily()
        print(f"[QUOTA] ▶  Resumed! Daily quotas reset at {datetime.now(IST).strftime('%H:%M IST')}")

    def status_line(self) -> str:
        """One-line status for periodic printing."""
        parts = []
        with self._lock:
            self._reset_if_new_period_locked()
            for model in self.models:
                total_used = sum(self._get_counter(ki, model).daily_count for ki in range(self.n_keys))
                total_limit = sum(self._get_counter(ki, model).daily_limit for ki in range(self.n_keys))
                parts.append(f"{model.split('/')[-1]}: {total_used}/{total_limit}")
            return f"Requests: {self.run_total_requests} total | " + " | ".join(parts)

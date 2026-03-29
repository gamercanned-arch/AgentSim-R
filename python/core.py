from __future__ import annotations

from dataclasses import dataclass

from config import (
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
)

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class TimeParts:
    day_number: int
    weekday_idx: int
    hour: int
    minute: int


def get_time_parts(sim_time: float) -> TimeParts:
    total_minutes = int(sim_time // 60)
    total_days = total_minutes // 1440
    day_number = total_days + 1
    weekday_idx = total_days % 7
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    return TimeParts(day_number=day_number, weekday_idx=weekday_idx, hour=hour, minute=minute)


def get_clock(sim_time: float) -> str:
    p = get_time_parts(sim_time)
    return f"{p.hour:02d}:{p.minute:02d}"


def get_time_string(sim_time: float, include_weekday: bool = True) -> str:
    p = get_time_parts(sim_time)
    if include_weekday:
        return f"Day {p.day_number} ({WEEKDAY_NAMES[p.weekday_idx]}), {p.hour:02d}:{p.minute:02d}"
    return f"Day {p.day_number}, {p.hour:02d}:{p.minute:02d}"


def is_market_open(sim_time: float) -> bool:
    p = get_time_parts(sim_time)
    if p.weekday_idx >= 5:
        return False
    current_minutes = p.hour * 60 + p.minute
    open_minutes = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MINUTE
    close_minutes = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MINUTE
    return open_minutes <= current_minutes < close_minutes
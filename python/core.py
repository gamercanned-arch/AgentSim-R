from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from python.config import (
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
)

WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
SIM_START_DATE = date(2026, 3, 30)


@dataclass(frozen=True)
class TimeParts:
    day_number: int
    weekday_idx: int
    year: int
    month: int
    day: int
    hour: int
    minute: int


def get_time_parts(sim_time: float) -> TimeParts:
    total_minutes = int(sim_time // 60)
    total_days = total_minutes // 1440
    day_number = total_days + 1
    current_date = SIM_START_DATE + timedelta(days=total_days)
    weekday_idx = current_date.weekday()
    hour = (total_minutes // 60) % 24
    minute = total_minutes % 60
    return TimeParts(
        day_number=day_number,
        weekday_idx=weekday_idx,
        year=current_date.year,
        month=current_date.month,
        day=current_date.day,
        hour=hour,
        minute=minute,
    )


def get_clock(sim_time: float) -> str:
    p = get_time_parts(sim_time)
    return f"{p.hour:02d}:{p.minute:02d}"


def get_time_string(sim_time: float, include_weekday: bool = True) -> str:
    p = get_time_parts(sim_time)
    if include_weekday:
        return f"{WEEKDAY_NAMES[p.weekday_idx]}, {p.day:02d} {MONTH_NAMES[p.month-1]} {p.year:04d} {p.hour:02d}:{p.minute:02d}"
    return f"{p.day:02d} {MONTH_NAMES[p.month-1]} {p.year:04d} {p.hour:02d}:{p.minute:02d}"


def is_market_open(sim_time: float) -> bool:
    p = get_time_parts(sim_time)
    if p.weekday_idx >= 5:
        return False
    current_minutes = p.hour * 60 + p.minute
    open_minutes = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MINUTE
    close_minutes = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MINUTE
    return open_minutes <= current_minutes < close_minutes


def next_market_open_time(sim_time: float) -> float:
    """
    Returns the sim_time (seconds) of the next market open (Mon–Fri, 09:30).
    If currently before open on a weekday, returns today's open.
    If currently after close (or weekend), returns next weekday's open.
    """
    p = get_time_parts(sim_time)

    day_start = float(int(sim_time // 86400) * 86400)
    current_minutes = p.hour * 60 + p.minute
    open_minutes = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MINUTE
    close_minutes = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MINUTE

    def _open_time_for_day(offset_days: int) -> float:
        return day_start + float(offset_days * 86400 + open_minutes * 60)

    # Weekday (Mon=0..Fri=4)
    if p.weekday_idx < 5:
        if current_minutes < open_minutes:
            return _open_time_for_day(0)
        if current_minutes >= close_minutes:
            # next weekday open
            off = 1
            wd = p.weekday_idx
            while (wd + off) % 7 >= 5:
                off += 1
            return _open_time_for_day(off)
        # during open hours, "next open" is now
        return float(sim_time)

    # Weekend: advance to next Monday
    off = 1
    while (p.weekday_idx + off) % 7 >= 5:
        off += 1
    return _open_time_for_day(off)
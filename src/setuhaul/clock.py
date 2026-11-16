"""A simulated clock.

The dataset is a snapshot of 4 August 2026 (Asia/Kolkata). The system that
reads it must never use the real wall clock for business decisions -- the
database's "now" is whatever point in that day the scenario has reached.
Every hold expiry, timeout and "latest acceptable" check in this project
goes through this clock so the whole system stays replayable and testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%M:%S+05:30"


class SimClock:
    """A settable, advanceable clock. No dependency on the real OS clock."""

    def __init__(self, start_ts: str):
        self._now = datetime.strptime(start_ts, FMT)

    def now(self) -> datetime:
        return self._now

    def now_ts(self) -> str:
        return self._now.strftime(FMT)

    def set(self, ts: str) -> None:
        self._now = datetime.strptime(ts, FMT)

    def advance(self, minutes: int) -> None:
        self._now = self._now + timedelta(minutes=minutes)

    @staticmethod
    def parse(ts: str) -> datetime:
        return datetime.strptime(ts, FMT)

    @staticmethod
    def format(dt: datetime) -> str:
        return dt.strftime(FMT)

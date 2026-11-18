"""Reporting periods shared by analytics views: 1d (last 24 hours), 3d, 7d, 3w, 1m (whole IST days ending now), custom.
All bucketing is done in the display timezone (Asia/Kolkata); storage stays UTC."""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.errors import ValidationAppError

TZ = ZoneInfo("Asia/Kolkata")
RANGES = {"1d": 1, "3d": 3, "7d": 7, "3w": 21, "1m": 30}
MAX_CUSTOM_DAYS = 120


@dataclass(frozen=True)
class Period:
    key: str
    start: datetime
    end: datetime

    @property
    def span(self) -> timedelta:
        return self.end - self.start

    @property
    def bucket(self) -> str:
        return "hour" if self.span <= timedelta(days=3, hours=1) else "day"

    @property
    def previous(self) -> "Period":
        return Period(self.key, self.start - self.span, self.start)

    def labels(self) -> list[str]:
        """Every bucket label in the period (empty buckets included), matching to_char in the SQL."""
        hourly = self.bucket == "hour"
        cur = self.start.astimezone(TZ).replace(minute=0, second=0, microsecond=0)
        if not hourly:
            cur = cur.replace(hour=0)
        last, step, out = self.end.astimezone(TZ), (timedelta(hours=1) if hourly else timedelta(days=1)), []
        while cur <= last and len(out) < 800:
            out.append(cur.strftime("%Y-%m-%d %H:00" if hourly else "%Y-%m-%d"))
            cur += step
        return out


def resolve(range_: str, date_from: datetime | None, date_to: datetime | None, now: datetime | None = None) -> Period:
    now = now or datetime.now(UTC)
    if range_ == "custom":
        if date_from is None:
            raise ValidationAppError("A custom range needs date_from")
        end = date_to or now + timedelta(minutes=1)
        if end <= date_from or (end - date_from).days > MAX_CUSTOM_DAYS:
            raise ValidationAppError(f"A custom range must be 1-{MAX_CUSTOM_DAYS} days")
        return Period("custom", date_from, end)
    if range_ not in RANGES:
        raise ValidationAppError("range must be one of " + ", ".join([*RANGES, "custom"]))
    if range_ == "1d":
        return Period(range_, now - timedelta(days=1), now + timedelta(minutes=1))
    local = now.astimezone(TZ)
    start = (local - timedelta(days=RANGES[range_] - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return Period(range_, start.astimezone(UTC), now + timedelta(minutes=1))

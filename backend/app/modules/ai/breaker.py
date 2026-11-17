"""Circuit breaker per provider and per key, state in Redis so every API instance agrees.

closed -> (threshold failures inside the window) -> open for `cooldown` seconds -> half-open: exactly one probe request is
let through; success closes the breaker, failure re-opens it. `now` is injectable so tests control time."""
import time
from dataclasses import dataclass

from redis.asyncio import Redis

DEFAULTS = {"threshold": 5, "window_seconds": 60, "cooldown_seconds": 30}


@dataclass
class BreakerConfig:
    threshold: int = 5
    window_seconds: int = 60
    cooldown_seconds: int = 30

    @classmethod
    def from_setting(cls, value) -> "BreakerConfig":
        v = {**DEFAULTS, **(value if isinstance(value, dict) else {})}
        return cls(int(v["threshold"]), int(v["window_seconds"]), int(v["cooldown_seconds"]))


def _k(scope: str, id_: str, what: str) -> str:
    return f"cb:{scope}:{id_}:{what}"


async def state(redis: Redis, scope: str, id_: str, cfg: BreakerConfig, now: float | None = None) -> str:
    """'closed' | 'open' | 'half_open' (a probe may be taken)."""
    now = now if now is not None else time.time()
    until = await redis.get(_k(scope, id_, "open_until"))
    if until is None:
        return "closed"
    return "open" if now < float(until) else "half_open"


async def allow(redis: Redis, scope: str, id_: str, cfg: BreakerConfig, now: float | None = None) -> bool:
    """True when a request may be sent. In half-open exactly one caller wins the probe."""
    s = await state(redis, scope, id_, cfg, now)
    if s == "closed":
        return True
    if s == "open":
        return False
    return bool(await redis.set(_k(scope, id_, "probe"), "1", nx=True, ex=max(5, cfg.cooldown_seconds)))


async def success(redis: Redis, scope: str, id_: str) -> None:
    await redis.delete(_k(scope, id_, "fails"), _k(scope, id_, "open_until"), _k(scope, id_, "probe"))


async def failure(redis: Redis, scope: str, id_: str, cfg: BreakerConfig, now: float | None = None) -> bool:
    """Records a failure; returns True when this failure opened (or re-opened) the breaker."""
    now = now if now is not None else time.time()
    probing = await redis.get(_k(scope, id_, "probe")) is not None
    n = await redis.incr(_k(scope, id_, "fails"))
    if n == 1:
        await redis.expire(_k(scope, id_, "fails"), cfg.window_seconds)
    if probing or n >= cfg.threshold:
        await redis.set(_k(scope, id_, "open_until"), str(now + cfg.cooldown_seconds), ex=cfg.cooldown_seconds * 20 + 60)
        await redis.delete(_k(scope, id_, "probe"), _k(scope, id_, "fails"))
        return True
    return False

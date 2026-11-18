"""Generate 30 days of realistic AI usage history (demo only) so the monitoring dashboard, budgets and logs have something to show.
Rows are tagged with request ids starting `demo-` and can be removed with --clear. Usage: python -m scripts.seed_ai_usage_demo [--clear]"""
import asyncio
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.db import async_session_factory
from app.modules.ai.models import AIModel, AIProvider, AIUsageLog

# task -> (share of traffic, mean tokens in, mean tokens out)
MIX = {"intent_classify": (0.62, 260, 70), "summarise": (0.13, 900, 160), "translate": (0.10, 220, 200),
       "coordinator_suggestion": (0.08, 520, 140), "driver_insight": (0.04, 1400, 260), "dock_insight": (0.03, 1300, 240)}
ERRORS = ["timeout", "rate_limit", "server_error"]


async def main(clear: bool) -> None:
    async with async_session_factory() as db:
        await db.execute(delete(AIUsageLog).where(AIUsageLog.request_id.like("demo-%")))
        if clear:
            await db.commit()
            print("demo usage removed")
            return
        prim = (await db.execute(select(AIModel, AIProvider).join(AIProvider, AIProvider.id == AIModel.provider_id).where(AIModel.model_name == "mock-primary", AIProvider.name == "Offline mock (demo)"))).first()
        fast = (await db.execute(select(AIModel, AIProvider).join(AIProvider, AIProvider.id == AIModel.provider_id).where(AIModel.model_name == "mock-fast", AIProvider.name == "Offline mock backup (demo)"))).first()
        if prim is None or fast is None:
            raise SystemExit("Run scripts.seed_ai_demo first")
        rnd = random.Random(7)
        now = datetime.now(UTC)
        tasks, weights = list(MIX), [MIX[t][0] for t in MIX]
        rows = 0
        for d in range(30, -1, -1):
            day = (now - timedelta(days=d)).replace(hour=0, minute=0, second=0, microsecond=0)
            volume = int(rnd.gauss(110, 25) * (0.55 if day.weekday() >= 5 else 1) * (0.6 + 0.4 * (30 - d) / 30))  # a growing, weekday-heavy pattern
            for _ in range(max(volume, 5)):
                ts = day + timedelta(minutes=int(rnd.triangular(330, 1320, 600)), seconds=rnd.randint(0, 59))
                if ts > now:
                    continue
                task = rnd.choices(tasks, weights)[0]
                _, mi, mo = MIX[task]
                tin, tout = max(20, int(rnd.gauss(mi, mi * 0.2))), max(5, int(rnd.gauss(mo, mo * 0.3)))
                roll, path, status, depth, err = rnd.random(), [], "ok", 0, None
                a_ms = max(120, int(rnd.lognormvariate(6.1, 0.35)))
                if roll < 0.035:  # primary fails, the fallback answers
                    err = rnd.choice(ERRORS)
                    f_ms = int(rnd.uniform(800, 4000)) if err == "timeout" else int(rnd.uniform(60, 400))
                    b_ms = max(90, int(a_ms * 0.7))
                    path = [{"step": 1, "provider": prim[1].name, "model": "mock-primary", "outcome": f"error:{err}", "ms": f_ms},
                            {"step": 2, "provider": fast[1].name, "model": "mock-fast", "outcome": "ok", "ms": b_ms}]
                    m, p_, depth, latency = fast[0], fast[1], 1, f_ms + b_ms
                elif roll < 0.045:  # everything fails
                    status, depth, err = "failed", 1, "ALL_STEPS_FAILED"
                    path = [{"step": 1, "provider": prim[1].name, "model": "mock-primary", "outcome": "error:server_error", "ms": 210},
                            {"step": 2, "provider": fast[1].name, "model": "mock-fast", "outcome": "error:timeout", "ms": 3000}]
                    m, p_, latency, tin, tout = None, None, 3210, 0, 0
                else:
                    m, p_ = prim
                    latency = a_ms
                    path = [{"step": 1, "provider": p_.name, "model": m.model_name, "outcome": "ok", "ms": latency}]
                cost = (Decimal(m.input_price) * tin + Decimal(m.output_price) * tout) / Decimal(1_000_000) if m else Decimal(0)
                db.add(AIUsageLog(id=uuid.uuid4(), request_id=f"demo-{uuid.uuid4().hex[:15]}", task=task, provider=p_.name if p_ else None,
                                  model=m.model_name if m else None, tokens_in=tin, tokens_out=tout, cost=cost.quantize(Decimal("0.000001")),
                                  latency_ms=latency, status=status, fallback_depth=depth, error_code=err, trace_id=uuid.uuid4().hex, path=path, created_at=ts))
                rows += 1
        await db.commit()
    print(f"{rows} demo usage rows created over 31 days")


if __name__ == "__main__":
    asyncio.run(main("--clear" in sys.argv))

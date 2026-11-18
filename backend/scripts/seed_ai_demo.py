"""Enable an offline mock AI provider and wire demo routes, so the simulator, evaluations and the fallback demo work
without any account or key. Idempotent. Never stores a real key. Usage: python -m scripts.seed_ai_demo"""
import asyncio

from sqlalchemy import delete, select

from app.core import audit_events
from app.core.db import async_session_factory
from app.modules.ai.models import AIModel, AIProvider, AIRoute, AIRouteStep

NAME = "Offline mock (demo)"
BACKUP = "Offline mock backup (demo)"  # a second provider, so a failure of the first shows real fallback
MODELS = ["mock-primary", "mock-weak", "mock-timeout", "mock-429", "mock-500", "mock-badjson", "mock-auth"]
TASKS = ["intent_classify", "driver_chat", "translate", "summarise", "coordinator_suggestion", "driver_insight", "dock_insight"]


async def main() -> None:
    audit_events.install()
    async with async_session_factory() as db:
        prov = (await db.execute(select(AIProvider).where(AIProvider.name == NAME))).scalar_one_or_none()
        if prov is None:
            prov = AIProvider(name=NAME, kind="mock", status="enabled", allow_pii=True, notes="Deterministic offline provider for demos and tests")
            db.add(prov)
            await db.flush()
        prov.status = "enabled"
        have = {m.model_name: m for m in (await db.execute(select(AIModel).where(AIModel.provider_id == prov.id))).scalars().all()}
        for name in MODELS:
            if name not in have:
                m = AIModel(provider_id=prov.id, model_name=name, capabilities=["chat", "json", "multilingual"], status="active")
                db.add(m)
                have[name] = m
        await db.flush()
        backup = (await db.execute(select(AIProvider).where(AIProvider.name == BACKUP))).scalar_one_or_none()
        if backup is None:
            backup = AIProvider(name=BACKUP, kind="mock", status="enabled", allow_pii=True, notes="Second offline provider used as the fallback step")
            db.add(backup)
            await db.flush()
        backup.status = "enabled"
        fast = (await db.execute(select(AIModel).where(AIModel.provider_id == backup.id, AIModel.model_name == "mock-fast"))).scalar_one_or_none()
        if fast is None:
            fast = AIModel(provider_id=backup.id, model_name="mock-fast", capabilities=["chat", "json", "multilingual"], status="active")
            db.add(fast)
            await db.flush()
        have["mock-fast"] = fast
        for task in TASKS:
            route = (await db.execute(select(AIRoute).where(AIRoute.task == task))).scalar_one_or_none()
            if route is None:
                route = AIRoute(task=task, enabled=True, fallback_on_refusal=True)
                db.add(route)
                await db.flush()
            await db.execute(delete(AIRouteStep).where(AIRouteStep.route_id == route.id))
            await db.flush()
            for prio, name in enumerate(("mock-primary", "mock-fast"), start=1):
                db.add(AIRouteStep(route_id=route.id, priority=prio, model_id=have[name].id, key_ids=[], key_strategy="single",
                                   timeout_ms=15000, max_retries=1, temperature=0.1, max_tokens=600, conditions={}))
        # demo list prices (USD per 1M tokens) so cost, budgets and monitoring show real numbers; real models carry their own prices
        for name, (pin, pout) in {"mock-primary": (3, 15), "mock-fast": (0.25, 1.25)}.items():
            if not have[name].input_price and not have[name].output_price:
                have[name].input_price, have[name].output_price = pin, pout
        await db.commit()
    print("AI demo routes ready (provider A mock-primary -> provider B mock-fast) for", ", ".join(TASKS))


if __name__ == "__main__":
    asyncio.run(main())

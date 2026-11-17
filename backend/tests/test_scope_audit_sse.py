import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import events
from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from tests.conftest import login


def codes(resp):
    return sorted(i["code"] for i in resp.json()["items"])


async def test_carrier_sees_only_own_rows(client, world):
    await login(client, "carrier_user")  # carrier A
    assert codes(await client.get("/api/v1/shipments")) == ["SHP-A"]
    assert codes(await client.get("/api/v1/drivers")) == ["DRV-A"]
    assert codes(await client.get("/api/v1/carriers")) == ["CAR-A"]


async def test_carrier_b_sees_only_b(client, world):
    await login(client, "carrier_b")
    assert codes(await client.get("/api/v1/shipments")) == ["SHP-B"]
    assert codes(await client.get("/api/v1/drivers")) == ["DRV-B"]


async def test_carrier_cannot_list_facilities(client, world):
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/facilities")).status_code == 403


async def test_planner_sees_only_own_facility(client, world):
    await login(client, "facility_planner")
    assert codes(await client.get("/api/v1/facilities")) == ["FAC-A"]
    assert codes(await client.get("/api/v1/shipments")) == ["SHP-A"]


async def test_coordinator_and_admin_see_everything(client, world):
    for who in ("coordinator", "admin"):
        client.cookies.clear()
        await login(client, who)
        assert codes(await client.get("/api/v1/shipments")) == ["SHP-A", "SHP-B"]
        assert codes(await client.get("/api/v1/facilities")) == ["FAC-A", "FAC-B"]


async def test_writes_are_audited_with_actor_and_secrets_masked(client, world):
    await login(client, "admin")
    r = await client.post("/api/v1/users", json={"email": "aud@test.io", "full_name": "Aud", "role": "coordinator"})
    assert r.status_code == 201
    audit = (await client.get("/api/v1/audit", params={"entity": "users", "action": "insert"})).json()
    row = next(i for i in audit["items"] if i["after"]["email"] == "aud@test.io")
    assert row["actor_type"] == "user" and row["actor_id"]
    assert "password_hash" not in str(row["after"]) or row["after"]["password_hash"] in (None, "***")


async def test_setting_change_records_before_and_after(client, world):
    await login(client, "admin")
    assert (await client.put("/api/v1/settings/hold_ttl_minutes", json={"value": 20})).status_code == 200
    rows = (await client.get("/api/v1/audit", params={"entity": "system_settings", "action": "update"})).json()["items"]
    assert rows[0]["before"]["value"] == 15 and rows[0]["after"]["value"] == 20


async def test_settings_forbidden_for_non_admin(client, world):
    await login(client, "coordinator")
    assert (await client.put("/api/v1/settings/hold_ttl_minutes", json={"value": 1})).status_code == 403
    assert (await client.get("/api/v1/settings")).status_code == 403


async def test_coordinator_audit_view_is_own_actions_only(client, world):
    await login(client, "admin")
    await client.put("/api/v1/settings/noshow_grace_minutes", json={"value": 45})
    client.cookies.clear()
    await login(client, "coordinator")
    items = (await client.get("/api/v1/audit")).json()["items"]
    assert all(i["actor_id"] != "admin" for i in items) and items == []
    client.cookies.clear()
    await login(client, "carrier_user")
    assert (await client.get("/api/v1/audit")).status_code == 403


async def test_audit_log_is_append_only(world):
    async with async_session_factory() as db:
        await db.execute(text("INSERT INTO audit_log (id, actor_type, action, entity, created_at) "
                              "VALUES (gen_random_uuid(), 'system', 'insert', 'x', now())"))
        await db.commit()
    for stmt in ("UPDATE audit_log SET entity = 'y'", "DELETE FROM audit_log"):
        async with async_session_factory() as db:
            with pytest.raises(Exception, match="append-only"):
                await db.execute(text(stmt))
                await db.commit()


def test_visibility_rules():
    fa, fb, ca, cb = uuid4(), uuid4(), uuid4(), uuid4()
    assert events.visible("admin", set(), None, str(fb), str(cb))
    assert events.visible("coordinator", set(), None, "", "")
    assert events.visible("facility_planner", {fa}, None, str(fa), "")
    assert not events.visible("facility_planner", {fa}, None, str(fb), "")
    assert not events.visible("facility_planner", {fa}, None, "", "")
    assert events.visible("carrier_user", set(), ca, "", str(ca))
    assert not events.visible("carrier_user", set(), ca, "", str(cb))
    assert not events.visible("carrier_user", set(), None, "", str(ca))
    assert not events.visible("nobody", {fa}, ca, str(fa), str(ca))


async def _collect(gen, n_events, timeout=3):
    out = []

    async def run():
        async for chunk in gen:
            if chunk.startswith("id:"):
                out.append(chunk)
                if len(out) >= n_events:
                    return

    try:
        await asyncio.wait_for(run(), timeout)
    except TimeoutError:
        pass
    return out


async def test_sse_stream_isolates_carriers(world):
    redis = get_redis()
    try:
        ca, cb = world.carrier_a.id, world.carrier_b.id
        # carrier A subscribes from "now", then both carriers' events are published
        gen = events.stream_for(redis, "carrier_user", set(), ca, last_id="0-0", block_ms=200)
        await events.publish("shipment.updated", {"who": "B"}, carrier_id=cb, redis=redis)
        await events.publish("shipment.updated", {"who": "A"}, carrier_id=ca, redis=redis)
        got = await _collect(gen, 2, timeout=2)
        assert len(got) == 1 and '"who": "A"' in got[0]
    finally:
        await redis.delete(events.STREAM)
        await redis.aclose()


async def test_sse_resumes_after_last_event_id(world):
    redis = get_redis()
    try:
        await redis.delete(events.STREAM)
        await events.publish("t", {"n": 1}, redis=redis)
        await events.publish("t", {"n": 2}, redis=redis)
        first = await _collect(events.stream_for(redis, "admin", set(), None, "0-0", 200), 1)
        last_id = first[0].split("\n")[0].removeprefix("id: ")
        rest = await _collect(events.stream_for(redis, "admin", set(), None, last_id, 200), 1, timeout=2)
        assert len(rest) == 1 and '"n": 2' in rest[0]
    finally:
        await redis.delete(events.STREAM)
        await redis.aclose()

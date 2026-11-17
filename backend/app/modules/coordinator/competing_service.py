"""Competing requests: open requests whose best option is the same slot. Ranked by the pure policy in
scheduling.ranking (fixed trucks first, priority, lost appointment, waiting, earliest start). A coordinator may
choose a different winner only with a written reason, which is stored on the request and in the audit log."""
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.appointments import service as appointments_service
from app.modules.appointments.models import ACTIVE_STATUSES, Appointment
from app.modules.booking import engine, readers
from app.modules.booking.models import ApprovalRequest, SlotHold
from app.modules.coordinator import locks, messaging
from app.modules.coordinator.inbox_schemas import DecideIn, DecideOut
from app.modules.scheduling import service as scheduling
from app.modules.scheduling.ranking import RankedRequest, RequestFacts, rank_requests
from app.modules.settings import service as settings_service
from app.modules.shipments import service as shipments_service

OPEN = ("waiting", "held", "suggested")


async def _target(db: AsyncSession, r: ApprovalRequest, now: datetime):
    """(slot_ids, start) this request is after: its active hold, else its best feasible option."""
    hold = await db.get(SlotHold, r.hold_id) if r.hold_id else None
    if hold is not None and hold.status == "active" and hold.expires_at > now:
        slots = await readers.slots_by_ids(db, hold.all_slot_ids)
        return hold.all_slot_ids, slots[hold.slot_id].slot_start_ts
    res = await scheduling.find_options(db, r.shipment_id, limit=1, now=now)
    if not res.options:
        return None
    o = res.options[0]
    return list(o.slot_ids), o.start


async def _facts(db: AsyncSession, r: ApprovalRequest, start: datetime, ship, now: datetime) -> RequestFacts:
    appt = (await appointments_service.current_for_shipments(db, [r.shipment_id])).get(r.shipment_id)
    has_current = appt is not None and appt.appointment_status in ACTIVE_STATUSES
    return RequestFacts(id=r.id, priority_code=ship.priority_code, option_start=start, is_unloading=ship.current_status == "IN_DOCK",
                        lost_appointment=(r.reason_code or "").startswith("REPLAN") or not has_current,
                        waiting_min=max(0, int((now - r.created_at).total_seconds() // 60)))


async def _weights(db: AsyncSession) -> dict:
    w = await settings_service.get_value(db, "ranking_weights", None)
    return w if isinstance(w, dict) else {}


async def groups(db: AsyncSession, facility_id: UUID | None, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    reqs = list((await db.execute(select(ApprovalRequest).where(ApprovalRequest.status.in_(OPEN)).order_by(ApprovalRequest.created_at)
                                  )).scalars().all())
    ships = await shipments_service.get_many(db, [r.shipment_id for r in reqs])
    targets: dict[UUID, tuple[list[UUID], datetime]] = {}
    for r in reqs:
        s = ships[r.shipment_id]
        if facility_id and s.destination_facility_id != facility_id:
            continue
        t = await _target(db, r, now)
        if t:
            targets[r.id] = t
    # union requests that share any slot
    parent: dict[UUID, UUID] = {rid: rid for rid in targets}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner_of_slot: dict[UUID, UUID] = {}
    for rid, (slot_ids, _) in targets.items():
        for sid in slot_ids:
            if sid in owner_of_slot:
                parent[find(rid)] = find(owner_of_slot[sid])
            else:
                owner_of_slot[sid] = rid
    buckets: dict[UUID, list[UUID]] = {}
    for rid in targets:
        buckets.setdefault(find(rid), []).append(rid)
    by_id = {r.id: r for r in reqs}
    weights = await _weights(db)
    out = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        facts = [await _facts(db, by_id[m], targets[m][1], ships[by_id[m].shipment_id], now) for m in members]
        ranked = rank_requests(facts, now=now, weights=weights)
        first_slot = targets[ranked[0].id][0][0]
        slot = (await readers.slots_by_ids(db, [first_slot]))[first_slot]
        dock = (await readers.docks_by_ids(db, [slot.dock_id]))[slot.dock_id]
        fac = (await readers.facilities_by_ids(db, [slot.facility_id]))[slot.facility_id]
        rows = []
        for rk in ranked:
            r = by_id[rk.id]
            f = next(x for x in facts if x.id == rk.id)
            rows.append({"request_id": r.id, "shipment_code": ships[r.shipment_id].code, "priority_code": ships[r.shipment_id].priority_code,
                         "rank": rk.rank, "score": rk.score, "fixed": rk.fixed, "tie_with_next": rk.tie_with_next, "reasons": rk.reasons,
                         "hold_id": r.hold_id, "waiting_min": f.waiting_min})
        out.append({"key": str(first_slot), "slot_id": slot.id, "slot_code": slot.code, "dock_code": dock.dock_code,
                    "start": slot.slot_start_ts, "facility_code": fac.code, "requests": rows})
    out.sort(key=lambda g: g["start"])
    return out


async def decide(db: AsyncSession, redis: Redis, body: DecideIn, user_id: UUID, now: datetime | None = None) -> DecideOut:
    now = now or datetime.now(UTC)
    ids = list(dict.fromkeys(body.group_request_ids))
    if body.winner_request_id not in ids:
        raise ValidationAppError("The winner must be one of the competing requests")
    reqs = {r.id: r for r in (await db.execute(select(ApprovalRequest).where(ApprovalRequest.id.in_(ids)))).scalars().all()}
    if len(reqs) != len(ids):
        raise NotFoundError("One or more requests were not found")
    for r in reqs.values():
        if r.status not in OPEN:
            raise ConflictError("REQUEST_CLOSED", f"Request for shipment {r.shipment_id} is already {r.status}")
        await locks.require_free(redis, "request", r.id, user_id)
    ships = await shipments_service.get_many(db, [r.shipment_id for r in reqs.values()])
    facts = []
    for r in reqs.values():
        t = await _target(db, r, now)
        if t is None:
            raise ConflictError("NO_OPTION", "A competing request no longer has a feasible slot; refresh and retry")
        facts.append(await _facts(db, r, t[1], ships[r.shipment_id], now))
    ranked: list[RankedRequest] = rank_requests(facts, now=now, weights=await _weights(db))
    policy_winner = ranked[0].id
    overrode = body.winner_request_id != policy_winner
    reason = (body.override_reason or "").strip()
    if overrode and len(reason) < 10:
        raise ValidationAppError("Choosing a different winner than the ranking policy needs a written reason (at least 10 characters)")
    winner = reqs[body.winner_request_id]
    hold = await db.get(SlotHold, winner.hold_id) if winner.hold_id else None
    if hold is None or hold.status != "active" or hold.expires_at <= now:
        target = await _target(db, winner, now)
        hold = await engine.place_hold(db, winner.shipment_id, target[0], exception_id=winner.exception_id, now=now)
        winner.hold_id, winner.slot_id = hold.id, hold.slot_id
    if overrode:
        winner.reason = f"OVERRIDE of ranking policy: {reason}"
    await db.flush()  # approve_request re-reads the row under lock: persist these changes first
    appt = await engine.approve_request(db, winner.id, user_id, now=now)
    await messaging.to_driver(db, winner.shipment_id, "appointment_confirmed", await messaging.slot_vars(db, appt.slot_id))
    return DecideOut(approved_appointment_id=appt.id, overrode_policy=overrode, policy_winner_request_id=policy_winner)


_ = Appointment

"""Booking-integrity proof over real HTTP against a running API and its PostgreSQL database.

It builds its own isolated facility (FAC-PROOF-<run id>) with a dock, slots and shipments, fires simultaneous
requests at the booking API from separate HTTP clients, queries PostgreSQL directly for the invariants, writes
docs/INTEGRITY_PROOF.md, then removes the data it created (use --keep to leave it).

    docker compose -f infra/docker-compose.yml up -d api
    MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml run --rm -v "$(pwd -W)/docs:/docs" api \
        python -m scripts.integrity_proof --base-url http://api:8000 --out /docs/INTEGRITY_PROOF.md

Uses the demo users from scripts.seed_demo_users (coordinator and planner)."""
import argparse
import asyncio
import json
import os
import platform
import time
import uuid
from collections import Counter
from datetime import UTC, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text

from app.core import audit_events
from app.core.db import async_session_factory
from app.core.model_registry import import_all_models
from app.modules.booking import engine
from app.modules.carriers.models import Carrier
from app.modules.docks.models import Dock
from app.modules.drivers.models import Driver
from app.modules.facilities.models import Facility
from app.modules.shipments.models import Shipment
from app.modules.slots.models import AppointmentSlot
from app.modules.vehicles.models import Vehicle, VehicleType

import_all_models()  # every table must be registered so foreign keys resolve
PASSWORD = os.environ.get("DEMO_PASSWORD", "SetuHaul-Demo-2026")
IST = ZoneInfo("Asia/Kolkata")
API = "/api/v1"


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.checks: list[tuple[str, bool]] = []

    def h(self, level: int, title: str) -> None:
        self.lines += ["", f"{'#' * level} {title}", ""]

    def p(self, text_: str = "") -> None:
        self.lines.append(text_)

    def table(self, header: list[str], rows: list[list]) -> None:
        self.lines.append("| " + " | ".join(header) + " |")
        self.lines.append("|" + "|".join(["---"] * len(header)) + "|")
        for r in rows:
            self.lines.append("| " + " | ".join(str(c) for c in r) + " |")
        self.lines.append("")

    def code(self, body: str, lang: str = "") -> None:
        self.lines += [f"```{lang}", body.rstrip(), "```", ""]

    def check(self, name: str, ok: bool) -> None:
        self.checks.append((name, ok))
        self.lines.append(f"- {'PASS' if ok else 'FAIL'}: {name}")


def err(r: httpx.Response) -> str | None:
    try:
        return r.json().get("error", {}).get("code")
    except Exception:
        return None


async def login(base: str, email: str) -> httpx.AsyncClient:
    c = httpx.AsyncClient(base_url=base, timeout=120)
    r = await c.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    r.raise_for_status()
    c.headers["X-CSRF-Token"] = c.cookies.get("csrf_token")
    return c


def clones(base: str, template: httpx.AsyncClient, n: int) -> list[httpx.AsyncClient]:
    return [httpx.AsyncClient(base_url=base, timeout=120, cookies=template.cookies,
                              headers={"X-CSRF-Token": template.headers["X-CSRF-Token"]}) for _ in range(n)]


async def close(cs: list[httpx.AsyncClient]) -> None:
    for c in cs:
        await c.aclose()


class World:
    """Isolated data for one proof run."""

    def __init__(self, run: str) -> None:
        self.run = run
        self.slots: dict[str, uuid.UUID] = {}
        self.shipment_ids: list[uuid.UUID] = []

    async def build(self) -> None:
        day = datetime.now(IST).date() + timedelta(days=9)
        eta = datetime.combine(day, dtime(6, 0), tzinfo=IST).astimezone(UTC)
        async with async_session_factory() as db:
            vt = (await db.execute(select(VehicleType).limit(1))).scalar_one()
            self.fac = Facility(code=f"FAC-PROOF-{self.run}", facility_name=f"Integrity proof {self.run}", city="Proofville",
                                state="PF", open_time=dtime(6, 0), close_time=dtime(22, 0))
            self.car = Carrier(code=f"CAR-PRF-{self.run}", carrier_name=f"Proof carrier {self.run}")
            db.add_all([self.fac, self.car])
            await db.flush()
            self.dock = Dock(code=f"{self.fac.code}-D1", facility_id=self.fac.id, dock_code="D1", dock_type="STANDARD",
                             max_vehicle_weight_kg=40000)
            db.add(self.dock)
            await db.flush()
            for hour in range(8, 21):
                start = datetime.combine(day, dtime(hour, 0), tzinfo=IST)
                s = AppointmentSlot(code=f"{self.dock.code}-{start:%y%m%d%H%M}", facility_id=self.fac.id, dock_id=self.dock.id,
                                    slot_start_ts=start.astimezone(UTC), slot_end_ts=(start + timedelta(hours=1)).astimezone(UTC))
                db.add(s)
                await db.flush()
                self.slots[f"{hour:02d}:00"] = s.id
            self.vt_id, self.eta = vt.id, eta
            await db.commit()
        self.n = 0

    async def shipments(self, count: int) -> list[uuid.UUID]:
        out = []
        async with async_session_factory() as db:
            for _ in range(count):
                self.n += 1
                n = self.n
                d = Driver(code=f"PD{self.run}{n}", carrier_id=self.car.id, driver_name=f"Proof driver {n}",
                           phone=f"+91770{self.run[-4:]}{n:03d}"[:15], licence_number=f"PL{self.run}{n}")
                db.add(d)
                await db.flush()
                v = Vehicle(code=f"PV{self.run}{n}", carrier_id=self.car.id, vehicle_type_id=self.vt_id,
                            registration_number=f"PR-{self.run}-{n}", capacity_kg=20000)
                db.add(v)
                await db.flush()
                s = Shipment(code=f"SHP-PRF-{self.run}-{n}", order_reference=f"PRF-{self.run}-{n}", carrier_id=self.car.id,
                             driver_id=d.id, vehicle_id=v.id, origin_name="Origin", origin_city="Delhi",
                             destination_facility_id=self.fac.id, customer_name="Proof", product_category="Goods",
                             load_weight_kg=5000, planned_departure_ts=self.eta - timedelta(hours=6), original_eta_ts=self.eta,
                             expected_unload_min=60, current_status="ASSIGNED", offer_status="accepted")
                db.add(s)
                await db.flush()
                out.append(s.id)
            await db.commit()
        self.shipment_ids += out
        return out

    async def cleanup(self) -> None:
        ids = [str(i) for i in self.shipment_ids]
        async with async_session_factory() as db:
            async def run(sql: str, **p):
                await db.execute(text(sql), p)

            fac = str(self.fac.id)
            await run("DELETE FROM outbox_events WHERE payload->>'shipment_id' = ANY(:ids)", ids=ids)
            await run("DELETE FROM approval_requests WHERE shipment_id = ANY(CAST(:ids AS uuid[]))", ids=ids)
            await run("DELETE FROM slot_claims WHERE slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = CAST(:f AS uuid))", f=fac)
            await run("DELETE FROM slot_holds WHERE shipment_id = ANY(CAST(:ids AS uuid[]))", ids=ids)
            await run("UPDATE appointments SET replaced_appointment_id = NULL WHERE shipment_id = ANY(CAST(:ids AS uuid[]))", ids=ids)
            await run("DELETE FROM appointments WHERE shipment_id = ANY(CAST(:ids AS uuid[]))", ids=ids)
            await run("DELETE FROM shipments WHERE id = ANY(CAST(:ids AS uuid[]))", ids=ids)
            await run("DELETE FROM vehicles WHERE carrier_id = CAST(:c AS uuid)", c=str(self.car.id))
            await run("DELETE FROM drivers WHERE carrier_id = CAST(:c AS uuid)", c=str(self.car.id))
            await run("DELETE FROM carriers WHERE id = CAST(:c AS uuid)", c=str(self.car.id))
            await run("DELETE FROM appointment_slots WHERE facility_id = CAST(:f AS uuid)", f=fac)
            await run("DELETE FROM docks WHERE facility_id = CAST(:f AS uuid)", f=fac)
            await run("DELETE FROM facilities WHERE id = CAST(:f AS uuid)", f=fac)
            await db.commit()


INVARIANTS = [
    ("No slot has more than one active claim",
     "SELECT slot_id, count(*) FROM slot_claims WHERE active AND slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) GROUP BY slot_id HAVING count(*) > 1"),
    ("No slot has more than one active appointment (PENDING_CONFIRMATION / CONFIRMED / IN_PROGRESS)",
     "SELECT slot_id, count(*) FROM appointments WHERE appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') AND slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) GROUP BY slot_id HAVING count(*) > 1"),
    ("No slot has more than one active hold",
     "SELECT slot_id, count(*) FROM slot_holds WHERE status = 'active' AND slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) GROUP BY slot_id HAVING count(*) > 1"),
    ("No shipment has more than one active hold",
     "SELECT shipment_id, count(*) FROM slot_holds WHERE status = 'active' AND slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) GROUP BY shipment_id HAVING count(*) > 1"),
    ("No shipment has more than one current active appointment",
     "SELECT shipment_id, count(*) FROM appointments WHERE is_current AND appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') AND slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) GROUP BY shipment_id HAVING count(*) > 1"),
    ("Every active appointment owns an active claim",
     "SELECT a.id FROM appointments a WHERE a.appointment_status IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS') AND a.slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) AND NOT EXISTS (SELECT 1 FROM slot_claims c WHERE c.appointment_id = a.id AND c.active)"),
    ("No ended appointment or closed hold still owns a claim",
     "SELECT c.id FROM slot_claims c LEFT JOIN appointments a ON a.id = c.appointment_id LEFT JOIN slot_holds h ON h.id = c.hold_id WHERE c.active AND c.slot_id IN (SELECT id FROM appointment_slots WHERE facility_id = :f) AND ((a.id IS NOT NULL AND a.appointment_status NOT IN ('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')) OR (h.id IS NOT NULL AND h.status <> 'active'))"),
]


async def invariants(world: World, rep: Report, label: str) -> bool:
    ok_all = True
    async with async_session_factory() as db:
        rows = []
        for name, sql in INVARIANTS:
            res = (await db.execute(text(sql), {"f": world.fac.id})).all()
            ok_all &= not res
            rows.append([name, len(res), "PASS" if not res else "FAIL"])
    rep.p(f"SQL invariants after {label} (violating rows must be 0):")
    rep.p()
    rep.table(["Invariant", "Violating rows", "Result"], rows)
    rep.checks.append((f"All SQL invariants hold after {label}", ok_all))
    return ok_all


async def slot_counts(slot_id: uuid.UUID) -> dict:
    async with async_session_factory() as db:
        q = lambda sql: db.execute(text(sql), {"s": slot_id})  # noqa: E731
        return {
            "active_claims": (await q("SELECT count(*) FROM slot_claims WHERE active AND slot_id = :s")).scalar_one(),
            "active_holds": (await q("SELECT count(*) FROM slot_holds WHERE status = 'active' AND slot_id = :s")).scalar_one(),
            "hold_rows": (await q("SELECT count(*) FROM slot_holds WHERE slot_id = :s")).scalar_one(),
            "appointments": (await q("SELECT count(*) FROM appointments WHERE slot_id = :s")).scalar_one(),
        }


async def timed(coros):
    t0 = time.perf_counter()
    res = await asyncio.gather(*coros)
    return res, time.perf_counter() - t0


def race_row(title: str, res: list[httpx.Response], secs: float) -> list:
    codes = Counter(r.status_code for r in res)
    errs = Counter(err(r) for r in res if r.status_code >= 400)
    return [title, len(res), codes.get(201, 0) + codes.get(200, 0), codes.get(409, 0),
            ", ".join(f"{k}x{v}" for k, v in sorted(errs.items(), key=str)) or "-", codes.get(500, 0), f"{secs:.2f}s"]


async def main(base: str, out: str, keep: bool) -> int:
    audit_events.install()
    run = datetime.now().strftime("%H%M%S")
    rep = Report()
    started = datetime.now(UTC)
    world = World(run)
    await world.build()
    coord = await login(base, "coordinator@setuhaul.demo")
    planner = await login(base, "planner@setuhaul.demo")
    rows: list[list] = []
    try:
        rep.h(2, "1. N simultaneous place_hold requests for one slot")
        rep.p("Each request comes from its own HTTP client (own connection) for a different shipment, all fired at the same "
              "instant at `POST /api/v1/booking/holds`. Exactly one may win; every other caller must receive `SLOT_TAKEN`.")
        rep.p()
        for n, hm in ((10, "08:00"), (50, "09:00")):
            ships = await world.shipments(n)
            cs = clones(base, coord, n)
            try:
                res, secs = await timed([c.post(f"{API}/booking/holds", json={"shipment_id": str(s), "slot_ids": [str(world.slots[hm])]})
                                         for c, s in zip(cs, ships, strict=True)])
            finally:
                await close(cs)
            row = race_row(f"{n} holds, slot {hm}", res, secs)
            rows.append(row)
            counts = await slot_counts(world.slots[hm])
            rep.check(f"{n} simultaneous holds: exactly 1 x 201 and {n - 1} x 409 SLOT_TAKEN, no 5xx",
                      row[2] == 1 and row[3] == n - 1 and row[5] == 0 and all(err(r) == "SLOT_TAKEN" for r in res if r.status_code == 409))
            rep.check(f"{n} simultaneous holds: PostgreSQL shows 1 active claim, 1 active hold, 1 hold row for the slot",
                      counts["active_claims"] == 1 and counts["active_holds"] == 1 and counts["hold_rows"] == 1)
            rep.code(json.dumps({"slot": hm, **counts}, indent=2), "json")
        rep.table(["Race", "Requests", "Succeeded (2xx)", "Rejected (409)", "Error codes", "5xx", "Wall time"], rows)
        await invariants(world, rep, "the hold races")

        rep.h(2, "2. Ten concurrent approvals of the same request")
        ship = (await world.shipments(1))[0]
        h = (await coord.post(f"{API}/booking/holds", json={"shipment_id": str(ship), "slot_ids": [str(world.slots["10:00"])]})).json()
        req = (await coord.post(f"{API}/booking/requests", json={"shipment_id": str(ship), "hold_id": h["id"]})).json()
        cs = clones(base, coord, 10)
        try:
            res, secs = await timed([c.post(f"{API}/booking/requests/{req['id']}/approve") for c in cs])
        finally:
            await close(cs)
        row = race_row("10 approvals, one request", res, secs)
        counts = await slot_counts(world.slots["10:00"])
        rep.table(["Race", "Requests", "Succeeded (2xx)", "Rejected (409)", "Error codes", "5xx", "Wall time"], [row])
        rep.check("Concurrent approvals of one request produce exactly one appointment and no 5xx",
                  counts["appointments"] == 1 and row[5] == 0)
        rep.code(json.dumps(counts, indent=2), "json")
        await invariants(world, rep, "the approval race")

        rep.h(2, "3. Overlapping multi-window claims: approval vs a competing hold")
        rep.p("Shipment X holds two consecutive slots but its hold has already expired (not yet swept). While X is approved, "
              "shipment Y holds a window that overlaps X's second slot. Exactly one of the two may win each round.")
        rep.p()
        rounds, outcomes = [], []
        for i, (a, b, c_) in enumerate((("11:00", "12:00", "13:00"), ("14:00", "15:00", "16:00"), ("17:00", "18:00", "19:00"))):
            x, y = await world.shipments(2)
            async with async_session_factory() as db:
                hx = await engine.place_hold(db, x, [world.slots[a], world.slots[b]], now=datetime.now(UTC) - timedelta(minutes=20))
                rx = await engine.create_request(db, x, hold_id=hx.id)
                await db.commit()
                rx_id = rx.id
            cs = clones(base, coord, 2)
            try:
                (ra, rb), secs = await timed([cs[0].post(f"{API}/booking/requests/{rx_id}/approve"),
                                              cs[1].post(f"{API}/booking/holds", json={"shipment_id": str(y), "slot_ids": [str(world.slots[b]), str(world.slots[c_])]})])
            finally:
                await close(cs)
            x_ok, y_ok = ra.status_code == 200, rb.status_code == 201
            outcomes.append(x_ok != y_ok and ra.status_code < 500 and rb.status_code < 500)
            rounds.append([i + 1, f"X [{a}, {b}] approve", ra.status_code, err(ra) or "-", f"Y [{b}, {c_}] hold", rb.status_code, err(rb) or "-",
                           "X wins" if x_ok else "Y wins" if y_ok else "nobody"])
        rep.table(["Round", "Request 1", "Status", "Error", "Request 2", "Status", "Error", "Winner"], rounds)
        rep.check("In every round exactly one of the two overlapping requests won", all(outcomes))
        await invariants(world, rep, "the overlapping-window races")

        rep.h(2, "4. Hold-expiry sweep racing with approval")
        rep.p("The expiry sweeper (`engine.sweep`, the function the arq job runs every minute) runs at the same instant as "
              "`POST /booking/requests/{id}/approve` for a hold that has just expired.")
        rep.p()
        sweep_rows, sweep_ok = [], []
        ships = await world.shipments(6)
        # fresh isolated dock/slots for this race so earlier rounds cannot interfere
        day = datetime.now(IST).date() + timedelta(days=10)
        async with async_session_factory() as db:
            slots2 = []
            for hour in range(8, 14):
                start = datetime.combine(day, dtime(hour, 0), tzinfo=IST)
                s = AppointmentSlot(code=f"{world.dock.code}-{start:%y%m%d%H%M}", facility_id=world.fac.id, dock_id=world.dock.id,
                                    slot_start_ts=start.astimezone(UTC), slot_end_ts=(start + timedelta(hours=1)).astimezone(UTC))
                db.add(s)
                slots2.append(s)
            await db.flush()
            ids2 = [s.id for s in slots2]
            await db.commit()
        eta2 = datetime.combine(day, dtime(6, 0), tzinfo=IST).astimezone(UTC)
        async with async_session_factory() as db:
            await db.execute(text("UPDATE shipments SET original_eta_ts = :e WHERE id = ANY(CAST(:ids AS uuid[]))"),
                             {"e": eta2, "ids": [str(s) for s in ships]})
            await db.commit()
        for i, (ship, slot) in enumerate(zip(ships, ids2, strict=True)):
            async with async_session_factory() as db:
                hold = await engine.place_hold(db, ship, [slot], now=datetime.now(UTC) - timedelta(minutes=20))
                rq = await engine.create_request(db, ship, hold_id=hold.id)
                await db.commit()
                rq_id, hid = rq.id, hold.id
            ap = httpx.AsyncClient(base_url=base, timeout=120, cookies=coord.cookies, headers={"X-CSRF-Token": coord.headers["X-CSRF-Token"]})

            async def sweep():
                async with async_session_factory() as db:
                    c = await engine.sweep(db)
                    await db.commit()
                    return c

            try:
                (r, counts_sw), secs = await timed([ap.post(f"{API}/booking/requests/{rq_id}/approve"), sweep()])
            finally:
                await ap.aclose()
            async with async_session_factory() as db:
                active = (await db.execute(text("SELECT count(*) FROM appointments WHERE slot_id = :s AND appointment_status IN "
                                                "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')"), {"s": slot})).scalar_one()
                hold_status = (await db.execute(text("SELECT status FROM slot_holds WHERE id = :i"), {"i": hid})).scalar_one()
            consistent = (r.status_code == 200 and active == 1 and hold_status == "converted") or \
                         (r.status_code == 409 and active == 0 and hold_status == "expired")
            sweep_ok.append(consistent and active <= 1)
            sweep_rows.append([i + 1, r.status_code, err(r) or "-", hold_status, active, f"{secs:.2f}s"])
        rep.table(["Round", "Approve status", "Error", "Hold final status", "Active appointments on slot", "Wall time"], sweep_rows)
        rep.check("Sweep vs approve: every round ended consistently (approved XOR expired), never two bookings", all(sweep_ok))
        await invariants(world, rep, "the sweep-vs-approve races")

        rep.h(2, "5. Two drivers choose the same option")
        a, b = await world.shipments(2)
        cs = clones(base, coord, 2)
        slot20 = str(world.slots["20:00"])
        try:
            (ra, rb), secs = await timed([cs[0].post(f"{API}/booking/holds", json={"shipment_id": str(a), "slot_ids": [slot20]}),
                                          cs[1].post(f"{API}/booking/holds", json={"shipment_id": str(b), "slot_ids": [slot20]})])
        finally:
            await close(cs)
        rep.table(["Driver", "Status", "Error"], [["A", ra.status_code, err(ra) or "-"], ["B", rb.status_code, err(rb) or "-"]])
        loser = ra if ra.status_code == 409 else rb
        rep.check("Exactly one driver got the slot; the other received SLOT_TAKEN with a plain message",
                  sorted([ra.status_code, rb.status_code]) == [201, 409] and err(loser) == "SLOT_TAKEN")
        rep.p(f"Message shown to the losing caller: _{loser.json()['error']['message']}_")
        rep.p()

        rep.h(2, "6. Permission spot check")
        r1 = await planner.post(f"{API}/booking/holds", json={"shipment_id": str(a), "slot_ids": [slot20]})
        rep.check("A planner cannot place holds (booking_decisions W is coordinator-only): 403", r1.status_code == 403)

        rep.h(2, "7. PostgreSQL is the backstop")
        rep.p("The invariants above are enforced by the database, not only by code. Constraints that make a second active "
              "allocation impossible even for raw SQL:")
        rep.p()
        async with async_session_factory() as db:
            idx = (await db.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN ("
                                         "'ux_active_appointment_per_slot','ux_current_active_appointment_per_shipment',"
                                         "'ux_active_hold_per_slot','ux_active_hold_per_shipment','ux_active_claim_per_slot') ORDER BY 1"))).all()
            con = (await db.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ex_slot_no_overlap'"))).all()
        rep.code("\n".join(f"{n}\n  {d}" for n, d in [*idx, *con]), "sql")
        rep.check("All five partial unique indexes and the tstzrange EXCLUDE constraint exist", len(idx) == 5 and len(con) == 1)

        try:
            m = (await httpx.AsyncClient(base_url=base, timeout=30).get("/metrics")).text
            wanted = [ln for ln in m.splitlines() if ln.startswith(("setuhaul_slot_taken_total", "setuhaul_holds_total",
                                                                  "setuhaul_approvals_total", "setuhaul_options_infeasible_total"))]
            rep.h(2, "8. Prometheus counters (cumulative since the API process started)")
            rep.code("\n".join(wanted), "text")
        except Exception as e:  # metrics are informative only
            rep.p(f"_metrics endpoint not reachable: {e}_")
    finally:
        await coord.aclose()
        await planner.aclose()
        if not keep:
            try:
                await world.cleanup()
                cleaned = "removed"
            except Exception as e:
                cleaned = f"cleanup failed ({type(e).__name__}); data left in place under {world.fac.code}"
        else:
            cleaned = f"kept under {world.fac.code}"

    passed = all(ok for _, ok in rep.checks)
    head = [
        "# Booking integrity proof",
        "",
        f"Generated by `python -m scripts.integrity_proof` on {started:%Y-%m-%d %H:%M} UTC against `{base}` "
        f"(Python {platform.python_version()}, PostgreSQL via the dev compose stack).",
        "",
        f"**Result: {'ALL CHECKS PASSED - zero double bookings' if passed else 'FAILURES - see below'}** "
        f"({sum(ok for _, ok in rep.checks)} of {len(rep.checks)} checks).",
        "",
        "Method: every request goes over real HTTP to the running FastAPI service from separate clients with separate "
        "connections; invariants are then checked with SQL directly on PostgreSQL. The script builds an isolated facility "
        f"(`FAC-PROOF-{run}`, one dock, hourly slots, 80+ shipments) and its data was {cleaned} afterwards. The expiry "
        "sweep is called in-process (it is an arq job, not an HTTP endpoint) at the same instant as the HTTP approval. "
        "A shipment holds one slot at a time; showing an option never reserves it; only CONFIRMED is a promise.",
        "",
        "## Summary of checks",
        "",
    ]
    summary = [f"- {'PASS' if ok else 'FAIL'}: {name}" for name, ok in rep.checks]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(head + summary + ["", "## Evidence", *rep.lines]) + "\n")
    print(f"wrote {out}: {'PASS' if passed else 'FAIL'} ({sum(ok for _, ok in rep.checks)}/{len(rep.checks)})")
    return 0 if passed else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--out", default="/docs/INTEGRITY_PROOF.md" if os.path.isdir("/docs") else "INTEGRITY_PROOF.md")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(main(a.base_url, a.out, a.keep)))

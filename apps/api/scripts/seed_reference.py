"""Load the reference SQLite snapshot into PostgreSQL.

Idempotent: surrogate UUIDs are uuid5(namespace, "<table>:<original id>"), rows are
inserted with ON CONFLICT DO NOTHING. Original text ids become the unique `code` column.
Usage: python -m scripts.seed_reference /data/setuhaul_freight_operations.db
"""
import asyncio
import sqlite3
import sys
import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

NS = uuid.UUID("5e7a0a1c-3b1d-4c7e-9a55-0d0c5e7a0a1c")

# table -> (pk column in sqlite, has code column, {fk column: referenced table},
#           renames {sqlite col: target col}, self-ref columns)
SPECS: dict[str, dict] = {
    "carriers": dict(pk="carrier_id", code=True, fks={}),
    "vehicle_types": dict(pk="vehicle_type_code", code=True, fks={}, rename={"vehicle_type_code": None}),
    "facilities": dict(pk="facility_id", code=True, fks={}),
    "drivers": dict(pk="driver_id", code=True, fks={"carrier_id": "carriers"}),
    "vehicles": dict(
        pk="vehicle_id", code=True, fks={"carrier_id": "carriers", "vehicle_type_code": "vehicle_types"},
        rename={"vehicle_type_code": "vehicle_type_id"},
    ),
    "docks": dict(pk="dock_id", code=True, fks={"facility_id": "facilities"}),
    "shipments": dict(
        pk="shipment_id", code=True,
        fks={"carrier_id": "carriers", "driver_id": "drivers", "vehicle_id": "vehicles",
             "destination_facility_id": "facilities"},
    ),
    "eta_updates": dict(
        pk="eta_update_id", code=False, fks={"shipment_id": "shipments", "reported_by_driver_id": "drivers"}
    ),
    "appointment_slots": dict(
        pk="slot_id", code=True, fks={"facility_id": "facilities", "dock_id": "docks"}, drop=["created_at"]
    ),
    "appointments": dict(
        pk="appointment_id", code=True,
        fks={"shipment_id": "shipments", "slot_id": "appointment_slots",
             "replaced_appointment_id": "appointments"},
        selfref=["replaced_appointment_id"], drop=["updated_at"],
    ),
    "facility_contacts": dict(pk="contact_id", code=False, fks={"facility_id": "facilities"}),
    "facility_rules": dict(pk="rule_id", code=False, fks={"facility_id": "facilities"}),
    "dock_status_events": dict(pk="dock_event_id", code=False, fks={"dock_id": "docks"}, drop=["created_at"]),
    "facility_checkins": dict(
        pk="checkin_id", code=False,
        fks={"shipment_id": "shipments", "facility_id": "facilities", "actual_dock_id": "docks"},
        drop=["updated_at"],
    ),
    "chat_threads": dict(
        pk="thread_id", code=True, fks={"driver_id": "drivers", "shipment_id": "shipments"}
    ),
    "chat_messages": dict(pk="chat_message_id", code=True, fks={"thread_id": "chat_threads"}),
    "driver_exceptions": dict(
        pk="exception_id", code=True,
        fks={"shipment_id": "shipments", "driver_id": "drivers", "thread_id": "chat_threads"},
    ),
    "operational_messages": dict(
        pk="operational_message_id", code=False,
        fks={"shipment_id": "shipments", "appointment_id": "appointments",
             "reply_to_message_id": "operational_messages"},
        selfref=["reply_to_message_id"],
    ),
}
BOOL_COLS = {
    "active_flag", "supports_refrigerated", "refrigerated_flag", "refrigeration_capable", "is_current",
    "is_duplicate", "requires_human_review", "temperature_control_required",
}
TIME_COLS = {"open_time", "close_time"}
DATE_COLS = {"effective_from", "effective_to"}


def uid(table: str, original: str) -> uuid.UUID:
    return uuid.uuid5(NS, f"{table}:{original}")


def convert(col: str, val):
    if val is None:
        return None
    if col in BOOL_COLS:
        return bool(val)
    if col in TIME_COLS:
        return time.fromisoformat(val)
    if col in DATE_COLS:
        return date.fromisoformat(val[:10])
    if col.endswith("_ts") or col.endswith("_at"):
        return datetime.fromisoformat(val)
    return val


async def main(sqlite_path: str) -> None:
    src = sqlite3.connect(f"file:{sqlite_path}?mode=ro&immutable=1", uri=True)
    src.row_factory = sqlite3.Row
    now = datetime.now(UTC)
    engine = create_async_engine(get_settings().database_url)
    counts: dict[str, int] = {}
    async with engine.begin() as conn:
        for table, spec in SPECS.items():
            rows = src.execute(f"SELECT * FROM {table}").fetchall()
            fks, rename = spec["fks"], spec.get("rename", {})
            selfref, drop = spec.get("selfref", []), set(spec.get("drop", []))
            deferred: list[tuple[uuid.UUID, str, uuid.UUID]] = []
            for row in rows:
                d = dict(row)
                rid = uid(table, d[spec["pk"]])
                out: dict = {"id": rid}
                if spec["code"]:
                    out["code"] = d[spec["pk"]]
                for col, val in d.items():
                    if col == spec["pk"] or col in drop:
                        continue
                    target = rename.get(col, col)
                    if target is None:
                        continue
                    if col in fks:
                        ref = uid(fks[col], val) if val is not None else None
                        if col in selfref:
                            if ref is not None:
                                deferred.append((rid, target, ref))
                            ref = None
                        out[target] = ref
                    else:
                        out[target] = convert(col, val)
                if table == "vehicle_types":
                    out["code"] = d["vehicle_type_code"]
                if table == "drivers":
                    out.update(whatsapp_number=d["phone"], whatsapp_opt_in=True, verified_at=now,
                               preferred_language="en")
                out.setdefault("created_at", now)
                out.setdefault("updated_at", now)
                out["version"] = 1
                cols = ", ".join(out)
                params = ", ".join(f":{c}" for c in out)
                await conn.execute(
                    text(f"INSERT INTO {table} ({cols}) VALUES ({params}) ON CONFLICT (id) DO NOTHING"), out
                )
            for rid, col, ref in deferred:
                await conn.execute(text(f"UPDATE {table} SET {col} = :ref WHERE id = :id"), {"ref": ref, "id": rid})
            counts[table] = len(rows)
    await engine.dispose()
    for t, n in counts.items():
        print(f"{t}: {n}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "/data/setuhaul_freight_operations.db"))

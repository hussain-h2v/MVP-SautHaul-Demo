"""Repository-layer scope filters, applied regardless of what the router did."""
from sqlalchemy import Select, false

from app.modules.auth.deps import Principal


def scope_by_facility(stmt: Select, facility_col, p: Principal) -> Select:
    if p.all_facilities:
        return stmt
    if p.role == "facility_planner" and p.facility_ids:
        return stmt.where(facility_col.in_(p.facility_ids))
    return stmt.where(false())


def scope_by_carrier(stmt: Select, carrier_col, p: Principal) -> Select:
    if p.role in ("admin", "coordinator", "facility_planner"):
        return stmt
    if p.role == "carrier_user" and p.carrier_id:
        return stmt.where(carrier_col == p.carrier_id)
    return stmt.where(false())

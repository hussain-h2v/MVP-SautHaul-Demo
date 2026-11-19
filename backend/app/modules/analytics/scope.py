"""Who may see which slice of the network. Planner = own facilities, carrier user = own carrier, coordinator and admin = all
(optionally narrowed by facility or carrier). Applied in SQL by the analytics queries, never trusted from the router."""
from dataclasses import dataclass
from uuid import UUID

from app.core.errors import ForbiddenError, NotFoundError
from app.modules.auth.deps import Principal


@dataclass(frozen=True)
class Scope:
    facility_ids: tuple[UUID, ...] | None  # None = every facility
    carrier_id: UUID | None  # None = every carrier
    label: str = "network"

    def clauses(self, facility_col: str, carrier_col: str | None) -> tuple[str, dict]:
        """SQL fragment (starting with AND) plus params; expanding bind names are `fac`."""
        sql, params = "", {}
        if self.facility_ids is not None:
            sql += f" AND {facility_col} IN :fac"
            params["fac"] = list(self.facility_ids)
        if self.carrier_id is not None and carrier_col:
            sql += f" AND {carrier_col} = :car"
            params["car"] = self.carrier_id
        return sql, params


def build(p: Principal, *, facility_id: UUID | None = None, carrier_id: UUID | None = None, view: str) -> Scope:
    """view: network | facility | coordinator | carrier. Raises 403 when the role has no business with the view."""
    if view in ("network", "coordinator"):
        if p.role not in ("admin", "coordinator"):
            raise ForbiddenError("This view is for head office and the operations desk")
        return Scope(None, None, view)
    if view == "facility":
        if p.role == "carrier_user":
            raise ForbiddenError("Facility analytics are not available to carrier users")
        if p.role == "facility_planner":
            own = tuple(sorted(p.facility_ids, key=str))
            if facility_id is not None:
                if facility_id not in p.facility_ids:
                    raise NotFoundError("Facility not found")
                return Scope((facility_id,), None, "facility")
            return Scope(own, None, "facility") if own else Scope((), None, "facility")
        return Scope((facility_id,) if facility_id else None, None, "facility")
    if view == "carrier":
        if p.role == "carrier_user":
            if not p.carrier_id:
                raise ForbiddenError("No carrier assigned")
            return Scope(None, p.carrier_id, "carrier")  # a requested carrier_id is ignored: identity comes from the session
        if p.role in ("admin", "coordinator"):
            return Scope(None, carrier_id, "carrier")
        raise ForbiddenError("Carrier analytics are not available to this role")
    raise ForbiddenError("Unknown view")

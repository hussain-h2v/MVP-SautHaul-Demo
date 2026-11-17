"""Capability matrix (spec section 4). W implies R. Deny by default."""
R, W = "R", "W"
ROLES = ("admin", "facility_planner", "coordinator", "carrier_user")


def _row(a, p, c, k) -> dict[str, str | None]:
    return dict(zip(ROLES, (a, p, c, k), strict=True))


MATRIX: dict[str, dict[str, str | None]] = {
    #                         admin planner coordinator carrier
    "manage_master":         _row(W, None, None, None),
    "shipments_write":       _row(W, None, None, None),
    "docks_slots_rules":     _row(R, W, R, None),
    "day_schedule":          _row(R, W, R, R),
    "drivers_vehicles":      _row(R, None, R, W),
    "assign_driver_vehicle": _row(None, None, None, W),
    "shipment_details":      _row(R, R, R, R),
    "booking_decisions":     _row(None, R, W, None),
    "escalations_takeover":  _row(None, None, W, None),
    "ai_management":         _row(W, None, None, None),
    "ai_insights":           _row(R, R, W, R),
    "analytics":             _row(R, R, R, R),
    "audit_log":             _row(R, None, R, None),
    "system_settings":       _row(W, None, None, None),
}


def allowed(role: str, capability: str, level: str) -> bool:
    granted = MATRIX.get(capability, {}).get(role)
    if granted is None:
        return False
    return granted == W or level == R


def capabilities_for(role: str) -> dict[str, str]:
    return {c: roles[role] for c, roles in MATRIX.items() if roles.get(role)}

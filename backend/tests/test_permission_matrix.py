"""One test per cell of the spec section 4 matrix, allowed and denied. The expected table is
written out independently of app.core.permissions so the test is not a tautology."""
import pytest
from fastapi import Depends

from app.main import app
from app.modules.auth.deps import require
from tests.conftest import login

ROLES = ["admin", "facility_planner", "coordinator", "carrier_user"]
# capability -> grants in ROLES order. W=write, R=read-only, -=none
EXPECTED = {
    "manage_master":         "W---",
    "shipments_write":       "W---",
    "docks_slots_rules":     "RWR-",
    "day_schedule":          "RWRR",
    "drivers_vehicles":      "R-RW",
    "assign_driver_vehicle": "---W",
    "shipment_details":      "RRRR",
    "booking_decisions":     "-RW-",
    "escalations_takeover":  "--W-",
    "ai_management":         "W---",
    "ai_insights":           "RRWR",
    "analytics":             "RRRR",
    "audit_log":             "R-R-",
    "system_settings":       "W---",
}

for _cap in EXPECTED:
    for _lvl, _method in (("R", "get"), ("W", "post")):
        async def _probe(_p=Depends(require(_cap, _lvl))) -> dict:  # noqa: B008
            return {"ok": True}

        app.add_api_route(f"/__probe/{_cap}/{_lvl}", _probe, methods=[_method.upper()])

CASES = [(cap, role, lvl) for cap in EXPECTED for role in ROLES for lvl in ("R", "W")]


def expected_allowed(cap: str, role: str, lvl: str) -> bool:
    grant = EXPECTED[cap][ROLES.index(role)]
    return grant == "W" or (grant == "R" and lvl == "R")


@pytest.mark.parametrize("cap,role,lvl", CASES, ids=[f"{c}-{r}-{l}" for c, r, l in CASES])
async def test_matrix_cell(client, world, cap, role, lvl):
    await login(client, role)
    method = "get" if lvl == "R" else "post"
    resp = await getattr(client, method)(f"/__probe/{cap}/{lvl}")
    assert resp.status_code == (200 if expected_allowed(cap, role, lvl) else 403), (cap, role, lvl, resp.text)


async def test_probe_requires_authentication(client, world):
    assert (await client.get("/__probe/analytics/R")).status_code == 401

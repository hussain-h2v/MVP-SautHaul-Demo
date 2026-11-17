"""Shared permission guards."""
from fastapi import Depends

from app.core.errors import ForbiddenError
from app.modules.auth.deps import Principal, require


def facility_staff(capability: str, level: str):
    """Capability check that additionally shuts carrier users out of facility-operations endpoints."""
    base = require(capability, level)

    async def dep(p: Principal = Depends(base)) -> Principal:
        if p.role == "carrier_user":
            raise ForbiddenError("Facility operations are not available to carrier users")
        return p

    return dep

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.auth.deps import Principal, get_principal
from app.modules.vehicles import service

router = APIRouter(prefix="/vehicle-types", tags=["vehicles"])


class VehicleTypeOut(BaseModel):
    code: str
    description: str


@router.get("", response_model=list[VehicleTypeOut])
async def vehicle_types(_: Principal = Depends(get_principal), db: AsyncSession = Depends(get_db)):
    return [VehicleTypeOut(code=t.code, description=t.description) for t in await service.list_types(db)]

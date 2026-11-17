from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DriverOut(BaseModel):
    id: UUID
    code: str
    carrier_id: UUID
    carrier_name: str = ""
    driver_name: str
    phone: str
    whatsapp_number: str | None
    preferred_language: str
    whatsapp_opt_in: bool
    verified: bool
    driver_status: str
    licence_number: str
    active_shipments: int = 0
    last_activity: datetime | None = None


class DriverPage(BaseModel):
    total: int
    items: list[DriverOut]

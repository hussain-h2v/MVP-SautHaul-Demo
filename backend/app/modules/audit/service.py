from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


async def for_entity(db: AsyncSession, entity: str, entity_id: str, limit: int = 200) -> list[AuditLog]:
    return list((await db.execute(
        select(AuditLog).where(AuditLog.entity == entity, AuditLog.entity_id == entity_id)
        .order_by(AuditLog.created_at).limit(limit)
    )).scalars().all())

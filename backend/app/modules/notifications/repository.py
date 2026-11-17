from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.deps import Principal
from app.modules.notifications.models import Notification, NotificationRead


def visible_clause(p: Principal):
    """Rows addressed to the user, or to their role narrowed by facility/carrier. Applied to every read."""
    if p.all_facilities:
        facility_ok = True
    elif p.role == "facility_planner" and p.facility_ids:
        facility_ok = or_(Notification.facility_id.is_(None), Notification.facility_id.in_(p.facility_ids))
    else:
        facility_ok = Notification.facility_id.is_(None)
    carrier_ok = (or_(Notification.carrier_id.is_(None), Notification.carrier_id == p.carrier_id)
                  if p.carrier_id else Notification.carrier_id.is_(None))
    if p.role in ("admin", "coordinator", "facility_planner"):
        carrier_ok = True  # carrier-addressed rows carry a role of carrier_user, so role matching already isolates them
    by_role = and_(Notification.recipient_role == p.role, facility_ok, carrier_ok)
    return or_(Notification.recipient_user_id == p.user_id, by_role)


def _read_exists(p: Principal):
    return select(NotificationRead.id).where(NotificationRead.notification_id == Notification.id,
                                             NotificationRead.user_id == p.user_id).exists()


async def list_page(db: AsyncSession, p: Principal, unread_only: bool, limit: int, offset: int):
    base = select(Notification).where(visible_clause(p))
    unread = base.where(~_read_exists(p))
    stmt = unread if unread_only else base
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    unread_n = (await db.execute(select(func.count()).select_from(unread.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
                             .limit(limit).offset(offset))).scalars().all()
    read_ids = set()
    if rows:
        r = await db.execute(select(NotificationRead.notification_id).where(
            NotificationRead.user_id == p.user_id, NotificationRead.notification_id.in_([n.id for n in rows])))
        read_ids = {x[0] for x in r.all()}
    return total, unread_n, rows, read_ids


async def get_visible(db: AsyncSession, p: Principal, notification_id: UUID) -> Notification | None:
    return (await db.execute(select(Notification).where(Notification.id == notification_id, visible_clause(p)))).scalar_one_or_none()


async def mark_read(db: AsyncSession, p: Principal, notification_id: UUID) -> None:
    now = datetime.now(UTC)
    await db.execute(pg_insert(NotificationRead).values(
        id=uuid4(), notification_id=notification_id, user_id=p.user_id, created_at=now, updated_at=now)
        .on_conflict_do_nothing(constraint="uq_notification_read"))


async def mark_all_read(db: AsyncSession, p: Principal) -> int:
    ids = [r[0] for r in (await db.execute(select(Notification.id).where(visible_clause(p), ~_read_exists(p)))).all()]
    for i in ids:
        await mark_read(db, p, i)
    return len(ids)

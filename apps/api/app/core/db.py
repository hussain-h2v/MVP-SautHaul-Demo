from collections.abc import AsyncIterator
from datetime import datetime, UTC
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    """Shared declarative base. Every mutable table gets id/created_at/updated_at/version."""


class UUIDPK:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Versioned:
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": "version"}


class BusinessCoded:
    """For entities carried over from the reference schema: a surrogate UUID PK
    (used for all new FKs) plus the original human-readable business key
    (e.g. 'SHP1002', 'DRV003') kept as a unique, indexed `code` column so the
    seeded ladder cases (SHP1002-SHP1019, THR001-THR012) stay referenceable.
    See docs/DECISIONS.md, decision on reference-schema key strategy."""

    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session

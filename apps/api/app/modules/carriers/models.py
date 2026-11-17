from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned


class Carrier(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """A carrier (transport company). Reference table, extended with
    created_at/updated_at/version per the new spec's mutable-table rule.

    No ORM relationship() is declared to other modules' tables: per the
    modular-monolith rule, cross-module reads go through that module's
    service/repository, joining on the FK column id, not a declarative
    relationship that would couple the mapped classes together."""

    __tablename__ = "carriers"
    __table_args__ = (CheckConstraint("char_length(carrier_name) > 0", name="ck_carrier_name_not_blank"),)

    carrier_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    active_flag: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, BusinessCoded, Timestamped, UUIDPK, Versioned

THREAD_STATUSES = ("OPEN", "WAITING_FOR_DRIVER", "WAITING_FOR_WAREHOUSE", "RESOLVED", "ESCALATED", "CLOSED")
THREAD_INTENTS = ("REPORT_DELAY", "ASK_SLOT_OPTIONS", "CHECK_STATUS", "EARLY_ARRIVAL", "GENERAL_QUESTION", "UNKNOWN")
SENDER_TYPES = ("DRIVER", "AGENT", "OPERATIONS", "WAREHOUSE", "SYSTEM")


class ChatThread(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """A driver conversation. shipment_id may be NULL when the thread hasn't
    been bound to a shipment yet (the LangGraph agent must ask, never guess,
    per spec section 7 — reference audit finding D)."""

    __tablename__ = "chat_threads"
    __table_args__ = (
        CheckConstraint(
            "thread_status IN ('OPEN','WAITING_FOR_DRIVER','WAITING_FOR_WAREHOUSE','RESOLVED','ESCALATED','CLOSED')",
            name="ck_thread_status",
        ),
        CheckConstraint(
            "thread_intent IN ('REPORT_DELAY','ASK_SLOT_OPTIONS','CHECK_STATUS','EARLY_ARRIVAL','GENERAL_QUESTION','UNKNOWN')",
            name="ck_thread_intent",
        ),
    )

    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"), nullable=False, index=True)
    shipment_id: Mapped[UUID | None] = mapped_column(ForeignKey("shipments.id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    thread_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    thread_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    taken_over_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class ChatMessage(Base, UUIDPK, BusinessCoded, Timestamped, Versioned):
    """Legacy reference chat event. Real inbound/outbound WhatsApp Cloud API
    traffic lands in `whatsapp_messages` (Milestone 8), deduplicated by
    wa_message_id; is_duplicate here stays for the reference-era rows
    (reference audit finding G)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("sender_type IN ('DRIVER','AGENT','OPERATIONS','WAREHOUSE','SYSTEM')", name="ck_msg_sender"),
    )

    thread_id: Mapped[UUID] = mapped_column(ForeignKey("chat_threads.id"), nullable=False, index=True)
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_reference: Mapped[str | None] = mapped_column(String(100))
    message_text: Mapped[str] = mapped_column(String(4000), nullable=False)
    message_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    external_message_id: Mapped[str | None] = mapped_column(String(200))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    parsed_intent: Mapped[str | None] = mapped_column(String(32))
    extracted_eta_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

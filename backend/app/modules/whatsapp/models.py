from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
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


DELIVERY_STATUSES = ("received", "queued", "sent", "delivered", "read", "failed")
APPROVAL_STATUSES = ("draft", "submitted", "approved", "rejected")


class WhatsAppWebhookEvent(Base, UUIDPK, Timestamped, Versioned):
    """Raw webhook payload stored before anything else happens, so nothing is lost and processing can be retried."""

    __tablename__ = "whatsapp_webhook_events"
    __table_args__ = (CheckConstraint("status IN ('pending','processed','failed')", name="ck_wa_event_status"),)

    signature_ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="pending", nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(String(1000))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WhatsAppMessage(Base, UUIDPK, Timestamped, Versioned):
    """Wire-level message log (inbound and outbound). wa_message_id is the WhatsApp message id: unique, so a webhook
    retry can never be processed twice. Outbound rows get their id from the Graph API after sending."""

    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        CheckConstraint("direction IN ('in','out')", name="ck_wa_msg_direction"),
        CheckConstraint("delivery_status IN ('received','queued','sent','delivered','read','failed')", name="ck_wa_msg_status"),
        Index("ix_wa_msg_thread_created", "thread_id", "created_at"),
        Index("ix_wa_msg_driver_created", "driver_id", "created_at"),
    )

    wa_message_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    driver_id: Mapped[UUID | None] = mapped_column(ForeignKey("drivers.id"))
    thread_id: Mapped[UUID | None] = mapped_column(ForeignKey("chat_threads.id"))
    to_number: Mapped[str | None] = mapped_column(String(20))
    type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    text: Mapped[str | None] = mapped_column(String(4000))
    language: Mapped[str | None] = mapped_column(String(10))
    template_name: Mapped[str | None] = mapped_column(String(60))
    delivery_status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(String(500))
    raw: Mapped[dict | None] = mapped_column(JSONB)
    purpose: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppTemplate(Base, UUIDPK, Timestamped, Versioned):
    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        CheckConstraint("approval_status IN ('draft','submitted','approved','rejected')", name="ck_wa_tpl_approval"),
        UniqueConstraint("name", "language", name="uq_wa_template_name_lang"),
    )

    name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(20), default="UTILITY", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    buttons: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(10), default="draft", nullable=False)
    needs_native_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta_template_id: Mapped[str | None] = mapped_column(String(100))


class WhatsAppOptEvent(Base, UUIDPK, Timestamped):
    """Audit trail of opt-in / opt-out decisions (driver keyword or admin override)."""

    __tablename__ = "whatsapp_opt_events"
    __table_args__ = (CheckConstraint("event IN ('opt_in','opt_out')", name="ck_wa_opt_event"),)

    driver_id: Mapped[UUID] = mapped_column(ForeignKey("drivers.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)

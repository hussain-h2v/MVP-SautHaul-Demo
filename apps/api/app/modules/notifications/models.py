from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamped, UUIDPK, Versioned

CHANNELS = ("EMAIL", "SMS", "WHATSAPP", "INTERNAL")
DELIVERY_STATUSES = ("QUEUED", "SENT", "DELIVERED", "FAILED", "REPLIED")


class OperationalMessage(Base, UUIDPK, Timestamped, Versioned):
    """Legacy reference outbound-comms record. The new `notifications` and
    `outbox_events` tables (spec section 3, added in Milestone 1) are the
    in-app/portal notification system; this table stays as the audit trail
    of actual email/SMS/WhatsApp sends tied to a shipment/appointment.
    A FAILED delivery_status is evidence of no confirmation, never treated
    as success (reference audit finding G)."""

    __tablename__ = "operational_messages"
    __table_args__ = (
        CheckConstraint("channel IN ('EMAIL','SMS','WHATSAPP','INTERNAL')", name="ck_opmsg_channel"),
        CheckConstraint(
            "delivery_status IN ('QUEUED','SENT','DELIVERED','FAILED','REPLIED')", name="ck_opmsg_delivery"
        ),
    )

    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), nullable=False, index=True)
    appointment_id: Mapped[UUID | None] = mapped_column(ForeignKey("appointments.id"))
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient_address: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300))
    message_body: Mapped[str] = mapped_column(String(4000), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("operational_messages.id"))

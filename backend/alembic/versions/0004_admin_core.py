"""admin core: facility address/notes, carrier vehicle types, shipment offers

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facilities", sa.Column("address", sa.String(500)))
    op.add_column("facilities", sa.Column("notes", sa.String(1000)))
    op.add_column("carriers", sa.Column("allowed_vehicle_type_codes", postgresql.JSONB(), nullable=False,
                                        server_default=sa.text("'[]'::jsonb")))
    op.alter_column("carriers", "allowed_vehicle_type_codes", server_default=None)
    for col in ("carrier_id", "driver_id", "vehicle_id"):
        op.alter_column("shipments", col, nullable=True)
    op.add_column("shipments", sa.Column("requested_date", sa.Date()))
    op.add_column("shipments", sa.Column("offer_status", sa.String(16), nullable=False, server_default="accepted"))
    op.alter_column("shipments", "offer_status", server_default=None)
    op.add_column("shipments", sa.Column("offer_decline_reason", sa.String(500)))
    op.create_check_constraint("ck_shipment_offer_status", "shipments",
                               "offer_status IN ('draft','offered','accepted','declined')")


def downgrade() -> None:
    op.drop_constraint("ck_shipment_offer_status", "shipments")
    for c in ("offer_decline_reason", "offer_status", "requested_date"):
        op.drop_column("shipments", c)
    for col in ("vehicle_id", "driver_id", "carrier_id"):
        op.alter_column("shipments", col, nullable=False)
    op.drop_column("carriers", "allowed_vehicle_type_codes")
    op.drop_column("facilities", "notes")
    op.drop_column("facilities", "address")

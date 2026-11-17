"""docks: compatible vehicle types and notes

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("docks", sa.Column("compatible_vehicle_type_codes", postgresql.JSONB(), nullable=False,
                                     server_default=sa.text("'[]'::jsonb")))
    op.alter_column("docks", "compatible_vehicle_type_codes", server_default=None)
    op.add_column("docks", sa.Column("notes", sa.String(500)))
    op.create_index("ix_dock_events_dock_start", "dock_status_events", ["dock_id", "event_start_ts"])


def downgrade() -> None:
    op.drop_index("ix_dock_events_dock_start", table_name="dock_status_events")
    op.drop_column("docks", "notes")
    op.drop_column("docks", "compatible_vehicle_type_codes")

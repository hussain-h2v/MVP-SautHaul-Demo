"""integrity constraints and operational views

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

ACTIVE = "('PENDING_CONFIRMATION','CONFIRMED','IN_PROGRESS')"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # Slots on the same dock can never overlap (spec section 3, rule 4).
    op.execute(
        "ALTER TABLE appointment_slots ADD CONSTRAINT ex_slot_no_overlap "
        "EXCLUDE USING gist (dock_id WITH =, tstzrange(slot_start_ts, slot_end_ts) WITH &&)"
    )
    # One active booking per slot; one current active appointment per shipment.
    op.execute(
        f"CREATE UNIQUE INDEX ux_active_appointment_per_slot ON appointments (slot_id) "
        f"WHERE appointment_status IN {ACTIVE}"
    )
    op.execute(
        f"CREATE UNIQUE INDEX ux_current_active_appointment_per_shipment ON appointments (shipment_id) "
        f"WHERE is_current AND appointment_status IN {ACTIVE}"
    )
    op.execute("CREATE INDEX ix_slots_facility_time ON appointment_slots (facility_id, slot_start_ts, slot_end_ts)")
    op.execute("CREATE INDEX ix_eta_updates_shipment_created ON eta_updates (shipment_id, created_at DESC)")
    op.execute("CREATE INDEX ix_chat_messages_thread_time ON chat_messages (thread_id, message_ts)")

    op.execute(
        """
        CREATE VIEW v_latest_eta AS
        WITH ranked AS (
            SELECT e.*, ROW_NUMBER() OVER (PARTITION BY shipment_id ORDER BY created_at DESC, id DESC) AS rn
            FROM eta_updates e
        )
        SELECT s.id AS shipment_id, s.code AS shipment_code, s.original_eta_ts,
               COALESCE(r.declared_eta_ts, s.latest_eta_ts, s.original_eta_ts) AS effective_eta_ts,
               COALESCE(r.source_type, 'ORIGINAL_PLAN') AS eta_source,
               COALESCE(r.confidence_code, 'HIGH') AS eta_confidence,
               r.delay_reason_code, r.note AS eta_note, r.created_at AS eta_updated_at
        FROM shipments s
        LEFT JOIN ranked r ON r.shipment_id = s.id AND r.rn = 1
        """
    )
    op.execute(
        f"""
        CREATE VIEW v_slot_availability AS
        SELECT sl.id AS slot_id, sl.code AS slot_code, sl.facility_id, d.dock_code, d.dock_type,
               d.supports_refrigerated, d.max_vehicle_weight_kg, sl.slot_start_ts, sl.slot_end_ts,
               CASE WHEN sl.slot_status <> 'OPEN' THEN sl.slot_status
                    WHEN a.id IS NOT NULL THEN 'OCCUPIED' ELSE 'AVAILABLE' END AS availability_status,
               a.id AS appointment_id, a.shipment_id, a.appointment_status
        FROM appointment_slots sl
        JOIN docks d ON d.id = sl.dock_id
        LEFT JOIN appointments a ON a.slot_id = sl.id AND a.appointment_status IN {ACTIVE}
        """
    )
    op.execute(
        f"""
        CREATE VIEW v_inbound_operational_state AS
        SELECT s.id AS shipment_id, s.code AS shipment_code, s.driver_id, s.vehicle_id,
               s.destination_facility_id, s.priority_code, s.required_dock_type,
               s.temperature_control_required, s.load_weight_kg, s.expected_unload_min, s.current_status,
               le.effective_eta_ts, le.eta_source, le.eta_confidence,
               ap.id AS appointment_id, sl.id AS slot_id, sl.slot_start_ts, sl.slot_end_ts,
               d.dock_code AS planned_dock_code, fc.gate_in_ts, fc.queue_state, fc.queue_position,
               ad.dock_code AS actual_dock_code
        FROM shipments s
        JOIN v_latest_eta le ON le.shipment_id = s.id
        LEFT JOIN appointments ap ON ap.shipment_id = s.id AND ap.is_current
             AND ap.appointment_status IN {ACTIVE}
        LEFT JOIN appointment_slots sl ON sl.id = ap.slot_id
        LEFT JOIN docks d ON d.id = sl.dock_id
        LEFT JOIN facility_checkins fc ON fc.shipment_id = s.id
        LEFT JOIN docks ad ON ad.id = fc.actual_dock_id
        """
    )
    op.execute(
        """
        CREATE VIEW v_current_facility_queue AS
        SELECT fc.facility_id, fc.shipment_id, s.driver_id, s.vehicle_id, s.priority_code, fc.gate_in_ts,
               fc.arrival_state, fc.queue_state, fc.queue_position, le.effective_eta_ts,
               s.expected_unload_min, s.required_dock_type
        FROM facility_checkins fc
        JOIN shipments s ON s.id = fc.shipment_id
        JOIN v_latest_eta le ON le.shipment_id = s.id
        WHERE fc.queue_state IN ('WAITING_EARLY','WAITING_LATE','WAITING_DOCK_UNAVAILABLE','CALLED_TO_DOCK')
        """
    )


def downgrade() -> None:
    for v in ("v_current_facility_queue", "v_inbound_operational_state", "v_slot_availability", "v_latest_eta"):
        op.execute(f"DROP VIEW IF EXISTS {v}")
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_thread_time")
    op.execute("DROP INDEX IF EXISTS ix_eta_updates_shipment_created")
    op.execute("DROP INDEX IF EXISTS ix_slots_facility_time")
    op.execute("DROP INDEX IF EXISTS ux_current_active_appointment_per_shipment")
    op.execute("DROP INDEX IF EXISTS ux_active_appointment_per_slot")
    op.execute("ALTER TABLE appointment_slots DROP CONSTRAINT IF EXISTS ex_slot_no_overlap")

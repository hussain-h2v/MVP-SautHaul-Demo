-- Issue: gate and dock activity can conflict with appointment state or planned dock, and those cases should be treated as escalation triggers
SELECT
    s.shipment_id,
    s.current_status,
    a.appointment_status,
    fc.queue_state,
    fc.actual_dock_id,
    sl.dock_id AS planned_dock_id,
    fc.gate_in_ts,
    fc.updated_at
FROM shipments s
LEFT JOIN appointments a
  ON a.shipment_id = s.shipment_id
 AND a.is_current = 1
 AND a.appointment_status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'IN_PROGRESS')
LEFT JOIN appointment_slots sl ON sl.slot_id = a.slot_id
LEFT JOIN facility_checkins fc ON fc.shipment_id = s.shipment_id
WHERE (fc.queue_state IN ('WAITING_EARLY', 'WAITING_LATE', 'WAITING_DOCK_UNAVAILABLE') AND a.appointment_status IS NULL)
   OR (fc.actual_dock_id IS NOT NULL AND a.slot_id IS NOT NULL AND fc.actual_dock_id <> sl.dock_id)
ORDER BY s.shipment_id;

-- Issue: dock compatibility is a business invariant that is not database-enforced and must be checked before confirmation
SELECT
    s.shipment_id,
    s.driver_id,
    s.required_dock_type,
    s.temperature_control_required,
    d.dock_type,
    d.supports_refrigerated,
    a.slot_id,
    a.appointment_status
FROM shipments s
JOIN appointments a
  ON a.shipment_id = s.shipment_id
 AND a.is_current = 1
 AND a.appointment_status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'IN_PROGRESS')
JOIN appointment_slots sl ON sl.slot_id = a.slot_id
JOIN docks d ON d.dock_id = sl.dock_id
WHERE (
        s.required_dock_type <> 'ANY'
        AND d.dock_type <> s.required_dock_type
      )
   OR (
        s.temperature_control_required = 1
        AND d.supports_refrigerated = 0
      );

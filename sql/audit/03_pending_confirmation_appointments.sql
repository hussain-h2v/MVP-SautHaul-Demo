-- Issue: pending-confirmation appointments are live but not yet final, so they must be treated as temporary state
SELECT
    a.appointment_id,
    a.shipment_id,
    s.driver_id,
    s.current_status,
    a.slot_id,
    a.booked_at,
    a.updated_at
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
WHERE a.appointment_status = 'PENDING_CONFIRMATION'
ORDER BY a.booked_at;

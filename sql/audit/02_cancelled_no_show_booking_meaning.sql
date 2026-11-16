-- Issue: cancelled or no-show bookings still appear in appointment history and must not be treated as live capacity
SELECT
    a.appointment_id,
    a.shipment_id,
    s.driver_id,
    s.current_status,
    a.appointment_status,
    a.slot_id,
    a.booked_at
FROM appointments a
JOIN shipments s ON s.shipment_id = a.shipment_id
WHERE a.appointment_status IN ('CANCELLED', 'NO_SHOW')
ORDER BY a.shipment_id, a.booked_at;

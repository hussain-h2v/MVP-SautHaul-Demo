-- Issue: a driver can be assigned more than one active shipment and therefore require shipment-level clarification
SELECT
    driver_id,
    COUNT(*) AS active_shipments
FROM shipments
WHERE current_status IN ('ASSIGNED', 'AT_GATE', 'WAITING', 'IN_DOCK', 'IN_TRANSIT')
GROUP BY driver_id
HAVING COUNT(*) > 1
ORDER BY driver_id;

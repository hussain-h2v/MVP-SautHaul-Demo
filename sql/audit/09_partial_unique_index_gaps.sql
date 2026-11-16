-- Issue: the partial unique indexes prevent only the obvious slot/shipment duplication, not ambiguous chat context or stale requests
SELECT
    t.thread_id,
    t.driver_id,
    t.shipment_id,
    d.driver_name,
    s.current_status
FROM chat_threads t
LEFT JOIN drivers d ON d.driver_id = t.driver_id
LEFT JOIN shipments s ON s.shipment_id = t.shipment_id
WHERE t.shipment_id IS NULL
   OR (t.shipment_id IS NOT NULL AND s.driver_id IS NULL)
ORDER BY t.thread_id;

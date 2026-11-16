-- Issue: a shipment can have multiple declared ETA revisions over time, so the system must choose the latest one deterministically and preserve the history
SELECT
    e.shipment_id,
    e.source_type,
    e.declared_eta_ts,
    e.created_at
FROM eta_updates e
WHERE e.shipment_id IN (
    SELECT shipment_id
    FROM eta_updates
    GROUP BY shipment_id
    HAVING COUNT(*) > 1
)
ORDER BY e.shipment_id, e.created_at;

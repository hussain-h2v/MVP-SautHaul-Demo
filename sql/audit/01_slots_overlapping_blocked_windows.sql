-- Issue: appointment slots overlapping blocked or maintenance windows
SELECT
    sl.slot_id,
    sl.facility_id,
    sl.dock_id,
    sl.slot_start_ts,
    sl.slot_end_ts,
    dse.event_type,
    dse.event_start_ts,
    dse.event_end_ts,
    dse.reason
FROM appointment_slots sl
JOIN dock_status_events dse
  ON dse.dock_id = sl.dock_id
WHERE sl.slot_status = 'OPEN'
  AND sl.slot_start_ts < dse.event_end_ts
  AND sl.slot_end_ts > dse.event_start_ts
ORDER BY sl.slot_id, dse.event_start_ts;

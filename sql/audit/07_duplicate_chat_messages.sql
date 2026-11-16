-- Issue: duplicate or retried messages must be ignored to prevent duplicate holds or bookings
SELECT
    chat_message_id,
    thread_id,
    message_text,
    message_ts,
    parsed_intent,
    is_duplicate
FROM chat_messages
WHERE is_duplicate = 1
ORDER BY thread_id, message_ts;

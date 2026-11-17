"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type StreamStatus = "connecting" | "live" | "reconnecting";

/** Named SSE events the backend emits (`event: <type>`); EventSource has no wildcard, so list them. */
export const SSE_EVENT_TYPES = [
  "schedule.changed",
  "shipment.offered",
  "shipment.updated",
  "appointment.changed",
  "yard.changed",
  "dock.event",
] as const;

/** Subscribes to the scoped SSE stream; any event invalidates the given query keys. */
export function useEventStream(invalidate: readonly (readonly unknown[])[] = [], enabled = true): StreamStatus {
  const qc = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let delay = 1000;
    let closed = false;

    const connect = () => {
      es = new EventSource("/api/v1/events/stream", { withCredentials: true });
      const refresh = () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [...k] }));
      es.onopen = () => {
        delay = 1000;
        setStatus("live");
      };
      es.onmessage = refresh;
      for (const type of SSE_EVENT_TYPES) es.addEventListener(type, refresh);
      es.onerror = () => {
        es?.close();
        if (closed) return;
        setStatus("reconnecting");
        timer = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30_000);
      };
    };
    connect();
    return () => {
      closed = true;
      es?.close();
      if (timer) clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, qc]);

  return status;
}

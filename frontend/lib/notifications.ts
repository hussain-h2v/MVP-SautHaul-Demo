"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { NotificationPage } from "./carrier-types";
import { buildQuery } from "./query";

/** All notification server state lives under the "notifications" key so SSE `notification.created` refreshes it. */
export function useNotifications(opts: { limit?: number; offset?: number; unreadOnly?: boolean } = {}, refetchMs?: number) {
  const { limit = 20, offset = 0, unreadOnly = false } = opts;
  const qs = buildQuery({ limit, offset, unread_only: unreadOnly ? true : undefined });
  return useQuery<NotificationPage>({
    queryKey: ["notifications", qs],
    queryFn: () => api<NotificationPage>(`/notifications${qs}`),
    refetchInterval: refetchMs,
  });
}

type Cache = [readonly unknown[], NotificationPage | undefined][];

function patchAll(qc: ReturnType<typeof useQueryClient>, fn: (p: NotificationPage) => NotificationPage): Cache {
  const snapshot = qc.getQueriesData<NotificationPage>({ queryKey: ["notifications"] });
  qc.setQueriesData<NotificationPage>({ queryKey: ["notifications"] }, (old) => (old ? fn(old) : old));
  return snapshot;
}

/** Marking read is safe to do optimistically: worst case it is rolled back and refetched. */
export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/notifications/${id}/read`, { method: "POST" }),
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: ["notifications"] });
      return patchAll(qc, (p) => {
        const hit = p.items.find((n) => n.id === id && !n.read);
        return hit
          ? { ...p, unread: Math.max(0, p.unread - 1), items: p.items.map((n) => (n.id === id ? { ...n, read: true } : n)) }
          : p;
      });
    },
    onError: (_e, _id, snapshot) => {
      for (const [key, data] of (snapshot as Cache | undefined) ?? []) qc.setQueryData(key, data);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/notifications/read-all", { method: "POST" }),
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: ["notifications"] });
      return patchAll(qc, (p) => ({ ...p, unread: 0, items: p.items.map((n) => ({ ...n, read: true })) }));
    },
    onError: (_e, _v, snapshot) => {
      for (const [key, data] of (snapshot as Cache | undefined) ?? []) qc.setQueryData(key, data);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

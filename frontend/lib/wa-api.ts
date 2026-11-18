"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "./api";
import { errorMessage } from "./use-api";

export const WA_KEY = "wa";

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** GET under /whatsapp/... with a shared query key so every WhatsApp mutation refreshes every WhatsApp screen. */
export function useWa<T>(path: string | null, opts: { refetchInterval?: number } = {}) {
  return useQuery<T>({
    queryKey: [WA_KEY, path],
    queryFn: () => api<T>(`/whatsapp${path}`),
    enabled: path !== null,
    refetchInterval: opts.refetchInterval,
  });
}

/** GET of any other endpoint (drivers, shipments, coordinator threads) under the same key family. */
export function useWaOther<T>(path: string | null, opts: { retry?: boolean } = {}) {
  return useQuery<T>({
    queryKey: [WA_KEY, "other", path],
    queryFn: () => api<T>(path as string),
    enabled: path !== null,
    retry: opts.retry ?? false,
    staleTime: 15_000,
  });
}

export function useWaMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { success?: string; onSuccess?: (res: TRes, vars: TVars) => void; errorFallback?: string; silent?: boolean } = {},
) {
  const qc = useQueryClient();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      qc.invalidateQueries({ queryKey: [WA_KEY] });
      if (opts.success) toast.success(opts.success);
      opts.onSuccess?.(res, vars);
    },
    onError: (e) => {
      if (!opts.silent) toast.error(errorMessage(e, opts.errorFallback ?? "Request failed"));
    },
  });
}

export const waPost = <T,>(path: string, body?: unknown) => api<T>(`/whatsapp${path}`, { method: "POST", body: body ?? {} });
export const waPatch = <T,>(path: string, body: unknown) => api<T>(`/whatsapp${path}`, { method: "PATCH", body });

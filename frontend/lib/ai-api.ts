"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "./api";
import { errorMessage } from "./use-api";

export const AI_KEY = "ai";

/** GET under /ai/... with a shared query key so every AI mutation can refresh every AI screen. */
export function useAi<T>(path: string | null, opts: { refetchInterval?: number } = {}) {
  return useQuery<T>({
    queryKey: [AI_KEY, path],
    queryFn: () => api<T>(`/ai${path}`),
    enabled: path !== null,
    refetchInterval: opts.refetchInterval,
  });
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== "" && v !== null && v !== undefined) sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** Mutation against /ai/...; toasts the server error message and refreshes all AI queries on success. */
export function useAiMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { success?: string | ((res: TRes) => string); onSuccess?: (res: TRes, vars: TVars) => void; errorFallback?: string } = {},
) {
  const qc = useQueryClient();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      qc.invalidateQueries({ queryKey: [AI_KEY] });
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(res) : opts.success);
      opts.onSuccess?.(res, vars);
    },
    onError: (e) => toast.error(errorMessage(e, opts.errorFallback ?? "Request failed")),
  });
}

export const aiPost = <T,>(path: string, body?: unknown) => api<T>(`/ai${path}`, { method: "POST", body: body ?? {} });
export const aiPatch = <T,>(path: string, body: unknown) => api<T>(`/ai${path}`, { method: "PATCH", body });
export const aiPut = <T,>(path: string, body: unknown) => api<T>(`/ai${path}`, { method: "PUT", body });
export const aiDelete = <T,>(path: string) => api<T>(`/ai${path}`, { method: "DELETE" });

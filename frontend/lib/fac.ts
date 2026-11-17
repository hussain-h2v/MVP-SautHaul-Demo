"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";
import { api, ApiError } from "./api";
import { useMe } from "./auth";
import type { Access, CapabilityKey } from "./types";

/** All facility-portal server state lives under the "fac" query key so SSE `schedule.changed` can refresh it. */
export function useFacQuery<T>(
  path: string | null,
  opts: Partial<Pick<UseQueryOptions<T>, "refetchInterval" | "staleTime">> = {},
) {
  return useQuery<T>({ queryKey: ["fac", path], queryFn: () => api<T>(path as string), enabled: !!path, ...opts });
}

export function useFacMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { success?: string; onSuccess?: (res: TRes, vars: TVars) => void; onError?: (e: unknown) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      for (const k of ["fac", "list", "detail", "options"]) qc.invalidateQueries({ queryKey: [k] });
      if (opts.success) toast.success(opts.success);
      opts.onSuccess?.(res, vars);
    },
    onError: (e) => (opts.onError ? opts.onError(e) : toast.error(apiErrorText(e))),
  });
}

export function apiErrorText(e: unknown, fallback = "Something went wrong"): string {
  return e instanceof ApiError ? e.message : fallback;
}

export function useCap(key: CapabilityKey): Access | undefined {
  const { data } = useMe();
  return data?.capabilities[key];
}

/** Current time, refreshed every `ms`. Used for countdowns. */
export function useNow(ms = 1000): number {
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

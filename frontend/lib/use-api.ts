"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, ApiError } from "./api";

export function errorMessage(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.message : fallback;
}

/** Detail query keyed so mutations invalidate it together with every list. */
export function useDetail<T>(path: string | null) {
  return useQuery<T>({ queryKey: ["detail", path], queryFn: () => api<T>(path as string), enabled: !!path });
}

/** Fetch a short, unpaginated reference list (facilities, carriers, vehicle types…). */
export function useOptions<T>(path: string) {
  return useQuery<T>({ queryKey: ["options", path], queryFn: () => api<T>(path), staleTime: 60_000 });
}

/** Mutation that toasts success/failure and refreshes lists and details. */
export function useApiMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { success?: string; onSuccess?: (res: TRes, vars: TVars) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      qc.invalidateQueries({ queryKey: ["list"] });
      qc.invalidateQueries({ queryKey: ["detail"] });
      qc.invalidateQueries({ queryKey: ["options"] });
      if (opts.success) toast.success(opts.success);
      opts.onSuccess?.(res, vars);
    },
  });
}

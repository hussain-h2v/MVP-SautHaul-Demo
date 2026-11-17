"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, ApiError } from "./api";
import type { UserOut } from "./types";

export const ME_KEY = ["me"] as const;

export function useMe() {
  return useQuery<UserOut | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api<UserOut>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) => api<UserOut>("/auth/login", { method: "POST", body }),
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      qc.clear();
      qc.setQueryData(ME_KEY, null);
      router.replace("/login");
    },
  });
}

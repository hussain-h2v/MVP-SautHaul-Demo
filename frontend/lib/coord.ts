"use client";

import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";
import { api, ApiError } from "./api";
import type { InboxItem, InboxKind, PersonRef } from "./coord-types";

/** All coordinator server state lives under the "coord" query key so SSE `inbox.changed` refreshes it. */
export function useCoordQuery<T>(
  path: string | null,
  opts: Partial<Pick<UseQueryOptions<T>, "refetchInterval" | "staleTime" | "enabled">> = {},
) {
  const { enabled = true, ...rest } = opts;
  return useQuery<T>({ queryKey: ["coord", path], queryFn: () => api<T>(path as string), enabled: !!path && enabled, ...rest });
}

export function useCoordMutation<TVars, TRes = unknown>(
  fn: (vars: TVars) => Promise<TRes>,
  opts: { success?: string; onSuccess?: (res: TRes, vars: TVars) => void; onError?: (e: unknown) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation<TRes, unknown, TVars>({
    mutationFn: fn,
    onSuccess: (res, vars) => {
      for (const k of ["coord", "fac", "list", "detail", "options", "notifications"]) qc.invalidateQueries({ queryKey: [k] });
      if (opts.success) toast.success(opts.success);
      opts.onSuccess?.(res, vars);
    },
    onError: (e) => {
      if (opts.onError) opts.onError(e);
    },
  });
}

// ---------------------------------------------------------------- pure helpers (unit tested)

export const PRIORITY_RANK: Record<string, number> = { CRITICAL: 4, HIGH: 3, NORMAL: 2, LOW: 1 };

/** Inbox order: priority (CRITICAL first), then oldest first so nothing waits behind newer work. Stable for ties. */
export function sortInbox<T extends { priority_code: string | null; created_at: string }>(items: readonly T[]): T[] {
  return items
    .map((item, i) => ({ item, i }))
    .sort((a, b) => {
      const pa = PRIORITY_RANK[a.item.priority_code ?? ""] ?? 0;
      const pb = PRIORITY_RANK[b.item.priority_code ?? ""] ?? 0;
      if (pa !== pb) return pb - pa;
      const ta = new Date(a.item.created_at).getTime();
      const tb = new Date(b.item.created_at).getTime();
      if (ta !== tb) return ta - tb;
      return a.i - b.i;
    })
    .map((x) => x.item);
}

export type CountdownTone = "ok" | "warn" | "danger" | "expired";

/** Hold countdown colour: amber under 5 minutes, red under 1, "expired" at or below zero. */
export function countdownTone(secondsLeft: number): CountdownTone {
  if (secondsLeft <= 0) return "expired";
  if (secondsLeft < 60) return "danger";
  if (secondsLeft < 300) return "warn";
  return "ok";
}

export function secondsLeft(expiresAt: string, now: number): number {
  return Math.floor((new Date(expiresAt).getTime() - now) / 1000);
}

export const MIN_OVERRIDE_REASON = 10;

export type DecisionCheck = { ok: true; overrode: boolean } | { ok: false; error: "noWinner" | "reasonRequired" };

/** Choosing anyone but the policy's top-ranked request is a manual override and needs a written reason (>= 10 chars). */
export function validateCompetingDecision(input: {
  winnerId: string | null;
  policyWinnerId: string | null;
  reason: string;
}): DecisionCheck {
  if (!input.winnerId) return { ok: false, error: "noWinner" };
  const overrode = input.policyWinnerId !== null && input.winnerId !== input.policyWinnerId;
  if (overrode && input.reason.trim().length < MIN_OVERRIDE_REASON) return { ok: false, error: "reasonRequired" };
  return { ok: true, overrode };
}

/** Where an inbox row leads. */
export function inboxHref(item: Pick<InboxItem, "kind" | "id" | "shipment_code">): string {
  switch (item.kind) {
    case "request":
      return `/coordinator/requests/${item.id}`;
    case "escalation":
      return `/coordinator/escalations/${item.id}`;
    case "hold":
      return "/coordinator/holds";
    case "exception":
    case "failed_message":
      return `/coordinator/conversations${item.shipment_code ? `?q=${encodeURIComponent(item.shipment_code)}` : ""}`;
    case "eta_change":
    default:
      return "/coordinator/board";
  }
}

export function nextIndex(current: number, delta: number, length: number): number {
  if (length <= 0) return -1;
  if (current < 0) return delta > 0 ? 0 : length - 1;
  return Math.min(length - 1, Math.max(0, current + delta));
}

export function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Single-key shortcuts: ignored while typing, with modifier keys, or while a dialog is open. */
export function useHotkeys(map: Record<string, () => void>, enabled = true) {
  const ref = React.useRef(map);
  ref.current = map;
  React.useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
      if (document.querySelector("[role='dialog']")) return;
      const fn = ref.current[e.key.toLowerCase()];
      if (fn) {
        e.preventDefault();
        fn();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}

export const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  hi: "हिन्दी (Hindi)",
  te: "తెలుగు (Telugu)",
  mr: "मराठी (Marathi)",
  gu: "ગુજરાતી (Gujarati)",
  pa: "ਪੰਜਾਬੀ (Punjabi)",
  ta: "தமிழ் (Tamil)",
  kn: "ಕನ್ನಡ (Kannada)",
  bn: "বাংলা (Bengali)",
};

export function languageName(code: string | null | undefined): string {
  return (code && LANGUAGE_NAMES[code]) || code || "—";
}

/** Error codes the coordinator flows must explain clearly (besides the SLOT_* ones in lib/problems.ts). */
export const COORD_ERROR_CODES = ["REQUEST_CLOSED", "CLAIMED", "HOLD_EXPIRED", "HOLD_RELEASED", "NO_HOLD", "SHIPMENT_CLOSED"] as const;

export function claimedByFrom(e: unknown): PersonRef | null {
  if (e instanceof ApiError && e.code === "CLAIMED") {
    const c = e.details?.claimed_by as PersonRef | undefined;
    return c ?? { id: "", name: "" };
  }
  return null;
}

// ---------------------------------------------------------------- alert preferences (sound / desktop notifications)

export interface AlertPrefs {
  sound: boolean;
  desktop: boolean;
}

const PREFS_KEY = "sh.coord.alerts";

export function loadPrefs(): AlertPrefs {
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<AlertPrefs>;
      return { sound: !!p.sound, desktop: !!p.desktop };
    }
  } catch {
    /* storage unavailable */
  }
  return { sound: false, desktop: false };
}

export function savePrefs(p: AlertPrefs): void {
  try {
    window.localStorage.setItem(PREFS_KEY, JSON.stringify(p));
  } catch {
    /* ignore */
  }
}

/** Short two-tone beep via WebAudio; no audio assets needed. */
export function beep(): void {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const tone = (freq: number, start: number) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + start);
      g.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + start + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + 0.25);
      o.connect(g).connect(ctx.destination);
      o.start(ctx.currentTime + start);
      o.stop(ctx.currentTime + start + 0.3);
    };
    tone(880, 0);
    tone(1175, 0.2);
    setTimeout(() => void ctx.close(), 800);
  } catch {
    /* audio blocked until a user gesture */
  }
}

// ---------------------------------------------------------------- soft claim (two coordinators never work the same item)

export type ClaimState = { status: "pending" } | { status: "mine" } | { status: "other"; owner: PersonRef } | { status: "error" };

const RENEW_MS = 4 * 60 * 1000;

/** Claims the item on mount, renews every 4 minutes, releases on leave. `other` means someone else is handling it. */
export function useClaim(kind: InboxKind, id: string | null, enabled = true): ClaimState {
  const [state, setState] = React.useState<ClaimState>({ status: "pending" });
  React.useEffect(() => {
    if (!id || !enabled) return;
    let cancelled = false;
    let mine = false;
    const claim = async () => {
      try {
        await api("/coordinator/claim", { method: "POST", body: { kind, id } });
        mine = true;
        if (!cancelled) setState({ status: "mine" });
      } catch (e) {
        const owner = claimedByFrom(e);
        if (!cancelled) setState(owner ? { status: "other", owner } : { status: "error" });
      }
    };
    void claim();
    const timer = setInterval(() => void claim(), RENEW_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
      if (mine) void api("/coordinator/release", { method: "POST", body: { kind, id } }).catch(() => undefined);
    };
  }, [kind, id, enabled]);
  return state;
}

export function toastError(message: string): void {
  toast.error(message);
}

"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { ApiError } from "@/lib/api";
import { claimedByFrom, countdownTone, COORD_ERROR_CODES, secondsLeft } from "@/lib/coord";
import { describeMoveError, describeProblem, type Tr } from "@/lib/problems";
import { cn } from "@/lib/utils";

/** Coordinator copy lives under `coord`; rule/problem codes come from `facility.problems`. */
export function useCoordText() {
  const tc = useTranslations("coord") as unknown as Tr;
  const tf = useTranslations("facility") as unknown as Tr;
  return { tc, tf };
}

/** Plain-language text for any failed decision call. */
export function describeCoordError(e: unknown, tc: Tr, tf: Tr): string {
  if (e instanceof ApiError) {
    if (e.code === "SLOT_UNAVAILABLE" || e.code === "SLOT_TAKEN" || e.code === "FIXED_IN_PROGRESS") return describeMoveError(e, tf);
    if (e.code === "CLAIMED") {
      const who = claimedByFrom(e)?.name;
      return who ? tc("errors.CLAIMED", { name: who }) : tc("errors.CLAIMEDGeneric");
    }
    if ((COORD_ERROR_CODES as readonly string[]).includes(e.code)) return tc(`errors.${e.code}`);
    return e.message || tc("errors.generic");
  }
  return tc("errors.generic");
}

export function PriorityBadge({ code }: { code: string | null | undefined }) {
  const { tc } = useCoordText();
  if (!code) return null;
  const tone = code === "CRITICAL" ? "danger" : code === "HIGH" ? "warning" : code === "LOW" ? "neutral" : "accent";
  return <Badge tone={tone}>{tc(`priority.${code}`)}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  const t = useTranslations("coord");
  const key = status.toLowerCase();
  const tone =
    key === "waiting" || key === "open" || key === "in_progress" || key === "failed"
      ? "warning"
      : key === "approved" || key === "resolved"
        ? "success"
        : key === "rejected" || key === "expired" || key === "escalated"
          ? "danger"
          : "accent";
  return <Badge tone={tone}>{t.has(`status.${key}`) ? t(`status.${key}`) : status.replace(/_/g, " ").toLowerCase()}</Badge>;
}

/** Live mm:ss countdown, amber under 5 min and red under 1. Colour is never the only signal (text + icon glyph). */
export function CountdownBadge({ expiresAt, now }: { expiresAt: string; now: number }) {
  const { tc } = useCoordText();
  const s = secondsLeft(expiresAt, now);
  const tone = countdownTone(s);
  const text = tone === "expired" ? tc("holds.expired") : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const glyph = tone === "danger" ? "⚠ " : tone === "warn" ? "◔ " : tone === "expired" ? "✕ " : "";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium tabular-nums",
        tone === "ok" && "bg-accent-soft text-accent",
        tone === "warn" && "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
        (tone === "danger" || tone === "expired") && "bg-danger/10 text-danger",
      )}
    >
      {glyph}
      {text}
    </span>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-[11px] text-muted">{children}</kbd>
  );
}

export function ReasonCodes({ codes, className }: { codes: string[]; className?: string }) {
  const { tf } = useCoordText();
  if (codes.length === 0) return null;
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)}>
      {codes.map((c) => (
        <li key={c}>
          <Badge tone={c.startsWith("NEEDS_PLANNER") ? "warning" : "neutral"}>{describeProblem(c, tf)}</Badge>
        </li>
      ))}
    </ul>
  );
}

/**
 * Confirmation summary for every decision: what will happen, to whom, and in which language the driver is told.
 * Children render the summary lines and any input (reason, minutes...).
 */
export function DecisionDialog({
  open,
  onClose,
  title,
  description,
  confirmLabel,
  onConfirm,
  pending,
  disabled,
  destructive,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
  disabled?: boolean;
  destructive?: boolean;
  children: React.ReactNode;
}) {
  const t = useTranslations("common");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      size="md"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={pending || disabled}
            className={destructive ? "bg-danger text-white hover:opacity-90" : undefined}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">{children}</div>
    </Dialog>
  );
}

export function SummaryList({ rows }: { rows: { label: string; value: React.ReactNode }[] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 rounded-md border border-border bg-background px-4 py-3">
      {rows.map((r, i) => (
        <React.Fragment key={i}>
          <dt className="text-xs font-medium uppercase tracking-wider text-muted">{r.label}</dt>
          <dd>{r.value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

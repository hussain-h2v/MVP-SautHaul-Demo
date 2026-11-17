"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/fields";
import { addDays, todayIn } from "@/lib/time";
import { cn } from "@/lib/utils";

/** Loading / error / empty wrapper for a react-query result. */
export function QueryState({
  isLoading,
  isError,
  onRetry,
  empty,
  emptyText,
  children,
}: {
  isLoading: boolean;
  isError: boolean;
  onRetry?: () => void;
  empty?: boolean;
  emptyText?: string;
  children: React.ReactNode;
}) {
  const c = useTranslations("common");
  if (isLoading)
    return (
      <div role="status" aria-label={c("loading")} className="space-y-2">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
    );
  if (isError)
    return (
      <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        {c("loadFailed")}{" "}
        {onRetry && (
          <button type="button" className="font-medium underline" onClick={onRetry}>
            {c("retry")}
          </button>
        )}
      </div>
    );
  if (empty) return <p className="rounded-md border border-dashed border-border py-10 text-center text-sm text-muted">{emptyText}</p>;
  return <>{children}</>;
}

/** Previous / next / today + native date input + optional "jump to a date with data". */
export function DatePicker({
  value,
  onChange,
  tz,
  dates,
}: {
  value: string;
  onChange: (v: string) => void;
  tz?: string;
  dates?: string[];
}) {
  const t = useTranslations("facility.date");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="icon" aria-label={t("prev")} onClick={() => onChange(addDays(value, -1))}>
        <ChevronLeft className="size-4" aria-hidden="true" />
      </Button>
      <label className="sr-only" htmlFor="date-input">
        {t("label")}
      </label>
      <Input id="date-input" type="date" value={value} onChange={(e) => e.target.value && onChange(e.target.value)} className="w-40" />
      <Button variant="outline" size="icon" aria-label={t("next")} onClick={() => onChange(addDays(value, 1))}>
        <ChevronRight className="size-4" aria-hidden="true" />
      </Button>
      <Button variant="outline" onClick={() => onChange(todayIn(tz))}>
        {t("today")}
      </Button>
      {dates && dates.length > 0 && (
        <>
          <label className="sr-only" htmlFor="date-jump">
            {t("jump")}
          </label>
          <Select id="date-jump" className="w-44" value="" onChange={(e) => e.target.value && onChange(e.target.value)}>
            <option value="">{t("jump")}</option>
            {[...dates].sort().reverse().slice(0, 60).map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </>
      )}
    </div>
  );
}

export function KeyValue({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <dt className="text-xs font-medium uppercase tracking-wider text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

export function TableShell({ caption, children, className }: { caption: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto rounded-xl border border-border bg-surface", className)}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export const th = "px-4 py-3 text-xs font-medium uppercase tracking-wider text-muted";
export const td = "px-4 py-3 align-top";

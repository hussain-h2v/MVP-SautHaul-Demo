"use client";

import { Check, CheckCheck, Clock, Copy, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/card";
import { deliveryTicks, STATUS_TONE } from "@/lib/wa";
import { cn } from "@/lib/utils";

export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function QueryState({
  isLoading,
  error,
  empty,
  emptyText,
  onRetry,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  empty?: boolean;
  emptyText?: string;
  onRetry?: () => void;
  children: React.ReactNode;
}) {
  const t = useTranslations("wa");
  if (isLoading)
    return (
      <div role="status" aria-label={t("g.loading")} className="space-y-3">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-2/3" />
      </div>
    );
  if (error)
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        <span>{t("g.error")}</span>
        {onRetry && (
          <Button size="sm" variant="outline" onClick={onRetry}>
            {t("g.retry")}
          </Button>
        )}
      </div>
    );
  if (empty) return <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted">{emptyText ?? t("g.empty")}</p>;
  return <>{children}</>;
}

/** Delivery or approval status as a badge: always text plus an icon, never colour alone. */
export function StatusBadge({ status, kind = "status" }: { status: string; kind?: "status" | "approval" }) {
  const t = useTranslations("wa");
  const label = t.has(`${kind}.${status}` as never) ? t(`${kind}.${status}` as never) : status;
  const Icon = status === "failed" || status === "rejected" ? TriangleAlert : status === "delivered" || status === "read" || status === "approved" ? CheckCheck : Check;
  return (
    <Badge tone={STATUS_TONE[status] ?? "neutral"} className="gap-1">
      <Icon className="size-3" aria-hidden="true" />
      {label}
    </Badge>
  );
}

/** WhatsApp-style ticks with a screen-reader label. */
export function Ticks({ status }: { status: string }) {
  const t = useTranslations("wa");
  const { ticks, read } = deliveryTicks(status);
  const label = status === "pending" ? t("sim.pendingMark") : status === "failed" ? t("sim.failedTick") : status === "read" ? t("sim.readTick") : status === "delivered" ? t("sim.deliveredTick") : t("sim.sentTick");
  if (status === "failed")
    return (
      <span className="inline-flex items-center text-danger" title={label}>
        <TriangleAlert className="size-3.5" aria-hidden="true" />
        <span className="sr-only">{label}</span>
      </span>
    );
  if (ticks === 0)
    return (
      <span className="inline-flex items-center text-muted" title={label}>
        <Clock className="size-3.5" aria-hidden="true" />
        <span className="sr-only">{label}</span>
      </span>
    );
  const Icon = ticks === 2 ? CheckCheck : Check;
  return (
    <span className={cn("inline-flex items-center", read ? "text-accent" : "text-muted")} title={label}>
      <Icon className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function CopyButton({ value, label }: { value: string; label: string }) {
  const t = useTranslations("wa");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("g.copied"));
    } catch {
      toast.error(t("g.error"));
    }
  };
  return (
    <Button size="sm" variant="outline" onClick={copy} aria-label={`${t("g.copy")}: ${label}`}>
      <Copy className="size-3.5" aria-hidden="true" />
      {t("g.copy")}
    </Button>
  );
}

export function Pager({ total, offset, limit, onChange }: { total: number; offset: number; limit: number; onChange: (offset: number) => void }) {
  const t = useTranslations("wa");
  if (total <= limit) return null;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  return (
    <nav aria-label={t("g.range", { from, to, total })} className="mt-3 flex items-center justify-between text-sm">
      <span className="text-muted" aria-live="polite">
        {t("g.range", { from, to, total })}
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          {t("g.prev")}
        </Button>
        <Button size="sm" variant="outline" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
          {t("g.next")}
        </Button>
      </div>
    </nav>
  );
}

export function LangChip({ code }: { code: string | null | undefined }) {
  if (!code) return <span className="text-muted">—</span>;
  return <span className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-xs uppercase">{code}</span>;
}

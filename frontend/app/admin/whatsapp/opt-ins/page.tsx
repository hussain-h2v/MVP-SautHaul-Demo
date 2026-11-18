"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { DataTableLite, SectionHeader } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { QueryState } from "@/components/wa/common";
import { formatDateTime } from "@/lib/format";
import { qs, waPost, useWa, useWaMutation } from "@/lib/wa-api";
import type { WaOptIn } from "@/lib/wa-types";
import { cn } from "@/lib/utils";

type Filter = "opted_out" | "opted_in" | "";

export default function OptInsPage() {
  const t = useTranslations("wa");
  const [state, setState] = React.useState<Filter>("opted_out");
  const [target, setTarget] = React.useState<WaOptIn | null>(null);
  const q = useWa<WaOptIn[]>(`/opt-ins${qs({ state })}`);
  const items = q.data ?? [];
  const toggle = useWaMutation((row: WaOptIn) => waPost(`/opt-ins/${row.driver_id}`, { opted_in: row.state === "opted_out" }), {
    success: t("oi.done"),
    onSuccess: () => setTarget(null),
  });
  const tabs: { value: Filter; label: string }[] = [
    { value: "opted_out", label: t("oi.optedOut") },
    { value: "opted_in", label: t("oi.optedIn") },
    { value: "", label: t("oi.all") },
  ];
  const optingIn = target?.state === "opted_out";
  return (
    <>
      <SectionHeader title={t("oi.title")} description={t("oi.description")} />
      <div role="group" aria-label={t("oi.state")} className="mb-4 inline-flex rounded-lg border border-border p-0.5">
        {tabs.map((tab) => (
          <button
            key={tab.value}
            type="button"
            aria-pressed={state === tab.value}
            onClick={() => setState(tab.value)}
            className={cn("rounded-md px-3 py-1.5 text-sm", state === tab.value ? "bg-accent text-accent-foreground" : "text-muted hover:text-foreground")}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <QueryState isLoading={q.isLoading} error={q.error} empty={!items.length} emptyText={t("oi.empty")} onRetry={() => q.refetch()}>
        <DataTableLite caption={t("oi.title")} head={[t("oi.driver"), t("oi.carrier"), t("oi.number"), t("oi.state"), t("oi.lastEvent"), ""]}>
          {items.map((r) => (
            <tr key={r.driver_id} className="align-top">
              <td className="px-4 py-3 font-medium">{r.driver_name}</td>
              <td className="px-4 py-3">{r.carrier_name}</td>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">
                {r.whatsapp_number ?? "—"}
                {!r.verified && <Badge className="ml-2">{t("oi.unverified")}</Badge>}
              </td>
              <td className="px-4 py-3">
                <Badge tone={r.state === "opted_in" ? "success" : "warning"}>{r.state === "opted_in" ? t("oi.optedIn") : t("oi.optedOut")}</Badge>
              </td>
              <td className="px-4 py-3 text-xs text-muted">
                {r.last_event ? `${r.last_event} · ${r.source ?? ""} · ${formatDateTime(r.last_event_at)}` : "—"}
              </td>
              <td className="px-4 py-3 text-right">
                <Button size="sm" variant="outline" onClick={() => setTarget(r)}>
                  {r.state === "opted_out" ? t("oi.optIn") : t("oi.optOut")}
                </Button>
              </td>
            </tr>
          ))}
        </DataTableLite>
      </QueryState>
      <ConfirmDialog
        open={!!target}
        onClose={() => setTarget(null)}
        onConfirm={() => target && toggle.mutate(target)}
        title={optingIn ? t("oi.confirmInTitle") : t("oi.confirmOutTitle")}
        message={optingIn ? t("oi.confirmInBody") : t("oi.confirmOutBody")}
        confirmLabel={optingIn ? t("oi.optIn") : t("oi.optOut")}
        destructive={!optingIn}
        pending={toggle.isPending}
      />
    </>
  );
}

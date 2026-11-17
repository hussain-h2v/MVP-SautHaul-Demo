"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { StatusBadge } from "@/components/coordinator/shared";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useCoordQuery } from "@/lib/coord";
import type { Escalation } from "@/lib/coord-types";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";

const TABS = ["open", "in_progress", "resolved", ""] as const;

export default function EscalationsPage() {
  const t = useTranslations("coord.escalations");
  const locale = useLocale();
  const [status, setStatus] = React.useState<string>("open");
  const q = useCoordQuery<Escalation[]>(`/coordinator/escalations${buildQuery({ status, limit: 100 })}`, { refetchInterval: 30_000 });
  const rows = q.data ?? [];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label={t("filter")}>
        {TABS.map((s) => (
          <Button key={s || "all"} role="tab" aria-selected={status === s} size="sm" variant={status === s ? "primary" : "outline"} onClick={() => setStatus(s)}>
            {s ? t(`tab.${s}`) : t("tab.all")}
          </Button>
        ))}
      </div>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border text-left">
              <th className={th}>{t("shipment")}</th>
              <th className={th}>{t("reason")}</th>
              <th className={th}>{t("driver")}</th>
              <th className={th}>{t("assignee")}</th>
              <th className={th}>{t("status")}</th>
              <th className={th}>{t("opened")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((e) => (
              <tr key={e.id} className="hover:bg-accent-soft">
                <td className={td}>
                  <Link href={`/coordinator/escalations/${e.id}`} className="font-mono font-medium text-accent underline">
                    {e.shipment_code ?? e.id.slice(0, 8)}
                  </Link>
                  <span className="block text-xs text-muted">{e.carrier_name}</span>
                </td>
                <td className={td}>{t.has(`reasonCode.${e.reason_code}`) ? t(`reasonCode.${e.reason_code}`) : e.reason_code}</td>
                <td className={td}>{e.driver_name ?? "—"}</td>
                <td className={td}>{e.assigned_to?.name ?? t("unassigned")}</td>
                <td className={td}>
                  <StatusBadge status={e.status} />
                </td>
                <td className={td + " text-muted"}>{formatDateTime(e.created_at, locale)}</td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>
    </>
  );
}

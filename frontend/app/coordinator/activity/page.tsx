"use client";

import { useLocale, useTranslations } from "next-intl";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/card";
import { useCoordQuery } from "@/lib/coord";
import type { ActivityRow } from "@/lib/coord-types";
import { formatDateTime } from "@/lib/format";

export default function ActivityPage() {
  const t = useTranslations("coord.activity");
  const locale = useLocale();
  const q = useCoordQuery<ActivityRow[]>("/coordinator/activity?limit=100", { refetchInterval: 60_000 });
  const rows = q.data ?? [];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border text-left">
              <th className={th}>{t("when")}</th>
              <th className={th}>{t("entity")}</th>
              <th className={th}>{t("action")}</th>
              <th className={th}>{t("summary")}</th>
              <th className={th}>{t("outcome")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r, i) => (
              <tr key={`${r.ts}-${i}`}>
                <td className={td + " whitespace-nowrap text-muted"}>{formatDateTime(r.ts, locale)}</td>
                <td className={td}>{r.entity.replace(/_/g, " ")}</td>
                <td className={td}>
                  <Badge tone="neutral">{r.action}</Badge>
                </td>
                <td className={td}>{r.summary}</td>
                <td className={td}>{r.outcome ? <Badge tone="accent">{r.outcome}</Badge> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>
    </>
  );
}

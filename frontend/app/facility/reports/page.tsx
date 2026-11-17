"use client";

import { Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { downloadCsv } from "@/lib/api";
import { apiErrorText, qs, useFacQuery } from "@/lib/fac";
import type { FacilitySummary, ReportResult } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { addDays, todayIn } from "@/lib/time";
import { cn } from "@/lib/utils";

const KINDS = ["utilisation", "detention", "overrun", "noshow"] as const;
type Kind = (typeof KINDS)[number];
const ISO = /^\d{4}-\d{2}-\d{2}T/;

function cell(v: unknown, locale: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string" && ISO.test(v)) return formatDateTime(v, locale);
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  return String(v);
}

function ReportsView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.reports");
  const locale = useLocale();
  const today = todayIn(facility.timezone);
  const [kind, setKind] = React.useState<Kind>("utilisation");
  const [from, setFrom] = React.useState(addDays(today, -6));
  const [to, setTo] = React.useState(today);
  const params = { facility_id: facility.id, date_from: from, date_to: to, kind };
  const q = useFacQuery<ReportResult>(`/reports/facility${qs(params)}`);
  const rows = q.data?.rows ?? [];

  const exportCsv = async () => {
    try {
      await downloadCsv(`/reports/facility/export.csv${qs(params)}`, `${facility.code}-${kind}-${from}-${to}.csv`);
    } catch (e) {
      toast.error(apiErrorText(e));
    }
  };

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="outline" onClick={exportCsv} disabled={rows.length === 0}>
            <Download className="size-4" aria-hidden="true" />
            {t("export")}
          </Button>
        }
      />
      <div role="tablist" aria-label={t("kind")} className="mb-4 flex flex-wrap gap-1 border-b border-border">
        {KINDS.map((k) => (
          <button
            key={k}
            role="tab"
            id={`rep-${k}`}
            aria-selected={kind === k}
            aria-controls="rep-panel"
            tabIndex={kind === k ? 0 : -1}
            onClick={() => setKind(k)}
            onKeyDown={(e) => {
              const i = KINDS.indexOf(kind);
              if (e.key === "ArrowRight") setKind(KINDS[(i + 1) % KINDS.length]);
              if (e.key === "ArrowLeft") setKind(KINDS[(i + KINDS.length - 1) % KINDS.length]);
            }}
            className={cn("-mb-px border-b-2 px-4 py-2 text-sm font-medium", kind === k ? "border-accent text-accent" : "border-transparent text-muted hover:text-foreground")}
          >
            {t(`kinds.${k}`)}
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("from")} htmlFor="rep-from">
          <Input id="rep-from" type="date" className="w-44" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        </Field>
        <Field label={t("to")} htmlFor="rep-to">
          <Input id="rep-to" type="date" className="w-44" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} />
        </Field>
      </div>
      <div role="tabpanel" id="rep-panel" aria-labelledby={`rep-${kind}`}>
        <p className="mb-3 text-sm text-muted">{t(`hint.${kind}`)}</p>
        <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
          {q.data && (
            <TableShell caption={t(`kinds.${kind}`)}>
              <thead>
                <tr className="border-b border-border">
                  {q.data.columns.map((c) => (
                    <th key={c} scope="col" className={th}>
                      {t.has(`cols.${c}` as "cols.dock") ? t(`cols.${c}` as "cols.dock") : c.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border last:border-b-0">
                    {q.data!.columns.map((c) => (
                      <td key={c} className={`${td} tabular-nums`}>
                        {cell(r[c], locale)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </TableShell>
          )}
        </QueryState>
      </div>
    </>
  );
}

export default function ReportsPage() {
  return <RequireFacility>{(f) => <ReportsView key={f.id} facility={f} />}</RequireFacility>;
}

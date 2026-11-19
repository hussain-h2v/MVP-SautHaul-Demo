"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { ViewPage } from "@/components/insights/view-page";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api, downloadCsv } from "@/lib/api";
import { toCsvFilename } from "@/lib/carrier";
import type { ReportResult } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";
import { addDays, todayIn } from "@/lib/time";
import { errorMessage } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const KINDS = ["shipments", "delays", "detention"] as const;
type Kind = (typeof KINDS)[number];
const ISO = /^\d{4}-\d{2}-\d{2}T/;

function cell(v: unknown, locale: string): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string" && ISO.test(v)) return formatDateTime(v, locale);
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(1);
  return String(v);
}

export default function CarrierReportsPage() {
  const t = useTranslations("carrier.reports");
  const locale = useLocale();
  const today = todayIn();
  const [kind, setKind] = React.useState<Kind>("shipments");
  const [from, setFrom] = React.useState(addDays(today, -29));
  const [to, setTo] = React.useState(today);
  const params = { kind, date_from: from, date_to: to };
  const q = useQuery<ReportResult>({
    queryKey: ["carrier", "report", kind, from, to],
    queryFn: () => api<ReportResult>(`/reports/carrier${buildQuery(params)}`),
  });
  const rows = q.data?.rows ?? [];

  const exportCsv = async () => {
    try {
      await downloadCsv(`/reports/carrier/export.csv${buildQuery(params)}`, toCsvFilename(kind, from, to));
    } catch (e) {
      toast.error(errorMessage(e, t("exportFailed")));
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
      <section aria-label={t("analytics")} className="mb-10 space-y-6">
        <h2 className="text-lg font-semibold">{t("analytics")}</h2>
        <ViewPage
          view="carrier" filenameBase="carrier" narrative={false}
          kpis={["arrivals", "on_time_rate", "late", "delay_reports", "avg_declared_delay_min", "no_show_rate", "slot_moves", "decline_rate"]}
          charts={["arrivals"]} csv={["series", "by_driver", "by_lane"]}
        />
      </section>
      <h2 className="mb-3 text-lg font-semibold">{t("detailTitle")}</h2>
      <div role="tablist" aria-label={t("kind")} className="mb-4 flex flex-wrap gap-1 border-b border-border">
        {KINDS.map((k) => (
          <button
            key={k}
            role="tab"
            id={`crep-${k}`}
            aria-selected={kind === k}
            aria-controls="crep-panel"
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
        <Field label={t("from")} htmlFor="crep-from">
          <Input id="crep-from" type="date" className="w-44" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        </Field>
        <Field label={t("to")} htmlFor="crep-to">
          <Input id="crep-to" type="date" className="w-44" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} />
        </Field>
      </div>
      <div role="tabpanel" id="crep-panel" aria-labelledby={`crep-${kind}`}>
        <p className="mb-3 text-sm text-muted">{t(`hint.${kind}`)}</p>
        <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
          {q.data && (
            <TableShell caption={t(`kinds.${kind}`)}>
              <thead>
                <tr className="border-b border-border">
                  {q.data.columns.map((col) => (
                    <th key={col} scope="col" className={th}>
                      {t.has(`cols.${col}`) ? t(`cols.${col}`) : col.replace(/_/g, " ")}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-border last:border-b-0">
                    {q.data!.columns.map((col) => (
                      <td key={col} className={`${td} tabular-nums`}>
                        {cell(r[col], locale)}
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

"use client";

import { useQuery } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { QueryStateBlock } from "@/components/insights/query-state";
import { Badge, Card } from "@/components/ui/card";
import { Field } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { qs, type Proposal } from "@/lib/insights";
import { addDays, todayIn } from "@/lib/time";

const CARDS = ["current", "fcfs", "proposed"] as const;

function hhmm(iso: string | null): string {
  return iso ? formatDateTime(iso).replace(/^.*?,\s*/, "") : "—";
}

/** Read-only schedule proposal. Nothing here can change a booking; the planner applies any move from the schedule grid. */
export function OptimiserPanel({ facilityId, timezone }: { facilityId: string; timezone: string }) {
  const t = useTranslations("insights.optimiser");
  const [day, setDay] = React.useState(addDays(todayIn(timezone), 1));
  const path = `/insights/optimiser/proposal${qs({ facility_id: facilityId, day })}`;
  const q = useQuery<Proposal>({ queryKey: ["insights", path], queryFn: () => api<Proposal>(path) });
  const p = q.data;
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Lightbulb className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
          <div>
            <h3 className="font-medium">{t("title")}</h3>
            <p className="max-w-2xl text-sm text-muted">{t("description")}</p>
          </div>
        </div>
        <Field label={t("day")} htmlFor="opt-day"><Input id="opt-day" type="date" className="w-44" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} /></Field>
      </div>
      <p className="rounded-md bg-background px-3 py-2 text-xs text-muted" role="note">{t("proposalOnly")}</p>
      <QueryStateBlock isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
        {p && p.movable === 0 && <p className="text-sm text-muted">{p.note === "no_slots" ? t("noSlots") : t("nothingMovable")}</p>}
        {p && p.movable > 0 && (
          <>
            <p className="text-sm">
              {p.better_than_current ? t("better", { n: p.saved_weighted_wait ?? 0 }) : t("noBetter")} <span className="text-muted">{t("movable", { n: p.movable })}</span>
            </p>
            <div className="grid gap-3 sm:grid-cols-3">
              {CARDS.map((k) => {
                const c = p.scorecards[k];
                return (
                  <div key={k} className={`rounded-lg border px-3 py-2 ${k === "proposed" ? "border-accent bg-accent-soft" : "border-border"}`}>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted">{t(`card.${k}`)}</p>
                    <dl className="mt-1 space-y-0.5 text-sm">
                      <div className="flex justify-between"><dt className="text-muted">{t("totalWait")}</dt><dd className="tabular-nums">{c.total_wait_min} min</dd></div>
                      <div className="flex justify-between"><dt className="text-muted">{t("weighted")}</dt><dd className="tabular-nums">{c.priority_weighted_wait}</dd></div>
                      <div className="flex justify-between"><dt className="text-muted">{t("highWait")}</dt><dd className="tabular-nums">{c.high_priority_wait_min} min</dd></div>
                      <div className="flex justify-between"><dt className="text-muted">{t("maxWait")}</dt><dd className="tabular-nums">{c.max_wait_min} min</dd></div>
                      {k !== "current" && <div className="flex justify-between"><dt className="text-muted">{t("moved")}</dt><dd className="tabular-nums">{c.moved}</dd></div>}
                    </dl>
                  </div>
                );
              })}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{t("movesCaption")}</caption>
                <thead className="text-xs uppercase tracking-wide text-muted">
                  <tr>{["shipment", "priority", "eta", "from", "to", "waitNow", "waitAfter"].map((h) => <th key={h} scope="col" className="whitespace-nowrap py-1 pr-3 font-medium">{t(`col.${h}`)}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {p.moves.map((m) => (
                    <tr key={m.shipment}>
                      <td className="py-1.5 pr-3 font-medium">{m.shipment}</td>
                      <td className="py-1.5 pr-3"><Badge tone={m.priority === "CRITICAL" || m.priority === "HIGH" ? "warning" : "neutral"}>{m.priority.toLowerCase()}</Badge></td>
                      <td className="py-1.5 pr-3 tabular-nums">{hhmm(m.eta)}</td>
                      <td className="py-1.5 pr-3 tabular-nums">{m.from_dock} {hhmm(m.from_start)}</td>
                      <td className="py-1.5 pr-3 tabular-nums">{m.placed ? `${m.to_dock} ${hhmm(m.to_start)}` : t("unplaced")}{m.changes ? ` · ${t("changes")}` : ` · ${t("stays")}`}</td>
                      <td className="py-1.5 pr-3 tabular-nums">{m.wait_before_min ?? "—"} min</td>
                      <td className="py-1.5 pr-3 tabular-nums">{m.wait_after_min ?? "—"} min</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted">{t("rule")}</p>
          </>
        )}
      </QueryStateBlock>
    </Card>
  );
}

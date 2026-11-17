"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { DataTableLite, QueryState, SectionHeader } from "@/components/ai/common";
import { Card } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { formatMoney, formatRate, PALETTE } from "@/lib/ai";
import { qs, useAi } from "@/lib/ai-api";
import type { Usage } from "@/lib/ai-types";

type Group = "provider" | "model" | "task" | "day";

function isoDaysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </Card>
  );
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <h3 className="mb-3 text-sm font-medium">{title}</h3>
      <div className="h-56 w-full" role="img" aria-label={title}>
        <ResponsiveContainer width="100%" height="100%">
          {children as React.ReactElement}
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

export default function UsagePage() {
  const t = useTranslations("ai");
  const [from, setFrom] = React.useState(isoDaysAgo(30));
  const [to, setTo] = React.useState(isoDaysAgo(0));
  const [group, setGroup] = React.useState<Group>("day");
  const usage = useAi<Usage>(`/usage${qs({ date_from: from, date_to: to, group_by: group })}`);
  const rows = usage.data?.rows ?? [];
  const totals = usage.data?.totals;
  const pct = rows.map((r) => ({ ...r, error_pct: Math.round(r.error_rate * 1000) / 10, fallback_pct: Math.round(r.fallback_rate * 1000) / 10 }));

  return (
    <>
      <SectionHeader title={t("us.title")} description={t("us.description")} />
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Field label={t("g.fromDate")} htmlFor="us-from">
          <Input id="us-from" type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t("g.toDate")} htmlFor="us-to">
          <Input id="us-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </Field>
        <Field label={t("us.groupBy")} htmlFor="us-group">
          <Select id="us-group" value={group} onChange={(e) => setGroup(e.target.value as Group)}>
            {(["day", "provider", "model", "task"] as const).map((g) => (
              <option key={g} value={g}>
                {t(`us.g.${g}`)}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <QueryState isLoading={usage.isLoading} error={usage.error} empty={!!usage.data && rows.length === 0} onRetry={() => usage.refetch()}>
        {totals && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Kpi label={t("g.requests")} value={totals.requests.toLocaleString()} />
              <Kpi label={t("g.cost")} value={formatMoney(totals.cost)} />
              <Kpi label={t("us.p50")} value={`${totals.p50_ms} ms`} />
              <Kpi label={t("us.p95")} value={`${totals.p95_ms} ms`} />
              <Kpi label={t("us.tokensIn")} value={totals.tokens_in.toLocaleString()} />
              <Kpi label={t("us.tokensOut")} value={totals.tokens_out.toLocaleString()} />
              <Kpi label={t("us.errorRate")} value={formatRate(totals.error_rate)} />
              <Kpi label={t("us.fallbackRate")} value={formatRate(totals.fallback_rate)} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard title={t("us.chartRequests")}>
                <BarChart data={rows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="key" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="requests" fill={PALETTE[0]} name={t("g.requests")} />
                </BarChart>
              </ChartCard>
              <ChartCard title={t("us.chartCost")}>
                <BarChart data={rows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="key" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="cost" fill={PALETTE[1]} name={t("g.cost")} />
                </BarChart>
              </ChartCard>
              <ChartCard title={t("us.chartLatency")}>
                <LineChart data={rows}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="key" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="p50_ms" stroke={PALETTE[0]} strokeWidth={2} name={t("us.p50")} />
                  <Line type="monotone" dataKey="p95_ms" stroke={PALETTE[4]} strokeWidth={2} strokeDasharray="6 3" name={t("us.p95")} />
                </LineChart>
              </ChartCard>
              <ChartCard title={t("us.chartRates")}>
                <LineChart data={pct}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="key" />
                  <YAxis unit="%" />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="error_pct" stroke={PALETTE[4]} strokeWidth={2} name={t("us.errorRate")} />
                  <Line type="monotone" dataKey="fallback_pct" stroke={PALETTE[2]} strokeWidth={2} strokeDasharray="6 3" name={t("us.fallbackRate")} />
                </LineChart>
              </ChartCard>
            </div>
            <section aria-label={t("us.table")}>
              <h3 className="mb-2 text-sm font-medium">{t("us.table")}</h3>
              <DataTableLite
                caption={t("us.table")}
                head={[t("us.group"), t("g.requests"), t("us.tokensIn"), t("us.tokensOut"), t("g.cost"), t("us.p50"), t("us.p95"), t("us.errorRate"), t("us.fallbackRate")]}
              >
                {rows.map((r) => (
                  <tr key={r.key}>
                    <td className="px-4 py-2 font-medium">{r.key}</td>
                    <td className="px-4 py-2">{r.requests}</td>
                    <td className="px-4 py-2">{r.tokens_in}</td>
                    <td className="px-4 py-2">{r.tokens_out}</td>
                    <td className="px-4 py-2">{formatMoney(r.cost)}</td>
                    <td className="px-4 py-2">{r.p50_ms} ms</td>
                    <td className="px-4 py-2">{r.p95_ms} ms</td>
                    <td className="px-4 py-2">{formatRate(r.error_rate)}</td>
                    <td className="px-4 py-2">{formatRate(r.fallback_rate)}</td>
                  </tr>
                ))}
              </DataTableLite>
            </section>
          </div>
        )}
      </QueryState>
    </>
  );
}

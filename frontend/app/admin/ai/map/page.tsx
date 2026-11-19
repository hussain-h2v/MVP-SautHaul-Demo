"use client";

import { ArrowDown, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { QueryState, SectionHeader, useEnum } from "@/components/ai/common";
import { Badge, Card } from "@/components/ui/card";
import { formatMoney, formatRate } from "@/lib/ai";
import { useAi } from "@/lib/ai-api";
import type { MapItem, UsageMap } from "@/lib/ai-monitor-types";
import { formatDateTime } from "@/lib/format";

const tone = { wired: "success", planned: "neutral", reserved: "warning" } as const;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 py-1.5 text-sm sm:grid-cols-[9rem_1fr]">
      <dt className="text-muted">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function UseCard({ item }: { item: MapItem }) {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const s = item.last_30d;
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold">{item.title}</h3>
          <p className="text-xs text-muted">{task(item.task)} · {item.portal}</p>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={tone[item.status]}>{t(`map.status.${item.status}`)}</Badge>
          <Badge tone={item.route_enabled && item.route_steps > 0 ? "success" : "neutral"}>
            {item.route_steps > 0 ? t("map.route", { n: item.route_steps }) : t("map.noRoute")}
          </Badge>
        </div>
      </div>
      <dl className="divide-y divide-border/60">
        <Row label={t("map.where")} value={item.where} />
        <Row label={t("map.trigger")} value={item.trigger} />
        {item.status !== "reserved" && (
          <>
            <Row label={t("map.input")} value={item.input} />
            <Row label={t("map.output")} value={item.output} />
            <Row label={t("map.affects")} value={item.affects} />
            <Row label={t("map.cannot")} value={item.cannot} />
            <Row label={t("map.fallback")} value={item.fallback} />
          </>
        )}
      </dl>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-background px-3 py-2 text-xs">
        <span>{t("map.last30", { n: s.requests.toLocaleString(), cost: formatMoney(s.cost), ms: s.avg_ms })}</span>
        <span className="text-muted">{s.last_used ? t("map.lastUsed", { when: formatDateTime(s.last_used) }) : t("map.neverUsed")}{s.requests > 0 ? ` · ${t("us.errorRate")} ${formatRate(s.error_rate)}` : ""}</span>
        {s.requests > 0 && <Link className="text-accent hover:underline" href={`/admin/ai/logs?task=${item.task}&range=1m`}>{t("mon.viewLogs")}</Link>}
      </div>
    </Card>
  );
}

export default function UsageMapPage() {
  const t = useTranslations("ai");
  const q = useAi<UsageMap>("/usage-map");
  const d = q.data;
  const wired = d?.items.filter((i) => i.status === "wired") ?? [];
  const other = d?.items.filter((i) => i.status !== "wired") ?? [];
  return (
    <>
      <SectionHeader title={t("map.title")} description={t("map.description")} />
      <QueryState isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
        {d && (
          <div className="space-y-8">
            <section aria-label={t("map.flow")}>
              <h3 className="mb-3 text-sm font-medium">{t("map.flow")}</h3>
              <Card>
                <ol className="mx-auto max-w-2xl space-y-1.5">
                  {d.flow.map((step, i) => (
                    <li key={i}>
                      <div className="flex items-center gap-3 rounded-lg border border-border bg-background px-3 py-2 text-sm">
                        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{i + 1}</span>
                        {step}
                      </div>
                      {i < d.flow.length - 1 && <ArrowDown className="mx-auto my-0.5 size-4 text-muted" aria-hidden="true" />}
                    </li>
                  ))}
                </ol>
              </Card>
            </section>

            <section aria-label={t("map.guards")}>
              <h3 className="mb-3 text-sm font-medium">{t("map.guards")}</h3>
              <Card className="flex items-start gap-3">
                <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
                <ul className="list-disc space-y-1 pl-4 text-sm">{d.guards.map((g) => <li key={g}>{g}</li>)}</ul>
              </Card>
            </section>

            <section aria-label={t("map.inUse", { n: wired.length })}>
              <h3 className="mb-3 text-sm font-medium">{t("map.inUse", { n: wired.length })}</h3>
              <div className="space-y-4">{wired.map((i) => <UseCard key={i.task} item={i} />)}</div>
            </section>

            <section aria-label={t("map.notYet", { n: other.length })}>
              <h3 className="mb-1 text-sm font-medium">{t("map.notYet", { n: other.length })}</h3>
              <p className="mb-3 text-xs text-muted">{t("map.notYetNote")}</p>
              <div className="grid gap-4 xl:grid-cols-2">{other.map((i) => <UseCard key={i.task} item={i} />)}</div>
            </section>

            <section aria-label={t("map.tools")}>
              <h3 className="mb-3 text-sm font-medium">{t("map.tools")}</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                {d.admin_tools.map((x) => (
                  <Card key={x.name} className="!p-4">
                    <p className="font-medium">{x.name}</p>
                    <p className="text-xs text-muted">{x.where}</p>
                    <p className="mt-1 text-sm">{x.note}</p>
                  </Card>
                ))}
              </div>
            </section>
          </div>
        )}
      </QueryState>
    </>
  );
}

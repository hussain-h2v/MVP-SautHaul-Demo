"use client";

import { Gauge, Hourglass, PackageCheck, Truck, TriangleAlert, ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { QueryState } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Badge, Card } from "@/components/ui/card";
import { qs, useFacQuery } from "@/lib/fac";
import type { FacilityHome, FacilitySummary } from "@/lib/facility-types";

function Kpi({ icon: Icon, label, value, href, tone }: { icon: React.ElementType; label: string; value: React.ReactNode; href?: string; tone?: "warning" | "danger" }) {
  const body = (
    <Card className="h-full transition-colors hover:border-accent">
      <div className="flex items-center gap-2 text-sm text-muted">
        <Icon className="size-4" aria-hidden="true" />
        {label}
      </div>
      <p className={`mt-2 text-3xl font-semibold tabular-nums ${tone === "danger" ? "text-danger" : ""}`}>{value}</p>
    </Card>
  );
  return href ? (
    <Link href={href} className="block rounded-xl focus-visible:outline-2">
      {body}
    </Link>
  ) : (
    body
  );
}

function HomeView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.home");
  const f = useTranslations("facility");
  const q = useFacQuery<FacilityHome>(`/analytics/facility-home${qs({ facility_id: facility.id })}`, { refetchInterval: 60_000 });
  const d = q.data;
  return (
    <>
      <PageHeader title={facility.facility_name} description={t("description", { hours: `${facility.open_time}–${facility.close_time}` })} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()}>
        {d && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              <Kpi icon={Gauge} label={t("utilisation")} value={`${Math.round(d.utilisation_pct)}%`} href="/facility/schedule" />
              <Kpi icon={Truck} label={t("inbound")} value={d.inbound_count} href="/facility/inbound" />
              <Kpi icon={PackageCheck} label={t("inYard")} value={d.in_yard_count} href="/facility/yard" />
              <Kpi icon={ClipboardCheck} label={t("pending")} value={d.pending_confirmations} href="/facility/pending" tone={d.pending_confirmations > 0 ? "warning" : undefined} />
              <Kpi icon={Hourglass} label={t("holds")} value={d.active_holds} />
              <Kpi icon={TriangleAlert} label={t("exceptions")} value={d.open_exceptions} tone={d.open_exceptions > 0 ? "danger" : undefined} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <h2 className="font-semibold">{t("dockStatus")}</h2>
                <ul className="mt-3 flex flex-wrap gap-2">
                  <li>
                    <Badge tone="success">
                      {f("dockStatus.ACTIVE")}: {d.dock_status.active}
                    </Badge>
                  </li>
                  <li>
                    <Badge tone="warning">
                      {f("dockStatus.MAINTENANCE")}: {d.dock_status.maintenance}
                    </Badge>
                  </li>
                  <li>
                    <Badge tone="danger">
                      {f("dockStatus.OUT_OF_SERVICE")}: {d.dock_status.out_of_service}
                    </Badge>
                  </li>
                  <li>
                    <Badge>
                      {f("dockStatus.INACTIVE")}: {d.dock_status.inactive}
                    </Badge>
                  </li>
                </ul>
                <p className="mt-3 text-sm text-muted">
                  <Link href="/facility/events" className="underline">
                    {t("openEvents", { count: d.dock_status.events_open })}
                  </Link>
                </p>
              </Card>
              <Card>
                <h2 className="font-semibold">{t("insightsTitle")}</h2>
                <p className="mt-2 text-sm text-muted">{t("insightsBody")}</p>
                <Badge className="mt-3" tone="accent">
                  {t("milestone9")}
                </Badge>
              </Card>
            </div>
          </div>
        )}
      </QueryState>
    </>
  );
}

export default function FacilityHomePage() {
  return <RequireFacility>{(f) => <HomeView key={f.id} facility={f} />}</RequireFacility>;
}

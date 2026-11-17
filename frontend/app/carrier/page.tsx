"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, PackageSearch, ShieldAlert, Sparkles, Truck, UserCheck, Users, Warehouse } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { CarrierDashboard } from "@/lib/carrier-types";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

type Icon = React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;

function Kpi({ href, label, value, icon: Icon, tone }: { href: string; label: string; value: React.ReactNode; icon: Icon; tone?: "warn" | "bad" }) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-border bg-surface p-5 transition hover:border-accent focus-visible:outline-2 focus-visible:outline-ring"
    >
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
        <Icon className={cn("size-4", tone === "bad" ? "text-danger" : tone === "warn" ? "text-amber-600" : "text-accent")} aria-hidden={true} />
      </div>
      <p className={cn("mt-2 text-3xl font-semibold tabular-nums", tone === "bad" && "text-danger")}>{value}</p>
    </Link>
  );
}

export default function CarrierDashboardPage() {
  const t = useTranslations("carrier.dashboard");
  const { data: user } = useMe();
  const q = useQuery<CarrierDashboard>({ queryKey: ["carrier", "dashboard"], queryFn: () => api<CarrierDashboard>("/carrier/dashboard") });
  const d = q.data;

  return (
    <>
      <PageHeader title={t("title")} description={user ? t("welcome", { name: user.full_name }) : undefined} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()}>
        {d && (
          <div className="space-y-6">
            {(d.unverified_drivers > 0 || d.awaiting_assignment > 0) && (
              <div role="status" className="space-y-2">
                {d.awaiting_assignment > 0 && (
                  <Link
                    href="/carrier/shipments?offer_status=accepted"
                    className="flex items-center gap-3 rounded-md border border-amber-400/50 bg-amber-100 px-4 py-3 text-sm text-amber-900 hover:opacity-90 dark:bg-amber-950 dark:text-amber-200"
                  >
                    <AlertTriangle className="size-4 shrink-0" aria-hidden="true" />
                    {t("alertAssign", { n: d.awaiting_assignment })}
                  </Link>
                )}
                {d.unverified_drivers > 0 && (
                  <Link
                    href="/carrier/drivers?verified=false"
                    className="flex items-center gap-3 rounded-md border border-amber-400/50 bg-amber-100 px-4 py-3 text-sm text-amber-900 hover:opacity-90 dark:bg-amber-950 dark:text-amber-200"
                  >
                    <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
                    {t("alertUnverified", { n: d.unverified_drivers })}
                  </Link>
                )}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi href="/carrier/drivers" label={t("driversAvailable")} value={d.drivers_available} icon={Users} />
              <Kpi href="/carrier/tracker?status=IN_TRANSIT" label={t("trucksOnRoad")} value={d.trucks_on_road} icon={Truck} />
              <Kpi href="/carrier/tracker" label={t("lateTrucks")} value={d.late_trucks} icon={Clock} tone={d.late_trucks > 0 ? "bad" : undefined} />
              <Kpi href="/carrier/shipments?offer_status=accepted" label={t("awaitingAssignment")} value={d.awaiting_assignment} icon={PackageSearch} tone={d.awaiting_assignment > 0 ? "warn" : undefined} />
              <Kpi href="/carrier/tracker" label={t("upcomingToday")} value={d.upcoming_appointments_today} icon={Warehouse} />
              <Kpi href="/carrier/reports" label={t("detentionHours")} value={d.detention_hours.toFixed(1)} icon={Clock} />
              <Kpi href="/carrier/drivers?verified=false" label={t("unverifiedDrivers")} value={d.unverified_drivers} icon={UserCheck} tone={d.unverified_drivers > 0 ? "warn" : undefined} />
              <Kpi href="/carrier/shipments" label={t("shipmentsTotal")} value={d.shipments_total} icon={PackageSearch} />
            </div>
            <Card className="flex items-start gap-3">
              <Sparkles className="mt-0.5 size-5 text-accent" aria-hidden="true" />
              <div>
                <h2 className="font-semibold">{t("insightsTitle")}</h2>
                <p className="mt-1 text-sm text-muted">{t("insightsBody")}</p>
                <Link href="/carrier/insights" className="mt-2 inline-block text-sm font-medium text-accent hover:underline">
                  {t("insightsLink")}
                </Link>
              </div>
            </Card>
          </div>
        )}
      </QueryState>
    </>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { PageHeader } from "@/components/page-header";
import { ViewPage } from "@/components/insights/view-page";
import { api } from "@/lib/api";
import type { Page } from "@/lib/admin-types";
import { useMe } from "@/lib/auth";

function Total({ path, label, href }: { path: string; label: string; href: string }) {
  const q = useQuery({ queryKey: ["list", path, "total"], queryFn: () => api<Page<unknown>>(`${path}?limit=1`), staleTime: 30_000 });
  return (
    <Link href={href} className="group block rounded-xl border border-border bg-surface p-5 transition hover:border-accent">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold tabular-nums">{q.isLoading ? "…" : q.error ? "—" : q.data?.total}</p>
      <ArrowRight className="mt-3 size-4 text-muted transition group-hover:translate-x-1 group-hover:text-accent" aria-hidden="true" />
    </Link>
  );
}

export default function AdminDashboard() {
  const t = useTranslations("admin.dashboard");
  const { data: user } = useMe();
  return (
    <>
      <PageHeader title={t("title")} description={user ? t("welcome", { name: user.full_name }) : undefined} />
      <h2 className="mb-3 text-sm font-semibold">{t("masterData")}</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Total path="/facilities" label={t("facilities")} href="/admin/facilities" />
        <Total path="/carriers" label={t("carriers")} href="/admin/carriers" />
        <Total path="/shipments" label={t("shipments")} href="/admin/shipments" />
      </div>
      <h2 className="mb-3 mt-8 text-sm font-semibold">{t("network")}</h2>
      <ViewPage
        view="network" filenameBase="network" aiSpend
        kpis={["utilisation_pct", "on_time_rate", "avg_wait_min", "avg_dwell_min", "no_show_rate", "loads_completed", "requests", "avg_decision_min", "escalations", "bot_resolution_rate", "delay_reports"]}
        charts={["utilisation", "arrivals", "requests", "delays"]} csv={["series", "by_facility", "delay_causes", "escalation_reasons"]}
      />
    </>
  );
}

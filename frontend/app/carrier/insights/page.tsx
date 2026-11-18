"use client";

import { useTranslations } from "next-intl";
import { ViewPage } from "@/components/insights/view-page";
import { PageHeader } from "@/components/page-header";

export default function CarrierInsightsPage() {
  const t = useTranslations("carrier.insights");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <ViewPage
        view="carrier" filenameBase="carrier"
        kpis={["arrivals", "on_time_rate", "late", "delay_reports", "avg_declared_delay_min", "no_show_rate", "slot_moves", "decline_rate"]}
        charts={["arrivals", "delays"]} csv={["series", "by_driver", "by_lane", "delay_causes"]}
      />
    </>
  );
}

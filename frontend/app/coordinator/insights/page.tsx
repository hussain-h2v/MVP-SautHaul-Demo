"use client";

import { useTranslations } from "next-intl";
import { ViewPage } from "@/components/insights/view-page";
import { PageHeader } from "@/components/page-header";

export default function CoordinatorInsightsPage() {
  const t = useTranslations("coord.insights");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <ViewPage
        view="coordinator" filenameBase="desk"
        kpis={["requests", "avg_decision_min", "decision_p90_min", "backlog", "escalations", "avg_resolution_min", "holds_expired", "bot_resolution_rate"]}
        charts={["requests", "delays"]} csv={["series", "request_mix", "escalation_reasons"]}
      />
    </>
  );
}

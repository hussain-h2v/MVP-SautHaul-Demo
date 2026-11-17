"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

export default function CoordinatorInsightsPage() {
  const t = useTranslations("coord.insights");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <Card className="flex items-start gap-3">
        <Sparkles className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
        <div>
          <p className="font-medium">{t("cardTitle")}</p>
          <p className="mt-1 text-sm text-muted">{t("cardBody")}</p>
        </div>
      </Card>
    </>
  );
}

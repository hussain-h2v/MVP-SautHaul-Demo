"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

export default function CarrierInsightsPage() {
  const t = useTranslations("carrier.insights");
  const items = ["delays", "detention", "risk", "utilisation"] as const;
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="grid gap-4 sm:grid-cols-2">
        {items.map((k) => (
          <Card key={k}>
            <div className="flex items-center gap-2">
              <Sparkles className="size-4 text-accent" aria-hidden="true" />
              <h2 className="font-semibold">{t(`${k}.title`)}</h2>
            </div>
            <p className="mt-2 text-sm text-muted">{t(`${k}.body`)}</p>
            <p className="mt-3 text-xs font-medium text-muted">{t("soon")}</p>
          </Card>
        ))}
      </div>
    </>
  );
}

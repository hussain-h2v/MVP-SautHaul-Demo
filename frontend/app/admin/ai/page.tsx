"use client";

import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/page-header";
import { Card } from "@/components/ui/card";

export default function AiManagementPage() {
  const t = useTranslations("admin.ai");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <Card>
        <p className="text-sm text-muted">{t("soon")}</p>
      </Card>
    </>
  );
}

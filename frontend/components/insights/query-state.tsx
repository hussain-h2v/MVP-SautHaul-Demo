"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";

export function QueryStateBlock({ isLoading, error, onRetry, children }: { isLoading: boolean; error: unknown; onRetry?: () => void; children: React.ReactNode }) {
  const t = useTranslations("insights");
  if (isLoading)
    return (
      <div role="status" aria-label={t("loading")} className="space-y-3">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-56 w-full" />
      </div>
    );
  if (error)
    return (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
        <span>{t("error")}</span>
        {onRetry && <Button size="sm" variant="outline" onClick={onRetry}>{t("retry")}</Button>}
      </div>
    );
  return <>{children}</>;
}

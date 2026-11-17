"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Skeleton } from "@/components/ui/card";
import { useMe } from "@/lib/auth";
import { portals } from "@/lib/portals";
import { roleHome } from "@/lib/types";

export default function Landing() {
  const t = useTranslations();
  const router = useRouter();
  const { data: user, isLoading } = useMe();

  useEffect(() => {
    if (user) router.replace(roleHome[user.role]);
  }, [user, router]);

  if (isLoading || user) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status" aria-label={t("common.loading")}>
        <Skeleton className="h-10 w-64" />
      </div>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-16">
      <p className="text-sm font-medium text-accent">{t("common.appName")}</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">{t("common.tagline")}</h1>
      <p className="mt-3 max-w-xl text-muted">{t("common.taglineSub")}</p>
      <div className="mt-10 grid gap-4 sm:grid-cols-2">
        {portals.map((p) => (
          <Link
            key={p.slug}
            href={`/login?next=${encodeURIComponent("/" + p.slug)}`}
            className="group rounded-xl border border-border bg-surface p-6 transition hover:border-accent hover:shadow-md"
          >
            <p className="text-xs uppercase tracking-wider text-muted">{p.audience}</p>
            <p className="mt-1 text-xl font-semibold group-hover:text-accent">{t(`portals.${p.slug}`)}</p>
            <p className="mt-2 text-sm text-muted">{p.blurb}</p>
            <p className="mt-4 text-sm font-medium text-accent">{t("landing.signIn")}</p>
          </Link>
        ))}
      </div>
    </main>
  );
}

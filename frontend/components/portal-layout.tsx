"use client";

import { useTranslations } from "next-intl";
import { Badge, Card } from "@/components/ui/card";
import { portals } from "@/lib/portals";
import { useMe } from "@/lib/auth";
import { PortalShell } from "./portal-shell";

export function makePortalLayout(slug: string) {
  const portal = portals.find((p) => p.slug === slug)!;
  return function Layout({ children }: { children: React.ReactNode }) {
    return <PortalShell portal={portal}>{children}</PortalShell>;
  };
}

export function makePortalHome(slug: string) {
  const portal = portals.find((p) => p.slug === slug)!;
  return function Home() {
    const t = useTranslations();
    const { data: user } = useMe();
    if (!user) return null;
    const caps = Object.entries(user.capabilities);
    return (
      <div className="mx-auto max-w-4xl space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("common.welcome", { name: user.full_name })}</h1>
          <p className="mt-1 text-muted">{portal.blurb}</p>
        </div>
        <Card>
          <p className="text-xs font-medium uppercase tracking-wider text-muted">{t("common.role")}</p>
          <p className="mt-1 font-medium">{t(`roles.${user.role}`)}</p>
          <p className="mt-4 text-xs font-medium uppercase tracking-wider text-muted">{t("common.capabilities")}</p>
          <ul className="mt-2 flex flex-wrap gap-2">
            {caps.map(([key, level]) => (
              <li key={key}>
                <Badge tone={level === "W" ? "success" : "accent"} title={level === "W" ? t("common.write") : t("common.read")}>
                  {key} · {level}
                </Badge>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-muted">{t("common.readOnlyNote")}</p>
        </Card>
        <div className="grid gap-4 sm:grid-cols-2">
          {portal.nav.slice(1).map((n) => (
            <Card key={n.href}>
              <p className="font-medium">{t(n.labelKey)}</p>
              <p className="mt-1 text-sm text-muted">{t("common.comingSoon")}</p>
            </Card>
          ))}
        </div>
      </div>
    );
  };
}

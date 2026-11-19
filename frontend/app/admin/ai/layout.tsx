"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/admin/ai", key: "overview" },
  { href: "/admin/ai/monitoring", key: "monitoring" },
  { href: "/admin/ai/logs", key: "logs" },
  { href: "/admin/ai/map", key: "map" },
  { href: "/admin/ai/providers", key: "providers" },
  { href: "/admin/ai/keys", key: "keys" },
  { href: "/admin/ai/models", key: "models" },
  { href: "/admin/ai/routes", key: "routes" },
  { href: "/admin/ai/prompts", key: "prompts" },
  { href: "/admin/ai/evals", key: "evals" },
  { href: "/admin/ai/usage", key: "usage" },
  { href: "/admin/ai/budgets", key: "budgets" },
  { href: "/admin/ai/safety", key: "safety" },
] as const;

export default function AiLayout({ children }: { children: React.ReactNode }) {
  const t = useTranslations("ai");
  const pathname = usePathname();
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="flex flex-col gap-6 lg:flex-row">
        <nav aria-label={t("nav.label")} className="lg:w-52 lg:shrink-0">
          <ul className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            {TABS.map((tab) => {
              const active = pathname === tab.href;
              return (
                <li key={tab.href} className="shrink-0">
                  <Link
                    href={tab.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "block whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors",
                      active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-accent-soft hover:text-foreground",
                    )}
                  >
                    {t(`nav.${tab.key}`)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </>
  );
}

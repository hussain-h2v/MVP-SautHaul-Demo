"use client";

import { Menu, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { UserMenu } from "@/components/user-menu";
import { Skeleton } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useMe } from "@/lib/auth";
import { filterNav, type Portal } from "@/lib/portals";
import { useEventStream } from "@/lib/sse";
import { roleHome } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PortalShell({
  portal,
  children,
  headerExtra,
}: {
  portal: Portal;
  children: React.ReactNode;
  headerExtra?: React.ReactNode;
}) {
  const t = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const { data: user, isLoading } = useMe();
  const [open, setOpen] = useState(false);
  const allowed = !!user && user.role === portal.role;
  const stream = useEventStream([["notifications"], ["inbox"], ["fac"]], allowed);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (isLoading) return;
    if (!user) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (user.role !== portal.role) router.replace(roleHome[user.role]);
  }, [isLoading, user, portal.role, pathname, router]);

  if (isLoading || !allowed) {
    return (
      <div className="flex min-h-screen items-center justify-center" role="status" aria-label={t("common.loading")}>
        <Skeleton className="h-10 w-64" />
      </div>
    );
  }

  const nav = filterNav(portal.nav, user);
  const dot = { live: "bg-success", connecting: "bg-muted", reconnecting: "bg-amber-500" }[stream];

  const sidebar = (
    <>
      <Link href="/" className="flex items-center gap-2 px-5 py-5 font-semibold tracking-tight">
        <span className="grid size-8 place-items-center rounded-lg bg-accent text-sm text-accent-foreground">S</span>
        {t("common.appName")}
      </Link>
      <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wider text-muted">{t(`portals.${portal.slug}`)}</p>
      <nav aria-label="Primary" className="flex flex-col gap-1 px-3">
        {nav.map((item) => {
          const active = pathname === item.href || (item.href.split("/").length > 2 && pathname.startsWith(`${item.href}/`));
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "rounded-md px-3 py-2 text-sm transition-colors",
                active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-accent-soft hover:text-foreground",
              )}
            >
              {t(item.labelKey)}
            </Link>
          );
        })}
      </nav>
    </>
  );

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-accent focus:px-4 focus:py-2 focus:text-accent-foreground"
      >
        {t("common.skipToContent")}
      </a>
      <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-surface md:flex">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} aria-hidden="true" />
          <aside className="relative flex h-full w-64 flex-col bg-surface">
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-2 top-3"
              aria-label={t("common.closeMenu")}
              onClick={() => setOpen(false)}
            >
              <X className="size-5" aria-hidden="true" />
            </Button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2 sm:px-6">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              aria-label={t("common.menu")}
              aria-expanded={open}
              onClick={() => setOpen(true)}
            >
              <Menu className="size-5" aria-hidden="true" />
            </Button>
            <span className="hidden text-sm font-medium text-muted lg:inline">{portal.audience}</span>
            {headerExtra}
          </div>
          <div className="flex items-center gap-3">
            <span role="status" className="flex items-center gap-2 text-xs text-muted">
              <span className={cn("size-2 rounded-full", dot)} aria-hidden="true" />
              {t(`common.${stream}`)}
            </span>
            <UserMenu user={user} />
          </div>
        </header>
        <main id="main" tabIndex={-1} className="flex-1 p-4 sm:p-6">
          {children}
        </main>
      </div>
    </div>
  );
}

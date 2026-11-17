"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { portals, type Portal } from "@/lib/portals";

export function PortalShell({ portal, children }: { portal: Portal; children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex dark:border-slate-800 dark:bg-slate-900">
        <Link href="/" className="flex items-center gap-2 px-5 py-5 font-semibold tracking-tight">
          <span className="grid size-8 place-items-center rounded-lg bg-indigo-600 text-sm text-white">S</span>
          SetuHaul
        </Link>
        <p className="px-5 pb-2 text-xs font-medium uppercase tracking-wider text-slate-500">{portal.name} portal</p>
        <nav aria-label="Primary" className="flex flex-col gap-1 px-3">
          {portal.nav.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-indigo-500 ${
                  active
                    ? "bg-indigo-50 font-medium text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3 dark:border-slate-800 dark:bg-slate-900">
          <h1 className="text-sm font-medium text-slate-500">{portal.audience}</h1>
          <div className="flex gap-1 text-xs">
            {portals.map((p) => (
              <Link
                key={p.slug}
                href={`/${p.slug}`}
                className={`rounded-full px-3 py-1 ${
                  p.slug === portal.slug
                    ? "bg-indigo-600 text-white"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
              >
                {p.name}
              </Link>
            ))}
          </div>
        </header>
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}

import { portals } from "@/lib/portals";
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
    return (
      <div className="mx-auto max-w-4xl">
        <h2 className="text-2xl font-semibold tracking-tight">{portal.name} portal</h2>
        <p className="mt-1 text-slate-500">{portal.blurb}</p>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {portal.nav.slice(1).map((n) => (
            <div key={n.href} className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900">
              <p className="font-medium">{n.label}</p>
              <p className="mt-1 text-sm text-slate-500">Arrives in an upcoming milestone.</p>
            </div>
          ))}
        </div>
      </div>
    );
  };
}

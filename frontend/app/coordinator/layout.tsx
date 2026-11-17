"use client";

import { CoordAlerts } from "@/components/coordinator/alerts";
import { PortalShell } from "@/components/portal-shell";
import { portals } from "@/lib/portals";

const portal = portals.find((p) => p.slug === "coordinator")!;

export default function CoordinatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <PortalShell portal={portal} headerExtra={<CoordAlerts />}>
      {children}
    </PortalShell>
  );
}

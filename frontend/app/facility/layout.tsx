"use client";

import { Suspense } from "react";
import { FacilityProvider, FacilitySwitcher } from "@/components/facility/facility-context";
import { PortalShell } from "@/components/portal-shell";
import { portals } from "@/lib/portals";

const portal = portals.find((p) => p.slug === "facility")!;

export default function FacilityLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={null}>
      <FacilityProvider>
        <PortalShell portal={portal} headerExtra={<FacilitySwitcher />}>
          {children}
        </PortalShell>
      </FacilityProvider>
    </Suspense>
  );
}

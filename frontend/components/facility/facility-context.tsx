"use client";

import { Building2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import type { Page } from "@/lib/admin-types";
import { useFacQuery } from "@/lib/fac";
import type { FacilitySummary } from "@/lib/facility-types";
import { pickFacility } from "@/lib/facility-select";
import { DEFAULT_TZ } from "@/lib/time";

const STORAGE_KEY = "sh.facility";

interface FacilityCtx {
  facilities: FacilitySummary[];
  facility: FacilitySummary | null;
  facilityId: string | null;
  tz: string;
  isLoading: boolean;
  isError: boolean;
  setFacility: (id: string) => void;
}

const Ctx = React.createContext<FacilityCtx | null>(null);

export function useFacility(): FacilityCtx {
  const v = React.useContext(Ctx);
  if (!v) throw new Error("useFacility must be used inside <FacilityProvider>");
  return v;
}

export function FacilityProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const q = useFacQuery<Page<FacilitySummary>>("/facilities?limit=200&active=true", { staleTime: 60_000 });
  const facilities = React.useMemo(() => q.data?.items ?? [], [q.data]);
  const fromUrl = params.get("facility");
  const [stored, setStored] = React.useState<string | null>(null);

  React.useEffect(() => {
    try {
      setStored(window.localStorage.getItem(STORAGE_KEY));
    } catch {
      /* storage unavailable */
    }
  }, []);

  const facilityId = pickFacility(facilities, fromUrl, stored);
  const facility = facilities.find((f) => f.id === facilityId) ?? null;

  const setFacility = React.useCallback(
    (id: string) => {
      setStored(id);
      try {
        window.localStorage.setItem(STORAGE_KEY, id);
      } catch {
        /* ignore */
      }
      const next = new URLSearchParams(params.toString());
      next.set("facility", id);
      router.replace(`${pathname}?${next.toString()}`);
    },
    [params, pathname, router],
  );

  const value = React.useMemo<FacilityCtx>(
    () => ({
      facilities,
      facility,
      facilityId,
      tz: facility?.timezone ?? DEFAULT_TZ,
      isLoading: q.isLoading,
      isError: q.isError,
      setFacility,
    }),
    [facilities, facility, facilityId, q.isLoading, q.isError, setFacility],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function FacilitySwitcher() {
  const t = useTranslations("facility");
  const { facilities, facilityId, setFacility, isLoading } = useFacility();
  const selected = facilities.find((f) => f.id === facilityId);
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Building2 className="size-4 shrink-0 text-muted" aria-hidden="true" />
      <label htmlFor="facility-switcher" className="sr-only">
        {t("switcher")}
      </label>
      <select
        id="facility-switcher"
        value={facilityId ?? ""}
        disabled={isLoading || facilities.length === 0}
        onChange={(e) => setFacility(e.target.value)}
        className="h-9 max-w-[16rem] truncate rounded-md border border-border bg-surface px-2 text-sm"
      >
        {facilities.length === 0 && <option value="">{isLoading ? t("loadingFacilities") : t("noFacilities")}</option>}
        {facilities.map((f) => (
          <option key={f.id} value={f.id}>
            {f.facility_name} · {f.open_time}–{f.close_time}
          </option>
        ))}
      </select>
      {selected && <span className="hidden text-xs text-muted xl:inline">{selected.code}</span>}
    </div>
  );
}

/** Wraps a page: shows loading / no-facility states and renders children only with a facility selected. */
export function RequireFacility({ children }: { children: (f: FacilitySummary) => React.ReactNode }) {
  const t = useTranslations("facility");
  const { facility, isLoading, isError } = useFacility();
  if (isLoading) return <p role="status" className="text-sm text-muted">{t("loadingFacilities")}</p>;
  if (isError) return <p role="alert" className="text-sm text-danger">{t("facilitiesFailed")}</p>;
  if (!facility) return <p className="text-sm text-muted">{t("noFacilities")}</p>;
  return <>{children(facility)}</>;
}

"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { PriorityBadge, useCoordText } from "@/components/coordinator/shared";
import { DatePicker, QueryState } from "@/components/facility/common";
import { ScheduleGrid, SlotLegend } from "@/components/facility/schedule-grid";
import { PageHeader } from "@/components/page-header";
import { Badge, Card } from "@/components/ui/card";
import { Select } from "@/components/ui/fields";
import type { Page } from "@/lib/admin-types";
import { BOARD_STAGES, type Board, type BoardRow, type BoardStage } from "@/lib/coord-types";
import { useCoordQuery } from "@/lib/coord";
import { useFacQuery } from "@/lib/fac";
import type { FacilitySummary, Schedule } from "@/lib/facility-types";
import { hhmm, todayIn } from "@/lib/time";
import { buildQuery } from "@/lib/query";
import { useOptions } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const STAGE_TONE: Record<BoardStage, string> = {
  travelling: "border-t-accent",
  late: "border-t-danger",
  in_yard: "border-t-amber-500",
  unloading: "border-t-emerald-500",
  done: "border-t-border",
};

export default function BoardPage() {
  const t = useTranslations("coord.board");
  const [date, setDate] = React.useState(() => todayIn());
  const [facilityId, setFacilityId] = React.useState("");
  const facilities = useOptions<Page<FacilitySummary>>("/facilities?limit=200&active=true");
  const list = facilities.data?.items ?? [];
  const gridFacility = facilityId || list[0]?.id || "";

  const board = useCoordQuery<Board>(`/coordinator/board${buildQuery({ facility_id: facilityId, date })}`, { refetchInterval: 30_000 });
  const schedule = useFacQuery<Schedule>(gridFacility ? `/schedule${buildQuery({ facility_id: gridFacility, date })}` : null, { refetchInterval: 60_000 });

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select aria-label={t("facility")} className="w-56" value={facilityId} onChange={(e) => setFacilityId(e.target.value)}>
          <option value="">{t("allFacilities")}</option>
          {list.map((f) => (
            <option key={f.id} value={f.id}>
              {f.code} · {f.facility_name}
            </option>
          ))}
        </Select>
        <DatePicker value={date} onChange={setDate} />
      </div>

      <QueryState isLoading={board.isLoading} isError={board.isError} onRetry={() => board.refetch()}>
        {board.data && (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {BOARD_STAGES.map((stage) => (
              <StageColumn key={stage} stage={stage} rows={board.data.stages[stage] ?? []} />
            ))}
          </div>
        )}
      </QueryState>

      <section className="mt-8" aria-label={t("gridTitle")}>
        <h2 className="mb-1 text-lg font-semibold">{t("gridTitle")}</h2>
        <p className="mb-3 text-sm text-muted">{t("gridNote", { facility: list.find((f) => f.id === gridFacility)?.code ?? "" })}</p>
        <div className="mb-3">
          <SlotLegend />
        </div>
        <QueryState isLoading={schedule.isLoading} isError={schedule.isError} onRetry={() => schedule.refetch()}>
          {schedule.data &&
            (schedule.data.docks.every((d) => d.slots.length === 0) ? (
              <p className="rounded-md border border-dashed border-border py-8 text-center text-sm text-muted">{t("noSlots")}</p>
            ) : (
              <ScheduleGrid schedule={schedule.data} pxPerHour={40} selectedSlotId={null} onSelect={() => undefined} />
            ))}
        </QueryState>
      </section>
    </>
  );
}

function StageColumn({ stage, rows }: { stage: BoardStage; rows: BoardRow[] }) {
  const t = useTranslations("coord.board");
  return (
    <section aria-label={t(`stage.${stage}`)} className={cn("rounded-xl border border-t-4 border-border bg-surface", STAGE_TONE[stage])}>
      <h2 className="flex items-center justify-between px-3 py-2 text-sm font-semibold">
        {t(`stage.${stage}`)}
        <Badge tone="neutral">{rows.length}</Badge>
      </h2>
      <ul className="max-h-[28rem] space-y-2 overflow-y-auto px-3 pb-3">
        {rows.length === 0 && <li className="py-4 text-center text-xs text-muted">{t("none")}</li>}
        {rows.map((r) => (
          <BoardCard key={r.shipment_id} r={r} />
        ))}
      </ul>
    </section>
  );
}

function BoardCard({ r }: { r: BoardRow }) {
  const t = useTranslations("coord.board");
  const { tc } = useCoordText();
  const locale = useLocale();
  void tc;
  void locale;
  return (
    <li>
      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-sm font-medium">{r.code}</span>
          <PriorityBadge code={r.priority_code} />
          {r.late_min != null && r.late_min > 0 && <Badge tone="danger">{t("lateBy", { min: r.late_min })}</Badge>}
        </div>
        <p className="mt-1 text-xs text-muted">
          {r.facility_code} · {r.carrier_name ?? "—"}
          {r.driver_name ? ` · ${r.driver_name}` : ""}
        </p>
        <p className="mt-1 text-xs">
          {t("eta")} {hhmm(r.eta_ts)}
          {r.eta_confidence === "LOW" && <span className="ml-1 text-danger">({t("vague")})</span>}
          {r.slot_code && (
            <>
              {" · "}
              {r.dock_code} {hhmm(r.slot_start_ts)}
            </>
          )}
        </p>
      </Card>
    </li>
  );
}

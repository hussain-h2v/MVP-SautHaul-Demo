"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { PriorityBadge } from "@/components/admin/badges";
import { DatePicker, QueryState } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, FormError, Select } from "@/components/ui/fields";
import { api, ApiError } from "@/lib/api";
import { apiErrorText, qs, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type { Dock, FacilitySummary, Yard, YardRow } from "@/lib/facility-types";
import { hhmm, todayIn } from "@/lib/time";

type Column = "expected" | "queue" | "in_dock" | "done";
const COLUMNS: Column[] = ["expected", "queue", "in_dock", "done"];

function AssignDockDialog({ row, facilityId, onClose }: { row: YardRow; facilityId: string; onClose: () => void }) {
  const t = useTranslations("facility.yard");
  const f = useTranslations("facility");
  const c = useTranslations("common");
  const docks = useFacQuery<Dock[]>(`/docks${qs({ facility_id: facilityId, status: "ACTIVE" })}`);
  const [dockId, setDockId] = React.useState("");
  const [problems, setProblems] = React.useState<string[]>([]);
  const [err, setErr] = React.useState<string | null>(null);
  const options = [...(docks.data ?? [])].sort((a, b) => Number(b.dock_code === row.planned_dock_code) - Number(a.dock_code === row.planned_dock_code) || a.dock_code.localeCompare(b.dock_code));
  const chosen = dockId || options[0]?.id || "";
  const assign = useFacMutation(() => api(`/yard/${row.checkin_id}/assign-dock`, { method: "POST", body: { dock_id: chosen } }), {
    success: t("assigned"),
    onSuccess: onClose,
    onError: (e) => {
      if (e instanceof ApiError && e.status === 422) {
        setProblems(Array.isArray(e.details.problems) ? (e.details.problems as string[]) : []);
        setErr(e.message);
      } else setErr(apiErrorText(e));
    },
  });

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("assignTitle", { shipment: row.shipment_code })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button disabled={!chosen || assign.isPending} onClick={() => assign.mutate()}>
            {t("assign")}
          </Button>
        </>
      }
    >
      <FormError message={problems.length === 0 ? err : null} />
      {problems.length > 0 && (
        <div role="alert" className="mb-4 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          <p className="font-medium">{t("incompatible")}</p>
          <ul className="mt-1 list-disc pl-5">
            {problems.map((p) => (
              <li key={p}>{f.has(`problems.${p}` as "problems.DOCK_NOT_ACTIVE") ? f(`problems.${p}` as "problems.DOCK_NOT_ACTIVE") : p}</li>
            ))}
          </ul>
        </div>
      )}
      <Field label={t("dock")} htmlFor="assign-dock" hint={t("loadHint", { load: row.load })}>
        <Select id="assign-dock" value={chosen} onChange={(e) => { setDockId(e.target.value); setProblems([]); setErr(null); }}>
          {options.map((d) => (
            <option key={d.id} value={d.id}>
              {d.dock_code} — {f(`dockType.${d.dock_type}`)}
              {d.dock_code === row.planned_dock_code ? ` (${t("planned")})` : ""}
              {row.load !== "ANY" && d.dock_type !== row.load ? ` ⚠` : ""}
            </option>
          ))}
        </Select>
      </Field>
    </Dialog>
  );
}

function YardCard({ row, column, canWrite, tz, onAssign, onNoShow }: { row: YardRow; column: Column; canWrite: boolean; tz: string; onAssign: (r: YardRow) => void; onNoShow: (r: YardRow) => void }) {
  const t = useTranslations("facility.yard");
  const f = useTranslations("facility");
  const [error, setError] = React.useState<string | null>(null);

  const useAct = (path: string, success: string) =>
    useFacMutation(() => api<{ overrun_min?: number; detention_min?: number } | undefined>(path, { method: "POST", body: path.endsWith("check-in") ? { shipment_id: row.shipment_id } : undefined }), {
      success,
      onSuccess: (res) => {
        setError(null);
        if (res && (res.overrun_min !== undefined || res.detention_min !== undefined))
          toast.info(t("finishSummary", { overrun: res.overrun_min ?? 0, detention: res.detention_min ?? 0 }));
      },
      onError: (e) => setError(apiErrorText(e)),
    });
  const checkIn = useAct("/yard/check-in", t("checkedIn"));
  const start = useAct(`/yard/${row.checkin_id}/start-unload`, t("unloadStarted"));
  const finish = useAct(`/yard/${row.checkin_id}/finish-unload`, t("unloadFinished"));
  const out = useAct(`/yard/${row.checkin_id}/gate-out`, t("gatedOut"));

  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{row.shipment_code}</p>
          <p className="text-xs text-muted">
            {row.carrier_name ?? "—"}
            {row.driver_name ? ` · ${row.driver_name}` : ""}
          </p>
        </div>
        <PriorityBadge value={row.priority_code} />
      </div>
      <div className="flex flex-wrap gap-1.5 text-xs">
        <Badge>{f(`dockType.${row.load}` as "dockType.STANDARD")}</Badge>
        {row.arrival_state && <Badge tone={row.arrival_state === "LATE" || row.arrival_state === "NO_SHOW" ? "danger" : row.arrival_state === "EARLY" ? "warning" : "success"}>{f(`arrival.${row.arrival_state}`)}</Badge>}
        {row.queue_state && column !== "done" && <Badge tone="accent">{f(`queueState.${row.queue_state}`)}</Badge>}
        {row.queue_position && column === "queue" && <Badge>#{row.queue_position}</Badge>}
        {row.dock_mismatch && (
          <Badge tone="warning" title={t("mismatchHint")}>
            <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
            {t("mismatch")}
          </Badge>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {row.slot_code && (
          <>
            <dt className="text-muted">{t("slot")}</dt>
            <dd>
              {row.planned_dock_code} · {hhmm(row.slot_start_ts, tz)}–{hhmm(row.slot_end_ts, tz)}
            </dd>
          </>
        )}
        {row.actual_dock_code && (
          <>
            <dt className="text-muted">{t("actualDock")}</dt>
            <dd>{row.actual_dock_code}</dd>
          </>
        )}
        {row.gate_in_ts && (
          <>
            <dt className="text-muted">{t("gateIn")}</dt>
            <dd>{hhmm(row.gate_in_ts, tz)}</dd>
          </>
        )}
        {row.waiting_min !== null && column === "queue" && (
          <>
            <dt className="text-muted">{t("waiting")}</dt>
            <dd>{t("minutes", { count: row.waiting_min })}</dd>
          </>
        )}
        {row.eta_ts && column === "expected" && (
          <>
            <dt className="text-muted">{t("eta")}</dt>
            <dd>{hhmm(row.eta_ts, tz)}</dd>
          </>
        )}
        {row.overrun_min !== null && row.overrun_min !== 0 && (
          <>
            <dt className="text-muted">{t("overrun")}</dt>
            <dd className={row.overrun_min > 0 ? "text-danger" : ""}>{t("minutes", { count: row.overrun_min })}</dd>
          </>
        )}
      </dl>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
      {canWrite && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {column === "expected" && (
            <>
              <Button size="sm" disabled={checkIn.isPending} onClick={() => checkIn.mutate()}>
                {t("checkIn")}
              </Button>
              {row.appointment_id && (
                <Button size="sm" variant="outline" onClick={() => onNoShow(row)}>
                  {t("noShow")}
                </Button>
              )}
            </>
          )}
          {column === "queue" && (
            <Button size="sm" onClick={() => onAssign(row)}>
              {t("assignDock")}
            </Button>
          )}
          {column === "in_dock" &&
            (row.unload_start_ts ? (
              <Button size="sm" disabled={finish.isPending} onClick={() => finish.mutate()}>
                {t("finishUnload")}
              </Button>
            ) : (
              <Button size="sm" disabled={start.isPending} onClick={() => start.mutate()}>
                {t("startUnload")}
              </Button>
            ))}
          {column === "done" && (
            <Button size="sm" variant="outline" disabled={out.isPending} onClick={() => out.mutate()}>
              {t("gateOut")}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

function YardView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.yard");
  const canWrite = useCap("day_schedule") === "W";
  const [date, setDate] = React.useState(() => todayIn(facility.timezone));
  const q = useFacQuery<Yard>(`/yard${qs({ facility_id: facility.id, date })}`, { refetchInterval: 30_000 });
  const [assigning, setAssigning] = React.useState<YardRow | null>(null);
  const [noShow, setNoShow] = React.useState<YardRow | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const markNoShow = useFacMutation((r: YardRow) => api("/yard/no-show", { method: "POST", body: { appointment_id: r.appointment_id } }), {
    success: t("noShowMarked"),
    onSuccess: () => setNoShow(null),
    onError: (e) => {
      setNoShow(null);
      setErr(e instanceof ApiError && e.code === "GRACE_NOT_ELAPSED" ? t("graceNotElapsed") : apiErrorText(e));
    },
  });
  const data = q.data;
  const total = data ? COLUMNS.reduce((n, c) => n + data[c].length, 0) : 0;

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4">
        <DatePicker value={date} onChange={setDate} tz={facility.timezone} />
      </div>
      <FormError message={err} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={!!data && total === 0} emptyText={t("empty")}>
        {data && (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {COLUMNS.map((col) => (
              <section key={col} aria-labelledby={`col-${col}`} className="rounded-xl bg-background/60 p-3 ring-1 ring-border">
                <h2 id={`col-${col}`} className="mb-3 flex items-center justify-between text-sm font-semibold">
                  {t(`col.${col}`)}
                  <Badge tone="accent">{data[col].length}</Badge>
                </h2>
                {data[col].length === 0 ? (
                  <p className="py-4 text-center text-xs text-muted">{t("columnEmpty")}</p>
                ) : (
                  <ul className="space-y-3">
                    {data[col].map((r) => (
                      <YardCard key={`${r.shipment_id}-${col}`} row={r} column={col} canWrite={canWrite} tz={facility.timezone} onAssign={setAssigning} onNoShow={(x) => { setErr(null); setNoShow(x); }} />
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        )}
      </QueryState>
      {assigning && assigning.checkin_id && <AssignDockDialog row={assigning} facilityId={facility.id} onClose={() => setAssigning(null)} />}
      <ConfirmDialog
        open={!!noShow}
        onClose={() => setNoShow(null)}
        title={t("noShowTitle")}
        message={t("noShowMessage", { shipment: noShow?.shipment_code ?? "" })}
        confirmLabel={t("noShow")}
        destructive
        pending={markNoShow.isPending}
        onConfirm={() => noShow && markNoShow.mutate(noShow)}
      />
    </>
  );
}

export default function YardPage() {
  return <RequireFacility>{(f) => <YardView key={f.id} facility={f} />}</RequireFacility>;
}

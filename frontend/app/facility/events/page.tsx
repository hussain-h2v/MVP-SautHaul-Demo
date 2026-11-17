"use client";

import { Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { apiErrorText, qs, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type { AffectedAppointment, Dock, DockEvent, DockEventResult, DockEventType, FacilitySummary } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { addDays, todayIn, zonedToIso } from "@/lib/time";

const TYPES: DockEventType[] = ["BREAKDOWN", "MAINTENANCE", "CAPACITY_REDUCTION", "MANUAL_BLOCK", "REOPENED"];
const tone: Record<string, "danger" | "warning" | "accent" | "neutral"> = {
  BREAKDOWN: "danger",
  MAINTENANCE: "warning",
  CAPACITY_REDUCTION: "warning",
  MANUAL_BLOCK: "neutral",
  REOPENED: "accent",
};

function AffectedList({ items }: { items: AffectedAppointment[] }) {
  const t = useTranslations("facility.events");
  if (items.length === 0) return <p className="text-sm text-muted">{t("noneAffected")}</p>;
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-danger">{t("affectedTitle", { count: items.length })}</p>
      <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">
        {items.map((a) => (
          <li key={a.appointment_id} className="flex justify-between gap-3 rounded border border-border px-3 py-1.5">
            <span className="font-medium">{a.shipment_code}</span>
            <span className="text-muted">{a.slot_code}</span>
            <Badge>{a.appointment_status}</Badge>
          </li>
        ))}
      </ul>
    </div>
  );
}

function LogEventDialog({ facility, onClose, onLogged }: { facility: FacilitySummary; onClose: () => void; onLogged: (r: DockEventResult) => void }) {
  const t = useTranslations("facility.events");
  const f = useTranslations("facility");
  const c = useTranslations("common");
  const docks = useFacQuery<Dock[]>(`/docks${qs({ facility_id: facility.id })}`);
  const today = todayIn(facility.timezone);
  const [dockId, setDockId] = React.useState("");
  const [type, setType] = React.useState<DockEventType>("BREAKDOWN");
  const [start, setStart] = React.useState(`${today}T08:00`);
  const [end, setEnd] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [preview, setPreview] = React.useState<AffectedAppointment[] | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  const payload = () => ({
    dock_id: dockId || docks.data?.[0]?.id,
    event_start_ts: zonedToIso(start, facility.timezone),
    event_end_ts: end ? zonedToIso(end, facility.timezone) : null,
  });
  const valid = reason.trim().length >= 3 && !!start && (!end || end > start);
  const check = useFacMutation(() => api<{ affected_appointments: AffectedAppointment[] }>("/dock-events/preview", { method: "POST", body: payload() }), {
    onSuccess: (r) => {
      setErr(null);
      setPreview(r.affected_appointments);
    },
    onError: (e) => setErr(apiErrorText(e)),
  });
  const save = useFacMutation(() => api<DockEventResult>("/dock-events", { method: "POST", body: { ...payload(), event_type: type, reason: reason.trim() } }), {
    success: t("logged"),
    onSuccess: (r) => onLogged(r),
    onError: (e) => setErr(apiErrorText(e)),
  });
  const invalidate = () => setPreview(null);

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("logTitle")}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button variant="outline" disabled={!valid || check.isPending} onClick={() => check.mutate()}>
            {t("previewAffected")}
          </Button>
          <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {t("log")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("dock")} htmlFor="ev-dock">
          <Select id="ev-dock" value={dockId || docks.data?.[0]?.id || ""} onChange={(e) => { setDockId(e.target.value); invalidate(); }}>
            {(docks.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.dock_code}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("type")} htmlFor="ev-type">
          <Select id="ev-type" value={type} onChange={(e) => setType(e.target.value as DockEventType)}>
            {TYPES.map((x) => (
              <option key={x} value={x}>
                {f(`eventType.${x}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("start")} htmlFor="ev-start">
          <Input id="ev-start" type="datetime-local" value={start} onChange={(e) => { setStart(e.target.value); invalidate(); }} />
        </Field>
        <Field label={t("end")} htmlFor="ev-end" hint={t("endHint")}>
          <Input id="ev-end" type="datetime-local" value={end} min={start} onChange={(e) => { setEnd(e.target.value); invalidate(); }} />
        </Field>
        <Field label={t("reason")} htmlFor="ev-reason" className="sm:col-span-2">
          <Input id="ev-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      {preview && (
        <div role="status" aria-live="polite" className="mt-4">
          <AffectedList items={preview} />
        </div>
      )}
    </Dialog>
  );
}

function EventsView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.events");
  const f = useTranslations("facility");
  const c = useTranslations("common");
  const locale = useLocale();
  const canWrite = useCap("docks_slots_rules") === "W";
  const today = todayIn(facility.timezone);
  const [from, setFrom] = React.useState(addDays(today, -7));
  const [to, setTo] = React.useState(addDays(today, 7));
  const [openOnly, setOpenOnly] = React.useState(false);
  const [logging, setLogging] = React.useState(false);
  const [result, setResult] = React.useState<DockEventResult | null>(null);
  const [resolving, setResolving] = React.useState<DockEvent | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const q = useFacQuery<DockEvent[]>(`/dock-events${qs({ facility_id: facility.id, date_from: from, date_to: to, open_only: openOnly })}`);
  const resolve = useFacMutation((e: DockEvent) => api(`/dock-events/${e.id}/resolve`, { method: "POST" }), {
    success: t("resolved"),
    onSuccess: () => setResolving(null),
    onError: (e) => {
      setResolving(null);
      setErr(apiErrorText(e));
    },
  });
  const events = q.data ?? [];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canWrite && (
            <Button onClick={() => setLogging(true)}>
              <Plus className="size-4" aria-hidden="true" />
              {t("logTitle")}
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label={t("from")} htmlFor="ev-from">
          <Input id="ev-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="w-44" />
        </Field>
        <Field label={t("to")} htmlFor="ev-to">
          <Input id="ev-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} className="w-44" />
        </Field>
        <Checkbox label={t("openOnly")} className="pb-2" checked={openOnly} onChange={(e) => setOpenOnly(e.target.checked)} />
      </div>
      <FormError message={err} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={events.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border">
              {[t("dock"), t("type"), t("start"), t("end"), t("reason"), t("affected"), canWrite ? c("actions") : ""].map((h, i) => (
                <th key={i} scope="col" className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id} className="border-b border-border last:border-b-0">
                <td className={`${td} font-medium`}>{e.dock_code}</td>
                <td className={td}>
                  <Badge tone={tone[e.event_type] ?? "neutral"}>{f(`eventType.${e.event_type}`)}</Badge>
                </td>
                <td className={td}>{formatDateTime(e.event_start_ts, locale)}</td>
                <td className={td}>{e.event_end_ts ? formatDateTime(e.event_end_ts, locale) : <Badge tone="danger">{t("open")}</Badge>}</td>
                <td className={td}>{e.reason}</td>
                <td className={td}>{e.affected_count > 0 ? <Badge tone="warning">{e.affected_count}</Badge> : "—"}</td>
                {canWrite && (
                  <td className={td}>
                    {!e.resolved && e.event_type !== "REOPENED" && (
                      <Button size="sm" variant="ghost" onClick={() => { setErr(null); setResolving(e); }}>
                        {t("resolve")}
                      </Button>
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>

      {logging && (
        <LogEventDialog
          facility={facility}
          onClose={() => setLogging(false)}
          onLogged={(r) => {
            setLogging(false);
            setResult(r);
          }}
        />
      )}
      <Dialog open={!!result} onClose={() => setResult(null)} title={t("resultTitle")} footer={<Button onClick={() => setResult(null)}>{c("done")}</Button>}>
        {result && (
          <div className="space-y-3">
            <p className="text-sm">{t("resultBody", { dock: result.dock_code })}</p>
            <AffectedList items={result.affected_appointments} />
            {result.affected_appointments.length > 0 && <p className="rounded-md bg-accent-soft px-3 py-2 text-sm">{t("replanSent")}</p>}
          </div>
        )}
      </Dialog>
      <ConfirmDialog
        open={!!resolving}
        onClose={() => setResolving(null)}
        title={t("resolveTitle")}
        message={t("resolveMessage", { dock: resolving?.dock_code ?? "" })}
        confirmLabel={t("resolve")}
        pending={resolve.isPending}
        onConfirm={() => resolving && resolve.mutate(resolving)}
      />
    </>
  );
}

export default function EventsPage() {
  return <RequireFacility>{(f) => <EventsView key={f.id} facility={f} />}</RequireFacility>;
}

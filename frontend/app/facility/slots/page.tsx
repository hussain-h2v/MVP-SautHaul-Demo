"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { DatePicker, QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { apiErrorText, qs, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type {
  AffectedAppointment, BulkStatusResult, CopyDayResult, Dock, FacilitySummary, GenerateResult, SlotRow, SlotTemplate,
} from "@/lib/facility-types";
import { hhmm, todayIn } from "@/lib/time";
import { cn } from "@/lib/utils";

type Tab = "generate" | "manage" | "copy";
const DOCK_TYPES = ["STANDARD", "REEFER", "HEAVY"] as const;

function Affected({ items }: { items: AffectedAppointment[] }) {
  const t = useTranslations("facility.slots");
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

/* ---------------------------------- generate --------------------------------- */
function GenerateTab({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.slots");
  const f = useTranslations("facility");
  const canWrite = useCap("docks_slots_rules") === "W";
  const docks = useFacQuery<Dock[]>(`/docks${qs({ facility_id: facility.id, status: "ACTIVE" })}`);
  const [from, setFrom] = React.useState(() => todayIn(facility.timezone));
  const [to, setTo] = React.useState(from);
  const [templates, setTemplates] = React.useState<SlotTemplate[] | null>(null);
  const [preview, setPreview] = React.useState<GenerateResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (templates || !docks.data) return;
    const present = DOCK_TYPES.filter((d) => docks.data!.some((x) => x.dock_type === d));
    setTemplates(present.map((d) => ({ dock_type: d, start: facility.open_time, end: facility.close_time, length_min: d === "HEAVY" ? 90 : 60 })));
  }, [docks.data, templates, facility]);

  const patch = (i: number, p: Partial<SlotTemplate>) => {
    setPreview(null);
    setTemplates((ts) => ts!.map((x, j) => (j === i ? { ...x, ...p } : x)));
  };
  const body = (dry_run: boolean) => ({ facility_id: facility.id, date_from: from, date_to: to, templates, dry_run });
  const run = useFacMutation((dry: boolean) => api<GenerateResult>("/slots/generate", { method: "POST", body: body(dry) }), {
    onSuccess: (res) => {
      setErr(null);
      setPreview(res);
    },
    onError: (e) => setErr(apiErrorText(e)),
  });
  const create = useFacMutation((dry: boolean) => api<GenerateResult>("/slots/generate", { method: "POST", body: body(dry) }), {
    success: t("generated"),
    onSuccess: () => setPreview(null),
    onError: (e) => setErr(apiErrorText(e)),
  });

  return (
    <div className="space-y-4">
      <FormError message={err} />
      <Card className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("dateFrom")} htmlFor="gen-from">
            <Input id="gen-from" type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPreview(null); }} />
          </Field>
          <Field label={t("dateTo")} htmlFor="gen-to">
            <Input id="gen-to" type="date" value={to} min={from} onChange={(e) => { setTo(e.target.value); setPreview(null); }} />
          </Field>
        </div>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">{t("templates")}</legend>
          <p className="mb-3 text-xs text-muted">{t("templatesHint")}</p>
          <div className="space-y-3">
            {(templates ?? []).map((tp, i) => (
              <div key={i} className="grid items-end gap-3 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_1fr_auto]">
                <Field label={t("dockType")} htmlFor={`tp-type-${i}`}>
                  <Select id={`tp-type-${i}`} value={tp.dock_type} onChange={(e) => patch(i, { dock_type: e.target.value as SlotTemplate["dock_type"] })}>
                    {DOCK_TYPES.map((d) => (
                      <option key={d} value={d}>
                        {f(`dockType.${d}`)}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label={t("start")} htmlFor={`tp-start-${i}`}>
                  <Input id={`tp-start-${i}`} type="time" value={tp.start} onChange={(e) => patch(i, { start: e.target.value })} />
                </Field>
                <Field label={t("end")} htmlFor={`tp-end-${i}`}>
                  <Input id={`tp-end-${i}`} type="time" value={tp.end} onChange={(e) => patch(i, { end: e.target.value })} />
                </Field>
                <Field label={t("length")} htmlFor={`tp-len-${i}`}>
                  <Input id={`tp-len-${i}`} type="number" min={15} step={15} value={tp.length_min} onChange={(e) => patch(i, { length_min: Number(e.target.value) })} />
                </Field>
                <Button variant="ghost" size="icon" aria-label={t("removeTemplate")} onClick={() => { setPreview(null); setTemplates((ts) => ts!.filter((_, j) => j !== i)); }}>
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
            ))}
          </div>
          <Button className="mt-3" variant="outline" size="sm" onClick={() => { setPreview(null); setTemplates((ts) => [...(ts ?? []), { dock_type: "STANDARD", start: facility.open_time, end: facility.close_time, length_min: 60 }]); }}>
            {t("addTemplate")}
          </Button>
        </fieldset>
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={run.isPending || !templates?.length} onClick={() => run.mutate(true)}>
              {t("preview")}
            </Button>
            <Button disabled={!preview || preview.to_create === 0 || create.isPending} onClick={() => create.mutate(false)}>
              {t("create", { count: preview?.to_create ?? 0 })}
            </Button>
          </div>
        )}
      </Card>
      {preview && (
        <Card aria-live="polite">
          <h3 className="font-semibold">{t("previewTitle")}</h3>
          <p className="mt-1 text-sm">{t("previewSummary", { create: preview.to_create, skipped: preview.skipped_overlap })}</p>
          {preview.per_dock.length > 0 && (
            <ul className="mt-3 flex flex-wrap gap-2">
              {preview.per_dock.map((d) => (
                <li key={d.dock_code}>
                  <Badge tone="accent">
                    {d.dock_code}: {d.count}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-muted">{t("previewNote")}</p>
        </Card>
      )}
    </div>
  );
}

/* ----------------------------------- manage ---------------------------------- */
type BulkAction = { status: "OPEN" | "BLOCKED" | "CLOSED" };

function BulkDialog({ action, slotIds, onClose }: { action: BulkAction; slotIds: string[]; onClose: () => void }) {
  const t = useTranslations("facility.slots");
  const c = useTranslations("common");
  const [reason, setReason] = React.useState("");
  const [affected, setAffected] = React.useState<AffectedAppointment[] | null>(null);
  const [understood, setUnderstood] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const needsReason = action.status !== "OPEN";

  const send = (dry_run: boolean, force: boolean) =>
    api<BulkStatusResult>("/slots/bulk-status", { method: "POST", body: { slot_ids: slotIds, status: action.status, reason: reason || null, dry_run, force } });

  const check = useFacMutation(() => send(true, false), {
    onSuccess: (r) => {
      setErr(null);
      setAffected(r.affected_appointments);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "BOOKINGS_AFFECTED") setAffected((e.details.affected_appointments as AffectedAppointment[]) ?? []);
      else setErr(apiErrorText(e));
    },
  });
  const apply = useFacMutation(() => send(false, (affected?.length ?? 0) > 0), {
    success: t("bulkDone"),
    onSuccess: onClose,
    onError: (e) => {
      if (e instanceof ApiError && e.code === "BOOKINGS_AFFECTED") setAffected((e.details.affected_appointments as AffectedAppointment[]) ?? []);
      else setErr(apiErrorText(e));
    },
  });
  const reasonOk = !needsReason || reason.trim().length >= 3;

  return (
    <Dialog
      open
      onClose={onClose}
      title={t(`bulk.${action.status}`, { count: slotIds.length })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          {affected === null ? (
            <Button disabled={!reasonOk || check.isPending} onClick={() => check.mutate()}>
              {t("checkEffect")}
            </Button>
          ) : (
            <Button
              className={affected.length > 0 ? "bg-danger text-white" : undefined}
              disabled={apply.isPending || (affected.length > 0 && !understood)}
              onClick={() => apply.mutate()}
            >
              {t("applyChange")}
            </Button>
          )}
        </>
      }
    >
      <FormError message={err} />
      <div className="space-y-4">
        {needsReason && (
          <Field label={t("reason")} htmlFor="bulk-reason">
            <Input id="bulk-reason" value={reason} disabled={affected !== null} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}
        {affected !== null && (
          <div role="status" aria-live="polite" className="space-y-3">
            <Affected items={affected} />
            {affected.length > 0 && <Checkbox label={t("understand")} checked={understood} onChange={(e) => setUnderstood(e.target.checked)} />}
          </div>
        )}
      </div>
    </Dialog>
  );
}

function ManageTab({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.slots");
  const f = useTranslations("facility");
  const canWrite = useCap("docks_slots_rules") === "W";
  const [date, setDate] = React.useState(() => todayIn(facility.timezone));
  const [dockId, setDockId] = React.useState("");
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const [action, setAction] = React.useState<BulkAction | null>(null);
  const docks = useFacQuery<Dock[]>(`/docks${qs({ facility_id: facility.id })}`);
  const dates = useFacQuery<string[]>(`/slots/dates${qs({ facility_id: facility.id })}`);
  const q = useFacQuery<SlotRow[]>(`/slots${qs({ facility_id: facility.id, date_from: date, date_to: date, dock_id: dockId })}`);
  const rows = q.data ?? [];
  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.id));

  React.useEffect(() => setSelected(new Set()), [date, dockId, facility.id]);

  const toggle = (id: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <DatePicker value={date} onChange={setDate} tz={facility.timezone} dates={dates.data} />
          <label className="sr-only" htmlFor="manage-dock">
            {t("dockFilter")}
          </label>
          <Select id="manage-dock" className="w-40" value={dockId} onChange={(e) => setDockId(e.target.value)}>
            <option value="">{t("allDocks")}</option>
            {(docks.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.dock_code}
              </option>
            ))}
          </Select>
        </div>
        {canWrite && (
          <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("bulkActions")}>
            <span className="text-sm text-muted" role="status">
              {t("selected", { count: selected.size })}
            </span>
            {(["BLOCKED", "CLOSED", "OPEN"] as const).map((s) => (
              <Button key={s} size="sm" variant="outline" disabled={selected.size === 0} onClick={() => setAction({ status: s })}>
                {t(`action.${s}`)}
              </Button>
            ))}
          </div>
        )}
      </div>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("noSlots")}>
        <TableShell caption={t("manageTitle")}>
          <thead>
            <tr className="border-b border-border">
              {canWrite && (
                <th scope="col" className={cn(th, "w-10")}>
                  <input
                    type="checkbox"
                    aria-label={t("selectAll")}
                    checked={allSelected}
                    onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)))}
                    className="size-4 accent-[var(--accent)]"
                  />
                </th>
              )}
              {[t("dock"), t("time"), t("status"), t("booked"), t("reason")].map((h) => (
                <th key={h} scope="col" className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-border last:border-b-0">
                {canWrite && (
                  <td className={td}>
                    <input type="checkbox" aria-label={`${r.dock_code} ${hhmm(r.start, facility.timezone)}`} checked={selected.has(r.id)} onChange={() => toggle(r.id)} className="size-4 accent-[var(--accent)]" />
                  </td>
                )}
                <td className={`${td} font-medium`}>{r.dock_code}</td>
                <td className={`${td} tabular-nums`}>
                  {hhmm(r.start, facility.timezone)}–{hhmm(r.end, facility.timezone)}
                </td>
                <td className={td}>
                  <Badge tone={r.slot_status === "OPEN" ? "success" : "danger"}>{f(`slotStatus.${r.slot_status}`)}</Badge>
                </td>
                <td className={td}>{r.booked ? <Badge tone="accent">{t("booked")}</Badge> : "—"}</td>
                <td className={td}>{r.block_reason ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>
      {action && <BulkDialog action={action} slotIds={Array.from(selected)} onClose={() => setAction(null)} />}
    </div>
  );
}

/* ----------------------------------- copy day -------------------------------- */
function CopyTab({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.slots");
  const canWrite = useCap("docks_slots_rules") === "W";
  const dates = useFacQuery<string[]>(`/slots/dates${qs({ facility_id: facility.id })}`);
  const [from, setFrom] = React.useState(() => todayIn(facility.timezone));
  const [target, setTarget] = React.useState("");
  const [targets, setTargets] = React.useState<string[]>([]);
  const [preview, setPreview] = React.useState<CopyDayResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const send = (dry_run: boolean) => api<CopyDayResult>("/slots/copy-day", { method: "POST", body: { facility_id: facility.id, from_date: from, to_dates: targets, dry_run } });
  const check = useFacMutation(() => send(true), { onSuccess: (r) => { setErr(null); setPreview(r); }, onError: (e) => setErr(apiErrorText(e)) });
  const apply = useFacMutation(() => send(false), { success: t("copied"), onSuccess: () => setPreview(null), onError: (e) => setErr(apiErrorText(e)) });

  return (
    <Card className="space-y-4">
      <FormError message={err} />
      <Field label={t("copyFrom")} htmlFor="copy-from" hint={t("copyHint")}>
        <div className="flex flex-wrap items-center gap-2">
          <Input id="copy-from" type="date" className="w-44" value={from} onChange={(e) => { setFrom(e.target.value); setPreview(null); }} />
          {dates.data && dates.data.length > 0 && (
            <Select aria-label={t("pickDataDate")} className="w-44" value="" onChange={(e) => e.target.value && setFrom(e.target.value)}>
              <option value="">{t("pickDataDate")}</option>
              {[...dates.data].sort().reverse().slice(0, 60).map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </Select>
          )}
        </div>
      </Field>
      <Field label={t("copyTo")} htmlFor="copy-to">
        <div className="flex flex-wrap items-center gap-2">
          <Input id="copy-to" type="date" className="w-44" value={target} onChange={(e) => setTarget(e.target.value)} />
          <Button variant="outline" disabled={!target || targets.includes(target) || target === from} onClick={() => { setTargets((x) => [...x, target]); setTarget(""); setPreview(null); }}>
            {t("addDate")}
          </Button>
        </div>
      </Field>
      {targets.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={t("copyTo")}>
          {targets.map((d) => (
            <li key={d}>
              <Badge tone="accent" className="gap-1.5">
                {d}
                <button type="button" aria-label={t("removeDate", { date: d })} onClick={() => { setTargets((x) => x.filter((y) => y !== d)); setPreview(null); }}>
                  ×
                </button>
              </Badge>
            </li>
          ))}
        </ul>
      )}
      {canWrite && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={targets.length === 0 || check.isPending} onClick={() => check.mutate()}>
            {t("preview")}
          </Button>
          <Button disabled={!preview || preview.to_create === 0 || apply.isPending} onClick={() => apply.mutate()}>
            {t("create", { count: preview?.to_create ?? 0 })}
          </Button>
        </div>
      )}
      {preview && (
        <p role="status" aria-live="polite" className="rounded-md bg-accent-soft px-3 py-2 text-sm">
          {t("previewSummary", { create: preview.to_create, skipped: preview.skipped_overlap })}
        </p>
      )}
    </Card>
  );
}

function SlotsView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.slots");
  const [tab, setTab] = React.useState<Tab>("generate");
  const tabs: Tab[] = ["generate", "manage", "copy"];
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div role="tablist" aria-label={t("title")} className="mb-4 flex gap-1 border-b border-border">
        {tabs.map((x) => (
          <button
            key={x}
            role="tab"
            id={`tab-${x}`}
            aria-selected={tab === x}
            aria-controls={`panel-${x}`}
            tabIndex={tab === x ? 0 : -1}
            onClick={() => setTab(x)}
            onKeyDown={(e) => {
              const i = tabs.indexOf(tab);
              if (e.key === "ArrowRight") setTab(tabs[(i + 1) % tabs.length]);
              if (e.key === "ArrowLeft") setTab(tabs[(i + tabs.length - 1) % tabs.length]);
            }}
            className={cn("-mb-px border-b-2 px-4 py-2 text-sm font-medium", tab === x ? "border-accent text-accent" : "border-transparent text-muted hover:text-foreground")}
          >
            {t(`tab.${x}`)}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "generate" && <GenerateTab facility={facility} />}
        {tab === "manage" && <ManageTab facility={facility} />}
        {tab === "copy" && <CopyTab facility={facility} />}
      </div>
    </>
  );
}

export default function SlotsPage() {
  return <RequireFacility>{(f) => <SlotsView key={f.id} facility={f} />}</RequireFacility>;
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Lock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import {
  DecisionDialog,
  describeCoordError,
  Kbd,
  PriorityBadge,
  ReasonCodes,
  StatusBadge,
  SummaryList,
  useCoordText,
} from "@/components/coordinator/shared";
import { KeyValue, QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Field, FormError, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { languageName, useClaim, useCoordMutation, useCoordQuery, useHotkeys } from "@/lib/coord";
import type { Booked, CoordOption, Escalation, RecommendedAction, RequestDetail } from "@/lib/coord-types";
import { useCap } from "@/lib/fac";
import type { SchedulingOptions } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { describeProblem } from "@/lib/problems";
import { hhmm, zonedToIso } from "@/lib/time";
import { cn } from "@/lib/utils";

type Dlg = null | "approve" | "suggest" | "hold" | "reject" | "escalate";
const OPEN_STATUSES = ["waiting", "held", "suggested"];

function range(start: string, end: string, locale: string) {
  return `${formatDateTime(start, locale)} – ${hhmm(end)}`;
}

export function RequestDetailView({ id }: { id: string }) {
  const t = useTranslations("coord.request");
  const nav = useTranslations("nav");
  const locale = useLocale();
  const router = useRouter();
  const canDecide = useCap("booking_decisions") === "W";
  const claim = useClaim("request", id);
  const q = useCoordQuery<RequestDetail>(`/coordinator/requests/${id}`, { refetchInterval: 15_000 });
  const [dlg, setDlg] = React.useState<Dlg>(null);
  const [now, setNow] = React.useState(() => Date.now());
  React.useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const d = q.data;
  const open = !!d && OPEN_STATUSES.includes(d.request.status);
  const blockedBy = claim.status === "other" ? claim.owner : d?.claimed_by && claim.status !== "mine" ? d.claimed_by : null;
  const actionable = canDecide && open && !blockedBy;
  const held = d?.held_option ?? null;
  const approveReady = !!held && held.feasible;

  const openDialog = (kind: Exclude<Dlg, null>) => {
    if (!actionable) return;
    if (kind === "approve" && !approveReady) return void toast.error(held ? t("approveInfeasible") : t("approveNeedsHold"));
    setDlg(kind);
  };

  useHotkeys(
    { a: () => openDialog("approve"), s: () => openDialog("suggest"), h: () => openDialog("hold"), r: () => openDialog("reject"), e: () => openDialog("escalate") },
    !!d,
  );

  const applyRecommendation = (action: RecommendedAction) => openDialog(action);

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: nav("inbox"), href: "/coordinator" }, { label: d?.shipment.code ?? "…" }]}
        title={d ? t("title", { code: d.shipment.code }) : t("titleLoading")}
        description={d ? `${d.facility.code} · ${d.shipment.carrier_name ?? "—"}` : undefined}
        actions={
          d && (
            <>
              <PriorityBadge code={d.shipment.priority_code} />
              <StatusBadge status={d.request.status} />
            </>
          )
        }
      />

      {blockedBy && (
        <div role="status" className="mb-4 flex items-center gap-2 rounded-md border border-amber-500 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">
          <Lock className="size-4 shrink-0" aria-hidden="true" />
          {blockedBy.name ? t("handledBy", { name: blockedBy.name }) : t("handledByOther")} {t("readOnly")}
        </div>
      )}
      {claim.status === "error" && <p className="mb-3 text-xs text-muted">{t("claimUnavailable")}</p>}

      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()}>
        {d && (
          <div className="grid gap-5 lg:grid-cols-3">
            <div className="space-y-5 lg:col-span-2">
              <MessageAndFacts d={d} locale={locale} />
              <OptionsCard d={d} now={now} locale={locale} actionable={actionable} onSuggest={() => openDialog("suggest")} />
              <EtaHistory d={d} locale={locale} />
            </div>
            <div className="space-y-5">
              <ActionBar
                actionable={actionable}
                approveReady={approveReady}
                open={open}
                canDecide={canDecide}
                onOpen={openDialog}
              />
              <RecommendationCard d={d} actionable={actionable} onApply={applyRecommendation} />
              <ShipmentCard d={d} locale={locale} />
            </div>
          </div>
        )}
      </QueryState>

      {d && (
        <>
          <ApproveDialog open={dlg === "approve"} onClose={() => setDlg(null)} d={d} locale={locale} onDone={() => router.push("/coordinator")} />
          <SuggestDialog open={dlg === "suggest"} onClose={() => setDlg(null)} d={d} locale={locale} onDone={() => setDlg(null)} />
          <HoldDialog open={dlg === "hold"} onClose={() => setDlg(null)} d={d} onDone={() => setDlg(null)} />
          <RejectDialog open={dlg === "reject"} onClose={() => setDlg(null)} d={d} onDone={() => router.push("/coordinator")} />
          <EscalateDialog open={dlg === "escalate"} onClose={() => setDlg(null)} d={d} onDone={(escId) => router.push(`/coordinator/escalations/${escId}`)} />
        </>
      )}
    </>
  );
}

// ---------------------------------------------------------------- cards

function MessageAndFacts({ d, locale }: { d: RequestDetail; locale: string }) {
  const t = useTranslations("coord.request");
  const f = d.facts;
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("driverMessage")}</h2>
      {f?.original_message ? (
        <blockquote className="rounded-md border-l-4 border-accent bg-background px-4 py-3 text-sm">
          <p lang={d.shipment.driver_language ?? undefined}>{f.original_message}</p>
          <p className="mt-2 border-t border-border pt-2 text-xs text-muted">
            {f.translation ? (
              <>
                <span className="font-medium">{t("translation")}:</span> {f.translation}
              </>
            ) : (
              t("noTranslation")
            )}
          </p>
        </blockquote>
      ) : (
        <p className="text-sm text-muted">{t("noMessage")}</p>
      )}
      {f && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted">{t("extractedFacts")}</h3>
            {f.confidence && <Badge tone={f.confidence === "HIGH" ? "success" : f.confidence === "LOW" ? "danger" : "warning"}>{t("confidence", { level: f.confidence })}</Badge>}
            {f.requires_human_review && (
              <Badge tone="warning">
                <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
                {t("needsReview")}
              </Badge>
            )}
          </div>
          <dl className="mt-3 grid gap-4 sm:grid-cols-3">
            <KeyValue label={t("facts.reason")}>{f.reason ?? "—"}</KeyValue>
            <KeyValue label={t("facts.delay")}>{f.reported_delay_min != null ? `${f.reported_delay_min} min` : "—"}</KeyValue>
            <KeyValue label={t("facts.declaredEta")}>{formatDateTime(f.declared_eta_ts, locale)}</KeyValue>
            <KeyValue label={t("facts.earliest")}>{formatDateTime(f.earliest_acceptable_ts, locale)}</KeyValue>
            <KeyValue label={t("facts.latest")}>{formatDateTime(f.latest_acceptable_ts, locale)}</KeyValue>
            <KeyValue label={t("facts.description")}>{f.description ?? "—"}</KeyValue>
          </dl>
        </>
      )}
    </Card>
  );
}

function ShipmentCard({ d, locale }: { d: RequestDetail; locale: string }) {
  const t = useTranslations("coord.request");
  const s = d.shipment;
  const a = d.current_appointment;
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("shipment")}</h2>
      <dl className="grid grid-cols-2 gap-3">
        <KeyValue label={t("sh.driver")}>{s.driver_name ?? "—"}</KeyValue>
        <KeyValue label={t("sh.language")}>{languageName(s.driver_language)}</KeyValue>
        <KeyValue label={t("sh.load")}>{`${s.required_dock_type} · ${s.load_weight_kg} kg`}</KeyValue>
        <KeyValue label={t("sh.unload")}>{`${s.expected_unload_min} min`}</KeyValue>
        {s.temperature_control_required && <KeyValue label={t("sh.temperature")}>{t("sh.temperatureYes")}</KeyValue>}
        <KeyValue label={t("sh.eta")} className="col-span-2">
          {d.eta ? (
            <span className="flex flex-wrap items-center gap-2">
              {formatDateTime(d.eta.upper_ts ?? d.eta.ts, locale)}
              <Badge tone="neutral">{d.eta.source}</Badge>
              <Badge tone={d.eta.confidence === "LOW" ? "danger" : "neutral"}>{d.eta.confidence}</Badge>
              {d.eta.requires_human_review && <Badge tone="warning">{t("needsReview")}</Badge>}
            </span>
          ) : (
            "—"
          )}
        </KeyValue>
        <KeyValue label={t("sh.currentAppointment")} className="col-span-2">
          {a ? (
            <span>
              {a.slot_code} · {a.dock_code} · {range(a.start, a.end, locale)} <Badge tone="neutral">{a.status}</Badge>
            </span>
          ) : (
            t("sh.noAppointment")
          )}
        </KeyValue>
      </dl>
      {s.driver_phone && (
        <a href={`tel:${s.driver_phone}`} className="mt-3 inline-block text-sm font-medium text-accent underline">
          {t("callDriver", { phone: s.driver_phone })}
        </a>
      )}
    </Card>
  );
}

function EtaHistory({ d, locale }: { d: RequestDetail; locale: string }) {
  const t = useTranslations("coord.request");
  const rows = [...d.eta_history].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("etaHistory")}</h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted">{t("noEtaHistory")}</p>
      ) : (
        <ol className="space-y-3 border-l-2 border-border pl-4">
          {rows.map((r, i) => (
            <li key={i} className="relative">
              <span className="absolute -left-[1.4rem] top-1.5 size-2.5 rounded-full bg-accent" aria-hidden="true" />
              <p className="text-sm font-medium">
                {formatDateTime(r.declared_eta_ts, locale)} <Badge tone="neutral">{r.source}</Badge> <Badge tone={r.confidence === "LOW" ? "danger" : "neutral"}>{r.confidence}</Badge>
              </p>
              <p className="text-xs text-muted">
                {formatDateTime(r.created_at, locale)}
                {r.reason ? ` · ${r.reason}` : ""}
                {r.note ? ` · ${r.note}` : ""}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function OptionsCard({
  d,
  now,
  locale,
  actionable,
  onSuggest,
}: {
  d: RequestDetail;
  now: number;
  locale: string;
  actionable: boolean;
  onSuggest: () => void;
}) {
  const t = useTranslations("coord.request");
  const { tf } = useCoordText();
  const held = d.held_option;
  const left = held ? Math.max(0, Math.floor((new Date(held.expires_at).getTime() - now) / 1000)) : 0;
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted">{t("options")}</h2>
        <Button size="sm" variant="outline" disabled={!actionable} onClick={onSuggest}>
          {t("pickAnother")}
        </Button>
      </div>
      {held && (
        <div className={cn("mb-4 rounded-md border px-4 py-3 text-sm", held.feasible ? "border-accent bg-accent-soft" : "border-danger/50 bg-danger/10")}>
          <p className="font-medium">
            {t("heldOption")}: {held.slot_codes.join(" + ")} · {held.dock_code} · {range(held.start, held.end, locale)}
          </p>
          <p className="mt-1 text-xs">
            {t("holdExpiresIn", { time: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` })}
            {!held.feasible && ` · ${t("noLongerFeasible")}: ${held.problems.map((p) => describeProblem(p, tf)).join(" ")}`}
          </p>
        </div>
      )}
      {d.options.length === 0 ? (
        <p className="rounded-md border border-dashed border-border py-6 text-center text-sm text-muted">{t("noOptions")}</p>
      ) : (
        <ol className="space-y-3">
          {d.options.map((o) => (
            <OptionRow key={o.slot_ids.join()} o={o} locale={locale} recommended={sameSlots(o.slot_ids, d.recommendation.slot_ids)} />
          ))}
        </ol>
      )}
    </Card>
  );
}

function sameSlots(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x) => b.includes(x));
}

function OptionRow({ o, locale, recommended }: { o: CoordOption; locale: string; recommended?: boolean }) {
  const t = useTranslations("coord.request");
  return (
    <li className={cn("rounded-md border px-4 py-3", recommended ? "border-accent" : "border-border")}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">#{o.rank}</Badge>
        <span className="font-medium">
          {o.slot_codes.join(" + ")} · {o.dock_code} ({o.dock_type})
        </span>
        <span className="text-sm text-muted">{range(o.start, o.end, locale)}</span>
        {o.needs_planner_approval && <Badge tone="warning">{t("needsPlanner")}</Badge>}
        {recommended && <Badge tone="success">{t("recommended")}</Badge>}
      </div>
      <p className="mt-1.5 text-sm text-muted">{o.explanation}</p>
      <ReasonCodes codes={o.reasons} className="mt-2" />
    </li>
  );
}

function RecommendationCard({ d, actionable, onApply }: { d: RequestDetail; actionable: boolean; onApply: (a: RecommendedAction) => void }) {
  const t = useTranslations("coord.request");
  const r = d.recommendation;
  return (
    <Card className="border-accent/60">
      <p className="text-xs font-medium uppercase tracking-wider text-muted">{t("recommendation")}</p>
      <p className="mt-1 text-lg font-semibold">{t(`actions.${r.action}`)}</p>
      <p className="text-xs text-muted">{t("recommendationSource")}</p>
      {r.reasons.length > 0 && (
        <>
          <h3 className="mt-3 text-xs font-medium uppercase tracking-wider text-muted">{t("why")}</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.reasons.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </>
      )}
      {r.impact.length > 0 && (
        <>
          <h3 className="mt-3 text-xs font-medium uppercase tracking-wider text-muted">{t("impact")}</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
            {r.impact.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </>
      )}
      {r.risk_flags.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5" aria-label={t("riskFlags")}>
          {r.risk_flags.map((x, i) => (
            <li key={i}>
              <Badge tone="warning">
                <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
                {x}
              </Badge>
            </li>
          ))}
        </ul>
      )}
      <Button className="mt-4 w-full" variant="outline" disabled={!actionable} onClick={() => onApply(r.action)}>
        {t("applyRecommendation", { action: t(`actions.${r.action}`) })}
      </Button>
    </Card>
  );
}

function ActionBar({
  actionable,
  approveReady,
  open,
  canDecide,
  onOpen,
}: {
  actionable: boolean;
  approveReady: boolean;
  open: boolean;
  canDecide: boolean;
  onOpen: (k: Exclude<Dlg, null>) => void;
}) {
  const t = useTranslations("coord.request");
  const items: { k: Exclude<Dlg, null>; key: string; variant: "primary" | "outline"; off?: boolean }[] = [
    { k: "approve", key: "a", variant: "primary", off: !approveReady },
    { k: "suggest", key: "s", variant: "outline" },
    { k: "hold", key: "h", variant: "outline" },
    { k: "reject", key: "r", variant: "outline" },
    { k: "escalate", key: "e", variant: "outline" },
  ];
  return (
    <Card>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("decide")}</h2>
      <div className="grid grid-cols-1 gap-2">
        {items.map((i) => (
          <Button key={i.k} variant={i.variant} disabled={!actionable || i.off} onClick={() => onOpen(i.k)} className="justify-between">
            <span>{t(`buttons.${i.k}`)}</span>
            <Kbd>{i.key}</Kbd>
          </Button>
        ))}
      </div>
      {!canDecide && <p className="mt-3 text-xs text-muted">{t("noPermission")}</p>}
      {canDecide && !open && <p className="mt-3 text-xs text-muted">{t("closed")}</p>}
      {actionable && !approveReady && <p className="mt-3 text-xs text-muted">{t("approveNeedsHold")}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- dialogs

function useDecision<TVars, TRes>(fn: (v: TVars) => Promise<TRes>, success: string, onDone: (r: TRes) => void) {
  const { tc, tf } = useCoordText();
  const [error, setError] = React.useState<string | null>(null);
  const m = useCoordMutation(fn, {
    success,
    onSuccess: (r) => {
      setError(null);
      onDone(r);
    },
    onError: (e) => {
      const msg = describeCoordError(e, tc, tf);
      setError(msg);
      toast.error(msg);
    },
  });
  return { m, error, reset: () => setError(null) };
}

function DriverLine({ d }: { d: RequestDetail }) {
  const t = useTranslations("coord.request");
  return (
    <p className="text-xs text-muted">
      {t("driverTold", { language: languageName(d.shipment.driver_language), driver: d.shipment.driver_name ?? "—" })}
    </p>
  );
}

function ApproveDialog({ open, onClose, d, locale, onDone }: { open: boolean; onClose: () => void; d: RequestDetail; locale: string; onDone: () => void }) {
  const t = useTranslations("coord.request.approve");
  const held = d.held_option;
  const { m, error } = useDecision(
    () => api<Booked>(`/booking/requests/${d.request.id}/approve`, { method: "POST" }),
    t("done"),
    (r) => {
      if (r.needs_planner_approval) toast.message(t("pendingNote"));
      onDone();
    },
  );
  return (
    <DecisionDialog open={open} onClose={onClose} title={t("title")} description={t("description")} confirmLabel={t("confirm")} onConfirm={() => m.mutate(undefined)} pending={m.isPending}>
      <FormError message={error} />
      <SummaryList
        rows={[
          { label: t("shipment"), value: `${d.shipment.code} · ${d.shipment.carrier_name ?? "—"}` },
          { label: t("slot"), value: held ? `${held.slot_codes.join(" + ")} · ${held.dock_code} · ${range(held.start, held.end, locale)}` : "—" },
          {
            label: t("replaces"),
            value: d.current_appointment
              ? `${d.current_appointment.slot_code} · ${range(d.current_appointment.start, d.current_appointment.end, locale)}`
              : t("none"),
          },
        ]}
      />
      <p>{t("promise")}</p>
      <DriverLine d={d} />
    </DecisionDialog>
  );
}

function SuggestDialog({ open, onClose, d, locale, onDone }: { open: boolean; onClose: () => void; d: RequestDetail; locale: string; onDone: () => void }) {
  const t = useTranslations("coord.request.suggest");
  const [more, setMore] = React.useState(false);
  const [choice, setChoice] = React.useState<string | null>(null);
  const extra = useQuery<SchedulingOptions>({
    queryKey: ["options", d.shipment.id, "more"],
    queryFn: () => api<SchedulingOptions>("/scheduling/options", { method: "POST", body: { shipment_id: d.shipment.id, limit: 10 } }),
    enabled: open && more,
  });
  const all = React.useMemo(() => {
    const seen = new Set<string>();
    const out: CoordOption[] = [];
    for (const o of [...d.options, ...(extra.data?.options ?? [])]) {
      const k = o.slot_ids.join();
      if (!seen.has(k)) {
        seen.add(k);
        out.push(o);
      }
    }
    return out;
  }, [d.options, extra.data]);
  React.useEffect(() => {
    if (open && choice === null) setChoice(all.find((o) => sameSlots(o.slot_ids, d.recommendation.slot_ids))?.slot_ids.join() ?? all[0]?.slot_ids.join() ?? null);
  }, [open, all, choice, d.recommendation.slot_ids]);
  const picked = all.find((o) => o.slot_ids.join() === choice);
  const { m, error } = useDecision(
    (slotIds: string[]) => api(`/booking/requests/${d.request.id}/suggest`, { method: "POST", body: { slot_ids: slotIds } }),
    t("done"),
    onDone,
  );
  return (
    <DecisionDialog
      open={open}
      onClose={onClose}
      title={t("title")}
      description={t("description")}
      confirmLabel={t("confirm")}
      onConfirm={() => picked && m.mutate(picked.slot_ids)}
      pending={m.isPending}
      disabled={!picked}
    >
      <FormError message={error} />
      {all.length === 0 ? (
        <p className="text-muted">{t("none")}</p>
      ) : (
        <ul className="max-h-72 space-y-2 overflow-y-auto" role="radiogroup" aria-label={t("title")}>
          {all.map((o) => {
            const k = o.slot_ids.join();
            return (
              <li key={k}>
                <label className={cn("flex cursor-pointer gap-3 rounded-md border px-3 py-2", choice === k ? "border-accent bg-accent-soft" : "border-border")}>
                  <input type="radio" name="slot" className="mt-1 accent-[var(--accent)]" checked={choice === k} onChange={() => setChoice(k)} />
                  <span className="text-sm">
                    <span className="font-medium">
                      #{o.rank} {o.slot_codes.join(" + ")} · {o.dock_code} · {range(o.start, o.end, locale)}
                    </span>
                    {o.needs_planner_approval && <Badge tone="warning" className="ml-2">{t("needsPlanner")}</Badge>}
                    <span className="mt-0.5 block text-xs text-muted">{o.explanation}</span>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {!more && (
        <Button size="sm" variant="outline" onClick={() => setMore(true)}>
          {t("showMore")}
        </Button>
      )}
      {more && extra.isLoading && <p className="text-xs text-muted">{t("loadingMore")}</p>}
      <p className="text-xs text-muted">{t("holdNote")}</p>
      <DriverLine d={d} />
    </DecisionDialog>
  );
}

function HoldDialog({ open, onClose, d, onDone }: { open: boolean; onClose: () => void; d: RequestDetail; onDone: () => void }) {
  const t = useTranslations("coord.request.hold");
  const [minutes, setMinutes] = React.useState("15");
  const [deadline, setDeadline] = React.useState("");
  const { m, error } = useDecision(
    () =>
      api(`/booking/requests/${d.request.id}/hold`, {
        method: "POST",
        body: { extend_minutes: Number(minutes), decision_deadline: deadline ? zonedToIso(deadline) : undefined },
      }),
    t("done"),
    onDone,
  );
  return (
    <DecisionDialog open={open} onClose={onClose} title={t("title")} description={t("description")} confirmLabel={t("confirm")} onConfirm={() => m.mutate(undefined)} pending={m.isPending}>
      <FormError message={error} />
      <Field label={t("minutes")} htmlFor="hold-min" hint={t("policy")}>
        <Select id="hold-min" value={minutes} onChange={(e) => setMinutes(e.target.value)}>
          {[15, 30, 45, 60].map((n) => (
            <option key={n} value={n}>
              {n} min
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t("deadline")} htmlFor="hold-deadline" hint={t("deadlineHint")}>
        <Input id="hold-deadline" type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
      </Field>
      <DriverLine d={d} />
    </DecisionDialog>
  );
}

function RejectDialog({ open, onClose, d, onDone }: { open: boolean; onClose: () => void; d: RequestDetail; onDone: () => void }) {
  const t = useTranslations("coord.request.reject");
  const [reason, setReason] = React.useState("");
  const valid = reason.trim().length >= 3;
  const { m, error } = useDecision(
    () => api(`/booking/requests/${d.request.id}/reject`, { method: "POST", body: { reason: reason.trim() } }),
    t("done"),
    onDone,
  );
  return (
    <DecisionDialog open={open} onClose={onClose} title={t("title")} description={t("description")} confirmLabel={t("confirm")} onConfirm={() => m.mutate(undefined)} pending={m.isPending} disabled={!valid} destructive>
      <FormError message={error} />
      <Field label={t("reason")} htmlFor="reject-reason" error={reason.length > 0 && !valid ? "tooShort" : undefined}>
        <Textarea id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("placeholder")} />
      </Field>
      <p>{t("effect")}</p>
      <DriverLine d={d} />
    </DecisionDialog>
  );
}

function EscalateDialog({ open, onClose, d, onDone }: { open: boolean; onClose: () => void; d: RequestDetail; onDone: (id: string) => void }) {
  const t = useTranslations("coord.request.escalate");
  const [reason, setReason] = React.useState("");
  const [note, setNote] = React.useState("");
  const valid = reason.trim().length >= 3;
  const { m, error } = useDecision(
    () => api<Escalation>(`/coordinator/requests/${d.request.id}/escalate`, { method: "POST", body: { reason: reason.trim(), note: note.trim() || undefined } }),
    t("done"),
    (esc) => onDone(esc.id),
  );
  return (
    <DecisionDialog open={open} onClose={onClose} title={t("title")} description={t("description")} confirmLabel={t("confirm")} onConfirm={() => m.mutate(undefined)} pending={m.isPending} disabled={!valid}>
      <FormError message={error} />
      <Field label={t("reason")} htmlFor="esc-reason" error={reason.length > 0 && !valid ? "tooShort" : undefined}>
        <Textarea id="esc-reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={t("placeholder")} />
      </Field>
      <Field label={t("note")} htmlFor="esc-note">
        <Textarea id="esc-note" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <p>{t("effect")}</p>
    </DecisionDialog>
  );
}

"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { DecisionDialog, describeCoordError, PriorityBadge, SummaryList, useCoordText } from "@/components/coordinator/shared";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Field, FormError, Select, Textarea } from "@/components/ui/fields";
import type { Page } from "@/lib/admin-types";
import { api } from "@/lib/api";
import { MIN_OVERRIDE_REASON, useCoordMutation, useCoordQuery, validateCompetingDecision } from "@/lib/coord";
import type { CompetingGroup, CompetingRequest, CompetingResult, DecideResult } from "@/lib/coord-types";
import { useCap } from "@/lib/fac";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";
import { useOptions } from "@/lib/use-api";
import { cn } from "@/lib/utils";

export default function CompetingPage() {
  const t = useTranslations("coord.competing");
  const locale = useLocale();
  const [facility, setFacility] = React.useState("");
  const facilities = useOptions<Page<{ id: string; code: string }>>("/facilities?limit=200&active=true");
  const q = useCoordQuery<CompetingResult>(`/coordinator/competing${buildQuery({ facility_id: facility })}`, { refetchInterval: 20_000 });
  const [pick, setPick] = React.useState<{ group: CompetingGroup; winner: CompetingRequest } | null>(null);
  const groups = q.data?.groups ?? [];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4">
        <Select aria-label={t("facility")} className="w-56" value={facility} onChange={(e) => setFacility(e.target.value)}>
          <option value="">{t("allFacilities")}</option>
          {facilities.data?.items.map((f) => (
            <option key={f.id} value={f.id}>
              {f.code}
            </option>
          ))}
        </Select>
      </div>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={groups.length === 0} emptyText={t("empty")}>
        <div className="space-y-6">
          {groups.map((g) => (
            <GroupView key={g.key} group={g} locale={locale} onChoose={(winner) => setPick({ group: g, winner })} />
          ))}
        </div>
      </QueryState>
      {pick && <DecideDialog pick={pick} locale={locale} onClose={() => setPick(null)} />}
    </>
  );
}

function GroupView({ group, locale, onChoose }: { group: CompetingGroup; locale: string; onChoose: (w: CompetingRequest) => void }) {
  const t = useTranslations("coord.competing");
  const canDecide = useCap("booking_decisions") === "W";
  const ordered = [...group.requests].sort((a, b) => a.rank - b.rank);
  return (
    <section aria-label={t("group", { slot: group.slot_code })}>
      <h2 className="mb-2 text-sm font-semibold">
        {group.facility_code} · {group.dock_code} · {group.slot_code} <span className="font-normal text-muted">({formatDateTime(group.start, locale)})</span>
      </h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {ordered.map((r) => (
          <Card key={r.request_id} className={cn(r.rank === 1 && "border-accent")}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={r.rank === 1 ? "success" : "neutral"}>#{r.rank}</Badge>
              <span className="font-mono font-medium">{r.shipment_code}</span>
              <PriorityBadge code={r.priority_code} />
              {r.fixed && <Badge tone="danger">{t("fixed")}</Badge>}
              {r.tie_with_next && <Badge tone="warning">{t("tie")}</Badge>}
            </div>
            <p className="mt-1 text-xs text-muted">
              {t("score", { score: r.score })} · {t("waiting", { min: r.waiting_min })}
            </p>
            <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm">
              {r.reasons.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
            <Button className="mt-3 w-full" size="sm" variant={r.rank === 1 ? "primary" : "outline"} disabled={!canDecide} onClick={() => onChoose(r)}>
              {r.rank === 1 ? t("approveTop") : t("override")}
            </Button>
          </Card>
        ))}
      </div>
    </section>
  );
}

function DecideDialog({ pick, locale, onClose }: { pick: { group: CompetingGroup; winner: CompetingRequest }; locale: string; onClose: () => void }) {
  const t = useTranslations("coord.competing.decide");
  const { tc, tf } = useCoordText();
  const policyWinner = [...pick.group.requests].sort((a, b) => a.rank - b.rank)[0];
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const check = validateCompetingDecision({ winnerId: pick.winner.request_id, policyWinnerId: policyWinner?.request_id ?? null, reason });
  const m = useCoordMutation(
    () =>
      api<DecideResult>("/coordinator/competing/decide", {
        method: "POST",
        body: {
          winner_request_id: pick.winner.request_id,
          group_request_ids: pick.group.requests.map((r) => r.request_id),
          override_reason: reason.trim() || undefined,
        },
      }),
    {
      success: t("done"),
      onSuccess: onClose,
      onError: (e) => {
        const msg = describeCoordError(e, tc, tf);
        setError(msg);
        toast.error(msg);
      },
    },
  );
  const overrode = check.ok ? check.overrode : pick.winner.request_id !== policyWinner?.request_id;
  return (
    <DecisionDialog
      open
      onClose={onClose}
      title={overrode ? t("overrideTitle") : t("title")}
      description={t("description")}
      confirmLabel={overrode ? t("overrideConfirm") : t("confirm")}
      onConfirm={() => check.ok && m.mutate(undefined)}
      pending={m.isPending}
      disabled={!check.ok}
    >
      <FormError message={error} />
      <SummaryList
        rows={[
          { label: t("winner"), value: `${pick.winner.shipment_code} (#${pick.winner.rank})` },
          { label: t("slot"), value: `${pick.group.slot_code} · ${pick.group.dock_code} · ${formatDateTime(pick.group.start, locale)}` },
          { label: t("policy"), value: policyWinner ? `${policyWinner.shipment_code} (#1)` : "—" },
        ]}
      />
      {overrode && (
        <>
          <p className="rounded-md border border-amber-500 bg-amber-50 px-3 py-2 text-amber-900 dark:bg-amber-950 dark:text-amber-100">{t("overrideWarning")}</p>
          <Field
            label={t("reason")}
            htmlFor="override-reason"
            hint={t("reasonHint", { min: MIN_OVERRIDE_REASON })}
            error={reason.length > 0 && !check.ok ? "min10" : undefined}
          >
            <Textarea id="override-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        </>
      )}
    </DecisionDialog>
  );
}

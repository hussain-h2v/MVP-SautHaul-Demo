"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { describeCoordError, useCoordText } from "@/components/coordinator/shared";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useCoordMutation, useCoordQuery } from "@/lib/coord";
import type { HandoverDraft, HandoverRecord } from "@/lib/coord-types";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";
import { DEFAULT_TZ, zonedToIso } from "@/lib/time";

/** "YYYY-MM-DDTHH:mm" in IST for a datetime-local input, N hours ago. */
function localHoursAgo(hours: number): string {
  const d = new Date(Date.now() - hours * 3_600_000);
  const p = new Intl.DateTimeFormat("en-CA", { timeZone: DEFAULT_TZ, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(d)
    .reduce<Record<string, string>>((a, x) => ({ ...a, [x.type]: x.value }), {});
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

function snapshotCounts(s: Record<string, unknown>): [string, number][] {
  return Object.entries(s).flatMap(([k, v]) =>
    typeof v === "number" ? [[k, v] as [string, number]] : Array.isArray(v) ? [[k, v.length] as [string, number]] : [],
  );
}

export default function HandoverPage() {
  const t = useTranslations("coord.handover");
  const { tc, tf } = useCoordText();
  const locale = useLocale();
  const [since, setSince] = React.useState(() => localHoursAgo(8));
  const sinceIso = React.useMemo(() => zonedToIso(since), [since]);
  const draft = useCoordQuery<HandoverDraft>(`/coordinator/handover/draft${buildQuery({ since: sinceIso })}`);
  const history = useCoordQuery<HandoverRecord[]>("/coordinator/handover?limit=20");
  const [summary, setSummary] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [edited, setEdited] = React.useState(false);

  React.useEffect(() => {
    if (draft.data && !edited) setSummary(draft.data.summary);
  }, [draft.data, edited]);

  const save = useCoordMutation(
    () => api("/coordinator/handover", { method: "POST", body: { shift_started_at: sinceIso, summary: summary.trim(), notes: notes.trim() || undefined } }),
    {
      success: t("saved"),
      onSuccess: () => {
        setNotes("");
        setEdited(false);
      },
      onError: (e) => toast.error(describeCoordError(e, tc, tf)),
    },
  );
  const counts = snapshotCounts(draft.data?.snapshot ?? {});

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <Field label={t("since")} htmlFor="since" hint={t("sinceHint")}>
              <Input
                id="since"
                type="datetime-local"
                className="w-64"
                value={since}
                onChange={(e) => {
                  setSince(e.target.value);
                  setEdited(false);
                }}
              />
            </Field>
            <QueryState isLoading={draft.isLoading} isError={draft.isError} onRetry={() => draft.refetch()}>
              <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label={t("snapshot")}>
                {counts.map(([k, n]) => (
                  <li key={k} className="rounded-md border border-border px-3 py-2">
                    <span className="block text-xs uppercase tracking-wider text-muted">{t.has(`counts.${k}`) ? t(`counts.${k}`) : k.replace(/_/g, " ")}</span>
                    <span className="text-xl font-semibold tabular-nums">{n}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-4 space-y-4">
                <Field label={t("summary")} htmlFor="summary" hint={t("summaryHint")}>
                  <Textarea
                    id="summary"
                    className="min-h-56"
                    value={summary}
                    onChange={(e) => {
                      setSummary(e.target.value);
                      setEdited(true);
                    }}
                  />
                </Field>
                <Field label={t("notes")} htmlFor="notes">
                  <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={summary.trim().length < 3 || save.isPending} onClick={() => save.mutate(undefined)}>
                    {t("save")}
                  </Button>
                  {edited && (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setEdited(false);
                        if (draft.data) setSummary(draft.data.summary);
                      }}
                    >
                      {t("resetDraft")}
                    </Button>
                  )}
                </div>
              </div>
            </QueryState>
          </Card>
        </div>

        <Card>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted">{t("history")}</h2>
          <QueryState isLoading={history.isLoading} isError={history.isError} onRetry={() => history.refetch()} empty={(history.data ?? []).length === 0} emptyText={t("noHistory")}>
            <ul className="space-y-4">
              {(history.data ?? []).map((h) => (
                <li key={h.id} className="border-b border-border pb-3 last:border-0">
                  <p className="text-sm font-medium">
                    {h.author_name} · {formatDateTime(h.created_at, locale)}
                  </p>
                  <p className="text-xs text-muted">{t("shiftFrom", { time: formatDateTime(h.shift_started_at, locale) })}</p>
                  <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-sm">{h.summary}</p>
                  {h.notes && <p className="mt-1 text-xs text-muted">{h.notes}</p>}
                </li>
              ))}
            </ul>
          </QueryState>
        </Card>
      </div>
    </>
  );
}

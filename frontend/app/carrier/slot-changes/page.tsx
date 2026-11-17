"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Badge, Card } from "@/components/ui/card";
import { Select } from "@/components/ui/fields";
import { api } from "@/lib/api";
import { groupByDay, SLOT_CHANGE_KINDS, slotChangeTone } from "@/lib/carrier";
import type { SlotChange } from "@/lib/carrier-types";
import { formatDate, formatDateTime } from "@/lib/format";
import { hhmm } from "@/lib/time";

/** READ ONLY feed of what facility planners and coordinators decided for this carrier's shipments, with reasons. */
export default function SlotChangesPage() {
  const t = useTranslations("carrier.slotChanges");
  const locale = useLocale();
  const [kind, setKind] = React.useState("");
  const q = useQuery<SlotChange[]>({ queryKey: ["carrier", "slot-changes"], queryFn: () => api<SlotChange[]>("/carrier/slot-changes?limit=200") });
  const items = (q.data ?? []).filter((c) => !kind || c.kind === kind);
  const groups = groupByDay(items, (c) => c.ts);

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <p className="mb-4 rounded-md border border-border bg-surface px-4 py-2 text-xs text-muted">{t("readOnlyNote")}</p>
      <div className="mb-5 max-w-xs">
        <label htmlFor="sc-kind" className="mb-1 block text-sm font-medium">
          {t("filter")}
        </label>
        <Select id="sc-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">{t("all")}</option>
          {SLOT_CHANGE_KINDS.map((k) => (
            <option key={k} value={k}>
              {t(`kinds.${k}`)}
            </option>
          ))}
        </Select>
      </div>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => void q.refetch()} empty={!q.isLoading && !q.isError && items.length === 0} emptyText={t("empty")}>
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.day} aria-label={formatDate(g.day, locale)}>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{formatDate(g.day, locale)}</h2>
              <ul className="space-y-2">
                {g.items.map((c, i) => (
                  <li key={`${c.ts}-${c.shipment_id}-${i}`}>
                    <Card className="flex flex-wrap items-start gap-3 p-4">
                      <Badge tone={slotChangeTone(c.kind)}>{t(`kinds.${c.kind}`)}</Badge>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">
                          <Link href={`/carrier/shipments/${c.shipment_id}`} className="font-mono font-medium text-accent hover:underline">
                            {c.shipment_code}
                          </Link>
                          {c.slot_code && (
                            <span className="text-muted">
                              {" "}
                              · {c.slot_code}
                              {c.start ? ` · ${hhmm(c.start)}` : ""}
                            </span>
                          )}
                        </p>
                        <p className="mt-0.5 text-sm text-muted">{c.reason ?? t("noReason")}</p>
                      </div>
                      <time className="text-xs text-muted" dateTime={c.ts}>
                        {formatDateTime(c.ts, locale)}
                      </time>
                    </Card>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </QueryState>
    </>
  );
}

"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { Suspense } from "react";
import { languageName, useCoordQuery } from "@/lib/coord";
import type { ThreadPage } from "@/lib/coord-types";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";

const PAGE = 30;
const STATUSES = ["OPEN", "WAITING_FOR_DRIVER", "WAITING_FOR_WAREHOUSE", "RESOLVED", "ESCALATED", "CLOSED"];

function ConversationsList() {
  const t = useTranslations("coord.conversations");
  const locale = useLocale();
  const params = useSearchParams();
  const [q, setQ] = React.useState(params.get("q") ?? "");
  const [debounced, setDebounced] = React.useState(q);
  const [status, setStatus] = React.useState("");
  const [taken, setTaken] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  React.useEffect(() => {
    const id = setTimeout(() => {
      setDebounced(q);
      setOffset(0);
    }, 300);
    return () => clearTimeout(id);
  }, [q]);

  const query = useCoordQuery<ThreadPage>(
    `/coordinator/threads${buildQuery({ q: debounced, status, taken_over: taken, limit: PAGE, offset })}`,
    { refetchInterval: 20_000 },
  );
  const rows = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4 flex flex-wrap gap-2" role="search">
        <Input aria-label={t("search")} placeholder={t("search")} className="w-64" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select aria-label={t("status")} className="w-52" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">{t("allStatuses")}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`threadStatus.${s}`)}
            </option>
          ))}
        </Select>
        <Select aria-label={t("takenOver")} className="w-48" value={taken} onChange={(e) => { setTaken(e.target.value); setOffset(0); }}>
          <option value="">{t("takenAny")}</option>
          <option value="true">{t("takenYes")}</option>
          <option value="false">{t("takenNo")}</option>
        </Select>
      </div>
      <QueryState isLoading={query.isLoading} isError={query.isError} onRetry={() => query.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border text-left">
              <th className={th}>{t("driver")}</th>
              <th className={th}>{t("shipment")}</th>
              <th className={th}>{t("lastMessage")}</th>
              <th className={th}>{t("status")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-accent-soft">
                <td className={td}>
                  <Link href={`/coordinator/conversations/${r.id}`} className="font-medium text-accent underline">
                    {r.driver_name}
                  </Link>
                  <span className="block text-xs text-muted">{languageName(r.driver_language)}</span>
                </td>
                <td className={td + " font-mono"}>{r.shipment_code ?? "—"}</td>
                <td className={td}>
                  <p className="line-clamp-2 max-w-md">{r.last_message_text ?? "—"}</p>
                  <p className="text-xs text-muted">{formatDateTime(r.last_message_ts, locale)}</p>
                </td>
                <td className={td}>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="neutral">{t(`threadStatus.${r.thread_status}`)}</Badge>
                    {r.requires_review && <Badge tone="warning">{t("review")}</Badge>}
                    {r.bot_paused && <Badge tone="accent">{r.taken_over_by ? t("takenBy", { name: r.taken_over_by.name }) : t("botPaused")}</Badge>}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
        <div className="mt-3 flex items-center justify-between text-sm text-muted">
          <span>{t("range", { from: total === 0 ? 0 : offset + 1, to: Math.min(offset + PAGE, total), total })}</span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              {t("prev")}
            </Button>
            <Button size="sm" variant="outline" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
              {t("next")}
            </Button>
          </div>
        </div>
      </QueryState>
    </>
  );
}

export default function ConversationsPage() {
  return (
    <Suspense fallback={null}>
      <ConversationsList />
    </Suspense>
  );
}

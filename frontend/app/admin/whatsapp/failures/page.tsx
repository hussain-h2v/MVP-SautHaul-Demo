"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import * as React from "react";
import { DataTableLite, SectionHeader } from "@/components/ai/common";
import { Badge } from "@/components/ui/card";
import { Pager, QueryState } from "@/components/wa/common";
import { formatDateTime } from "@/lib/format";
import { qs, useWa } from "@/lib/wa-api";
import type { WaFailure, WaPage } from "@/lib/wa-types";

const PAGE = 25;

export default function FailuresPage() {
  const t = useTranslations("wa");
  const [offset, setOffset] = React.useState(0);
  const q = useWa<WaPage<WaFailure>>(`/failures${qs({ limit: PAGE, offset })}`, { refetchInterval: 20_000 });
  const items = q.data?.items ?? [];
  return (
    <>
      <SectionHeader
        title={t("fl.title")}
        description={t("fl.description")}
        actions={
          <Link href="/admin/whatsapp/messages?status=failed" className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent-soft">
            {t("fl.viewLog")}
          </Link>
        }
      />
      <QueryState isLoading={q.isLoading} error={q.error} empty={!items.length} emptyText={t("fl.empty")} onRetry={() => q.refetch()}>
        <DataTableLite caption={t("fl.title")} head={[t("fl.when"), t("fl.driver"), t("fl.to"), t("fl.error"), t("fl.template"), t("fl.purpose")]}>
          {items.map((f) => (
            <tr key={f.id} className="align-top">
              <td className="whitespace-nowrap px-4 py-3">{formatDateTime(f.created_at)}</td>
              <td className="px-4 py-3">{f.driver_name ?? "—"}</td>
              <td className="whitespace-nowrap px-4 py-3 font-mono text-xs">{f.to ?? "—"}</td>
              <td className="px-4 py-3">
                <Badge tone="danger" className="font-mono">
                  {f.error ?? "?"}
                </Badge>
                {f.text && <p className="mt-1 line-clamp-2 max-w-xs text-xs text-muted">{f.text}</p>}
              </td>
              <td className="px-4 py-3 font-mono text-xs">{f.template_name ?? "—"}</td>
              <td className="px-4 py-3 text-xs">{f.purpose ?? "—"}</td>
            </tr>
          ))}
        </DataTableLite>
        <Pager total={q.data?.total ?? 0} offset={offset} limit={PAGE} onChange={setOffset} />
      </QueryState>
    </>
  );
}

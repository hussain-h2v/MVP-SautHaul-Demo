"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import type { AuditRow } from "@/lib/admin-types";
import { diffObjects, formatValue } from "@/lib/diff";
import { formatDateTime } from "@/lib/format";

const tones = { insert: "success", update: "accent", delete: "danger" } as const;

function DiffDialog({ row, onClose }: { row: AuditRow | null; onClose: () => void }) {
  const t = useTranslations("admin.audit");
  const locale = useLocale();
  if (!row) return null;
  const changes = diffObjects(row.before, row.after);
  return (
    <Dialog
      open
      onClose={onClose}
      size="xl"
      title={t("changes")}
      description={`${row.entity} · ${row.action} · ${formatDateTime(row.created_at, locale)}`}
      footer={<Button onClick={onClose}>{t("close")}</Button>}
    >
      {changes.length === 0 ? (
        <p className="text-sm text-muted">{t("noChanges")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">{t("changes")}</caption>
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
                <th scope="col" className="px-3 py-2 font-medium">{t("field")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("before")}</th>
                <th scope="col" className="px-3 py-2 font-medium">{t("after")}</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((ch) => (
                <tr key={ch.key} className="border-b border-border align-top last:border-0">
                  <th scope="row" className="px-3 py-2 text-left font-mono text-xs font-medium">{ch.key}</th>
                  <td className="px-3 py-2">
                    <span className={ch.kind === "added" ? "text-muted" : "rounded bg-danger/10 px-1.5 py-0.5 text-danger line-through"}>
                      {formatValue(ch.before)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={ch.kind === "removed" ? "text-muted" : "rounded bg-accent-soft px-1.5 py-0.5 text-success"}>
                      {formatValue(ch.after)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Dialog>
  );
}

export default function AuditPage() {
  const t = useTranslations("admin.audit");
  const locale = useLocale();
  const [viewing, setViewing] = React.useState<AuditRow | null>(null);

  const columns: Column<AuditRow>[] = [
    { key: "time", header: t("time"), cell: (r) => <span className="text-xs">{formatDateTime(r.created_at, locale)}</span> },
    {
      key: "actor",
      header: t("actor"),
      cell: (r) => (
        <div>
          <Badge>{r.actor_type}</Badge>
          <div className="mt-0.5 max-w-40 truncate font-mono text-xs text-muted" title={r.actor_id ?? ""}>
            {r.actor_id ?? "—"}
          </div>
        </div>
      ),
    },
    { key: "action", header: t("action"), cell: (r) => <Badge tone={tones[r.action as keyof typeof tones] ?? "neutral"}>{r.action}</Badge> },
    { key: "entity", header: t("entity"), cell: (r) => <span className="font-mono text-xs">{r.entity}</span> },
    { key: "entity_id", header: t("entityId"), cell: (r) => <span className="font-mono text-xs">{r.entity_id?.slice(0, 8) ?? "—"}</span> },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <DataTable<AuditRow>
        tableId="audit"
        path="/audit"
        columns={columns}
        rowKey={(r) => r.id}
        searchPlaceholder={t("search")}
        filters={[
          { key: "entity", label: t("entity"), type: "text" },
          { key: "actor_id", label: t("actor"), type: "text" },
          {
            key: "action",
            label: t("action"),
            type: "select",
            options: ["insert", "update", "delete"].map((a) => ({ value: a, label: a })),
          },
        ]}
        actions={(r) => (
          <RowActions>
            <Button variant="ghost" size="sm" onClick={() => setViewing(r)}>
              {t("viewChanges")}
            </Button>
          </RowActions>
        )}
      />
      <DiffDialog row={viewing} onClose={() => setViewing(null)} />
    </>
  );
}

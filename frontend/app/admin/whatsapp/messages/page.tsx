"use client";

import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { DataTableLite, SectionHeader } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { LangChip, Pager, QueryState, StatusBadge, useDebounced } from "@/components/wa/common";
import { formatDateTime } from "@/lib/format";
import { qs, useWa, useWaOther } from "@/lib/wa-api";
import type { SimDriver, WaMessage, WaPage } from "@/lib/wa-types";

const PAGE = 25;
const STATUSES = ["received", "queued", "sent", "delivered", "read", "failed"] as const;

function Detail({ m, onClose }: { m: WaMessage | null; onClose: () => void }) {
  const t = useTranslations("wa");
  return (
    <Dialog open={!!m} onClose={onClose} drawer title={t("ms.detail")} footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      {m && (
        <div className="space-y-4">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted">{t("ms.direction")}</dt>
            <dd>{t(`direction.${m.direction}`)}</dd>
            <dt className="text-muted">{t("ms.status")}</dt>
            <dd><StatusBadge status={m.delivery_status} /></dd>
            <dt className="text-muted">{t("ms.driver")}</dt>
            <dd>{m.driver_name ?? t("ms.unknownDriver")}</dd>
            <dt className="text-muted">{t("ms.when")}</dt>
            <dd>{formatDateTime(m.created_at)}</dd>
            <dt className="text-muted">{t("ms.type")}</dt>
            <dd>{m.type}</dd>
            <dt className="text-muted">{t("ms.language")}</dt>
            <dd><LangChip code={m.language} /></dd>
            <dt className="text-muted">{t("ms.template")}</dt>
            <dd className="font-mono text-xs">{m.template_name ?? "—"}</dd>
            <dt className="text-muted">{t("ms.purpose")}</dt>
            <dd>{m.purpose ?? "—"}</dd>
            <dt className="text-muted">{t("ms.thread")}</dt>
            <dd className="break-all font-mono text-xs">{m.thread_id ?? "—"}</dd>
            <dt className="text-muted">{t("ms.waId")}</dt>
            <dd className="break-all font-mono text-xs">{m.wa_message_id ?? "—"}</dd>
            <dt className="text-muted">{t("ms.error")}</dt>
            <dd className={m.error ? "text-danger" : ""}>{m.error ?? "—"}</dd>
          </dl>
          <div>
            <h3 className="mb-1 text-sm font-medium">{t("ms.text")}</h3>
            <pre className="whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-sm">{m.text ?? "—"}</pre>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function MessagesInner() {
  const t = useTranslations("wa");
  const params = useSearchParams();
  const [direction, setDirection] = React.useState("");
  const [status, setStatus] = React.useState(params.get("status") ?? "");
  const [driverId, setDriverId] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [offset, setOffset] = React.useState(0);
  const [open, setOpen] = React.useState<WaMessage | null>(null);
  const q = useDebounced(search);
  const drivers = useWaOther<WaPage<SimDriver>>("/drivers?limit=200");
  const res = useWa<WaPage<WaMessage>>(`/messages${qs({ direction, status, driver_id: driverId, q, limit: PAGE, offset })}`, { refetchInterval: 15_000 });
  const items = res.data?.items ?? [];
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };
  return (
    <>
      <SectionHeader title={t("ms.title")} description={t("ms.description")} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Field label={t("g.search")} htmlFor="ms-q">
          <Input id="ms-q" type="search" value={search} placeholder={t("ms.searchPlaceholder")} onChange={(e) => reset(setSearch)(e.target.value)} />
        </Field>
        <Field label={t("ms.direction")} htmlFor="ms-dir">
          <Select id="ms-dir" value={direction} onChange={(e) => reset(setDirection)(e.target.value)}>
            <option value="">{t("g.all")}</option>
            <option value="in">{t("direction.in")}</option>
            <option value="out">{t("direction.out")}</option>
          </Select>
        </Field>
        <Field label={t("ms.status")} htmlFor="ms-status">
          <Select id="ms-status" value={status} onChange={(e) => reset(setStatus)(e.target.value)}>
            <option value="">{t("g.all")}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`status.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("ms.driver")} htmlFor="ms-driver">
          <Select id="ms-driver" value={driverId} onChange={(e) => reset(setDriverId)(e.target.value)}>
            <option value="">{t("ms.allDrivers")}</option>
            {(drivers.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.driver_name} ({d.code})
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <QueryState isLoading={res.isLoading} error={res.error} empty={!items.length} onRetry={() => res.refetch()}>
        <DataTableLite caption={t("ms.title")} head={[t("ms.when"), t("ms.direction"), t("ms.driver"), t("ms.text"), t("ms.status")]}>
          {items.map((m) => (
            <tr key={m.id} className="cursor-pointer align-top hover:bg-accent-soft/40">
              <td className="whitespace-nowrap px-4 py-3">{formatDateTime(m.created_at)}</td>
              <td className="px-4 py-3">{t(`direction.${m.direction}`)}</td>
              <td className="px-4 py-3">{m.driver_name ?? <span className="text-muted">{t("ms.unknownDriver")}</span>}</td>
              <td className="px-4 py-3">
                <button type="button" onClick={() => setOpen(m)} className="block max-w-md text-left underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent">
                  <span className="line-clamp-2">{m.text ?? (m.template_name ? `[${m.template_name}]` : "—")}</span>
                </button>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={m.delivery_status} />
              </td>
            </tr>
          ))}
        </DataTableLite>
        <Pager total={res.data?.total ?? 0} offset={offset} limit={PAGE} onChange={setOffset} />
      </QueryState>
      <Detail m={open} onClose={() => setOpen(null)} />
    </>
  );
}

export default function MessagesPage() {
  return (
    <React.Suspense fallback={null}>
      <MessagesInner />
    </React.Suspense>
  );
}

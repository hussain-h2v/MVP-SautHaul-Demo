"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Kbd, PriorityBadge, StatusBadge, useCoordText } from "@/components/coordinator/shared";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/card";
import { Select } from "@/components/ui/fields";
import type { Page } from "@/lib/admin-types";
import { inboxHref, nextIndex, sortInbox, useCoordQuery, useHotkeys } from "@/lib/coord";
import type { Inbox, InboxItem, InboxKind } from "@/lib/coord-types";
import { useOptions } from "@/lib/use-api";
import { formatDateTime } from "@/lib/format";
import { buildQuery } from "@/lib/query";
import { cn } from "@/lib/utils";

const KINDS: InboxKind[] = ["request", "exception", "hold", "escalation", "failed_message", "eta_change"];
const COUNTER_FOR_KIND: Record<InboxKind, keyof Inbox["counters"]> = {
  request: "requests",
  exception: "exceptions",
  hold: "holds_expiring",
  escalation: "escalations",
  failed_message: "failed_messages",
  eta_change: "eta_changes",
};

export function InboxView() {
  const t = useTranslations("coord.inbox");
  const { tc } = useCoordText();
  const locale = useLocale();
  const router = useRouter();
  const [kind, setKind] = React.useState("");
  const [priority, setPriority] = React.useState("");
  const [facility, setFacility] = React.useState("");
  const [carrier, setCarrier] = React.useState("");
  const [claimed, setClaimed] = React.useState("");
  const [selected, setSelected] = React.useState(-1);
  const listRef = React.useRef<HTMLUListElement>(null);

  const facilities = useOptions<Page<{ id: string; code: string; facility_name: string }>>("/facilities?limit=200&active=true");
  const carriers = useOptions<Page<{ id: string; carrier_name: string }>>("/carriers?limit=200");

  const path = `/coordinator/inbox${buildQuery({ kind, priority, facility_id: facility, carrier_id: carrier, claimed, limit: 100 })}`;
  const q = useCoordQuery<Inbox>(path, { refetchInterval: 30_000 });
  const items = React.useMemo(() => sortInbox(q.data?.items ?? []), [q.data]);

  React.useEffect(() => setSelected(-1), [path]);
  React.useEffect(() => {
    if (selected < 0) return;
    listRef.current?.querySelector<HTMLElement>(`[data-idx="${selected}"]`)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  useHotkeys({
    j: () => setSelected((i) => nextIndex(i, 1, items.length)),
    k: () => setSelected((i) => nextIndex(i, -1, items.length)),
    arrowdown: () => setSelected((i) => nextIndex(i, 1, items.length)),
    arrowup: () => setSelected((i) => nextIndex(i, -1, items.length)),
    enter: () => {
      const it = items[selected];
      if (it) router.push(inboxHref(it));
    },
  });

  const c = q.data?.counters;
  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <p className="hidden items-center gap-1.5 text-xs text-muted md:flex">
            <Kbd>j</Kbd>/<Kbd>k</Kbd> {t("hintMove")} · <Kbd>Enter</Kbd> {t("hintOpen")}
          </p>
        }
      />

      <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7" aria-label={t("counters")}>
        <li>
          <button
            type="button"
            onClick={() => setKind("")}
            aria-pressed={kind === ""}
            className={cn("w-full rounded-xl border p-3 text-left", kind === "" ? "border-accent bg-accent-soft" : "border-border bg-surface")}
          >
            <span className="block text-xs uppercase tracking-wider text-muted">{t("kind.all")}</span>
            <span className="text-2xl font-semibold tabular-nums">{c?.total ?? "—"}</span>
          </button>
        </li>
        {KINDS.map((k) => (
          <li key={k}>
            <button
              type="button"
              onClick={() => setKind(kind === k ? "" : k)}
              aria-pressed={kind === k}
              className={cn("w-full rounded-xl border p-3 text-left", kind === k ? "border-accent bg-accent-soft" : "border-border bg-surface")}
            >
              <span className="block text-xs uppercase tracking-wider text-muted">{t(`kind.${k}`)}</span>
              <span className="text-2xl font-semibold tabular-nums">{c ? c[COUNTER_FOR_KIND[k]] : "—"}</span>
            </button>
          </li>
        ))}
      </ul>

      <div className="mb-4 flex flex-wrap gap-2" role="search" aria-label={t("filters")}>
        <Select aria-label={t("priority")} className="w-40" value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">{t("allPriorities")}</option>
          {["CRITICAL", "HIGH", "NORMAL", "LOW"].map((p) => (
            <option key={p} value={p}>
              {tc(`priority.${p}`)}
            </option>
          ))}
        </Select>
        <Select aria-label={t("facility")} className="w-48" value={facility} onChange={(e) => setFacility(e.target.value)}>
          <option value="">{t("allFacilities")}</option>
          {facilities.data?.items.map((f) => (
            <option key={f.id} value={f.id}>
              {f.code}
            </option>
          ))}
        </Select>
        <Select aria-label={t("carrier")} className="w-52" value={carrier} onChange={(e) => setCarrier(e.target.value)}>
          <option value="">{t("allCarriers")}</option>
          {carriers.data?.items.map((x) => (
            <option key={x.id} value={x.id}>
              {x.carrier_name}
            </option>
          ))}
        </Select>
        <Select aria-label={t("claimedFilter")} className="w-44" value={claimed} onChange={(e) => setClaimed(e.target.value)}>
          <option value="">{t("claimedAny")}</option>
          <option value="false">{t("claimedNo")}</option>
          <option value="true">{t("claimedYes")}</option>
        </Select>
      </div>

      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={items.length === 0} emptyText={t("empty")}>
        <ul ref={listRef} className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface" aria-label={t("list")}>
          {items.map((it, i) => (
            <InboxRow key={it.key} item={it} index={i} selected={i === selected} locale={locale} onHover={() => setSelected(i)} />
          ))}
        </ul>
      </QueryState>
    </>
  );
}

function InboxRow({
  item,
  index,
  selected,
  locale,
  onHover,
}: {
  item: InboxItem;
  index: number;
  selected: boolean;
  locale: string;
  onHover: () => void;
}) {
  const t = useTranslations("coord.inbox");
  return (
    <li data-idx={index}>
      <Link
        href={inboxHref(item)}
        onFocus={onHover}
        aria-current={selected ? "true" : undefined}
        className={cn("flex flex-wrap items-start gap-3 px-4 py-3 hover:bg-accent-soft", selected && "bg-accent-soft ring-2 ring-inset ring-accent")}
      >
        <div className="flex w-28 shrink-0 flex-col gap-1">
          <Badge tone="neutral">{t(`kind.${item.kind}`)}</Badge>
          <PriorityBadge code={item.priority_code} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {item.shipment_code && <span className="mr-2 font-mono text-accent">{item.shipment_code}</span>}
            {item.title}
          </p>
          <p className="mt-0.5 line-clamp-2 text-sm text-muted">{item.summary}</p>
          <p className="mt-1 text-xs text-muted">
            {[item.carrier_name, item.facility_code].filter(Boolean).join(" · ")}
            {item.carrier_name || item.facility_code ? " · " : ""}
            {formatDateTime(item.created_at, locale)}
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge status={item.status} />
          {item.claimed_by && <Badge tone="warning">{t("handledBy", { name: item.claimed_by.name })}</Badge>}
        </div>
      </Link>
    </li>
  );
}

"use client";

import { Bell, BellOff } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { QueryState } from "@/components/facility/common";
import { groupByDay, notificationTypeKey } from "@/lib/carrier";
import { formatDate, formatDateTime } from "@/lib/format";
import { useMarkAllRead, useMarkRead, useNotifications } from "@/lib/notifications";
import { cn } from "@/lib/utils";

const PAGE = 25;

/** One page component reused by every portal's /notifications route. */
export function NotificationsPage() {
  const t = useTranslations("notifications");
  const locale = useLocale();
  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [offset, setOffset] = React.useState(0);
  const q = useNotifications({ limit: PAGE, offset, unreadOnly });
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const items = q.data?.items ?? [];
  const groups = groupByDay(items, (n) => n.created_at);
  const typeLabel = (type: string) => {
    const key = `types.${notificationTypeKey(type)}`;
    return t.has(key) ? t(key) : type;
  };

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <Button variant="outline" onClick={() => { setUnreadOnly((v) => !v); setOffset(0); }} aria-pressed={unreadOnly}>
              {unreadOnly ? t("showAll") : t("unreadOnly")}
            </Button>
            <Button variant="outline" disabled={(q.data?.unread ?? 0) === 0 || markAll.isPending} onClick={() => markAll.mutate()}>
              {t("markAll")}
            </Button>
          </>
        }
      />
      <p role="status" className="mb-3 text-sm text-muted">
        {t("summary", { unread: q.data?.unread ?? 0, total: q.data?.total ?? 0 })}
      </p>
      <QueryState
        isLoading={q.isLoading}
        isError={q.isError}
        onRetry={() => void q.refetch()}
        empty={!q.isLoading && !q.isError && items.length === 0}
        emptyText={unreadOnly ? t("emptyUnread") : t("empty")}
      >
        <div className="space-y-6">
          {groups.map((g) => (
            <section key={g.day} aria-label={formatDate(g.day, locale)}>
              <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{formatDate(g.day, locale)}</h2>
              <ul className="space-y-2">
                {g.items.map((n) => (
                  <li key={n.id}>
                    <Card className={cn("flex items-start gap-3 p-4", !n.read && "border-accent/50 bg-accent-soft/30")}>
                      {n.read ? <BellOff className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden="true" /> : <Bell className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden="true" />}
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className={cn("text-sm", !n.read && "font-semibold")}>{n.title}</p>
                          <Badge>{typeLabel(n.type)}</Badge>
                          {!n.read && <Badge tone="accent">{t("unread")}</Badge>}
                        </div>
                        {n.body && <p className="mt-1 text-sm text-muted">{n.body}</p>}
                        <p className="mt-1 text-xs text-muted">
                          <time dateTime={n.created_at}>{formatDateTime(n.created_at, locale)}</time>
                        </p>
                      </div>
                      {!n.read && (
                        <Button variant="ghost" size="sm" onClick={() => markRead.mutate(n.id)}>
                          {t("markRead")}
                        </Button>
                      )}
                    </Card>
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {(q.data?.total ?? 0) > PAGE && (
            <nav aria-label={t("pagination")} className="flex items-center justify-between">
              <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                {t("prev")}
              </Button>
              <span className="text-xs text-muted">{t("range", { from: offset + 1, to: Math.min(offset + PAGE, q.data?.total ?? 0), total: q.data?.total ?? 0 })}</span>
              <Button variant="outline" size="sm" disabled={offset + PAGE >= (q.data?.total ?? 0)} onClick={() => setOffset(offset + PAGE)}>
                {t("next")}
              </Button>
            </nav>
          )}
        </div>
      </QueryState>
    </>
  );
}

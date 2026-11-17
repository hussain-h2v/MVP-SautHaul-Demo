"use client";

import { Bell } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { Dropdown, MenuLabel, MenuSeparator } from "@/components/ui/dropdown";
import { badgeCount, notificationsHref } from "@/lib/carrier";
import { formatDateTime } from "@/lib/format";
import { useMarkAllRead, useMarkRead, useNotifications } from "@/lib/notifications";
import { cn } from "@/lib/utils";

/** Header bell for every portal: unread badge, latest 8, mark read, link to the full page. */
export function NotificationBell({ slug }: { slug: string }) {
  const t = useTranslations("notifications");
  const locale = useLocale();
  const { data, isError } = useNotifications({ limit: 8 }, 60_000);
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const unread = data?.unread ?? 0;
  const count = badgeCount(unread);

  return (
    <Dropdown
      label={unread > 0 ? t("bellUnread", { n: unread }) : t("bell")}
      trigger={
        <span className="relative grid size-8 place-items-center">
          <Bell className="size-5" aria-hidden="true" />
          {count && (
            <span
              aria-hidden="true"
              className="absolute -right-1.5 -top-1 min-w-4 rounded-full bg-danger px-1 text-center text-[10px] font-semibold leading-4 text-white"
            >
              {count}
            </span>
          )}
        </span>
      }
    >
      <div className="w-80 max-w-[calc(100vw-2rem)]">
        <div className="flex items-center justify-between pr-2">
          <MenuLabel>{t("title")}</MenuLabel>
          {unread > 0 && (
            <button
              type="button"
              role="menuitem"
              className="rounded px-2 py-1 text-xs font-medium text-accent hover:bg-accent-soft"
              onClick={(e) => {
                e.stopPropagation();
                markAll.mutate();
              }}
            >
              {t("markAll")}
            </button>
          )}
        </div>
        <MenuSeparator />
        {isError && <p className="px-3 py-4 text-sm text-danger">{t("failed")}</p>}
        {!isError && data && data.items.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted">{t("empty")}</p>}
        <ul className="max-h-80 overflow-y-auto">
          {data?.items.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                role="menuitem"
                onClick={() => !n.read && markRead.mutate(n.id)}
                className={cn("flex w-full gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-accent-soft", !n.read && "bg-accent-soft/40")}
              >
                <span aria-hidden="true" className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read ? "bg-transparent" : "bg-accent")} />
                <span className="min-w-0">
                  <span className={cn("block truncate", !n.read && "font-medium")}>{n.title}</span>
                  {n.body && <span className="block line-clamp-2 text-xs text-muted">{n.body}</span>}
                  <span className="mt-0.5 block text-xs text-muted">
                    <time dateTime={n.created_at}>{formatDateTime(n.created_at, locale)}</time>
                    {n.read ? "" : ` · ${t("unread")}`}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        <MenuSeparator />
        <Link
          href={notificationsHref(slug)}
          role="menuitem"
          className="block rounded-md px-3 py-2 text-center text-sm font-medium text-accent hover:bg-accent-soft"
        >
          {t("viewAll")}
        </Link>
      </div>
    </Dropdown>
  );
}

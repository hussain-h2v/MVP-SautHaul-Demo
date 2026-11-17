"use client";

import { AlertTriangle, Bot, Copy, Languages, Send } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import { describeCoordError, useCoordText } from "@/components/coordinator/shared";
import { QueryState } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Textarea } from "@/components/ui/fields";
import { api } from "@/lib/api";
import { languageName, useCoordMutation, useCoordQuery } from "@/lib/coord";
import type { ChatMsg, Draft, ThreadMessages } from "@/lib/coord-types";
import { useCap } from "@/lib/fac";
import { formatDateTime } from "@/lib/format";
import { useMe } from "@/lib/auth";
import { cn } from "@/lib/utils";

const SIDE: Record<string, "left" | "right" | "center"> = {
  DRIVER: "left",
  WAREHOUSE: "left",
  AGENT: "right",
  OPERATIONS: "right",
  SYSTEM: "center",
};

export default function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const t = useTranslations("coord.conversation");
  const nav = useTranslations("nav");
  const { tc, tf } = useCoordText();
  const locale = useLocale();
  const { data: me } = useMe();
  const canTake = useCap("escalations_takeover") === "W";
  const q = useCoordQuery<ThreadMessages>(`/coordinator/threads/${id}/messages`, { refetchInterval: 8_000 });
  const [showTranslation, setShowTranslation] = React.useState(true);
  const [text, setText] = React.useState("");
  const endRef = React.useRef<HTMLDivElement>(null);
  const base = `/coordinator/threads/${id}`;
  const fail = (e: unknown) => toast.error(describeCoordError(e, tc, tf));

  const thread = q.data?.thread;
  const messages = q.data?.messages ?? [];
  const mine = !!thread?.taken_over_by && thread.taken_over_by.id === me?.id;
  const other = !!thread?.taken_over_by && !mine;

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  const takeover = useCoordMutation(() => api(`${base}/takeover`, { method: "POST" }), { success: t("tookOver"), onError: fail });
  const handback = useCoordMutation(() => api(`${base}/handback`, { method: "POST" }), { success: t("handedBack"), onError: fail });
  const reply = useCoordMutation(() => api(`${base}/reply`, { method: "POST", body: { text: text.trim() } }), {
    success: t("sent"),
    onSuccess: () => setText(""),
    onError: fail,
  });
  const draft = useCoordMutation(() => api<Draft>(`${base}/draft`), {
    onSuccess: (d) => setText(d.text),
    onError: fail,
  });

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && mine && text.trim()) reply.mutate(undefined);
  };

  return (
    <>
      <PageHeader
        breadcrumbs={[{ label: nav("conversations"), href: "/coordinator/conversations" }, { label: thread?.driver_name ?? "…" }]}
        title={thread ? t("title", { driver: thread.driver_name }) : t("loading")}
        description={thread ? `${thread.shipment_code ?? "—"} · ${languageName(thread.driver_language)} · ${thread.thread_status}` : undefined}
        actions={
          thread && (
            <>
              <Button variant="outline" size="sm" aria-pressed={showTranslation} onClick={() => setShowTranslation((v) => !v)}>
                <Languages className="size-4" aria-hidden="true" />
                {t("translation")}
              </Button>
              {thread.driver_phone && (
                <a href={`tel:${thread.driver_phone}`} className="text-sm font-medium text-accent underline">
                  {thread.driver_phone}
                </a>
              )}
              {mine ? (
                <Button size="sm" variant="outline" disabled={handback.isPending} onClick={() => handback.mutate(undefined)}>
                  {t("handBack")}
                </Button>
              ) : (
                <Button size="sm" disabled={!canTake || other || takeover.isPending} onClick={() => takeover.mutate(undefined)}>
                  {t("takeOver")}
                </Button>
              )}
            </>
          )
        }
      />
      {thread && (
        <div
          role="status"
          className={cn(
            "mb-4 flex items-center gap-2 rounded-md border px-4 py-2 text-sm",
            thread.bot_paused ? "border-accent bg-accent-soft" : "border-border bg-surface text-muted",
          )}
        >
          <Bot className="size-4 shrink-0" aria-hidden="true" />
          {mine ? t("bannerMine") : other ? t("bannerOther", { name: thread.taken_over_by?.name ?? "" }) : t("bannerBot")}
        </div>
      )}

      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={!!q.data && messages.length === 0} emptyText={t("empty")}>
        <ol className="mb-4 max-h-[60vh] space-y-3 overflow-y-auto rounded-xl border border-border bg-surface p-4" aria-label={t("transcript")} aria-live="polite">
          {messages.map((m) => (
            <Bubble key={m.id} m={m} locale={locale} showTranslation={showTranslation} />
          ))}
          <div ref={endRef} />
        </ol>
      </QueryState>

      <div className="rounded-xl border border-border bg-surface p-4">
        <label htmlFor="composer" className="mb-1.5 block text-sm font-medium">
          {t("composer")}
        </label>
        <Textarea
          id="composer"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          disabled={!mine}
          placeholder={mine ? t("placeholderMine") : t("placeholderLocked")}
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted">{t("draftNote")}</p>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={!mine || draft.isPending} onClick={() => draft.mutate(undefined)}>
              <Copy className="size-4" aria-hidden="true" />
              {t("useDraft")}
            </Button>
            <Button size="sm" disabled={!mine || !text.trim() || reply.isPending} onClick={() => reply.mutate(undefined)}>
              <Send className="size-4" aria-hidden="true" />
              {t("send")}
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}

function Bubble({ m, locale, showTranslation }: { m: ChatMsg; locale: string; showTranslation: boolean }) {
  const t = useTranslations("coord.conversation");
  const side = SIDE[m.sender_type] ?? "left";
  return (
    <li className={cn("flex", side === "right" && "justify-end", side === "center" && "justify-center")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
          side === "left" && "rounded-bl-sm bg-background",
          side === "right" && (m.sender_type === "OPERATIONS" ? "rounded-br-sm bg-accent text-accent-foreground" : "rounded-br-sm bg-accent-soft"),
          side === "center" && "bg-background text-xs text-muted",
        )}
      >
        <p className={cn("mb-0.5 text-[11px] font-medium uppercase tracking-wider", m.sender_type === "OPERATIONS" ? "opacity-80" : "text-muted")}>{t(`sender.${m.sender_type}`)}</p>
        <p className="whitespace-pre-wrap">{m.text}</p>
        {showTranslation && (
          <p className={cn("mt-1.5 border-t pt-1.5 text-xs", m.sender_type === "OPERATIONS" ? "border-white/30" : "border-border text-muted")}>
            {m.translation ?? t("noTranslation")}
          </p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] opacity-70">{formatDateTime(m.ts, locale)}</span>
          {m.is_duplicate && <Badge tone="warning">{t("duplicate")}</Badge>}
          {m.requires_human_review && (
            <Badge tone="warning">
              <AlertTriangle className="mr-1 size-3" aria-hidden="true" />
              {t("review")}
            </Badge>
          )}
          {m.parsed_intent && <Badge tone="neutral">{m.parsed_intent}</Badge>}
        </div>
      </div>
    </li>
  );
}

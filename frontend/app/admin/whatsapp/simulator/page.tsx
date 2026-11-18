"use client";

import { RotateCcw, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { SectionHeader } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { LangChip, QueryState, Ticks } from "@/components/wa/common";
import { formatDateTime } from "@/lib/format";
import { useEventStream } from "@/lib/sse";
import { detectLanguageHint, pendingBubble, QUICK_TESTS, quickReplyPayload, textPayload, toBubbles, type Bubble } from "@/lib/wa";
import { WA_KEY, useWa, useWaMutation, useWaOther, waPost } from "@/lib/wa-api";
import type { SimDriver, SimMessage, SimSendBody, SimSendResult, ThreadInfo, WaPage } from "@/lib/wa-types";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK"]);
const QUICK_LABEL = { breakdown: "sim.qBreakdown", hindi: "sim.qHindi", options: "sim.qOptions", arrived: "sim.qArrived", safety: "sim.qSafety", stop: "sim.qStop" } as const;
const STORE = "wa-sim-driver";

interface ShipRow {
  id: string;
  code: string;
  driver_id: string | null;
  current_status: string;
}

function BubbleView({ b, onTap, busy }: { b: Bubble; onTap: (kind: "button" | "list", id: string, title: string) => void; busy: boolean }) {
  const t = useTranslations("wa");
  const mine = b.side === "driver";
  return (
    <li className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div className={cn("max-w-[85%] space-y-2 rounded-2xl px-3.5 py-2 text-sm shadow-sm", mine ? "rounded-br-sm bg-accent text-accent-foreground" : "rounded-bl-sm border border-border bg-surface")}>
        <p className="whitespace-pre-wrap break-words">{b.text}</p>
        {b.template && (
          <p className={cn("text-[11px]", mine ? "opacity-80" : "text-muted")}>
            {t("sim.template")}: <span className="font-mono">{b.template}</span>
          </p>
        )}
        {b.buttons.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1" role="group" aria-label={t("sim.tapHint")}>
            {b.buttons.map((btn) => (
              <button
                key={btn.id}
                type="button"
                disabled={!b.tappable || busy}
                onClick={() => onTap("button", btn.id, btn.title)}
                className="rounded-full border border-accent px-3 py-1 text-xs font-medium text-accent transition-colors hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
              >
                {btn.title}
              </button>
            ))}
          </div>
        )}
        {b.rows.length > 0 && (
          <details open={b.tappable} className="rounded-lg border border-border bg-background">
            <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-accent">{b.listButton ?? t("sim.listOpen")}</summary>
            <ul className="divide-y divide-border">
              {b.rows.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    disabled={!b.tappable || busy}
                    onClick={() => onTap("list", r.id, r.title)}
                    className="block w-full px-3 py-2 text-left text-xs hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <span className="block font-medium">{r.title}</span>
                    {r.description && <span className="block text-muted">{r.description}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
        <div className={cn("flex items-center justify-end gap-1.5 text-[11px]", mine ? "opacity-80" : "text-muted")}>
          <time dateTime={b.time}>{formatDateTime(b.time)}</time>
          {mine && <Ticks status={b.status} />}
        </div>
      </div>
    </li>
  );
}

export default function SimulatorPage() {
  const t = useTranslations("wa");
  const drivers = useWaOther<WaPage<SimDriver>>("/drivers?limit=200");
  const ships = useWaOther<WaPage<ShipRow>>("/shipments?limit=200");
  const [driverId, setDriverId] = React.useState("");
  const [text, setText] = React.useState("");
  const [pendingText, setPendingText] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [confirmReset, setConfirmReset] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const endRef = React.useRef<HTMLDivElement>(null);
  useEventStream([[WA_KEY]], true);

  React.useEffect(() => {
    try {
      const saved = localStorage.getItem(STORE);
      if (saved) setDriverId(saved);
    } catch {
      /* private mode */
    }
  }, []);
  React.useEffect(() => {
    if (!driverId && drivers.data?.items.length) setDriverId(drivers.data.items[0].id);
  }, [drivers.data, driverId]);
  const pick = (id: string) => {
    setDriverId(id);
    setError(null);
    try {
      localStorage.setItem(STORE, id);
    } catch {
      /* ignore */
    }
  };

  const driver = drivers.data?.items.find((d) => d.id === driverId) ?? null;
  const active = (ships.data?.items ?? []).filter((s) => s.driver_id === driverId && ACTIVE.has(s.current_status));
  const convo = useWa<SimMessage[]>(driverId ? `/simulator/conversation?driver_id=${driverId}&limit=200` : null, { refetchInterval: 5000 });
  const thread = useWaOther<WaPage<ThreadInfo>>(driver ? `/coordinator/threads?q=${encodeURIComponent(driver.driver_name)}&limit=20` : null);
  const myThread = thread.data?.items.find((x) => x.driver_id === driverId) ?? null;

  const send = useWaMutation<SimSendBody, SimSendResult>((body) => waPost<SimSendResult>("/simulator/send", body), { silent: true });
  const doSend = (body: SimSendBody, shown: string) => {
    setError(null);
    setPendingText(shown);
    send.mutate(body, {
      onError: (e) => setError(e instanceof Error ? e.message : t("sim.sendFailed")),
      onSettled: () => {
        setPendingText(null);
        convo.refetch();
        inputRef.current?.focus();
      },
    });
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const v = text.trim();
    if (!v || !driverId || send.isPending) return;
    setText("");
    doSend(textPayload(driverId, v), v);
  };
  const tap = (kind: "button" | "list", id: string, title: string) => driverId && doSend(quickReplyPayload(driverId, kind, id, title), title);

  const reset = useWaMutation(() => waPost(`/simulator/reset?driver_id=${driverId}`), {
    success: t("g.saved"),
    onSuccess: () => setConfirmReset(false),
  });

  const messages = convo.data ?? [];
  const bubbles: Bubble[] = [...toBubbles(messages), ...(pendingText ? [pendingBubble(pendingText)] : [])];
  const lastDriver = [...messages].reverse().find((m) => m.direction === "in");
  const lastBot = [...messages].reverse().find((m) => m.direction === "out");
  const wrote = lastDriver?.text ? detectLanguageHint(lastDriver.text) : null;
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [bubbles.length, send.isPending]);

  return (
    <>
      <SectionHeader title={t("sim.title")} />
      <div role="note" className="mb-4 rounded-md border border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
        {t("sim.banner")}
      </div>
      <QueryState isLoading={drivers.isLoading} error={drivers.error} empty={!drivers.data?.items.length} emptyText={t("sim.noDrivers")} onRetry={() => drivers.refetch()}>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
          <section aria-label={t("sim.chat")} className="flex h-[34rem] min-w-0 flex-col overflow-hidden rounded-2xl border border-border bg-background shadow-sm">
            <header className="flex items-center justify-between gap-3 border-b border-border bg-surface px-4 py-3">
              <div>
                <p className="text-sm font-semibold">SetuHaul</p>
                <p className="text-xs text-muted">{driver ? `${driver.driver_name} · ${driver.whatsapp_number ?? "—"}` : t("sim.pickDriver")}</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setConfirmReset(true)} disabled={!driverId}>
                <RotateCcw className="size-3.5" aria-hidden="true" />
                {t("sim.reset")}
              </Button>
            </header>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
              <QueryState isLoading={convo.isLoading && !!driverId} error={convo.error} empty={!bubbles.length} emptyText={t("sim.empty")} onRetry={() => convo.refetch()}>
                <ol role="log" aria-live="polite" aria-relevant="additions" aria-label={t("sim.chat")} className="space-y-3">
                  {bubbles.map((b) => (
                    <BubbleView key={b.id} b={b} onTap={tap} busy={send.isPending} />
                  ))}
                  {send.isPending && (
                    <li role="status" className="flex justify-start">
                      <div className="rounded-2xl rounded-bl-sm border border-border bg-surface px-3.5 py-2 text-xs text-muted">{t("sim.typing")}</div>
                    </li>
                  )}
                </ol>
                <div ref={endRef} />
              </QueryState>
            </div>
            {error && (
              <p role="alert" className="border-t border-danger/40 bg-danger/10 px-4 py-2 text-xs text-danger">
                {t("sim.sendFailed")} {error}
              </p>
            )}
            <form onSubmit={submit} className="flex items-center gap-2 border-t border-border bg-surface p-3">
              <label htmlFor="sim-input" className="sr-only">
                {t("sim.placeholder")}
              </label>
              <Input id="sim-input" ref={inputRef} value={text} onChange={(e) => setText(e.target.value)} placeholder={t("sim.placeholder")} autoComplete="off" disabled={!driverId} />
              <Button type="submit" disabled={!text.trim() || !driverId || send.isPending}>
                <Send className="size-4" aria-hidden="true" />
                {t("sim.send")}
              </Button>
            </form>
          </section>

          <aside aria-label={t("sim.sideLabel")} className="space-y-4">
            <Card className="space-y-3">
              <Field label={t("sim.driver")} htmlFor="sim-driver">
                <Select id="sim-driver" value={driverId} onChange={(e) => pick(e.target.value)}>
                  {(drivers.data?.items ?? []).map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.driver_name} ({d.code})
                    </option>
                  ))}
                </Select>
              </Field>
              {driver && (
                <>
                  <p className="text-sm text-muted">{driver.carrier_name}</p>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={driver.verified ? "success" : "warning"}>{driver.verified ? t("sim.verified") : t("sim.unverified")}</Badge>
                    <Badge tone={driver.whatsapp_opt_in ? "success" : "danger"}>{driver.whatsapp_opt_in ? t("sim.optedIn") : t("sim.optedOut")}</Badge>
                    <span className="text-xs text-muted">{t("sim.language")}:</span>
                    <LangChip code={driver.preferred_language} />
                  </div>
                  {!driver.whatsapp_opt_in && <p className="text-xs text-danger">{t("sim.optedOutNote")}</p>}
                  {!driver.verified && <p className="text-xs text-amber-700 dark:text-amber-300">{t("sim.unverifiedNote")}</p>}
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted">{t("sim.active")}</p>
                    {active.length ? (
                      <ul className="mt-1 flex flex-wrap gap-1.5">
                        {active.map((s) => (
                          <li key={s.id}>
                            <Badge tone="accent" className="font-mono">
                              {s.code}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="mt-1 text-sm text-muted">{t("sim.none")}</p>
                    )}
                  </div>
                  <dl className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 text-xs">
                    <dt className="text-muted">{t("sim.detected")}</dt>
                    <dd><LangChip code={wrote} /></dd>
                    <dt className="text-muted">{t("sim.replied")}</dt>
                    <dd><LangChip code={lastBot?.language} /></dd>
                  </dl>
                </>
              )}
            </Card>

            <Card className="space-y-2">
              <h3 className="text-sm font-semibold">{t("sim.thread")}</h3>
              {myThread ? (
                <>
                  <p className="font-mono text-sm">{myThread.code}</p>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <dt className="text-muted">{t("sim.status")}</dt>
                    <dd>{myThread.thread_status}</dd>
                    <dt className="text-muted">{t("sim.intent")}</dt>
                    <dd>{myThread.thread_intent}</dd>
                  </dl>
                  {myThread.requires_review && <Badge tone="warning">{t("sim.review")}</Badge>}
                  <p className={cn("text-xs", myThread.taken_over_by ? "font-medium text-amber-700 dark:text-amber-300" : "text-muted")} aria-live="polite">
                    {myThread.taken_over_by ? t("sim.takenOver", { name: myThread.taken_over_by.name }) : t("sim.botActive")}
                  </p>
                  <p className="text-xs text-muted">{t("sim.coordinatorNote")}</p>
                </>
              ) : (
                <p className="text-sm text-muted">{t("sim.threadNone")}</p>
              )}
            </Card>

            <Card className="space-y-2">
              <h3 className="text-sm font-semibold">{t("sim.quick")}</h3>
              <ul className="flex flex-wrap gap-2">
                {QUICK_TESTS.map((q) => (
                  <li key={q.key}>
                    <button
                      type="button"
                      title={q.text}
                      disabled={!driverId || send.isPending}
                      onClick={() => driverId && doSend(textPayload(driverId, q.text), q.text)}
                      className="rounded-full border border-border px-3 py-1 text-xs hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                    >
                      {t(QUICK_LABEL[q.key])}
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          </aside>
        </div>
      </QueryState>
      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={() => reset.mutate(undefined)}
        title={t("sim.resetTitle")}
        message={t("sim.resetBody")}
        confirmLabel={t("sim.reset")}
        destructive
        pending={reset.isPending}
      />
    </>
  );
}

"use client";

import { ShieldCheck, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { BreakerBadge, Busy, QueryState, RunResultView, SectionHeader, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Checkbox, Field, Select, Textarea } from "@/components/ui/fields";
import { AI_TASKS } from "@/lib/ai";
import { aiPost, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiHealth, RunResult } from "@/lib/ai-types";

const stateTone = { ok: "success", degraded: "warning", off: "danger", unconfigured: "neutral" } as const;

export default function AiOverviewPage() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const stateLabel = useEnum("taskState");
  const health = useAi<AiHealth>("/health", { refetchInterval: 15000 });
  const [taskName, setTaskName] = React.useState<string>("intent_classify");
  const [message, setMessage] = React.useState(t("ov.sampleMessage"));
  const [asIntent, setAsIntent] = React.useState(true);
  const [result, setResult] = React.useState<RunResult | null>(null);

  const send = useAiMutation(
    () => aiPost<RunResult>("/test", { task: taskName, messages: [{ role: "user", content: message }], schema: asIntent ? "intent" : null }),
    { onSuccess: setResult },
  );

  return (
    <div className="space-y-8">
      {health.data?.kill_switch && (
        <div role="alert" className="flex items-start gap-3 rounded-xl border border-danger/50 bg-danger/10 px-4 py-3 text-sm text-danger">
          <TriangleAlert className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <p>{t("ov.killBanner")}</p>
        </div>
      )}

      <Card className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden="true" />
        <div>
          <h2 className="font-medium">{t("ov.degradeTitle")}</h2>
          <p className="mt-1 text-sm text-muted">{t("ov.degrade")}</p>
        </div>
      </Card>

      <QueryState isLoading={health.isLoading} error={health.error} onRetry={() => health.refetch()}>
        {health.data && (
          <div className="grid gap-6 lg:grid-cols-2">
            <section aria-labelledby="ov-providers">
              <SectionHeader title={t("ov.providers")} />
              <ul id="ov-providers" className="space-y-2">
                {health.data.providers.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-4 py-3">
                    <div>
                      <p className="font-medium">{p.name}</p>
                      {p.last_error && <p className="text-xs text-danger">{p.last_error}</p>}
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={p.status === "enabled" ? "success" : "neutral"}>{p.status === "enabled" ? t("g.enabled") : t("g.disabled")}</Badge>
                      <BreakerBadge state={p.breaker} />
                    </div>
                  </li>
                ))}
              </ul>
              <h3 className="mb-2 mt-6 text-sm font-medium">{t("ov.failedKeys")}</h3>
              {health.data.failed_keys.length === 0 ? (
                <p className="text-sm text-muted">{t("ov.noFailedKeys")}</p>
              ) : (
                <ul className="space-y-2">
                  {health.data.failed_keys.map((k) => (
                    <li key={k.id} role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-2 text-sm text-danger">
                      {k.provider_name} · {k.label}
                      {k.last_error ? `: ${k.last_error}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="ov-tasks">
              <SectionHeader title={t("ov.tasks")} />
              <ul id="ov-tasks" className="space-y-2">
                {health.data.tasks.map((x) => (
                  <li key={x.task} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-4 py-3">
                    <div>
                      <p className="font-medium">{task(x.task)}</p>
                      <p className="text-xs text-muted">{t("ov.steps", { healthy: x.healthy_steps, steps: x.steps })}</p>
                    </div>
                    <Badge tone={stateTone[x.state]}>{stateLabel(x.state)}</Badge>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </QueryState>

      <section aria-labelledby="ov-play">
        <SectionHeader title={t("ov.playground")} description={t("ov.playgroundHint")} />
        <Card className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("ov.task")} htmlFor="pg-task">
              <Select id="pg-task" value={taskName} onChange={(e) => setTaskName(e.target.value)}>
                {AI_TASKS.map((x) => (
                  <option key={x} value={x}>
                    {task(x)}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex items-end">
              <Checkbox label={t("ov.asIntent")} checked={asIntent} onChange={(e) => setAsIntent(e.target.checked)} />
            </div>
          </div>
          <Field label={t("ov.message")} htmlFor="pg-msg">
            <Textarea id="pg-msg" value={message} onChange={(e) => setMessage(e.target.value)} />
          </Field>
          <Button onClick={() => send.mutate(undefined)} disabled={send.isPending || !message.trim()}>
            {send.isPending ? <Busy label={t("g.loading")} /> : t("ov.send")}
          </Button>
          {result && (
            <div className="border-t border-border pt-4">
              <h3 className="mb-2 text-sm font-medium">{t("ov.result")}</h3>
              <RunResultView result={result} />
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}

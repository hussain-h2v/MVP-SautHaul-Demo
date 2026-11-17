"use client";

import { Power } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { QueryState, SectionHeader, Switch, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { aiPatch, aiPut, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiSafety } from "@/lib/ai-types";

export default function SafetyPage() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const safety = useAi<AiSafety>("/safety");
  const [confirmKill, setConfirmKill] = React.useState(false);
  const [logBodies, setLogBodies] = React.useState(false);
  const [retention, setRetention] = React.useState("30");
  const [threshold, setThreshold] = React.useState("5");
  const [windowS, setWindowS] = React.useState("60");
  const [cooldown, setCooldown] = React.useState("30");
  const s = safety.data;
  React.useEffect(() => {
    if (!s) return;
    setLogBodies(s.log_bodies);
    setRetention(String(s.log_retention_days));
    setThreshold(String(s.breaker.threshold));
    setWindowS(String(s.breaker.window_seconds));
    setCooldown(String(s.breaker.cooldown_seconds));
  }, [s]);

  const kill = useAiMutation((v: boolean) => aiPut("/safety", { kill_switch: v }), { onSuccess: () => setConfirmKill(false), success: t("sf.saved") });
  const taskToggle = useAiMutation((x: { task: string; enabled: boolean }) => aiPatch(`/routes/${x.task}/enabled`, { enabled: x.enabled }));
  const pii = useAiMutation((x: { id: string; allow_pii: boolean }) => aiPatch(`/providers/${x.id}`, { allow_pii: x.allow_pii }));
  const saveSettings = useAiMutation(
    () =>
      aiPut("/safety", {
        log_bodies: logBodies,
        log_retention_days: Number(retention),
        breaker: { threshold: Number(threshold), window_seconds: Number(windowS), cooldown_seconds: Number(cooldown) },
      }),
    { success: t("sf.saved") },
  );
  const invalid = ![retention, threshold, windowS, cooldown].every((v) => Number(v) > 0);

  return (
    <>
      <SectionHeader title={t("sf.title")} description={t("sf.description")} />
      <QueryState isLoading={safety.isLoading} error={safety.error} onRetry={() => safety.refetch()}>
        {s && (
          <div className="space-y-6">
            <Card className={s.kill_switch ? "border-danger/60" : ""}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="max-w-2xl">
                  <h3 className="flex items-center gap-2 text-lg font-semibold">
                    <Power className="size-5" aria-hidden="true" />
                    {t("sf.kill")}
                  </h3>
                  <p className="mt-1 text-sm font-medium" aria-live="polite">
                    <Badge tone={s.kill_switch ? "danger" : "success"}>{s.kill_switch ? t("sf.killOn") : t("sf.killOff")}</Badge>
                  </p>
                  <p className="mt-2 text-sm text-muted">{t("sf.killExplain")}</p>
                </div>
                <Button variant={s.kill_switch ? "primary" : "outline"} className={s.kill_switch ? "" : "border-danger text-danger"} onClick={() => setConfirmKill(true)}>
                  {s.kill_switch ? t("sf.killUndo") : t("sf.killDo")}
                </Button>
              </div>
            </Card>

            <section aria-labelledby="sf-tasks">
              <h3 id="sf-tasks" className="mb-2 text-sm font-medium">{t("sf.tasks")}</h3>
              <ul className="grid gap-2 sm:grid-cols-2">
                {s.tasks.map((x) => (
                  <li key={x.task} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3">
                    <span>{task(x.task)}</span>
                    <Switch checked={x.enabled} label={task(x.task)} onChange={(v) => taskToggle.mutate({ task: x.task, enabled: v })} />
                  </li>
                ))}
              </ul>
            </section>

            <section aria-labelledby="sf-prov">
              <h3 id="sf-prov" className="mb-1 text-sm font-medium">{t("sf.providers")}</h3>
              <p className="mb-2 text-xs text-muted">{t("sf.providersHint")}</p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {s.providers.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-3">
                    <div>
                      <p>{p.name}</p>
                      <Badge tone={p.allow_pii ? "warning" : "neutral"}>{p.allow_pii ? t("sf.piiAllowed") : t("sf.piiMasked")}</Badge>
                    </div>
                    <Switch checked={p.allow_pii} label={`${t("sf.piiAllowed")}: ${p.name}`} onChange={(v) => pii.mutate({ id: p.id, allow_pii: v })} />
                  </li>
                ))}
              </ul>
            </section>

            <Card className="space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="font-medium">{t("sf.logBodies")}</p>
                  <p className="text-xs text-muted">{t("sf.logBodiesHint")}</p>
                </div>
                <Switch checked={logBodies} onChange={setLogBodies} label={t("sf.logBodies")} />
              </div>
              <Field label={t("sf.retention")} htmlFor="sf-ret" className="max-w-xs">
                <Input id="sf-ret" type="number" min={1} value={retention} onChange={(e) => setRetention(e.target.value)} />
              </Field>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">{t("sf.breaker")}</legend>
                <p className="text-xs text-muted">{t("sf.breakerHint")}</p>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Field label={t("sf.breakerThreshold")} htmlFor="sf-thr"><Input id="sf-thr" type="number" min={1} value={threshold} onChange={(e) => setThreshold(e.target.value)} /></Field>
                  <Field label={t("sf.breakerWindow")} htmlFor="sf-win"><Input id="sf-win" type="number" min={1} value={windowS} onChange={(e) => setWindowS(e.target.value)} /></Field>
                  <Field label={t("sf.breakerCooldown")} htmlFor="sf-cool"><Input id="sf-cool" type="number" min={1} value={cooldown} onChange={(e) => setCooldown(e.target.value)} /></Field>
                </div>
              </fieldset>
              <Button onClick={() => saveSettings.mutate(undefined)} disabled={invalid || saveSettings.isPending}>{t("sf.saveSettings")}</Button>
            </Card>
          </div>
        )}
      </QueryState>
      <ConfirmDialog
        open={confirmKill}
        onClose={() => setConfirmKill(false)}
        onConfirm={() => s && kill.mutate(!s.kill_switch)}
        title={s?.kill_switch ? t("sf.killConfirmOff") : t("sf.killConfirmOn")}
        message={t("sf.killConfirmMsg")}
        confirmLabel={s?.kill_switch ? t("sf.killUndo") : t("sf.killDo")}
        destructive={!s?.kill_switch}
        pending={kill.isPending}
      />
    </>
  );
}

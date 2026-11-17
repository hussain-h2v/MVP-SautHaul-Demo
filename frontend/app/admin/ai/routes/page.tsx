"use client";

import { ArrowDown, ArrowUp, GripVertical, Plus, Trash2, Zap } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Busy, PathChain, QueryState, SectionHeader, Switch, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { blankStep, ERROR_CODES, moveStep, removeStep, sameSteps, stepRole, stepsPayload } from "@/lib/ai";
import { aiPatch, aiPost, aiPut, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiKey, AiModel, AiProvider, AiRoute, KeyStrategy, RouteStep, RunResult } from "@/lib/ai-types";

const STRATEGIES: KeyStrategy[] = ["single", "round_robin", "weighted"];

function StepDialog({
  step,
  models,
  keys,
  providers,
  onClose,
  onSave,
}: {
  step: RouteStep | null;
  models: AiModel[];
  keys: AiKey[];
  providers: AiProvider[];
  onClose: () => void;
  onSave: (s: RouteStep) => void;
}) {
  const t = useTranslations("ai");
  const strat = useEnum("strategy");
  const [d, setD] = React.useState<RouteStep | null>(step);
  const [langs, setLangs] = React.useState("");
  React.useEffect(() => {
    setD(step);
    setLangs(step?.conditions.languages?.join(",") ?? "");
  }, [step]);
  if (!d) return null;
  const model = models.find((m) => m.id === d.model_id);
  const providerKeys = keys.filter((k) => k.provider_id === model?.provider_id);
  const poolIds = d.key_ids.length ? d.key_ids : d.key_id ? [d.key_id] : [];
  const setPool = (ids: string[]) => setD({ ...d, key_ids: ids, key_id: ids[0] ?? null });
  const num = (v: string) => (v === "" ? undefined : Number(v));
  const save = () => {
    const languages = langs.split(",").map((x) => x.trim()).filter(Boolean);
    const conditions = { ...d.conditions, languages: languages.length ? languages : undefined };
    if (!conditions.languages) delete conditions.languages;
    onSave({ ...d, conditions });
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("rt.editStep")}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={save} disabled={!d.model_id}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("rt.model")} htmlFor="st-model">
          <Select id="st-model" value={d.model_id} onChange={(e) => setD({ ...d, model_id: e.target.value, key_id: null, key_ids: [] })}>
            <option value="">{t("rt.pickModel")}</option>
            {providers.map((p) => {
              const list = models.filter((m) => m.provider_id === p.id);
              return list.length ? (
                <optgroup key={p.id} label={p.name}>
                  {list.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.model_name}
                    </option>
                  ))}
                </optgroup>
              ) : null;
            })}
          </Select>
        </Field>
        <fieldset>
          <legend className="text-sm font-medium">{t("rt.keys")}</legend>
          <p className="mb-2 text-xs text-muted">{t("rt.keysHint")}</p>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {providerKeys.map((k) => (
              <Checkbox
                key={k.id}
                label={`${k.label} ••••${k.key_last4}`}
                checked={poolIds.includes(k.id)}
                onChange={(e) => setPool(e.target.checked ? [...poolIds, k.id] : poolIds.filter((x) => x !== k.id))}
              />
            ))}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("rt.strategy")} htmlFor="st-strat">
            <Select id="st-strat" value={d.key_strategy} onChange={(e) => setD({ ...d, key_strategy: e.target.value as KeyStrategy })}>
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {strat(s)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("rt.timeout")} htmlFor="st-timeout">
            <Input id="st-timeout" type="number" min={500} value={d.timeout_ms} onChange={(e) => setD({ ...d, timeout_ms: Number(e.target.value) })} />
          </Field>
          <Field label={t("rt.retries")} htmlFor="st-retry">
            <Input id="st-retry" type="number" min={0} max={5} value={d.max_retries} onChange={(e) => setD({ ...d, max_retries: Number(e.target.value) })} />
          </Field>
          <Field label={t("rt.temperature")} htmlFor="st-temp">
            <Input id="st-temp" type="number" min={0} max={2} step="0.1" value={d.temperature} onChange={(e) => setD({ ...d, temperature: Number(e.target.value) })} />
          </Field>
          <Field label={t("rt.maxTokens")} htmlFor="st-max">
            <Input id="st-max" type="number" min={1} value={d.max_tokens} onChange={(e) => setD({ ...d, max_tokens: Number(e.target.value) })} />
          </Field>
        </div>
        <fieldset className="space-y-3 rounded-md border border-border p-3">
          <legend className="px-1 text-sm font-medium">{t("rt.conditions")}</legend>
          <Field label={t("rt.languages")} htmlFor="st-langs" hint={t("rt.languagesHint")}>
            <Input id="st-langs" value={langs} onChange={(e) => setLangs(e.target.value)} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t("rt.maxChars")} htmlFor="st-maxc">
              <Input id="st-maxc" type="number" min={1} value={d.conditions.max_input_chars ?? ""} onChange={(e) => setD({ ...d, conditions: { ...d.conditions, max_input_chars: num(e.target.value) } })} />
            </Field>
            <Field label={t("rt.minChars")} htmlFor="st-minc">
              <Input id="st-minc" type="number" min={1} value={d.conditions.min_input_chars ?? ""} onChange={(e) => setD({ ...d, conditions: { ...d.conditions, min_input_chars: num(e.target.value) } })} />
            </Field>
          </div>
        </fieldset>
      </div>
    </Dialog>
  );
}

function RouteCard({ route, models, keys, providers }: { route: AiRoute; models: AiModel[]; keys: AiKey[]; providers: AiProvider[] }) {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const err = useEnum("err");
  const tp = t as unknown as (key: string, values?: Record<string, unknown>) => string;
  const [steps, setSteps] = React.useState<RouteStep[]>(route.steps);
  const [refusal, setRefusal] = React.useState(route.fallback_on_refusal);
  const [announce, setAnnounce] = React.useState("");
  const [editing, setEditing] = React.useState<number | null>(null);
  const [dragFrom, setDragFrom] = React.useState<number | null>(null);
  const [errCode, setErrCode] = React.useState<string>("timeout");
  const [sim, setSim] = React.useState<RunResult | null>(null);
  const serverSig = JSON.stringify(route);
  React.useEffect(() => {
    setSteps(route.steps);
    setRefusal(route.fallback_on_refusal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverSig]);
  const dirty = !sameSteps(steps, route.steps) || refusal !== route.fallback_on_refusal;
  const modelName = (id: string) => models.find((m) => m.id === id)?.model_name ?? "?";
  const providerOf = (id: string) => providers.find((p) => p.id === models.find((m) => m.id === id)?.provider_id)?.name ?? "";

  const move = (from: number, to: number) => {
    if (to < 0 || to >= steps.length || from === to) return;
    const next = moveStep(steps, from, to);
    setSteps(next);
    setAnnounce(t("rt.moved", { model: modelName(steps[from].model_id), pos: to + 1, total: steps.length }));
  };

  const save = useAiMutation(() => aiPut(`/routes/${route.task}`, { enabled: route.enabled, fallback_on_refusal: refusal, steps: stepsPayload(steps) }), {
    success: t("rt.saved"),
  });
  const enable = useAiMutation((v: boolean) => aiPatch(`/routes/${route.task}/enabled`, { enabled: v }));
  const simulate = useAiMutation(() => aiPost<RunResult & { unavailable: boolean }>(`/routes/${route.task}/simulate-failure`, { error_code: errCode, seconds: 60 }), {
    onSuccess: setSim,
  });

  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold">{task(route.task)}</h3>
          {route.description && <p className="text-sm text-muted">{route.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          <span id={`en-${route.task}`} className="text-sm">
            {t("rt.taskEnabled")}
          </span>
          <Switch checked={route.enabled} onChange={(v) => enable.mutate(v)} label={`${t("rt.taskEnabled")}: ${task(route.task)}`} />
        </div>
      </div>
      {!route.enabled && <p className="text-xs text-muted">{t("rt.taskOffHint")}</p>}

      <p aria-live="polite" className="sr-only">
        {announce}
      </p>
      {steps.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-4 py-5 text-center text-sm text-muted">{t("rt.noSteps")}</p>
      ) : (
        <ol className="space-y-2" aria-label={task(route.task)}>
          {steps.map((s, i) => (
            <li
              key={`${i}-${s.model_id}`}
              draggable
              onDragStart={() => setDragFrom(i)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragFrom !== null) move(dragFrom, i);
                setDragFrom(null);
              }}
              onDragEnd={() => setDragFrom(null)}
              className={`flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background px-3 py-2 ${dragFrom === i ? "opacity-50" : ""}`}
            >
              <GripVertical className="size-4 cursor-grab text-muted" aria-label={t("rt.dragHandle")} role="img" />
              <Badge tone={i === 0 ? "accent" : "neutral"}>{tp(`role.${stepRole(i)}`, { n: i + 1 })}</Badge>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{modelName(s.model_id)}</p>
                <p className="truncate text-xs text-muted">
                  {providerOf(s.model_id)} · {s.timeout_ms} ms · {s.max_retries}× · {s.key_strategy}
                  {s.conditions.languages?.length ? ` · ${s.conditions.languages.join(",")}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" className="size-8" aria-label={t("rt.moveUp")} disabled={i === 0} onClick={() => move(i, i - 1)}>
                  <ArrowUp className="size-4" aria-hidden="true" />
                </Button>
                <Button size="icon" variant="ghost" className="size-8" aria-label={t("rt.moveDown")} disabled={i === steps.length - 1} onClick={() => move(i, i + 1)}>
                  <ArrowDown className="size-4" aria-hidden="true" />
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(i)}>
                  {t("g.edit")}
                </Button>
                <Button size="icon" variant="ghost" className="size-8 text-danger" aria-label={t("rt.removeStep")} onClick={() => setSteps(removeStep(steps, i))}>
                  <Trash2 className="size-4" aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ol>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" disabled={!models.length} onClick={() => { setSteps([...steps, blankStep(models[0].id)]); setEditing(steps.length); }}>
          <Plus className="size-4" aria-hidden="true" />
          {t("rt.addStep")}
        </Button>
        <Checkbox label={t("rt.fallbackRefusal")} checked={refusal} onChange={(e) => setRefusal(e.target.checked)} />
        <div className="ml-auto flex items-center gap-2">
          {dirty && <Badge tone="warning">{t("g.unsaved")}</Badge>}
          {dirty && (
            <Button variant="ghost" size="sm" onClick={() => { setSteps(route.steps); setRefusal(route.fallback_on_refusal); }}>
              {t("rt.discard")}
            </Button>
          )}
          <Button onClick={() => save.mutate(undefined)} disabled={!dirty || save.isPending || steps.some((s) => !s.model_id)}>
            {t("g.save")}
          </Button>
        </div>
      </div>

      <div className="space-y-3 border-t border-border pt-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-48">
            <Field label={t("rt.simulate")} htmlFor={`sim-${route.task}`} hint={t("rt.simulateHelp")}>
              <Select id={`sim-${route.task}`} value={errCode} onChange={(e) => setErrCode(e.target.value)}>
                {ERROR_CODES.map((c) => (
                  <option key={c} value={c}>
                    {err(c)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Button variant="outline" onClick={() => simulate.mutate(undefined)} disabled={simulate.isPending || route.steps.length === 0 || dirty}>
            {simulate.isPending ? <Busy label={t("g.loading")} /> : (
              <>
                <Zap className="size-4" aria-hidden="true" />
                {t("rt.simulateRun")}
              </>
            )}
          </Button>
          {dirty && <p className="pb-2 text-xs text-muted">{t("g.unsaved")}</p>}
        </div>
        {sim && (
          <div aria-live="polite" className="space-y-2 rounded-lg border border-border bg-background p-3">
            <h4 className="text-sm font-medium">{t("rt.simulateResult")}</h4>
            <p className="text-sm">
              {sim.unavailable || !sim.used ? t("rt.noneAnswered") : t("rt.usedFallback", { model: sim.used.model, provider: sim.used.provider, depth: sim.fallback_depth ?? 0 })}
            </p>
            <PathChain path={sim.path} />
          </div>
        )}
      </div>

      <StepDialog
        step={editing !== null ? steps[editing] ?? null : null}
        models={models}
        keys={keys}
        providers={providers}
        onClose={() => setEditing(null)}
        onSave={(s) => {
          if (editing !== null) setSteps(steps.map((x, i) => (i === editing ? s : x)));
          setEditing(null);
        }}
      />
    </Card>
  );
}

export default function RoutesPage() {
  const t = useTranslations("ai");
  const routes = useAi<AiRoute[]>("/routes");
  const models = useAi<AiModel[]>("/models");
  const keys = useAi<AiKey[]>("/keys");
  const providers = useAi<AiProvider[]>("/providers");
  const loading = routes.isLoading || models.isLoading || keys.isLoading || providers.isLoading;
  const error = routes.error || models.error || keys.error || providers.error;
  return (
    <>
      <SectionHeader title={t("rt.title")} description={t("rt.description")} />
      <QueryState isLoading={loading} error={error} onRetry={() => routes.refetch()}>
        <div className="space-y-6">
          {routes.data?.map((r) => (
            <RouteCard key={r.task} route={r} models={models.data ?? []} keys={keys.data ?? []} providers={providers.data ?? []} />
          ))}
        </div>
      </QueryState>
    </>
  );
}

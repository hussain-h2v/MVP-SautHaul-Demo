"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { QueryState, SectionHeader, Switch, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { AI_TASKS, budgetState, formatMoney, formatPercent } from "@/lib/ai";
import { aiDelete, aiPatch, aiPost, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiBudget, AiKey, AiProvider } from "@/lib/ai-types";
import { cn } from "@/lib/utils";

const stateTone = { ok: "success", alert: "warning", exhausted: "danger" } as const;
const barColor = { ok: "bg-success", alert: "bg-amber-500", exhausted: "bg-danger" } as const;

function BudgetDialog({ budget, open, onClose, providers, keys }: { budget: AiBudget | null; open: boolean; onClose: () => void; providers: AiProvider[]; keys: AiKey[] }) {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const [scope, setScope] = React.useState<AiBudget["scope"]>("global");
  const [scopeId, setScopeId] = React.useState("");
  const [period, setPeriod] = React.useState<AiBudget["period"]>("monthly");
  const [limit, setLimit] = React.useState("");
  const [threshold, setThreshold] = React.useState("80");
  React.useEffect(() => {
    if (!open) return;
    setScope(budget?.scope ?? "global");
    setScopeId(budget?.scope_id ?? "");
    setPeriod(budget?.period ?? "monthly");
    setLimit(budget?.limit_amount?.toString() ?? "");
    setThreshold(budget ? String(Math.round(budget.alert_threshold * 100)) : "80");
  }, [open, budget]);
  const options =
    scope === "provider" ? providers.map((p) => ({ id: p.id, label: p.name }))
    : scope === "key" ? keys.map((k) => ({ id: k.id, label: `${k.provider_name} · ${k.label} ••••${k.key_last4}` }))
    : scope === "task" ? AI_TASKS.map((x) => ({ id: x, label: task(x) }))
    : [];
  const save = useAiMutation(
    () => {
      const body = { scope, scope_id: scope === "global" ? null : scopeId, period, limit_amount: Number(limit), alert_threshold: Number(threshold) / 100 };
      return budget ? aiPatch(`/budgets/${budget.id}`, body) : aiPost("/budgets", body);
    },
    { success: t("g.saved"), onSuccess: onClose },
  );
  const invalid = !(Number(limit) > 0) || !(Number(threshold) > 0 && Number(threshold) <= 100) || (scope !== "global" && !scopeId);
  return (
    <Dialog open={open} onClose={onClose} title={budget ? t("bg.edit") : t("bg.add")} footer={
      <>
        <Button variant="outline" onClick={onClose}>{t("g.cancel")}</Button>
        <Button onClick={() => save.mutate(undefined)} disabled={invalid || save.isPending}>{t("g.save")}</Button>
      </>
    }>
      <div className="space-y-4">
        <Field label={t("bg.scopeLabel")} htmlFor="bg-scope">
          <Select id="bg-scope" value={scope} onChange={(e) => { setScope(e.target.value as AiBudget["scope"]); setScopeId(""); }}>
            {(["global", "provider", "task", "key"] as const).map((s) => <option key={s} value={s}>{t(`bg.scope.${s}`)}</option>)}
          </Select>
        </Field>
        {scope !== "global" && (
          <Field label={t("bg.target")} htmlFor="bg-target">
            <Select id="bg-target" value={scopeId} onChange={(e) => setScopeId(e.target.value)}>
              <option value="">—</option>
              {options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </Select>
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("bg.period")} htmlFor="bg-period">
            <Select id="bg-period" value={period} onChange={(e) => setPeriod(e.target.value as AiBudget["period"])}>
              <option value="daily">{t("bg.daily")}</option>
              <option value="monthly">{t("bg.monthly")}</option>
            </Select>
          </Field>
          <Field label={t("bg.limit")} htmlFor="bg-limit">
            <Input id="bg-limit" type="number" min={0} step="0.01" value={limit} onChange={(e) => setLimit(e.target.value)} />
          </Field>
          <Field label={t("bg.threshold")} htmlFor="bg-thr">
            <Input id="bg-thr" type="number" min={1} max={100} value={threshold} onChange={(e) => setThreshold(e.target.value)} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

export default function BudgetsPage() {
  const t = useTranslations("ai");
  const task = useEnum("task");
  const budgets = useAi<AiBudget[]>("/budgets");
  const providers = useAi<AiProvider[]>("/providers");
  const keys = useAi<AiKey[]>("/keys");
  const [editing, setEditing] = React.useState<AiBudget | null>(null);
  const [open, setOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<AiBudget | null>(null);
  const toggle = useAiMutation((b: AiBudget) => aiPatch(`/budgets/${b.id}`, { enabled: !b.enabled }));
  const del = useAiMutation((b: AiBudget) => aiDelete(`/budgets/${b.id}`), { success: t("g.deleted"), onSuccess: () => setDeleting(null) });

  const target = (b: AiBudget) => {
    if (b.scope === "global") return t("bg.globalTarget");
    if (b.scope === "provider") return providers.data?.find((p) => p.id === b.scope_id)?.name ?? b.scope_id ?? "";
    if (b.scope === "key") return keys.data?.find((k) => k.id === b.scope_id)?.label ?? b.scope_id ?? "";
    return task(b.scope_id ?? "");
  };

  return (
    <>
      <SectionHeader
        title={t("bg.title")}
        description={t("bg.description")}
        actions={
          <Button onClick={() => { setEditing(null); setOpen(true); }}>
            <Plus className="size-4" aria-hidden="true" />
            {t("bg.add")}
          </Button>
        }
      />
      <QueryState isLoading={budgets.isLoading} error={budgets.error} empty={budgets.data?.length === 0} onRetry={() => budgets.refetch()}>
        <ul className="space-y-3">
          {budgets.data?.map((b) => {
            const state = b.state ?? budgetState(b.spent, b.limit_amount, b.alert_threshold);
            const pct = Math.min(100, Math.round((b.spent / (b.limit_amount || 1)) * 100));
            return (
              <li key={b.id}>
                <Card className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-medium">
                        {t(`bg.scope.${b.scope}`)}: {target(b)}
                      </p>
                      <p className="text-xs text-muted">{b.period === "daily" ? t("bg.daily") : t("bg.monthly")} · {t("bg.threshold")} {Math.round(b.alert_threshold * 100)}%</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge tone={stateTone[state]}>{t(`bg.state.${state}`)}</Badge>
                      <Switch checked={b.enabled} onChange={() => toggle.mutate(b)} label={`${t("g.enabled")}: ${target(b)}`} />
                      <Button size="sm" variant="ghost" onClick={() => { setEditing(b); setOpen(true); }}>{t("g.edit")}</Button>
                      <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(b)}>{t("g.delete")}</Button>
                    </div>
                  </div>
                  <div>
                    <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={target(b)} className="h-2.5 overflow-hidden rounded-full bg-border">
                      <div className={cn("h-full rounded-full", barColor[state])} style={{ width: `${pct}%` }} />
                    </div>
                    <p className="mt-1 text-sm">{t("bg.spent", { spent: formatMoney(b.spent), limit: formatMoney(b.limit_amount), pct: formatPercent(b.spent, b.limit_amount) })}</p>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      </QueryState>
      <BudgetDialog budget={editing} open={open} onClose={() => setOpen(false)} providers={providers.data ?? []} keys={keys.data ?? []} />
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} onConfirm={() => deleting && del.mutate(deleting)} title={t("bg.deleteTitle")} message={deleting ? target(deleting) : ""} confirmLabel={t("g.delete")} destructive pending={del.isPending} />
    </>
  );
}

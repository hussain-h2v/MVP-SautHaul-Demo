"use client";

import { Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { ActiveBadge } from "@/components/admin/badges";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { diffObjects, formatValue } from "@/lib/diff";
import { apiErrorText, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type { AuditRow, FacilityRule, FacilitySummary, RuleType } from "@/lib/facility-types";
import { formatDateTime } from "@/lib/format";
import { todayIn } from "@/lib/time";

function RuleDialog({ facility, rule, types, onClose }: { facility: FacilitySummary; rule: FacilityRule | "new"; types: RuleType[]; onClose: () => void }) {
  const t = useTranslations("facility.rules");
  const c = useTranslations("common");
  const existing = rule === "new" ? undefined : rule;
  const [type, setType] = React.useState(existing?.rule_type ?? types[0]?.type ?? "");
  const [value, setValue] = React.useState(existing?.rule_value ?? "");
  const [description, setDescription] = React.useState(existing?.description ?? "");
  const [from, setFrom] = React.useState(existing?.effective_from ?? todayIn(facility.timezone));
  const [to, setTo] = React.useState(existing?.effective_to ?? "");
  const [active, setActive] = React.useState(existing?.active_flag ?? true);
  const [err, setErr] = React.useState<string | null>(null);
  const hint = types.find((x) => x.type === type);
  const valid = value.trim().length > 0 && description.trim().length >= 3 && !!from && (!to || to >= from);

  const save = useFacMutation(
    () =>
      existing
        ? api<FacilityRule>(`/facilities/${facility.id}/rules/${existing.id}`, {
            method: "PATCH",
            body: { rule_value: value.trim(), description: description.trim(), effective_from: from, effective_to: to || null, active_flag: active },
          })
        : api<FacilityRule>(`/facilities/${facility.id}/rules`, {
            method: "POST",
            body: { rule_type: type, rule_value: value.trim(), description: description.trim(), effective_from: from, effective_to: to || null },
          }),
    { success: t("saved"), onSuccess: onClose, onError: (e) => setErr(apiErrorText(e)) },
  );

  return (
    <Dialog
      open
      onClose={onClose}
      title={existing ? t("edit") : t("new")}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {c("save")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("type")} htmlFor="rule-type" hint={hint?.description} className="sm:col-span-2">
          <Select id="rule-type" value={type} disabled={!!existing} onChange={(e) => setType(e.target.value)}>
            {types.map((x) => (
              <option key={x.type} value={x.type}>
                {x.type}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("value")} htmlFor="rule-value" hint={hint?.value_hint}>
          <Input id="rule-value" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Field label={t("descriptionField")} htmlFor="rule-desc">
          <Input id="rule-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label={t("from")} htmlFor="rule-from">
          <Input id="rule-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t("to")} htmlFor="rule-to" hint={t("toHint")}>
          <Input id="rule-to" type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </Field>
        {existing && <Checkbox label={t("active")} checked={active} onChange={(e) => setActive(e.target.checked)} />}
      </div>
    </Dialog>
  );
}

function HistoryDrawer({ facility, rule, onClose }: { facility: FacilitySummary; rule: FacilityRule; onClose: () => void }) {
  const t = useTranslations("facility.rules");
  const locale = useLocale();
  const q = useFacQuery<{ items: AuditRow[] }>(`/facilities/${facility.id}/rules/${rule.id}/history`);
  return (
    <Dialog open drawer onClose={onClose} title={t("historyTitle")} description={`${rule.rule_type} = ${rule.rule_value}`}>
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={(q.data?.items.length ?? 0) === 0} emptyText={t("noHistory")}>
        <ol className="space-y-4 border-l border-border pl-4">
          {(q.data?.items ?? []).map((a, i) => {
            const changes = diffObjects(a.before, a.after).filter((x) => !["updated_at", "created_at", "version", "id"].includes(x.key));
            return (
              <li key={i} className="text-sm">
                <p className="font-medium">
                  {a.action} · <span className="font-normal text-muted">{a.actor_type}{a.actor_id ? `:${a.actor_id.slice(0, 8)}` : ""}</span>
                </p>
                <p className="text-xs text-muted">{formatDateTime(a.created_at, locale)}</p>
                <ul className="mt-1 space-y-0.5">
                  {changes.map((ch) => (
                    <li key={ch.key} className="text-xs">
                      <span className="font-medium">{ch.key}</span>: <span className="text-danger line-through">{formatValue(ch.before)}</span> → <span className="text-success">{formatValue(ch.after)}</span>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ol>
      </QueryState>
    </Dialog>
  );
}

function RulesView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.rules");
  const c = useTranslations("common");
  const locale = useLocale();
  const canWrite = useCap("docks_slots_rules") === "W";
  const q = useFacQuery<FacilityRule[]>(`/facilities/${facility.id}/rules`);
  const types = useFacQuery<RuleType[]>("/facilities/rule-types");
  const [editing, setEditing] = React.useState<FacilityRule | "new" | null>(null);
  const [history, setHistory] = React.useState<FacilityRule | null>(null);
  const today = todayIn(facility.timezone);
  const rules = [...(q.data ?? [])].sort((a, b) => a.rule_type.localeCompare(b.rule_type) || (b.effective_from ?? "").localeCompare(a.effective_from ?? ""));
  const state = (r: FacilityRule) => (!r.active_flag ? "inactive" : r.effective_to && r.effective_to < today ? "expired" : r.effective_from && r.effective_from > today ? "scheduled" : "current");

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canWrite && (
            <Button onClick={() => setEditing("new")} disabled={!types.data}>
              <Plus className="size-4" aria-hidden="true" />
              {t("new")}
            </Button>
          )
        }
      />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rules.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border">
              {[t("type"), t("value"), t("descriptionField"), t("from"), t("to"), c("status"), c("actions")].map((h) => (
                <th key={h} scope="col" className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => {
              const s = state(r);
              return (
                <tr key={r.id} className="border-b border-border last:border-b-0">
                  <td className={`${td} font-mono text-xs`}>{r.rule_type}</td>
                  <td className={`${td} font-medium`}>{r.rule_value}</td>
                  <td className={td}>{r.description}</td>
                  <td className={td}>{r.effective_from ? new Date(`${r.effective_from}T00:00:00`).toLocaleDateString(locale === "hi" ? "hi-IN" : "en-IN") : "—"}</td>
                  <td className={td}>{r.effective_to ? new Date(`${r.effective_to}T00:00:00`).toLocaleDateString(locale === "hi" ? "hi-IN" : "en-IN") : "—"}</td>
                  <td className={td}>{s === "current" ? <ActiveBadge active /> : <Badge tone={s === "scheduled" ? "accent" : "neutral"}>{t(`state.${s}`)}</Badge>}</td>
                  <td className={td}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setHistory(r)}>
                        {t("history")}
                      </Button>
                      {canWrite && (
                        <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>
                          {c("edit")}
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </TableShell>
      </QueryState>
      {editing && types.data && <RuleDialog key={editing === "new" ? "new" : editing.id} facility={facility} rule={editing} types={types.data} onClose={() => setEditing(null)} />}
      {history && <HistoryDrawer facility={facility} rule={history} onClose={() => setHistory(null)} />}
    </>
  );
}

export default function RulesPage() {
  return <RequireFacility>{(f) => <RulesView key={f.id} facility={f} />}</RequireFacility>;
}

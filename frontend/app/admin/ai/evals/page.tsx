"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Busy, DataTableLite, QueryState, SectionHeader } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { compareDeltas, disagreementCount, formatMoney, languageChartData, PALETTE } from "@/lib/ai";
import { aiDelete, aiPatch, aiPost, qs, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiModel, EvalCase, EvalCompare, EvalResultRow, EvalRun } from "@/lib/ai-types";
import { formatDateTime, LANGUAGES } from "@/lib/format";
import { cn } from "@/lib/utils";

const INTENTS = ["report_delay", "ask_options", "choose_option", "accept_suggestion", "decline_suggestion", "report_arrival", "ask_status", "ask_gate_info", "safety_issue", "unknown"];

function CaseDialog({ item, open, onClose }: { item: EvalCase | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("ai");
  const [language, setLanguage] = React.useState("en");
  const [text, setText] = React.useState("");
  const [intent, setIntent] = React.useState("report_delay");
  const [delay, setDelay] = React.useState("");
  const [eta, setEta] = React.useState("");
  React.useEffect(() => {
    if (!open) return;
    setLanguage(item?.language ?? "en");
    setText(item?.text ?? "");
    setIntent(item?.expected.intent ?? "report_delay");
    setDelay(item?.expected.delay_minutes?.toString() ?? "");
    setEta(item?.expected.eta_time ?? "");
  }, [open, item]);
  const save = useAiMutation(
    () => {
      const body = { language, text: text.trim(), expected: { intent, delay_minutes: delay ? Number(delay) : null, eta_time: eta || null } };
      return item ? aiPatch(`/evals/cases/${item.id}`, body) : aiPost("/evals/cases", body);
    },
    { success: t("g.saved"), onSuccess: onClose },
  );
  const etaInvalid = eta !== "" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(eta);
  return (
    <Dialog open={open} onClose={onClose} title={item ? t("ev.editCase") : t("ev.addCase")} footer={
      <>
        <Button variant="outline" onClick={onClose}>{t("g.cancel")}</Button>
        <Button onClick={() => save.mutate(undefined)} disabled={!text.trim() || etaInvalid || save.isPending}>{t("g.save")}</Button>
      </>
    }>
      <div className="space-y-4">
        <Field label={t("ev.language")} htmlFor="ec-lang">
          <Select id="ec-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
          </Select>
        </Field>
        <Field label={t("ev.text")} htmlFor="ec-text">
          <Textarea id="ec-text" value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label={t("ev.intent")} htmlFor="ec-intent">
          <Select id="ec-intent" value={intent} onChange={(e) => setIntent(e.target.value)}>
            {INTENTS.map((i) => <option key={i} value={i}>{i}</option>)}
          </Select>
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ev.delay")} htmlFor="ec-delay">
            <Input id="ec-delay" type="number" min={0} value={delay} onChange={(e) => setDelay(e.target.value)} />
          </Field>
          <Field label={t("ev.eta")} htmlFor="ec-eta" error={etaInvalid ? "HH:MM" : undefined}>
            <Input id="ec-eta" placeholder="14:30" value={eta} onChange={(e) => setEta(e.target.value)} aria-invalid={etaInvalid} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

function RunDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("ai");
  const models = useAi<AiModel[]>("/models");
  const [label, setLabel] = React.useState("");
  const [modelId, setModelId] = React.useState("");
  const [langs, setLangs] = React.useState("");
  React.useEffect(() => {
    if (open) {
      setLabel("");
      setModelId("");
      setLangs("");
    }
  }, [open]);
  const run = useAiMutation(
    () =>
      aiPost<EvalRun>("/evals/run", {
        label: label.trim() || undefined,
        model_id: modelId || undefined,
        languages: langs.split(",").map((x) => x.trim()).filter(Boolean),
      }),
    { onSuccess: (r) => { onClose(); void r; }, success: (r) => t("ev.ranDone", { acc: `${Math.round(r.accuracy * 100)}%` }) },
  );
  return (
    <Dialog open={open} onClose={onClose} title={t("ev.runTitle")} footer={
      <>
        <Button variant="outline" onClick={onClose}>{t("g.cancel")}</Button>
        <Button onClick={() => run.mutate(undefined)} disabled={run.isPending}>
          {run.isPending ? <Busy label={t("ev.running")} /> : t("ev.run")}
        </Button>
      </>
    }>
      <div className="space-y-4" aria-live="polite">
        <Field label={t("ev.label")} htmlFor="er-label">
          <Input id="er-label" value={label} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        <Field label={t("ev.target")} htmlFor="er-model">
          <Select id="er-model" value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">{t("ev.currentRoute")}</option>
            {models.data?.map((m) => <option key={m.id} value={m.id}>{m.provider_name ? `${m.provider_name} / ` : ""}{m.model_name}</option>)}
          </Select>
        </Field>
        <Field label={t("ev.languagesOnly")} htmlFor="er-langs">
          <Input id="er-langs" value={langs} onChange={(e) => setLangs(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

function RunDetail({ run, onClose }: { run: EvalRun | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const detail = useAi<EvalRun & { results: EvalResultRow[] }>(run ? `/evals/runs/${run.id}` : null);
  return (
    <Dialog open={!!run} onClose={onClose} title={`${t("ev.detail")}: ${run?.label ?? ""}`} size="xl" footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      <QueryState isLoading={detail.isLoading} error={detail.error}>
        <DataTableLite head={[t("ev.language"), t("ev.text"), t("ev.expected"), t("ev.got"), t("g.status"), t("g.latency")]}>
          {detail.data?.results.map((r) => (
            <tr key={r.case_id} className="align-top">
              <td className="px-4 py-2">{r.language}</td>
              <td className="max-w-xs px-4 py-2">{r.text}</td>
              <td className="px-4 py-2 font-mono text-xs">{JSON.stringify(r.expected)}</td>
              <td className="px-4 py-2 font-mono text-xs">{r.error ?? JSON.stringify(r.got)}</td>
              <td className="px-4 py-2"><Badge tone={r.correct ? "success" : "danger"}>{r.correct ? t("ev.pass") : t("ev.fail")}</Badge></td>
              <td className="px-4 py-2">{r.latency_ms} ms</td>
            </tr>
          ))}
        </DataTableLite>
      </QueryState>
    </Dialog>
  );
}

function CompareDialog({ ids, onClose }: { ids: string[] | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const cmp = useAi<EvalCompare>(ids ? `/evals/compare${qs({ ids: ids.join(",") })}` : null);
  const runs = cmp.data?.runs ?? [];
  const deltas = compareDeltas(runs);
  const chart = languageChartData(runs);
  const names = runs.map((r) => r.label || r.id.slice(0, 6));
  const signed = (n: number, f: (v: number) => string) => `${n > 0 ? "+" : ""}${f(n)}`;
  return (
    <Dialog open={!!ids} onClose={onClose} title={t("ev.compareTitle")} size="xl" footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      <QueryState isLoading={cmp.isLoading} error={cmp.error}>
        <div className="space-y-6">
          <DataTableLite caption={t("ev.compareTitle")} head={["", t("ev.accuracy"), t("ev.avgLatency"), t("g.cost"), t("ev.deltaVsFirst")]}>
            {runs.map((r, i) => (
              <tr key={r.id}>
                <td className="px-4 py-2 font-medium">{names[i]}</td>
                <td className="px-4 py-2">{Math.round(r.accuracy * 100)}% <span className="text-xs text-muted">({t("ev.correct", { c: r.correct, t: r.total })})</span></td>
                <td className="px-4 py-2">{r.avg_latency_ms} ms</td>
                <td className="px-4 py-2">{formatMoney(r.total_cost)}</td>
                <td className="px-4 py-2 text-xs">
                  {i === 0 ? "—" : `${signed(Math.round(deltas[i].accuracy * 100), (v) => `${v}`)} pp · ${signed(deltas[i].avg_latency_ms, (v) => `${v}`)} ms · ${signed(deltas[i].total_cost, (v) => v.toFixed(4))} $`}
                </td>
              </tr>
            ))}
          </DataTableLite>
          <div>
            <h3 className="mb-2 text-sm font-medium">{t("ev.byLanguage")}</h3>
            <div className="h-64 w-full" role="img" aria-label={t("ev.byLanguage")}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chart}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="language" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Legend />
                  {names.map((n, i) => <Bar key={n} dataKey={n} fill={PALETTE[i % PALETTE.length]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <DataTableLite caption={t("ev.byLanguage")} head={[t("ev.language"), ...names]}>
              {chart.map((row) => (
                <tr key={String(row.language)}>
                  <td className="px-4 py-2">{row.language}</td>
                  {names.map((n) => <td key={n} className="px-4 py-2">{row[n]}%</td>)}
                </tr>
              ))}
            </DataTableLite>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-medium">{t("ev.differing")} ({cmp.data ? disagreementCount(cmp.data) : 0})</h3>
            {cmp.data && cmp.data.differences.length === 0 ? (
              <p className="text-sm text-muted">{t("ev.noDiffering")}</p>
            ) : (
              <DataTableLite head={[t("ev.language"), t("ev.text"), t("ev.expected"), ...names]}>
                {cmp.data?.differences.map((d) => (
                  <tr key={d.case_id} className="align-top">
                    <td className="px-4 py-2">{d.language}</td>
                    <td className="max-w-xs px-4 py-2">{d.text}</td>
                    <td className="px-4 py-2 font-mono text-xs">{JSON.stringify(d.expected)}</td>
                    {runs.map((r) => {
                      const res = d.results.find((x) => x.run_id === r.id);
                      return (
                        <td key={r.id} className="px-4 py-2">
                          <Badge tone={res?.correct ? "success" : "danger"}>{res?.correct ? t("ev.pass") : t("ev.fail")}</Badge>
                          <p className="mt-1 font-mono text-xs">{JSON.stringify(res?.got)}</p>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </DataTableLite>
            )}
          </div>
        </div>
      </QueryState>
    </Dialog>
  );
}

export default function EvalsPage() {
  const t = useTranslations("ai");
  const [view, setView] = React.useState<"cases" | "runs">("cases");
  const [langFilter, setLangFilter] = React.useState("");
  const cases = useAi<EvalCase[]>(`/evals/cases${qs({ language: langFilter })}`);
  const runs = useAi<EvalRun[]>("/evals/runs");
  const [editing, setEditing] = React.useState<EvalCase | null>(null);
  const [caseOpen, setCaseOpen] = React.useState(false);
  const [runOpen, setRunOpen] = React.useState(false);
  const [selected, setSelected] = React.useState<string[]>([]);
  const [compare, setCompare] = React.useState<string[] | null>(null);
  const [detail, setDetail] = React.useState<EvalRun | null>(null);
  const [deleting, setDeleting] = React.useState<EvalCase | null>(null);

  const seed = useAiMutation(() => aiPost<{ added: number }>("/evals/seed-golden"), { success: (r) => t("ev.seeded", { n: r.added }) });
  const review = useAiMutation((c: EvalCase) => aiPatch(`/evals/cases/${c.id}`, { reviewed: true }));
  const del = useAiMutation((c: EvalCase) => aiDelete(`/evals/cases/${c.id}`), { success: t("g.deleted"), onSuccess: () => setDeleting(null) });

  return (
    <>
      <SectionHeader
        title={t("ev.title")}
        description={t("ev.description")}
        actions={
          <>
            <Button variant="outline" onClick={() => seed.mutate(undefined)} disabled={seed.isPending}>{t("ev.seed")}</Button>
            <Button onClick={() => setRunOpen(true)}>{t("ev.run")}</Button>
          </>
        }
      />
      <div role="tablist" aria-label={t("ev.title")} className="mb-4 flex gap-1">
        {(["cases", "runs"] as const).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={cn("rounded-md px-4 py-2 text-sm", view === v ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-accent-soft")}
          >
            {t(v === "cases" ? "ev.cases" : "ev.runs")}
          </button>
        ))}
      </div>

      {view === "cases" ? (
        <>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div className="w-48">
              <Field label={t("ev.language")} htmlFor="ev-lang">
                <Select id="ev-lang" value={langFilter} onChange={(e) => setLangFilter(e.target.value)}>
                  <option value="">{t("g.all")}</option>
                  {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                </Select>
              </Field>
            </div>
            <Button variant="outline" onClick={() => { setEditing(null); setCaseOpen(true); }}>
              <Plus className="size-4" aria-hidden="true" />
              {t("ev.addCase")}
            </Button>
          </div>
          <QueryState isLoading={cases.isLoading} error={cases.error} empty={cases.data?.length === 0} onRetry={() => cases.refetch()}>
            <DataTableLite caption={t("ev.cases")} head={[t("ev.language"), t("ev.text"), t("ev.intent"), t("ev.source"), t("g.status"), t("g.actions")]}>
              {cases.data?.map((c) => (
                <tr key={c.id} className="align-top">
                  <td className="px-4 py-3 font-mono">{c.language}</td>
                  <td className="max-w-md px-4 py-3">{c.text}</td>
                  <td className="px-4 py-3 text-xs">
                    <p className="font-mono">{c.expected.intent}</p>
                    <p className="text-muted">
                      {c.expected.delay_minutes != null ? `${c.expected.delay_minutes} min` : ""} {c.expected.eta_time ?? ""}
                    </p>
                  </td>
                  <td className="px-4 py-3">{c.source}</td>
                  <td className="px-4 py-3">
                    {c.reviewed ? <Badge tone="success">{t("ev.reviewed")}</Badge> : <Badge tone="warning">{t("ev.needsReview")}</Badge>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {!c.reviewed && <Button size="sm" variant="outline" onClick={() => review.mutate(c)}>{t("ev.markReviewed")}</Button>}
                      <Button size="sm" variant="ghost" onClick={() => { setEditing(c); setCaseOpen(true); }}>{t("g.edit")}</Button>
                      <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(c)}>{t("g.delete")}</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </DataTableLite>
          </QueryState>
        </>
      ) : (
        <>
          <div className="mb-4 flex items-center gap-3">
            <Button variant="outline" disabled={selected.length < 2} onClick={() => setCompare(selected)}>{t("ev.compare")}</Button>
            {selected.length < 2 && <p className="text-xs text-muted">{t("ev.compareNeeds")}</p>}
          </div>
          <QueryState isLoading={runs.isLoading} error={runs.error} empty={runs.data?.length === 0} onRetry={() => runs.refetch()}>
            <DataTableLite caption={t("ev.runs")} head={["", t("ev.label"), t("g.status"), t("ev.accuracy"), t("ev.avgLatency"), t("g.cost"), t("pm.language"), ""]}>
              {runs.data?.map((r) => (
                <tr key={r.id} className="align-top">
                  <td className="px-4 py-3">
                    <Checkbox label={<span className="sr-only">{r.label}</span>} checked={selected.includes(r.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, r.id] : selected.filter((x) => x !== r.id))} />
                  </td>
                  <td className="px-4 py-3"><p className="font-medium">{r.label}</p><p className="text-xs text-muted">{formatDateTime(r.created_at)}</p></td>
                  <td className="px-4 py-3">{r.status}</td>
                  <td className="px-4 py-3">{Math.round(r.accuracy * 100)}% <span className="text-xs text-muted">({t("ev.correct", { c: r.correct, t: r.total })})</span></td>
                  <td className="px-4 py-3">{r.avg_latency_ms} ms</td>
                  <td className="px-4 py-3">{formatMoney(r.total_cost)}</td>
                  <td className="px-4 py-3 text-xs">{Object.entries(r.by_language).map(([l, a]) => `${l} ${Math.round(a * 100)}%`).join(" · ")}</td>
                  <td className="px-4 py-3"><Button size="sm" variant="ghost" onClick={() => setDetail(r)}>{t("ev.detail")}</Button></td>
                </tr>
              ))}
            </DataTableLite>
          </QueryState>
        </>
      )}
      <CaseDialog item={editing} open={caseOpen} onClose={() => setCaseOpen(false)} />
      <RunDialog open={runOpen} onClose={() => { setRunOpen(false); setView("runs"); }} />
      <RunDetail run={detail} onClose={() => setDetail(null)} />
      <CompareDialog ids={compare} onClose={() => setCompare(null)} />
      <ConfirmDialog open={!!deleting} onClose={() => setDeleting(null)} onConfirm={() => deleting && del.mutate(deleting)} title={t("ev.deleteTitle")} message={deleting?.text ?? ""} confirmLabel={t("g.delete")} destructive pending={del.isPending} />
    </>
  );
}

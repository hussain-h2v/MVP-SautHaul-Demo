"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Busy, QueryState, RunResultView, SectionHeader, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { toast } from "sonner";
import { AI_TASKS, templateVariables } from "@/lib/ai";
import { aiPatch, aiPost, qs, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiModel, AiPrompt, DiffChange, RunResult } from "@/lib/ai-types";
import { formatDateTime, LANGUAGES } from "@/lib/format";

const statusTone = { draft: "warning", active: "success", archived: "neutral" } as const;

function EditorDialog({ task, language, prompt, open, onClose }: { task: string; language: string; prompt: AiPrompt | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("ai");
  const [template, setTemplate] = React.useState("");
  const [notes, setNotes] = React.useState("");
  React.useEffect(() => {
    if (open) {
      setTemplate(prompt?.template ?? "");
      setNotes(prompt?.notes ?? "");
    }
  }, [open, prompt]);
  const vars = templateVariables(template);
  const save = useAiMutation(
    () => (prompt ? aiPatch(`/prompts/${prompt.id}`, { template, notes }) : aiPost("/prompts", { task, language, template, notes })),
    { success: prompt ? t("g.saved") : t("pm.created"), onSuccess: onClose },
  );
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={prompt ? `${t("pm.edit")} (${t("pm.version", { v: prompt.version })})` : t("pm.new")}
      size="xl"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!template.trim() || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("pm.template")} htmlFor="pm-tpl" hint={t("pm.templateHint")}>
          <Textarea id="pm-tpl" className="min-h-64 font-mono text-xs" value={template} onChange={(e) => setTemplate(e.target.value)} />
        </Field>
        <p className="text-xs text-muted" aria-live="polite">
          {vars.length ? t("pm.variables", { list: vars.map((v) => `{{${v}}}`).join(", ") }) : t("pm.noVariables")}
        </p>
        <Field label={t("pm.notes")} htmlFor="pm-notes">
          <Input id="pm-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

function DiffDialog({ a, b, onClose }: { a: AiPrompt | null; b: AiPrompt | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const diff = useAi<{ unified: string; changes: DiffChange[] }>(a && b ? `/prompts/diff${qs({ a: a.id, b: b.id })}` : null);
  return (
    <Dialog open={!!a && !!b} onClose={onClose} title={t("pm.diffTitle", { a: a?.version ?? 0, b: b?.version ?? 0 })} size="xl" footer={<Button variant="outline" onClick={onClose}>{t("g.close")}</Button>}>
      <QueryState isLoading={diff.isLoading} error={diff.error}>
        {diff.data && diff.data.changes.every((c) => c.type === "same") ? (
          <p className="text-sm text-muted">{t("pm.noDiff")}</p>
        ) : (
          <pre className="overflow-auto rounded-md border border-border text-xs leading-relaxed" aria-label={t("pm.diff")}>
            {diff.data?.changes.map((c, i) => (
              <div
                key={i}
                className={
                  c.type === "add"
                    ? "bg-accent-soft px-3 text-success"
                    : c.type === "del"
                      ? "bg-danger/10 px-3 text-danger"
                      : "px-3 text-muted"
                }
              >
                <span aria-hidden="true">{c.type === "add" ? "+ " : c.type === "del" ? "- " : "  "}</span>
                <span className="sr-only">{c.type === "add" ? t("pm.added") : c.type === "del" ? t("pm.removed") : ""}</span>
                {c.text}
              </div>
            ))}
          </pre>
        )}
      </QueryState>
    </Dialog>
  );
}

function Playground({ task, language, prompt, open, onClose }: { task: string; language: string; prompt: AiPrompt | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("ai");
  const models = useAi<AiModel[]>("/models");
  const [sample, setSample] = React.useState(t("ov.sampleMessage"));
  const [vars, setVars] = React.useState("{}");
  const [modelId, setModelId] = React.useState("");
  const [result, setResult] = React.useState<RunResult | null>(null);
  React.useEffect(() => {
    if (open) setResult(null);
  }, [open]);
  let varsError = false;
  let parsedVars: unknown = {};
  try {
    parsedVars = JSON.parse(vars || "{}");
  } catch {
    varsError = true;
  }
  const run = useAiMutation(
    () => aiPost<RunResult>("/prompts/test", { prompt_id: prompt?.id, variables: parsedVars, task, language, model_id: modelId || undefined, sample_message: sample }),
    { onSuccess: setResult },
  );
  return (
    <Dialog open={open} onClose={onClose} title={t("pm.playground")} size="lg" footer={
      <>
        <Button variant="outline" onClick={onClose}>{t("g.close")}</Button>
        <Button onClick={() => run.mutate(undefined)} disabled={run.isPending || varsError || !sample.trim()}>
          {run.isPending ? <Busy label={t("g.loading")} /> : t("g.run")}
        </Button>
      </>
    }>
      <div className="space-y-4">
        <Field label={t("pm.sample")} htmlFor="pg-sample">
          <Textarea id="pg-sample" value={sample} onChange={(e) => setSample(e.target.value)} />
        </Field>
        <Field label={t("pm.vars")} htmlFor="pg-vars" error={varsError ? t("pm.varsInvalid") : undefined}>
          <Textarea id="pg-vars" className="font-mono text-xs" aria-invalid={varsError} value={vars} onChange={(e) => setVars(e.target.value)} />
        </Field>
        <Field label={t("rt.model")} htmlFor="pg-model">
          <Select id="pg-model" value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">{t("ev.currentRoute")}</option>
            {models.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.provider_name ? `${m.provider_name} / ` : ""}
                {m.model_name}
              </option>
            ))}
          </Select>
        </Field>
        {result && <RunResultView result={result} />}
      </div>
    </Dialog>
  );
}

export default function PromptsPage() {
  const t = useTranslations("ai");
  const taskLabel = useEnum("task");
  const [task, setTask] = React.useState<string>("intent_classify");
  const [language, setLanguage] = React.useState("en");
  const list = useAi<AiPrompt[]>(`/prompts${qs({ task, language })}`);
  const [editing, setEditing] = React.useState<AiPrompt | null>(null);
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [diff, setDiff] = React.useState<{ a: AiPrompt; b: AiPrompt } | null>(null);
  const [play, setPlay] = React.useState<AiPrompt | null | "none">(null);

  const prompts = [...(list.data ?? [])].sort((x, y) => y.version - x.version);
  const active = prompts.find((p) => p.status === "active") ?? null;
  const activate = useAiMutation((p: AiPrompt) => aiPost(`/prompts/${p.id}/activate`), { success: t("pm.activated") });
  const archive = useAiMutation((p: AiPrompt) => aiPost(`/prompts/${p.id}/archive`), { success: t("pm.archived") });
  const rollback = useAiMutation((p: AiPrompt) => aiPost(`/prompts/${p.task}/${p.language}/rollback`, { version: p.version }), {
    onSuccess: (_, p) => toast.success(t("pm.rolledBack", { v: p.version })),
  });

  return (
    <>
      <SectionHeader
        title={t("pm.title")}
        description={t("pm.description")}
        actions={
          <>
            <Button variant="outline" onClick={() => setPlay("none")}>
              {t("pm.playground")}
            </Button>
            <Button onClick={() => { setEditing(null); setEditorOpen(true); }}>
              <Plus className="size-4" aria-hidden="true" />
              {t("pm.new")}
            </Button>
          </>
        }
      />
      <div className="mb-5 grid max-w-xl gap-4 sm:grid-cols-2">
        <Field label={t("ov.task")} htmlFor="pm-task">
          <Select id="pm-task" value={task} onChange={(e) => setTask(e.target.value)}>
            {AI_TASKS.map((x) => (
              <option key={x} value={x}>
                {taskLabel(x)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("pm.language")} htmlFor="pm-lang">
          <Select id="pm-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <QueryState isLoading={list.isLoading} error={list.error} onRetry={() => list.refetch()}>
        {prompts.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-4 py-8 text-center text-sm text-muted">{t("pm.noPrompts")}</p>
        ) : (
          <ul className="space-y-3">
            {prompts.map((p) => (
              <li key={p.id}>
                <Card className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium">{t("pm.version", { v: p.version })}</h3>
                      <Badge tone={statusTone[p.status]}>{t(`pm.status.${p.status}`)}</Badge>
                      <span className="text-xs text-muted">{formatDateTime(p.created_at)}</span>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {p.status === "draft" && (
                        <Button size="sm" variant="outline" onClick={() => { setEditing(p); setEditorOpen(true); }}>
                          {t("g.edit")}
                        </Button>
                      )}
                      {p.status !== "active" && active && (
                        <Button size="sm" variant="outline" onClick={() => setDiff({ a: p, b: active })}>
                          {t("pm.diff")}
                        </Button>
                      )}
                      {p.status === "draft" && (
                        <Button size="sm" onClick={() => activate.mutate(p)} disabled={activate.isPending}>
                          {t("pm.activate")}
                        </Button>
                      )}
                      {p.status === "archived" && (
                        <Button size="sm" onClick={() => rollback.mutate(p)} disabled={rollback.isPending}>
                          {t("pm.rollback")}
                        </Button>
                      )}
                      {p.status !== "archived" && (
                        <Button size="sm" variant="ghost" onClick={() => archive.mutate(p)}>
                          {t("pm.archive")}
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" onClick={() => setPlay(p)}>
                        {t("g.test")}
                      </Button>
                    </div>
                  </div>
                  {p.notes && <p className="text-sm text-muted">{p.notes}</p>}
                  <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 font-mono text-xs">{p.template}</pre>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      <EditorDialog task={task} language={language} prompt={editing} open={editorOpen} onClose={() => setEditorOpen(false)} />
      <DiffDialog a={diff?.a ?? null} b={diff?.b ?? null} onClose={() => setDiff(null)} />
      <Playground task={task} language={language} prompt={play === "none" ? null : play} open={play !== null} onClose={() => setPlay(null)} />
    </>
  );
}

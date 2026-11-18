"use client";

import { Languages, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { SectionHeader, Switch } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { QueryState, StatusBadge } from "@/components/wa/common";
import { bodyVariables, catalogueLanguages, MAX_BUTTONS, renderPreview, validateButtons, validateTemplateVars } from "@/lib/wa";
import { waPatch, waPost, useWa, useWaMutation } from "@/lib/wa-api";
import type { ApprovalStatus, WaButton, WaTemplate } from "@/lib/wa-types";
import { cn } from "@/lib/utils";

const STATUSES: ApprovalStatus[] = ["draft", "submitted", "approved", "rejected"];
const CATEGORIES = ["UTILITY", "AUTHENTICATION", "MARKETING"];

function EditDialog({ tpl, open, onClose }: { tpl: WaTemplate | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("wa");
  const [body, setBody] = React.useState("");
  const [status, setStatus] = React.useState<ApprovalStatus>("draft");
  const [review, setReview] = React.useState(false);
  const [buttons, setButtons] = React.useState<WaButton[]>([]);
  React.useEffect(() => {
    if (!open || !tpl) return;
    setBody(tpl.body);
    setStatus(tpl.approval_status);
    setReview(tpl.needs_native_review);
    setButtons(tpl.buttons ?? []);
  }, [open, tpl]);
  const check = tpl ? validateTemplateVars(body, tpl.variables) : { ok: true, unused: [], unknown: [] };
  const btnErr = validateButtons(buttons);
  const save = useWaMutation(
    () => waPatch(`/templates/${tpl!.id}`, { body, approval_status: status, needs_native_review: review, buttons }),
    { success: t("g.saved"), onSuccess: onClose },
  );
  const setBtn = (i: number, patch: Partial<WaButton>) => setButtons((bs) => bs.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const errText = btnErr === "tooMany" ? t("tp.btnTooMany") : btnErr === "empty" ? t("tp.btnEmpty") : btnErr === "tooLong" ? t("tp.btnTooLong") : btnErr === "duplicate" ? t("tp.btnDuplicate") : null;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="xl"
      title={tpl ? `${t("tp.edit")}: ${tpl.name} (${tpl.language})` : t("tp.edit")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!tpl || !check.ok || !!btnErr || !body.trim() || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      {tpl && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <Field label={t("tp.body")} htmlFor="tp-body">
              <Textarea id="tp-body" rows={7} value={body} onChange={(e) => setBody(e.target.value)} aria-describedby="tp-vars" />
            </Field>
            <div id="tp-vars" aria-live="polite" className="space-y-1 text-sm">
              <p className="font-medium">{t("tp.variables")}</p>
              <ul className="flex flex-wrap gap-1.5">
                {tpl.variables.map((v) => (
                  <li key={v}>
                    <Badge tone={check.unused.includes(v) ? "warning" : "neutral"} className="font-mono">{`{{${v}}}`}</Badge>
                  </li>
                ))}
              </ul>
              {check.ok ? <p className="text-success">{t("tp.varsOk")}</p> : null}
              {check.unused.length > 0 && (
                <p role="alert" className="text-danger">
                  {t("tp.varsUnused", { names: check.unused.map((n) => `{{${n}}}`).join(", ") })}
                </p>
              )}
              {check.unknown.length > 0 && (
                <p role="alert" className="text-danger">
                  {t("tp.varsUnknown", { names: check.unknown.map((n) => `{{${n}}}`).join(", ") })}
                </p>
              )}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("tp.approval")} htmlFor="tp-approval">
                <Select id="tp-approval" value={status} onChange={(e) => setStatus(e.target.value as ApprovalStatus)}>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {t(`approval.${s}`)}
                    </option>
                  ))}
                </Select>
              </Field>
              <div className="space-y-1.5">
                <p className="text-sm font-medium">{t("tp.review")}</p>
                <div className="flex items-center gap-2">
                  <Switch checked={review} onChange={setReview} label={t("tp.review")} />
                  <span className="text-sm text-muted">{review ? t("tp.flagged") : t("tp.reviewed")}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="space-y-4">
            <section aria-labelledby="tp-preview">
              <h3 id="tp-preview" className="text-sm font-medium">
                {t("tp.preview")}
              </h3>
              <div className="mt-2 rounded-2xl rounded-tl-sm border border-border bg-background px-4 py-3 text-sm shadow-sm">
                <p className="whitespace-pre-wrap">{renderPreview(body)}</p>
                {buttons.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
                    {buttons.map((b, i) => (
                      <span key={i} className="rounded-full border border-accent px-3 py-1 text-xs font-medium text-accent">
                        {b.title || "…"}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <p className="mt-1 text-xs text-muted">{t("tp.previewHint")}</p>
            </section>
            <section aria-labelledby="tp-buttons">
              <div className="flex items-center justify-between">
                <h3 id="tp-buttons" className="text-sm font-medium">
                  {t("tp.buttons")}
                </h3>
                <Button size="sm" variant="outline" disabled={buttons.length >= MAX_BUTTONS} onClick={() => setButtons((bs) => [...bs, { id: "", title: "" }])}>
                  <Plus className="size-3.5" aria-hidden="true" />
                  {t("tp.addButton")}
                </Button>
              </div>
              <ul className="mt-2 space-y-2">
                {buttons.map((b, i) => (
                  <li key={i} className="flex items-end gap-2">
                    <Field label={t("tp.buttonId")} htmlFor={`tp-bid-${i}`} className="flex-1">
                      <Input id={`tp-bid-${i}`} value={b.id} onChange={(e) => setBtn(i, { id: e.target.value })} className="font-mono" />
                    </Field>
                    <Field label={`${t("tp.buttonTitle")} (${b.title.length}/20)`} htmlFor={`tp-bt-${i}`} className="flex-1">
                      <Input id={`tp-bt-${i}`} value={b.title} onChange={(e) => setBtn(i, { title: e.target.value })} aria-invalid={b.title.length > 20} />
                    </Field>
                    <Button variant="ghost" size="icon" aria-label={t("tp.removeButton")} onClick={() => setButtons((bs) => bs.filter((_, j) => j !== i))}>
                      <Trash2 className="size-4" aria-hidden="true" />
                    </Button>
                  </li>
                ))}
              </ul>
              {errText && (
                <p role="alert" className="mt-2 text-xs text-danger">
                  {errText}
                </p>
              )}
            </section>
          </div>
        </div>
      )}
    </Dialog>
  );
}

function CreateDialog({ open, onClose, languages }: { open: boolean; onClose: () => void; languages: string[] }) {
  const t = useTranslations("wa");
  const [name, setName] = React.useState("");
  const [language, setLanguage] = React.useState("en");
  const [category, setCategory] = React.useState("UTILITY");
  const [vars, setVars] = React.useState("");
  const [body, setBody] = React.useState("");
  React.useEffect(() => {
    if (open) {
      setName("");
      setLanguage("en");
      setCategory("UTILITY");
      setVars("");
      setBody("");
    }
  }, [open]);
  const declared = vars.split(",").map((v) => v.trim()).filter(Boolean);
  const check = validateTemplateVars(body, declared);
  const nameOk = /^[a-z][a-z0-9_]*$/.test(name);
  const save = useWaMutation(() => waPost("/templates", { name, language, category, body, variables: declared }), { success: t("tp.created"), onSuccess: onClose });
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("tp.add")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!nameOk || !body.trim() || !check.ok || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("tp.name")} htmlFor="tpn-name" hint={t("tp.nameHint")}>
          <Input id="tpn-name" value={name} onChange={(e) => setName(e.target.value)} className="font-mono" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("tp.language")} htmlFor="tpn-lang">
            <Select id="tpn-lang" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {languages.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("tp.category")} htmlFor="tpn-cat">
            <Select id="tpn-cat" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label={t("tp.declare")} htmlFor="tpn-vars">
          <Input id="tpn-vars" value={vars} onChange={(e) => setVars(e.target.value)} placeholder="slot_code, dock_code, start" className="font-mono" />
        </Field>
        <Field label={t("tp.body")} htmlFor="tpn-body">
          <Textarea id="tpn-body" rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
        </Field>
        <div aria-live="polite" className="text-sm">
          {bodyVariables(body).length > 0 && check.unknown.length > 0 && (
            <p role="alert" className="text-danger">
              {t("tp.varsUnknown", { names: check.unknown.map((n) => `{{${n}}}`).join(", ") })}
            </p>
          )}
          {check.unused.length > 0 && body && (
            <p role="alert" className="text-danger">
              {t("tp.varsUnused", { names: check.unused.map((n) => `{{${n}}}`).join(", ") })}
            </p>
          )}
        </div>
        {body && <p className="whitespace-pre-wrap rounded-md border border-border bg-background px-3 py-2 text-sm">{renderPreview(body)}</p>}
      </div>
    </Dialog>
  );
}

export default function TemplatesPage() {
  const t = useTranslations("wa");
  const q = useWa<WaTemplate[]>("/templates");
  const [editing, setEditing] = React.useState<WaTemplate | null>(null);
  const [creating, setCreating] = React.useState(false);
  const list = q.data ?? [];
  const langs = catalogueLanguages(list.map((x) => x.language));
  const names = [...new Set(list.map((x) => x.name))].sort();
  const cell = (name: string, lang: string) => list.find((x) => x.name === name && x.language === lang);
  const review = useWaMutation((id: string) => waPatch(`/templates/${id}`, { needs_native_review: false }), { success: t("g.saved") });
  const needReview = list.filter((x) => x.needs_native_review).length;
  return (
    <>
      <SectionHeader
        title={t("tp.title")}
        description={t("tp.description")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" aria-hidden="true" />
            {t("tp.add")}
          </Button>
        }
      />
      {needReview > 0 && (
        <div role="note" className="mb-4 flex items-start gap-2 rounded-md border border-amber-400 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          <Languages className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>
            <strong>{needReview}</strong> · {t("tp.review")}. {t("tp.reviewNote")}
          </p>
        </div>
      )}
      <QueryState isLoading={q.isLoading} error={q.error} empty={!list.length} onRetry={() => q.refetch()}>
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("tp.grid")}</caption>
            <thead className="border-b border-border bg-background text-xs uppercase tracking-wide text-muted">
              <tr>
                <th scope="col" className="px-4 py-2.5 font-medium">
                  {t("tp.name")}
                </th>
                {langs.map((l) => (
                  <th key={l} scope="col" className="px-4 py-2.5 font-medium">
                    {l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {names.map((name) => (
                <tr key={name}>
                  <th scope="row" className="whitespace-nowrap px-4 py-3 font-mono text-xs font-medium">
                    {name}
                  </th>
                  {langs.map((l) => {
                    const c = cell(name, l);
                    return (
                      <td key={l} className="px-4 py-3 align-top">
                        {c ? (
                          <div className="space-y-1.5">
                            <button
                              type="button"
                              onClick={() => setEditing(c)}
                              className={cn("block max-w-xs rounded-md text-left underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent")}
                              aria-label={`${t("tp.edit")}: ${name} (${l})`}
                            >
                              <span className="line-clamp-2 text-xs text-muted">{c.body}</span>
                            </button>
                            <div className="flex flex-wrap items-center gap-1.5">
                              <StatusBadge status={c.approval_status} kind="approval" />
                              {c.needs_native_review && (
                                <Badge tone="warning" className="gap-1">
                                  <Languages className="size-3" aria-hidden="true" />
                                  {t("tp.flagged")}
                                </Badge>
                              )}
                            </div>
                            {c.needs_native_review && (
                              <Button size="sm" variant="outline" onClick={() => review.mutate(c.id)} disabled={review.isPending}>
                                {t("tp.markReviewed")}
                              </Button>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-muted">{t("tp.missing")}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </QueryState>
      <EditDialog tpl={editing} open={!!editing} onClose={() => setEditing(null)} />
      <CreateDialog open={creating} onClose={() => setCreating(false)} languages={langs} />
    </>
  );
}

"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Busy, DataTableLite, QueryState, SectionHeader, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { CAPABILITIES, formatMoney } from "@/lib/ai";
import { aiDelete, aiPatch, aiPost, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiModel, AiProvider, Capability } from "@/lib/ai-types";

function ModelDialog({ model, open, onClose, providers }: { model: AiModel | null; open: boolean; onClose: () => void; providers: AiProvider[] }) {
  const t = useTranslations("ai");
  const cap = useEnum("cap");
  const [provider, setProvider] = React.useState("");
  const [name, setName] = React.useState("");
  const [caps, setCaps] = React.useState<Capability[]>(["chat"]);
  const [ctx, setCtx] = React.useState("");
  const [pin, setPin] = React.useState("0");
  const [pout, setPout] = React.useState("0");
  React.useEffect(() => {
    if (!open) return;
    setProvider(model?.provider_id ?? providers[0]?.id ?? "");
    setName(model?.model_name ?? "");
    setCaps(model?.capabilities ?? ["chat"]);
    setCtx(model?.context_window?.toString() ?? "");
    setPin(model?.input_price?.toString() ?? "0");
    setPout(model?.output_price?.toString() ?? "0");
  }, [open, model, providers]);
  const save = useAiMutation(
    () => {
      const body = { model_name: name.trim(), capabilities: caps, context_window: ctx ? Number(ctx) : null, input_price: Number(pin) || 0, output_price: Number(pout) || 0 };
      return model ? aiPatch(`/models/${model.id}`, body) : aiPost("/models", { provider_id: provider, ...body });
    },
    { success: t("g.saved"), onSuccess: onClose },
  );
  const toggleCap = (c: Capability) => setCaps(caps.includes(c) ? caps.filter((x) => x !== c) : [...caps, c]);
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={model ? t("md.edit") : t("md.add")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={() => save.mutate(undefined)} disabled={!name.trim() || !provider || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!model && (
          <Field label={t("ky.provider")} htmlFor="md-prov">
            <Select id="md-prov" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label={t("md.name")} htmlFor="md-name">
          <Input id="md-name" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">{t("md.capabilities")}</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {CAPABILITIES.map((c) => (
              <Checkbox key={c} label={cap(c)} checked={caps.includes(c)} onChange={() => toggleCap(c)} />
            ))}
          </div>
        </fieldset>
        <Field label={t("md.context")} htmlFor="md-ctx">
          <Input id="md-ctx" type="number" min={1} value={ctx} onChange={(e) => setCtx(e.target.value)} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("md.inPrice")} htmlFor="md-pin">
            <Input id="md-pin" type="number" min={0} step="0.0001" value={pin} onChange={(e) => setPin(e.target.value)} />
          </Field>
          <Field label={t("md.outPrice")} htmlFor="md-pout">
            <Input id="md-pout" type="number" min={0} step="0.0001" value={pout} onChange={(e) => setPout(e.target.value)} />
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

interface TestOut {
  text: string | null;
  latency_ms: number;
  tokens_in: number;
  tokens_out: number;
  cost: number;
  error: string | null;
}

function TestDialog({ model, onClose }: { model: AiModel | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const [prompt, setPrompt] = React.useState(t("md.samplePrompt"));
  const [out, setOut] = React.useState<TestOut | null>(null);
  React.useEffect(() => setOut(null), [model]);
  const run = useAiMutation(() => aiPost<TestOut>(`/models/${model!.id}/test`, { prompt }), { onSuccess: setOut });
  return (
    <Dialog
      open={!!model}
      onClose={onClose}
      title={t("md.testTitle", { name: model?.model_name ?? "" })}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.close")}
          </Button>
          <Button onClick={() => run.mutate(undefined)} disabled={run.isPending || !prompt.trim()}>
            {run.isPending ? <Busy label={t("g.loading")} /> : t("g.run")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("md.prompt")} htmlFor="md-test">
          <Textarea id="md-test" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        </Field>
        <div aria-live="polite">
          {out &&
            (out.error ? (
              <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {out.error}
              </p>
            ) : (
              <div className="space-y-2">
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-background p-3 text-sm">{out.text}</pre>
                <p className="text-xs text-muted">{t("md.testResult", { ms: out.latency_ms, tin: out.tokens_in, tout: out.tokens_out, cost: formatMoney(out.cost) })}</p>
              </div>
            ))}
        </div>
      </div>
    </Dialog>
  );
}

export default function ModelsPage() {
  const t = useTranslations("ai");
  const cap = useEnum("cap");
  const [providerFilter, setProviderFilter] = React.useState("");
  const providers = useAi<AiProvider[]>("/providers");
  const models = useAi<AiModel[]>(`/models${providerFilter ? `?provider_id=${providerFilter}` : ""}`);
  const [editing, setEditing] = React.useState<AiModel | null>(null);
  const [open, setOpen] = React.useState(false);
  const [testing, setTesting] = React.useState<AiModel | null>(null);
  const [deleting, setDeleting] = React.useState<AiModel | null>(null);
  const del = useAiMutation((m: AiModel) => aiDelete(`/models/${m.id}`), { success: t("g.deleted"), onSuccess: () => setDeleting(null) });
  const byId = new Map((providers.data ?? []).map((p) => [p.id, p.name]));

  return (
    <>
      <SectionHeader
        title={t("md.title")}
        description={t("md.description")}
        actions={
          <Button
            disabled={!providers.data?.length}
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden="true" />
            {t("md.add")}
          </Button>
        }
      />
      {providers.data && providers.data.length === 0 && <p className="mb-4 text-sm text-muted">{t("md.noProvider")}</p>}
      <div className="mb-4 max-w-xs">
        <Field label={t("ky.provider")} htmlFor="md-filter">
          <Select id="md-filter" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
            <option value="">{t("g.all")}</option>
            {providers.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <QueryState isLoading={models.isLoading} error={models.error} empty={models.data?.length === 0} onRetry={() => models.refetch()}>
        <DataTableLite caption={t("md.title")} head={[t("md.name"), t("ky.provider"), t("md.capabilities"), t("md.context"), t("md.inPrice"), t("md.outPrice"), t("g.actions")]}>
          {models.data?.map((m) => (
            <tr key={m.id} className="align-top">
              <td className="px-4 py-3 font-medium">{m.model_name}</td>
              <td className="px-4 py-3">{m.provider_name ?? byId.get(m.provider_id) ?? "—"}</td>
              <td className="px-4 py-3">
                <div className="flex max-w-xs flex-wrap gap-1">
                  {m.capabilities.map((c) => (
                    <Badge key={c}>{cap(c)}</Badge>
                  ))}
                </div>
              </td>
              <td className="px-4 py-3">{m.context_window ?? "—"}</td>
              <td className="px-4 py-3">{formatMoney(m.input_price)}</td>
              <td className="px-4 py-3">{formatMoney(m.output_price)}</td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => setTesting(m)}>
                    {t("g.test")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setEditing(m);
                      setOpen(true);
                    }}
                  >
                    {t("g.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(m)}>
                    {t("g.delete")}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </DataTableLite>
      </QueryState>
      <ModelDialog model={editing} open={open} onClose={() => setOpen(false)} providers={providers.data ?? []} />
      <TestDialog model={testing} onClose={() => setTesting(null)} />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && del.mutate(deleting)}
        title={t("md.deleteTitle")}
        message={deleting ? t("md.deleteMsg", { name: deleting.model_name }) : ""}
        confirmLabel={t("g.delete")}
        destructive
        pending={del.isPending}
      />
    </>
  );
}

"use client";

import { KeyRound, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { DataTableLite, QueryState, SectionHeader } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { formatMoney } from "@/lib/ai";
import { aiDelete, aiPatch, aiPost, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiKey, AiProvider } from "@/lib/ai-types";
import { formatDateTime } from "@/lib/format";

/** The secret lives only in this input's state, is cleared the moment it is submitted, and is never persisted. */
function KeyDialog({ keyRow, open, onClose, providers }: { keyRow: AiKey | null; open: boolean; onClose: () => void; providers: AiProvider[] }) {
  const t = useTranslations("ai");
  const [provider, setProvider] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [budget, setBudget] = React.useState("");
  const [weight, setWeight] = React.useState("1");
  React.useEffect(() => {
    if (!open) return;
    setSecret("");
    setProvider(keyRow?.provider_id ?? providers[0]?.id ?? "");
    setLabel(keyRow?.label ?? "");
    setBudget(keyRow?.monthly_budget?.toString() ?? "");
    setWeight(keyRow?.weight?.toString() ?? "1");
  }, [open, keyRow, providers]);
  const save = useAiMutation(
    (apiKey: string) => {
      const common = { label: label.trim(), monthly_budget: budget ? Number(budget) : null, weight: Number(weight) || 1 };
      return keyRow ? aiPatch(`/keys/${keyRow.id}`, common) : aiPost("/keys", { provider_id: provider, api_key: apiKey, ...common });
    },
    { success: t("g.saved"), onSuccess: onClose },
  );
  const submit = () => {
    const value = secret;
    setSecret("");
    save.mutate(value);
  };
  const invalid = !label.trim() || (!keyRow && (!provider || secret.length < 8));
  return (
    <Dialog
      open={open}
      onClose={() => {
        setSecret("");
        onClose();
      }}
      title={keyRow ? t("ky.edit") : t("ky.add")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={submit} disabled={invalid || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <form
        autoComplete="off"
        onSubmit={(e) => {
          e.preventDefault();
          if (!invalid) submit();
        }}
        className="space-y-4"
      >
        {!keyRow && (
          <Field label={t("ky.provider")} htmlFor="ky-prov">
            <Select id="ky-prov" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        <Field label={t("ky.label")} htmlFor="ky-label">
          <Input id="ky-label" value={label} onChange={(e) => setLabel(e.target.value)} />
        </Field>
        {!keyRow && (
          <Field label={t("ky.apiKey")} htmlFor="ky-secret" hint={t("ky.apiKeyHint")}>
            <Input id="ky-secret" type="password" autoComplete="new-password" spellCheck={false} value={secret} onChange={(e) => setSecret(e.target.value)} />
          </Field>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("ky.budget")} htmlFor="ky-budget">
            <Input id="ky-budget" type="number" min={0} step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} />
          </Field>
          <Field label={t("ky.weight")} htmlFor="ky-weight" hint={t("ky.weightHint")}>
            <Input id="ky-weight" type="number" min={1} value={weight} onChange={(e) => setWeight(e.target.value)} />
          </Field>
        </div>
      </form>
    </Dialog>
  );
}

function RotateDialog({ keyRow, onClose }: { keyRow: AiKey | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const [secret, setSecret] = React.useState("");
  React.useEffect(() => setSecret(""), [keyRow]);
  const rotate = useAiMutation((apiKey: string) => aiPost(`/keys/${keyRow!.id}/rotate`, { api_key: apiKey }), {
    success: t("g.saved"),
    onSuccess: onClose,
  });
  const submit = () => {
    const value = secret;
    setSecret("");
    rotate.mutate(value);
  };
  return (
    <Dialog
      open={!!keyRow}
      onClose={() => {
        setSecret("");
        onClose();
      }}
      title={t("ky.rotateTitle")}
      description={keyRow ? t("ky.masked", { last4: keyRow.key_last4 }) : undefined}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={submit} disabled={secret.length < 8 || rotate.isPending}>
            {t("ky.rotate")}
          </Button>
        </>
      }
    >
      <Field label={t("ky.apiKey")} htmlFor="ky-rot" hint={t("ky.apiKeyHint")}>
        <Input id="ky-rot" type="password" autoComplete="new-password" spellCheck={false} value={secret} onChange={(e) => setSecret(e.target.value)} />
      </Field>
    </Dialog>
  );
}

export default function KeysPage() {
  const t = useTranslations("ai");
  const [providerFilter, setProviderFilter] = React.useState("");
  const providers = useAi<AiProvider[]>("/providers");
  const keys = useAi<AiKey[]>(`/keys${providerFilter ? `?provider_id=${providerFilter}` : ""}`);
  const [editing, setEditing] = React.useState<AiKey | null>(null);
  const [open, setOpen] = React.useState(false);
  const [rotating, setRotating] = React.useState<AiKey | null>(null);
  const [deleting, setDeleting] = React.useState<AiKey | null>(null);

  const toggle = useAiMutation((k: AiKey) => aiPatch(`/keys/${k.id}`, { status: k.status === "active" ? "disabled" : "active" }));
  const del = useAiMutation((k: AiKey) => aiDelete(`/keys/${k.id}`), { success: t("g.deleted"), onSuccess: () => setDeleting(null) });
  const statusTone = { active: "success", disabled: "neutral", failed: "danger" } as const;

  return (
    <>
      <SectionHeader
        title={t("ky.title")}
        description={t("ky.description")}
        actions={
          <Button
            disabled={!providers.data?.length}
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden="true" />
            {t("ky.add")}
          </Button>
        }
      />
      <div className="mb-4 max-w-xs">
        <Field label={t("ky.provider")} htmlFor="ky-filter">
          <Select id="ky-filter" value={providerFilter} onChange={(e) => setProviderFilter(e.target.value)}>
            <option value="">{t("g.all")}</option>
            {providers.data?.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <QueryState isLoading={keys.isLoading} error={keys.error} empty={keys.data?.length === 0} onRetry={() => keys.refetch()}>
        <DataTableLite
          caption={t("ky.title")}
          head={[t("ky.label"), t("ky.provider"), t("g.status"), t("ky.lastUsed"), t("ky.spend"), t("ky.reqs"), t("ky.weight"), t("g.actions")]}
        >
          {keys.data?.map((k) => {
            const near = k.monthly_budget ? k.month_spend >= k.monthly_budget * 0.8 : false;
            return (
              <tr key={k.id} className="align-top">
                <td className="px-4 py-3">
                  <p className="flex items-center gap-1.5 font-medium">
                    <KeyRound className="size-4 text-muted" aria-hidden="true" />
                    {k.label}
                  </p>
                  <p className="font-mono text-xs text-muted" aria-label={t("ky.masked", { last4: k.key_last4 })}>
                    ••••{k.key_last4}
                  </p>
                  {k.last_error && <p className="max-w-xs text-xs text-danger">{k.last_error}</p>}
                </td>
                <td className="px-4 py-3">{k.provider_name}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-col items-start gap-1">
                    <Badge tone={statusTone[k.status]}>{t(`ky.status.${k.status}`)}</Badge>
                    {near && <Badge tone="warning">{t("ky.nearBudget")}</Badge>}
                  </div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-muted">{k.last_used_at ? formatDateTime(k.last_used_at) : t("g.never")}</td>
                <td className="px-4 py-3 whitespace-nowrap">
                  {formatMoney(k.month_spend)}
                  {k.monthly_budget ? <span className="text-muted"> / {formatMoney(k.monthly_budget)}</span> : null}
                </td>
                <td className="px-4 py-3">{k.month_requests}</td>
                <td className="px-4 py-3">{k.weight}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => toggle.mutate(k)}>
                      {k.status === "active" ? t("ky.disable") : t("ky.enable")}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setRotating(k)}>
                      {t("ky.rotate")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setEditing(k);
                        setOpen(true);
                      }}
                    >
                      {t("g.edit")}
                    </Button>
                    <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(k)}>
                      {t("g.delete")}
                    </Button>
                  </div>
                </td>
              </tr>
            );
          })}
        </DataTableLite>
      </QueryState>
      <KeyDialog keyRow={editing} open={open} onClose={() => setOpen(false)} providers={providers.data ?? []} />
      <RotateDialog keyRow={rotating} onClose={() => setRotating(null)} />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && del.mutate(deleting)}
        title={t("ky.deleteTitle")}
        message={deleting ? t("ky.deleteMsg", { label: deleting.label, last4: deleting.key_last4 }) : ""}
        confirmLabel={t("g.delete")}
        destructive
        pending={del.isPending}
      />
    </>
  );
}

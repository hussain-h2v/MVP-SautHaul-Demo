"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { BreakerBadge, Busy, DataTableLite, QueryState, SectionHeader, Switch, useEnum } from "@/components/ai/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Field, FormError, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { ERROR_CODES, PROVIDER_KINDS } from "@/lib/ai";
import { aiDelete, aiPatch, aiPost, useAi, useAiMutation } from "@/lib/ai-api";
import type { AiProvider, ProviderKind } from "@/lib/ai-types";
import { formatDateTime } from "@/lib/format";

interface Draft {
  name: string;
  kind: ProviderKind;
  base_url: string;
  rate_limit_rpm: string;
  allow_pii: boolean;
  notes: string;
}

const blank: Draft = { name: "", kind: "openai_compatible", base_url: "", rate_limit_rpm: "", allow_pii: false, notes: "" };

function ProviderDialog({ provider, open, onClose }: { provider: AiProvider | null; open: boolean; onClose: () => void }) {
  const t = useTranslations("ai");
  const kind = useEnum("kind");
  const [d, setD] = React.useState<Draft>(blank);
  React.useEffect(() => {
    if (open)
      setD(
        provider
          ? { name: provider.name, kind: provider.kind, base_url: provider.base_url ?? "", rate_limit_rpm: provider.rate_limit_rpm?.toString() ?? "", allow_pii: provider.allow_pii, notes: provider.notes ?? "" }
          : blank,
      );
  }, [open, provider]);
  const save = useAiMutation(
    () => {
      const body = {
        name: d.name.trim(),
        kind: d.kind,
        base_url: d.base_url.trim() || null,
        rate_limit_rpm: d.rate_limit_rpm ? Number(d.rate_limit_rpm) : null,
        allow_pii: d.allow_pii,
        notes: d.notes.trim() || null,
      };
      return provider ? aiPatch(`/providers/${provider.id}`, body) : aiPost("/providers", body);
    },
    { success: t("g.saved"), onSuccess: onClose },
  );
  const invalid = !d.name.trim() || (d.rate_limit_rpm !== "" && !(Number(d.rate_limit_rpm) > 0));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={provider ? t("pr.edit") : t("pr.add")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("g.cancel")}
          </Button>
          <Button onClick={() => save.mutate(undefined)} disabled={invalid || save.isPending}>
            {t("g.save")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <FormError message={null} />
        <Field label={t("g.name")} htmlFor="pv-name">
          <Input id="pv-name" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} />
        </Field>
        <Field label={t("pr.kind")} htmlFor="pv-kind">
          <Select id="pv-kind" value={d.kind} onChange={(e) => setD({ ...d, kind: e.target.value as ProviderKind })}>
            {PROVIDER_KINDS.map((k) => (
              <option key={k} value={k}>
                {kind(k)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("pr.baseUrl")} htmlFor="pv-url" hint={t("pr.baseUrlHint")}>
          <Input id="pv-url" inputMode="url" value={d.base_url} onChange={(e) => setD({ ...d, base_url: e.target.value })} />
        </Field>
        <Field label={t("pr.rpm")} htmlFor="pv-rpm" hint={t("pr.rpmHint")}>
          <Input id="pv-rpm" type="number" min={1} value={d.rate_limit_rpm} onChange={(e) => setD({ ...d, rate_limit_rpm: e.target.value })} />
        </Field>
        <div className="rounded-md border border-amber-400/60 bg-amber-50 p-3 dark:bg-amber-950/30">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor="pv-pii" className="text-sm font-medium">
              {t("pr.allowPii")}
            </label>
            <Switch id="pv-pii" checked={d.allow_pii} onChange={(v) => setD({ ...d, allow_pii: v })} label={t("pr.allowPii")} />
          </div>
          <p className="mt-2 text-xs text-muted">{t("pr.allowPiiWarn")}</p>
        </div>
        <Field label={t("pr.notes")} htmlFor="pv-notes">
          <Textarea id="pv-notes" value={d.notes} onChange={(e) => setD({ ...d, notes: e.target.value })} />
        </Field>
      </div>
    </Dialog>
  );
}

function SimulateDialog({ provider, onClose }: { provider: AiProvider | null; onClose: () => void }) {
  const t = useTranslations("ai");
  const err = useEnum("err");
  const [code, setCode] = React.useState<string>("timeout");
  const [seconds, setSeconds] = React.useState("60");
  const go = useAiMutation(() => aiPost(`/providers/${provider!.id}/simulate-failure`, { error_code: code, seconds: Number(seconds) }), {
    success: t("pr.simulating", { s: seconds }),
    onSuccess: onClose,
  });
  const clear = useAiMutation(() => aiDelete(`/providers/${provider!.id}/simulate-failure`), { success: t("g.saved"), onSuccess: onClose });
  return (
    <Dialog
      open={!!provider}
      onClose={onClose}
      title={t("pr.simulate")}
      description={t("pr.simulateHint")}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={() => clear.mutate(undefined)} disabled={clear.isPending}>
            {t("pr.clearSim")}
          </Button>
          <Button onClick={() => go.mutate(undefined)} disabled={go.isPending || !(Number(seconds) > 0)}>
            {t("pr.simulate")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("pr.errorCode")} htmlFor="sim-code">
          <Select id="sim-code" value={code} onChange={(e) => setCode(e.target.value)}>
            {ERROR_CODES.map((c) => (
              <option key={c} value={c}>
                {err(c)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("pr.seconds")} htmlFor="sim-sec">
          <Input id="sim-sec" type="number" min={1} max={600} value={seconds} onChange={(e) => setSeconds(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

export default function ProvidersPage() {
  const t = useTranslations("ai");
  const kind = useEnum("kind");
  const providers = useAi<AiProvider[]>("/providers");
  const [editing, setEditing] = React.useState<AiProvider | null>(null);
  const [open, setOpen] = React.useState(false);
  const [simulating, setSimulating] = React.useState<AiProvider | null>(null);
  const [deleting, setDeleting] = React.useState<AiProvider | null>(null);
  const [status, setStatus] = React.useState<string>("");

  const toggle = useAiMutation((p: AiProvider) => aiPatch(`/providers/${p.id}`, { status: p.status === "enabled" ? "disabled" : "enabled" }));
  const test = useAiMutation(
    (p: AiProvider) => aiPost<{ ok: boolean; latency_ms: number; model: string; error: string | null }>(`/providers/${p.id}/test`),
    {
      onSuccess: (r) =>
        r.ok ? toast.success(t("pr.testOk", { ms: r.latency_ms, model: r.model })) : toast.error(t("pr.testFail", { error: r.error ?? "?" })),
    },
  );
  const load = useAiMutation((p: AiProvider) => aiPost<{ added: string[] }>(`/providers/${p.id}/load-models`), {
    success: (r) => t("pr.loaded", { n: r.added.length }),
  });
  const del = useAiMutation((p: AiProvider) => aiDelete(`/providers/${p.id}`), { success: t("g.deleted"), onSuccess: () => setDeleting(null) });

  return (
    <>
      <SectionHeader
        title={t("pr.title")}
        description={t("pr.description")}
        actions={
          <Button
            onClick={() => {
              setEditing(null);
              setOpen(true);
            }}
          >
            <Plus className="size-4" aria-hidden="true" />
            {t("pr.add")}
          </Button>
        }
      />
      <div aria-live="polite" className="sr-only">
        {status}
      </div>
      <QueryState isLoading={providers.isLoading} error={providers.error} empty={providers.data?.length === 0} onRetry={() => providers.refetch()}>
        <DataTableLite
          caption={t("pr.title")}
          head={[t("g.name"), t("pr.kind"), t("g.status"), t("pr.keys"), t("pr.models"), t("pr.allowPii"), t("pr.lastChecked"), t("g.actions")]}
        >
          {providers.data?.map((p) => (
            <tr key={p.id} className="align-top">
              <td className="px-4 py-3">
                <p className="font-medium">{p.name}</p>
                {p.last_error && <p className="max-w-xs text-xs text-danger">{p.last_error}</p>}
              </td>
              <td className="px-4 py-3">{kind(p.kind)}</td>
              <td className="px-4 py-3">
                <div className="flex flex-col items-start gap-1.5">
                  <Switch
                    checked={p.status === "enabled"}
                    label={t("pr.toggle", { name: p.name })}
                    onChange={() => {
                      toggle.mutate(p);
                      setStatus(`${p.name}: ${p.status === "enabled" ? t("g.disabled") : t("g.enabled")}`);
                    }}
                  />
                  <BreakerBadge state={p.breaker} />
                </div>
              </td>
              <td className="px-4 py-3">{p.key_count}</td>
              <td className="px-4 py-3">{p.model_count}</td>
              <td className="px-4 py-3">
                <Badge tone={p.allow_pii ? "warning" : "neutral"}>{p.allow_pii ? t("g.yes") : t("sf.piiMasked")}</Badge>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-muted">{p.last_checked_at ? formatDateTime(p.last_checked_at) : t("g.never")}</td>
              <td className="px-4 py-3">
                <div className="flex flex-wrap gap-1.5">
                  <Button size="sm" variant="outline" onClick={() => test.mutate(p)} disabled={test.isPending && test.variables?.id === p.id}>
                    {test.isPending && test.variables?.id === p.id ? <Busy label={t("g.loading")} /> : t("pr.testConn")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => load.mutate(p)} disabled={load.isPending && load.variables?.id === p.id}>
                    {t("pr.loadModels")}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setSimulating(p)}>
                    {t("pr.simulate")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setEditing(p);
                      setOpen(true);
                    }}
                  >
                    {t("g.edit")}
                  </Button>
                  <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(p)}>
                    {t("g.delete")}
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </DataTableLite>
      </QueryState>
      <ProviderDialog provider={editing} open={open} onClose={() => setOpen(false)} />
      <SimulateDialog provider={simulating} onClose={() => setSimulating(null)} />
      <ConfirmDialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && del.mutate(deleting)}
        title={t("pr.deleteTitle")}
        message={deleting ? t("pr.deleteMsg", { name: deleting.name }) : ""}
        confirmLabel={t("g.delete")}
        destructive
        pending={del.isPending}
      />
    </>
  );
}

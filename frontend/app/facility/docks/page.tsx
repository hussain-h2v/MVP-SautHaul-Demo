"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ActiveBadge, YesNo } from "@/components/admin/badges";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { RequireFacility } from "@/components/facility/facility-context";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/card";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { apiErrorText, qs, useCap, useFacMutation, useFacQuery } from "@/lib/fac";
import type { Dock, FacilitySummary, VehicleType } from "@/lib/facility-types";

const DOCK_TYPES = ["STANDARD", "REEFER", "HEAVY"] as const;
const DOCK_STATUSES = ["ACTIVE", "MAINTENANCE", "OUT_OF_SERVICE", "INACTIVE"] as const;

const schema = z.object({
  dock_code: z.string().trim().min(1, "required").max(16),
  dock_type: z.enum(DOCK_TYPES),
  supports_refrigerated: z.boolean(),
  max_vehicle_weight_kg: z.number({ error: "required" }).int("int").min(1, "min"),
  dock_status: z.enum(DOCK_STATUSES),
  compatible_vehicle_type_codes: z.array(z.string()),
  notes: z.string().optional(),
});
type Values = z.infer<typeof schema>;

function DockDialog({ facility, dock, onClose }: { facility: FacilitySummary; dock?: Dock | "new"; onClose: () => void }) {
  const t = useTranslations("facility.docks");
  const f = useTranslations("facility");
  const c = useTranslations("common");
  const existing = dock && dock !== "new" ? dock : undefined;
  const [err, setErr] = React.useState<string | null>(null);
  const types = useFacQuery<VehicleType[]>("/vehicle-types");
  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: existing
      ? { ...existing, notes: existing.notes ?? "" }
      : { dock_type: "STANDARD", supports_refrigerated: false, max_vehicle_weight_kg: 30000, dock_status: "ACTIVE", compatible_vehicle_type_codes: [], notes: "" },
  });
  const selected = watch("compatible_vehicle_type_codes");
  const save = useFacMutation(
    (v: Values) =>
      existing
        ? api<Dock>(`/docks/${existing.id}`, { method: "PATCH", body: { ...v, notes: v.notes || null } })
        : api<Dock>("/docks", { method: "POST", body: { facility_id: facility.id, ...v, notes: v.notes || null } }),
    { success: existing ? t("updated") : t("created"), onSuccess: onClose, onError: (e) => setErr(apiErrorText(e)) },
  );

  return (
    <Dialog
      open={!!dock}
      onClose={onClose}
      title={existing ? t("edit") : t("new")}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button type="submit" form="dock-form" disabled={save.isPending}>
            {c("save")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <form id="dock-form" onSubmit={handleSubmit((v) => save.mutate(v))} className="grid gap-4 sm:grid-cols-2" noValidate>
        <Field label={t("code")} htmlFor="dock_code" error={errors.dock_code?.message}>
          <Input id="dock_code" {...register("dock_code")} aria-invalid={!!errors.dock_code} />
        </Field>
        <Field label={t("type")} htmlFor="dock_type">
          <Select id="dock_type" {...register("dock_type")}>
            {DOCK_TYPES.map((d) => (
              <option key={d} value={d}>
                {f(`dockType.${d}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("maxWeight")} htmlFor="max_vehicle_weight_kg" error={errors.max_vehicle_weight_kg?.message}>
          <Input id="max_vehicle_weight_kg" type="number" {...register("max_vehicle_weight_kg", { valueAsNumber: true })} aria-invalid={!!errors.max_vehicle_weight_kg} />
        </Field>
        <Field label={c("status")} htmlFor="dock_status">
          <Select id="dock_status" {...register("dock_status")}>
            {DOCK_STATUSES.map((d) => (
              <option key={d} value={d}>
                {f(`dockStatus.${d}`)}
              </option>
            ))}
          </Select>
        </Field>
        <Checkbox label={t("refrigerated")} className="sm:col-span-2" {...register("supports_refrigerated")} />
        <fieldset className="sm:col-span-2">
          <legend className="mb-2 text-sm font-medium">{t("vehicleTypes")}</legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {(types.data ?? []).map((vt) => (
              <Checkbox
                key={vt.code}
                label={`${vt.code} — ${vt.description}`}
                checked={selected.includes(vt.code)}
                onChange={(e) =>
                  setValue(
                    "compatible_vehicle_type_codes",
                    e.target.checked ? [...selected, vt.code] : selected.filter((x) => x !== vt.code),
                  )
                }
              />
            ))}
          </div>
        </fieldset>
        <Field label={t("notes")} htmlFor="notes" className="sm:col-span-2">
          <Textarea id="notes" {...register("notes")} />
        </Field>
      </form>
    </Dialog>
  );
}

function DocksView({ facility }: { facility: FacilitySummary }) {
  const t = useTranslations("facility.docks");
  const f = useTranslations("facility");
  const c = useTranslations("common");
  const canWrite = useCap("docks_slots_rules") === "W";
  const q = useFacQuery<Dock[]>(`/docks${qs({ facility_id: facility.id })}`);
  const [editing, setEditing] = React.useState<Dock | "new" | undefined>();
  const [retiring, setRetiring] = React.useState<Dock | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const retire = useFacMutation((d: Dock) => api<void>(`/docks/${d.id}`, { method: "DELETE" }), {
    success: t("retired"),
    onSuccess: () => setRetiring(null),
    onError: (e) => {
      setRetiring(null);
      setErr(apiErrorText(e));
    },
  });
  const docks = q.data ?? [];

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canWrite && (
            <Button onClick={() => setEditing("new")}>
              <Plus className="size-4" aria-hidden="true" />
              {t("new")}
            </Button>
          )
        }
      />
      <FormError message={err} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={docks.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border">
              {[t("code"), t("type"), c("status"), t("maxWeight"), t("refrigerated"), t("vehicleTypes"), canWrite ? c("actions") : ""].map((h, i) => (
                <th key={i} scope="col" className={th}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {docks.map((d) => (
              <tr key={d.id} className="border-b border-border last:border-b-0">
                <td className={`${td} font-medium`}>
                  {d.dock_code}
                  <span className="block text-xs font-normal text-muted">{d.code}</span>
                </td>
                <td className={td}>
                  <Badge tone={d.dock_type === "REEFER" ? "accent" : d.dock_type === "HEAVY" ? "warning" : "neutral"}>{f(`dockType.${d.dock_type}`)}</Badge>
                </td>
                <td className={td}>
                  {d.dock_status === "ACTIVE" ? <ActiveBadge active /> : <Badge tone="danger">{f(`dockStatus.${d.dock_status}`)}</Badge>}
                </td>
                <td className={td}>{d.max_vehicle_weight_kg.toLocaleString()} kg</td>
                <td className={td}>
                  <YesNo value={d.supports_refrigerated} />
                </td>
                <td className={td}>{d.compatible_vehicle_type_codes.join(", ") || "—"}</td>
                {canWrite && (
                  <td className={td}>
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setEditing(d)}>
                        {c("edit")}
                      </Button>
                      {d.dock_status !== "INACTIVE" && (
                        <Button size="sm" variant="ghost" onClick={() => { setErr(null); setRetiring(d); }}>
                          {t("retire")}
                        </Button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>
      {editing && <DockDialog key={editing === "new" ? "new" : editing.id} facility={facility} dock={editing} onClose={() => setEditing(undefined)} />}
      <ConfirmDialog
        open={!!retiring}
        onClose={() => setRetiring(null)}
        title={t("retireTitle")}
        message={t("retireMessage", { dock: retiring?.dock_code ?? "" })}
        confirmLabel={t("retire")}
        destructive
        pending={retire.isPending}
        onConfirm={() => retiring && retire.mutate(retiring)}
      />
    </>
  );
}

export default function DocksPage() {
  return <RequireFacility>{(f) => <DocksView key={f.id} facility={f} />}</RequireFacility>;
}

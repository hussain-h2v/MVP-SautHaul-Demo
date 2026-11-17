"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { VehicleType } from "@/lib/admin-types";
import type { VehicleRow } from "@/lib/carrier-types";
import { errorMessage, useApiMutation, useOptions } from "@/lib/use-api";

export const vehicleSchema = z.object({
  vehicle_type_code: z.string().min(1, "required"),
  registration_number: z.string().trim().min(4, "min4").max(32),
  capacity_kg: z.coerce.number({ error: "int" }).int("int").min(1, "min"),
  refrigeration_capable: z.boolean(),
  heavy_capable: z.boolean(),
});
export type VehicleValues = z.infer<typeof vehicleSchema>;

export function VehicleFormDialog({ open, onClose, vehicle }: { open: boolean; onClose: () => void; vehicle?: VehicleRow }) {
  const t = useTranslations("carrier.vehicles");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const types = useOptions<VehicleType[]>("/vehicle-types");
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<z.input<typeof vehicleSchema>, unknown, VehicleValues>({
    resolver: zodResolver(vehicleSchema),
    defaultValues: vehicle
      ? {
          vehicle_type_code: vehicle.vehicle_type_code,
          registration_number: vehicle.registration_number,
          capacity_kg: vehicle.capacity_kg,
          refrigeration_capable: vehicle.refrigeration_capable,
          heavy_capable: vehicle.heavy_capable,
        }
      : { vehicle_type_code: "", registration_number: "", capacity_kg: 10000, refrigeration_capable: false, heavy_capable: false },
  });
  const save = useApiMutation(
    (v: VehicleValues) =>
      vehicle
        ? api<VehicleRow>(`/vehicles/${vehicle.id}`, { method: "PATCH", body: v })
        : api<VehicleRow>("/vehicles", { method: "POST", body: v }),
    { success: vehicle ? t("updated") : t("created"), onSuccess: onClose },
  );
  const formId = "vehicle-form";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={vehicle ? t("edit") : t("new")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={save.isPending}>
            {save.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {c("save")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <form
        id={formId}
        noValidate
        className="space-y-4"
        onSubmit={handleSubmit((v) => {
          setErr(null);
          save.mutate(v, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
        })}
      >
        <Field label={t("registration")} htmlFor="veh-reg" error={errors.registration_number?.message}>
          <Input id="veh-reg" autoComplete="off" className="uppercase" aria-invalid={!!errors.registration_number} {...register("registration_number")} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("type")} htmlFor="veh-type" error={errors.vehicle_type_code?.message}>
            <Select id="veh-type" aria-invalid={!!errors.vehicle_type_code} {...register("vehicle_type_code")}>
              <option value="">{t("chooseType")}</option>
              {types.data?.map((vt) => (
                <option key={vt.code} value={vt.code}>
                  {vt.code} · {vt.description}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("capacity")} htmlFor="veh-cap" error={errors.capacity_kg?.message}>
            <Input id="veh-cap" type="number" min={1} inputMode="numeric" aria-invalid={!!errors.capacity_kg} {...register("capacity_kg")} />
          </Field>
        </div>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("capabilities")}</legend>
          <Checkbox label={t("reefer")} {...register("refrigeration_capable")} />
          <Checkbox label={t("heavy")} {...register("heavy_capable")} />
          <p className="text-xs text-muted">{t("capabilitiesHint")}</p>
        </fieldset>
      </form>
    </Dialog>
  );
}

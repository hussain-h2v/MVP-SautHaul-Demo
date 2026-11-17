"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Carrier, VehicleType } from "@/lib/admin-types";
import { errorMessage, useApiMutation, useOptions } from "@/lib/use-api";

const schema = z.object({
  code: z.string().trim().min(1, "required").max(32),
  carrier_name: z.string().trim().min(1, "required"),
  contact_email: z.string().trim().email("email").or(z.literal("")),
  contact_phone: z.string().trim().optional(),
});
type Values = z.infer<typeof schema>;

export function CarrierFormDialog({ open, onClose, carrier }: { open: boolean; onClose: () => void; carrier?: Carrier }) {
  const t = useTranslations("admin.carriers");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const [allowed, setAllowed] = React.useState<string[]>(carrier?.allowed_vehicle_type_codes ?? []);
  const types = useOptions<VehicleType[]>("/vehicle-types");
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: carrier
      ? { code: carrier.code, carrier_name: carrier.carrier_name, contact_email: carrier.contact_email ?? "", contact_phone: carrier.contact_phone ?? "" }
      : { code: "", carrier_name: "", contact_email: "", contact_phone: "" },
  });
  const save = useApiMutation(
    (v: Values) => {
      const body = { ...v, contact_email: v.contact_email || null, contact_phone: v.contact_phone || null, allowed_vehicle_type_codes: allowed };
      if (carrier) {
        const { code, ...rest } = body;
        void code;
        return api<Carrier>(`/carriers/${carrier.id}`, { method: "PATCH", body: rest });
      }
      return api<Carrier>("/carriers", { method: "POST", body });
    },
    { success: carrier ? t("updated") : t("created"), onSuccess: onClose },
  );
  const formId = "carrier-form";
  const toggle = (code: string) => setAllowed((a) => (a.includes(code) ? a.filter((x) => x !== code) : [...a, code]));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={carrier ? t("edit") : t("new")}
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
        <Field label={t("code")} htmlFor="car-code" error={errors.code?.message}>
          <Input id="car-code" disabled={!!carrier} aria-invalid={!!errors.code} {...register("code")} />
        </Field>
        <Field label={t("name")} htmlFor="car-name" error={errors.carrier_name?.message}>
          <Input id="car-name" aria-invalid={!!errors.carrier_name} {...register("carrier_name")} />
        </Field>
        <Field label={t("email")} htmlFor="car-email" error={errors.contact_email?.message}>
          <Input id="car-email" type="email" aria-invalid={!!errors.contact_email} {...register("contact_email")} />
        </Field>
        <Field label={t("phone")} htmlFor="car-phone">
          <Input id="car-phone" type="tel" {...register("contact_phone")} />
        </Field>
        <fieldset>
          <legend className="text-sm font-medium">{t("allowedTypes")}</legend>
          <p className="mb-2 text-xs text-muted">{t("allowedTypesHint")}</p>
          {types.isLoading && <p className="text-sm text-muted">{c("loading")}</p>}
          <div className="grid gap-2 sm:grid-cols-2">
            {types.data?.map((vt) => (
              <Checkbox
                key={vt.code}
                label={`${vt.code} · ${vt.description}`}
                checked={allowed.includes(vt.code)}
                onChange={() => toggle(vt.code)}
              />
            ))}
          </div>
        </fieldset>
      </form>
    </Dialog>
  );
}

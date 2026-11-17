"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Carrier, Facility, Page, Shipment } from "@/lib/admin-types";
import { errorMessage, useApiMutation, useOptions } from "@/lib/use-api";

export const DOCK_TYPES = ["ANY", "STANDARD", "REEFER", "HEAVY"] as const;
export const PRIORITIES = ["LOW", "NORMAL", "HIGH", "CRITICAL"] as const;
export const STATUSES = ["PLANNED", "ASSIGNED", "IN_TRANSIT", "AT_GATE", "WAITING", "IN_DOCK", "COMPLETED", "CANCELLED"] as const;
export const OFFER_STATUSES = ["draft", "offered", "accepted", "declined"] as const;

const schema = z.object({
  order_reference: z.string().trim().min(1, "required"),
  destination_facility_id: z.string().min(1, "required"),
  customer_name: z.string().trim().min(1, "required"),
  origin_name: z.string().trim().min(1, "required"),
  origin_city: z.string().trim().min(1, "required"),
  product_category: z.string().trim().min(1, "required"),
  load_weight_kg: z.number({ error: "required" }).int("int").min(1, "min"),
  pallet_count: z.string().regex(/^\d*$/, "int"),
  required_dock_type: z.enum(DOCK_TYPES),
  temperature_control_required: z.boolean(),
  priority_code: z.enum(PRIORITIES),
  expected_unload_min: z.number({ error: "required" }).int("int").min(1, "min"),
  requested_date: z.string().optional(),
});
type Values = z.infer<typeof schema>;

export function ShipmentFormDialog({ open, onClose, shipment }: { open: boolean; onClose: () => void; shipment?: Shipment }) {
  const t = useTranslations("admin.shipments");
  const d = useTranslations("enums.dock");
  const p = useTranslations("enums.priority");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const facilities = useOptions<Page<Facility>>("/facilities?limit=200");
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: shipment
      ? {
          order_reference: shipment.order_reference,
          destination_facility_id: shipment.destination_facility_id,
          customer_name: shipment.customer_name,
          origin_name: shipment.origin_name,
          origin_city: shipment.origin_city,
          product_category: shipment.product_category,
          load_weight_kg: shipment.load_weight_kg,
          pallet_count: shipment.pallet_count?.toString() ?? "",
          required_dock_type: shipment.required_dock_type,
          temperature_control_required: shipment.temperature_control_required,
          priority_code: shipment.priority_code,
          expected_unload_min: shipment.expected_unload_min,
          requested_date: shipment.requested_date ?? "",
        }
      : {
          order_reference: "",
          destination_facility_id: "",
          customer_name: "",
          origin_name: "",
          origin_city: "",
          product_category: "",
          pallet_count: "",
          required_dock_type: "ANY",
          temperature_control_required: false,
          priority_code: "NORMAL",
          expected_unload_min: 60,
          requested_date: "",
        },
  });
  const save = useApiMutation(
    (v: Values) => {
      const body = { ...v, pallet_count: v.pallet_count === "" ? null : Number(v.pallet_count), requested_date: v.requested_date || null };
      return shipment
        ? api<Shipment>(`/shipments/${shipment.id}`, { method: "PATCH", body })
        : api<Shipment>("/shipments", { method: "POST", body });
    },
    { success: shipment ? t("updated") : t("created"), onSuccess: onClose },
  );
  const formId = "shipment-form";
  const err2 = (k: keyof Values) => errors[k]?.message as string | undefined;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={shipment ? t("edit") : t("new")}
      size="xl"
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
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        onSubmit={handleSubmit((v) => {
          setErr(null);
          save.mutate(v, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
        })}
      >
        <Field label={t("orderRef")} htmlFor="s-order" error={err2("order_reference")}>
          <Input id="s-order" aria-invalid={!!errors.order_reference} {...register("order_reference")} />
        </Field>
        <Field label={t("facility")} htmlFor="s-fac" error={err2("destination_facility_id")} className="lg:col-span-2">
          <Select id="s-fac" aria-invalid={!!errors.destination_facility_id} {...register("destination_facility_id")}>
            <option value="">{t("chooseFacility")}</option>
            {facilities.data?.items.map((f) => (
              <option key={f.id} value={f.id}>
                {f.code} · {f.facility_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("customer")} htmlFor="s-cust" error={err2("customer_name")}>
          <Input id="s-cust" aria-invalid={!!errors.customer_name} {...register("customer_name")} />
        </Field>
        <Field label={t("originName")} htmlFor="s-oname" error={err2("origin_name")}>
          <Input id="s-oname" aria-invalid={!!errors.origin_name} {...register("origin_name")} />
        </Field>
        <Field label={t("originCity")} htmlFor="s-ocity" error={err2("origin_city")}>
          <Input id="s-ocity" aria-invalid={!!errors.origin_city} {...register("origin_city")} />
        </Field>
        <Field label={t("goods")} htmlFor="s-goods" error={err2("product_category")}>
          <Input id="s-goods" aria-invalid={!!errors.product_category} {...register("product_category")} />
        </Field>
        <Field label={t("weight")} htmlFor="s-weight" error={err2("load_weight_kg")}>
          <Input id="s-weight" type="number" aria-invalid={!!errors.load_weight_kg} {...register("load_weight_kg", { valueAsNumber: true })} />
        </Field>
        <Field label={t("pallets")} htmlFor="s-pallets" error={err2("pallet_count")}>
          <Input id="s-pallets" inputMode="numeric" aria-invalid={!!errors.pallet_count} {...register("pallet_count")} />
        </Field>
        <Field label={t("dockType")} htmlFor="s-dock">
          <Select id="s-dock" {...register("required_dock_type")}>
            {DOCK_TYPES.map((x) => (
              <option key={x} value={x}>
                {d(x)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("priority")} htmlFor="s-prio">
          <Select id="s-prio" {...register("priority_code")}>
            {PRIORITIES.map((x) => (
              <option key={x} value={x}>
                {p(x)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("unload")} htmlFor="s-unload" error={err2("expected_unload_min")} hint={t("unloadHint")}>
          <Input id="s-unload" type="number" aria-invalid={!!errors.expected_unload_min} {...register("expected_unload_min", { valueAsNumber: true })} />
        </Field>
        <Field label={t("requestedDate")} htmlFor="s-date">
          <Input id="s-date" type="date" {...register("requested_date")} />
        </Field>
        <div className="flex items-end pb-2">
          <Checkbox label={t("temperature")} {...register("temperature_control_required")} />
        </div>
      </form>
    </Dialog>
  );
}

export function CancelShipmentDialog({ shipment, onClose }: { shipment: Shipment | null; onClose: () => void }) {
  const t = useTranslations("admin.shipments");
  const c = useTranslations("common");
  const [reason, setReason] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const cancel = useApiMutation((r: string) => api<Shipment>(`/shipments/${shipment!.id}/cancel`, { method: "POST", body: { reason: r } }), {
    success: t("cancelled"),
    onSuccess: onClose,
  });
  if (!shipment) return null;
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("cancelTitle")}
      description={t("cancelMessage", { code: shipment.code })}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("back")}
          </Button>
          <Button
            className="bg-danger text-white"
            disabled={!reason.trim() || cancel.isPending}
            onClick={() => {
              setErr(null);
              cancel.mutate(reason.trim(), { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
            }}
          >
            {t("cancelConfirm")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <label htmlFor="cancel-reason" className="text-sm font-medium">
        {t("cancelReason")}
      </label>
      <Textarea id="cancel-reason" className="mt-1.5" value={reason} onChange={(e) => setReason(e.target.value)} data-autofocus />
    </Dialog>
  );
}

export function OfferShipmentDialog({ shipment, onClose }: { shipment: Shipment | null; onClose: () => void }) {
  const t = useTranslations("admin.shipments");
  const c = useTranslations("common");
  const carriers = useOptions<Page<Carrier>>("/carriers?limit=200&active=true");
  const [carrier, setCarrier] = React.useState("");
  const [err, setErr] = React.useState<string | null>(null);
  const offer = useApiMutation((id: string) => api<Shipment>(`/shipments/${shipment!.id}/offer`, { method: "POST", body: { carrier_id: id } }), {
    success: t("offered"),
    onSuccess: onClose,
  });
  if (!shipment) return null;
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("offerTitle")}
      description={t("offerMessage", { code: shipment.code })}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button
            disabled={!carrier || offer.isPending}
            onClick={() => {
              setErr(null);
              offer.mutate(carrier, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
            }}
          >
            {t("offerConfirm")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <label htmlFor="offer-carrier" className="text-sm font-medium">
        {t("carrier")}
      </label>
      <Select id="offer-carrier" className="mt-1.5" value={carrier} onChange={(e) => setCarrier(e.target.value)} data-autofocus>
        <option value="">{t("chooseCarrier")}</option>
        {carriers.data?.items.map((x) => (
          <option key={x.id} value={x.id}>
            {x.carrier_name}
          </option>
        ))}
      </Select>
    </Dialog>
  );
}

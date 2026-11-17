"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Textarea } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { Facility, FacilityContact } from "@/lib/admin-types";
import { errorMessage, useApiMutation } from "@/lib/use-api";

const time = z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/, "time");
const num = (min: number) => z.number({ error: "required" }).int("int").min(min, "min");

const facilitySchema = z.object({
  code: z.string().trim().min(1, "required").max(32),
  facility_name: z.string().trim().min(1, "required"),
  address: z.string().optional(),
  city: z.string().trim().min(1, "required"),
  state: z.string().trim().min(1, "required"),
  timezone: z.string().trim().min(1, "required"),
  open_time: time,
  close_time: time,
  checkin_grace_min: num(0),
  default_unload_min: num(1),
  notes: z.string().optional(),
});
type FacilityValues = z.infer<typeof facilitySchema>;

export function FacilityFormDialog({ open, onClose, facility }: { open: boolean; onClose: () => void; facility?: Facility }) {
  const t = useTranslations("admin.facilities");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FacilityValues>({
    resolver: zodResolver(facilitySchema),
    defaultValues: facility
      ? { ...facility, address: facility.address ?? "", notes: facility.notes ?? "" }
      : { timezone: "Asia/Kolkata", open_time: "06:00", close_time: "22:00", checkin_grace_min: 30, default_unload_min: 60 },
  });
  const save = useApiMutation(
    (v: FacilityValues) => {
      const { code, ...rest } = v;
      return facility
        ? api<Facility>(`/facilities/${facility.id}`, { method: "PATCH", body: rest })
        : api<Facility>("/facilities", { method: "POST", body: { code, ...rest } });
    },
    { success: facility ? t("updated") : t("created"), onSuccess: onClose },
  );
  const formId = "facility-form";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={facility ? t("edit") : t("new")}
      size="lg"
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
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={handleSubmit((v) => {
          setErr(null);
          save.mutate(v, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
        })}
      >
        <Field label={t("code")} htmlFor="f-code" error={errors.code?.message}>
          <Input id="f-code" disabled={!!facility} aria-invalid={!!errors.code} {...register("code")} />
        </Field>
        <Field label={t("name")} htmlFor="f-name" error={errors.facility_name?.message}>
          <Input id="f-name" aria-invalid={!!errors.facility_name} {...register("facility_name")} />
        </Field>
        <Field label={t("address")} htmlFor="f-address" className="sm:col-span-2">
          <Input id="f-address" {...register("address")} />
        </Field>
        <Field label={t("city")} htmlFor="f-city" error={errors.city?.message}>
          <Input id="f-city" aria-invalid={!!errors.city} {...register("city")} />
        </Field>
        <Field label={t("state")} htmlFor="f-state" error={errors.state?.message}>
          <Input id="f-state" aria-invalid={!!errors.state} {...register("state")} />
        </Field>
        <Field label={t("timezone")} htmlFor="f-tz" error={errors.timezone?.message} className="sm:col-span-2">
          <Input id="f-tz" aria-invalid={!!errors.timezone} {...register("timezone")} />
        </Field>
        <Field label={t("opens")} htmlFor="f-open" error={errors.open_time?.message}>
          <Input id="f-open" type="time" aria-invalid={!!errors.open_time} {...register("open_time")} />
        </Field>
        <Field label={t("closes")} htmlFor="f-close" error={errors.close_time?.message}>
          <Input id="f-close" type="time" aria-invalid={!!errors.close_time} {...register("close_time")} />
        </Field>
        <Field label={t("grace")} htmlFor="f-grace" error={errors.checkin_grace_min?.message} hint={t("graceHint")}>
          <Input id="f-grace" type="number" aria-invalid={!!errors.checkin_grace_min} {...register("checkin_grace_min", { valueAsNumber: true })} />
        </Field>
        <Field label={t("unload")} htmlFor="f-unload" error={errors.default_unload_min?.message} hint={t("unloadHint")}>
          <Input id="f-unload" type="number" aria-invalid={!!errors.default_unload_min} {...register("default_unload_min", { valueAsNumber: true })} />
        </Field>
        <Field label={t("notes")} htmlFor="f-notes" className="sm:col-span-2">
          <Textarea id="f-notes" {...register("notes")} />
        </Field>
      </form>
    </Dialog>
  );
}

const contactSchema = z.object({
  contact_role: z.string().trim().min(1, "required"),
  contact_name: z.string().trim().min(1, "required"),
  email: z.string().trim().email("email").or(z.literal("")),
  phone: z.string().trim().optional(),
});
type ContactValues = z.infer<typeof contactSchema>;

export function ContactFormDialog({
  open,
  onClose,
  facilityId,
  contact,
}: {
  open: boolean;
  onClose: () => void;
  facilityId: string;
  contact?: FacilityContact;
}) {
  const t = useTranslations("admin.facilities");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ContactValues>({
    resolver: zodResolver(contactSchema),
    defaultValues: contact
      ? { contact_role: contact.contact_role, contact_name: contact.contact_name, email: contact.email ?? "", phone: contact.phone ?? "" }
      : { contact_role: "", contact_name: "", email: "", phone: "" },
  });
  const save = useApiMutation(
    (v: ContactValues) => {
      const body = { ...v, email: v.email || null, phone: v.phone || null };
      return contact
        ? api<FacilityContact>(`/facilities/${facilityId}/contacts/${contact.id}`, { method: "PATCH", body })
        : api<FacilityContact>(`/facilities/${facilityId}/contacts`, { method: "POST", body });
    },
    { success: t("contactSaved"), onSuccess: onClose },
  );
  const formId = "contact-form";
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={contact ? t("editContact") : t("addContact")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={save.isPending}>
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
        <Field label={t("contactRole")} htmlFor="c-role" error={errors.contact_role?.message}>
          <Input id="c-role" aria-invalid={!!errors.contact_role} {...register("contact_role")} />
        </Field>
        <Field label={t("contactName")} htmlFor="c-name" error={errors.contact_name?.message}>
          <Input id="c-name" aria-invalid={!!errors.contact_name} {...register("contact_name")} />
        </Field>
        <Field label={t("email")} htmlFor="c-email" error={errors.email?.message}>
          <Input id="c-email" type="email" aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label={t("phone")} htmlFor="c-phone">
          <Input id="c-phone" type="tel" {...register("phone")} />
        </Field>
      </form>
    </Dialog>
  );
}

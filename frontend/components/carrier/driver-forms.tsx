"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, MessageCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { DriverRow } from "@/lib/admin-types";
import { LANGUAGE_OPTIONS } from "@/lib/carrier";
import type { VerificationSent } from "@/lib/carrier-types";
import { formatDateTime } from "@/lib/format";
import { errorMessage, useApiMutation } from "@/lib/use-api";

const E164 = /^\+[1-9]\d{7,14}$/;
const STATUSES = ["ACTIVE", "OFF_DUTY", "INACTIVE"] as const;

export const driverSchema = z.object({
  driver_name: z.string().trim().min(2, "min2").max(200),
  phone: z.string().trim().regex(E164, "phone"),
  whatsapp_number: z.string().trim().regex(E164, "phone").or(z.literal("")),
  preferred_language: z.string().min(2),
  licence_number: z.string().trim().min(4, "min4").max(64),
  home_base_city: z.string().trim().max(100).optional(),
  driver_status: z.string().optional(),
});
export type DriverValues = z.infer<typeof driverSchema>;

export function DriverFormDialog({ open, onClose, driver }: { open: boolean; onClose: () => void; driver?: DriverRow & { home_base_city?: string | null } }) {
  const t = useTranslations("carrier.drivers");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<DriverValues>({
    resolver: zodResolver(driverSchema),
    defaultValues: driver
      ? {
          driver_name: driver.driver_name,
          phone: driver.phone,
          whatsapp_number: driver.whatsapp_number ?? "",
          preferred_language: driver.preferred_language,
          licence_number: driver.licence_number,
          home_base_city: driver.home_base_city ?? "",
          driver_status: driver.driver_status,
        }
      : { driver_name: "", phone: "", whatsapp_number: "", preferred_language: "en", licence_number: "", home_base_city: "", driver_status: "ACTIVE" },
  });
  const save = useApiMutation(
    (v: DriverValues) => {
      const body = { ...v, whatsapp_number: v.whatsapp_number || null, home_base_city: v.home_base_city || null };
      if (driver) return api<DriverRow>(`/drivers/${driver.id}`, { method: "PATCH", body });
      const { driver_status, ...create } = body;
      void driver_status;
      return api<DriverRow>("/drivers", { method: "POST", body: create });
    },
    { success: driver ? t("updated") : t("created"), onSuccess: onClose },
  );
  const formId = "driver-form";
  const numberChanged = !!driver && (watch("whatsapp_number") || "") !== (driver.whatsapp_number ?? "");

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={driver ? t("edit") : t("new")}
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
        <Field label={t("name")} htmlFor="drv-name" error={errors.driver_name?.message}>
          <Input id="drv-name" autoComplete="off" aria-invalid={!!errors.driver_name} {...register("driver_name")} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("phone")} htmlFor="drv-phone" error={errors.phone?.message} hint={t("phoneHint")}>
            <Input id="drv-phone" type="tel" placeholder="+919876543210" aria-invalid={!!errors.phone} {...register("phone")} />
          </Field>
          <Field label={t("whatsapp")} htmlFor="drv-wa" error={errors.whatsapp_number?.message} hint={numberChanged ? t("numberChangedHint") : t("whatsappHint")}>
            <Input id="drv-wa" type="tel" placeholder="+919876543210" aria-invalid={!!errors.whatsapp_number} {...register("whatsapp_number")} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("language")} htmlFor="drv-lang" hint={t("languageHint")}>
            <Select id="drv-lang" {...register("preferred_language")}>
              {LANGUAGE_OPTIONS.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.native} ({l.code.toUpperCase()})
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("licence")} htmlFor="drv-lic" error={errors.licence_number?.message}>
            <Input id="drv-lic" autoComplete="off" aria-invalid={!!errors.licence_number} {...register("licence_number")} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("homeBase")} htmlFor="drv-city">
            <Input id="drv-city" {...register("home_base_city")} />
          </Field>
          {driver && (
            <Field label={c("status")} htmlFor="drv-status">
              <Select id="drv-status" {...register("driver_status")}>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`statuses.${s}`)}
                  </option>
                ))}
                {driver.driver_status === "SUSPENDED" && <option value="SUSPENDED" disabled>{t("statuses.SUSPENDED")}</option>}
              </Select>
            </Field>
          )}
        </div>
      </form>
    </Dialog>
  );
}

const verifySchema = z.object({ code: z.string().trim().regex(/^\d{6}$/, "code6") });

/** Two steps: send the template message, then check the 6-digit code the driver replies with. */
export function VerifyDialog({ open, onClose, driver }: { open: boolean; onClose: () => void; driver: DriverRow }) {
  const t = useTranslations("carrier.drivers.verify");
  const c = useTranslations("common");
  const locale = useLocale();
  const [sent, setSent] = React.useState<VerificationSent | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<z.infer<typeof verifySchema>>({ resolver: zodResolver(verifySchema), defaultValues: { code: "" } });

  const send = useApiMutation(() => api<VerificationSent>(`/drivers/${driver.id}/whatsapp/verification`, { method: "POST" }), {
    onSuccess: (r) => {
      setSent(r);
      setErr(null);
    },
  });
  const verify = useApiMutation((v: { code: string }) => api<{ verified: boolean }>(`/drivers/${driver.id}/whatsapp/verify`, { method: "POST", body: v }), {
    success: t("done"),
    onSuccess: () => close(),
  });

  const close = () => {
    setSent(null);
    setErr(null);
    reset();
    onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t("title", { name: driver.driver_name })}
      description={t("description", { number: driver.whatsapp_number ?? driver.phone })}
      footer={
        <Button variant="outline" onClick={close}>
          {c("close")}
        </Button>
      }
    >
      <FormError message={err} />
      {!driver.whatsapp_number && <p className="mb-4 rounded-md border border-amber-400/50 bg-amber-100 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">{t("noNumber")}</p>}
      <div className="space-y-5">
        <div>
          <Button
            disabled={send.isPending || !driver.whatsapp_number}
            onClick={() => send.mutate(undefined as never, { onError: (e) => setErr(errorMessage(e, t("sendFailed"))) })}
          >
            {send.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : <MessageCircle className="size-4" aria-hidden="true" />}
            {sent ? t("resend") : t("send")}
          </Button>
          {sent && (
            <p role="status" className="mt-2 text-sm text-muted">
              {t("sent", { time: formatDateTime(sent.expires_at, locale) })}
            </p>
          )}
          {sent?.dev_code && (
            <p className="mt-2 rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted">
              {t("devHint")} <code className="font-mono text-sm text-foreground">{sent.dev_code}</code>
            </p>
          )}
        </div>
        <form
          noValidate
          className="space-y-3"
          onSubmit={handleSubmit((v) => {
            setErr(null);
            verify.mutate(v, { onError: (e) => setErr(errorMessage(e, t("invalidCode"))) });
          })}
        >
          <Field label={t("code")} htmlFor="ver-code" error={errors.code?.message ? t(errors.code.message as "code6") : undefined} hint={t("codeHint")}>
            <Input id="ver-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="max-w-40 tracking-widest" aria-invalid={!!errors.code} {...register("code")} />
          </Field>
          <Button type="submit" disabled={verify.isPending}>
            {verify.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {t("confirm")}
          </Button>
        </form>
      </div>
    </Dialog>
  );
}

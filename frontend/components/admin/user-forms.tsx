"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Check, Copy, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Checkbox, Field, FormError, Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { AdminUser, Carrier, Facility, InvitedUser, Page, UserRole, UserStatus } from "@/lib/admin-types";
import { errorMessage, useApiMutation, useOptions } from "@/lib/use-api";

export const ROLES: UserRole[] = ["admin", "facility_planner", "coordinator", "carrier_user"];

const schema = z.object({
  email: z.string().trim().email("email"),
  full_name: z.string().trim().min(1, "required"),
  role: z.enum(["admin", "facility_planner", "coordinator", "carrier_user"]),
  status: z.enum(["active", "disabled", "invited"]),
  carrier_id: z.string().optional(),
});
type Values = z.infer<typeof schema>;

export function UserFormDialog({
  open,
  onClose,
  user,
  onInvited,
}: {
  open: boolean;
  onClose: () => void;
  user?: AdminUser;
  onInvited: (u: InvitedUser) => void;
}) {
  const t = useTranslations("admin.users");
  const r = useTranslations("enums.role");
  const s = useTranslations("enums.userStatus");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const [facilityIds, setFacilityIds] = React.useState<string[]>(user?.facility_ids ?? []);
  const facilities = useOptions<Page<Facility>>("/facilities?limit=200");
  const carriers = useOptions<Page<Carrier>>("/carriers?limit=200");
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: user?.email ?? "",
      full_name: user?.full_name ?? "",
      role: user?.role ?? "coordinator",
      status: user?.status ?? "invited",
      carrier_id: user?.carrier_id ?? "",
    },
  });
  const role = watch("role");
  const scopeError =
    role === "facility_planner" && facilityIds.length === 0 ? t("needFacility") : role === "carrier_user" && !watch("carrier_id") ? t("needCarrier") : null;

  const save = useApiMutation(
    (v: Values) => {
      const scope = {
        facility_ids: v.role === "facility_planner" ? facilityIds : [],
        carrier_id: v.role === "carrier_user" ? v.carrier_id || null : null,
      };
      return user
        ? api<AdminUser>(`/users/${user.id}`, { method: "PATCH", body: { full_name: v.full_name, role: v.role, status: v.status as UserStatus, ...scope } })
        : api<InvitedUser>("/users", { method: "POST", body: { email: v.email, full_name: v.full_name, role: v.role, ...scope } });
    },
    {
      success: user ? t("updated") : undefined,
      onSuccess: (res) => {
        onClose();
        if (!user) onInvited(res as InvitedUser);
      },
    },
  );
  const formId = "user-form";
  const toggleFacility = (id: string) => setFacilityIds((a) => (a.includes(id) ? a.filter((x) => x !== id) : [...a, id]));

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={user ? t("edit") : t("invite")}
      description={user ? undefined : t("inviteHint")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={save.isPending || !!scopeError}>
            {save.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {user ? c("save") : t("sendInvite")}
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
        <Field label={t("email")} htmlFor="u-email" error={errors.email?.message}>
          <Input id="u-email" type="email" disabled={!!user} aria-invalid={!!errors.email} {...register("email")} />
        </Field>
        <Field label={t("fullName")} htmlFor="u-name" error={errors.full_name?.message}>
          <Input id="u-name" aria-invalid={!!errors.full_name} {...register("full_name")} />
        </Field>
        <Field label={t("role")} htmlFor="u-role">
          <Select id="u-role" {...register("role")}>
            {ROLES.map((x) => (
              <option key={x} value={x}>
                {r(x)}
              </option>
            ))}
          </Select>
        </Field>
        {user && (
          <Field label={c("status")} htmlFor="u-status">
            <Select id="u-status" {...register("status")}>
              {(["active", "disabled", "invited"] as const).map((x) => (
                <option key={x} value={x}>
                  {s(x)}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {role === "facility_planner" && (
          <fieldset>
            <legend className="text-sm font-medium">{t("facilitiesScope")}</legend>
            <div className="mt-2 grid max-h-40 gap-2 overflow-y-auto sm:grid-cols-2">
              {facilities.data?.items.map((f) => (
                <Checkbox key={f.id} label={`${f.code} · ${f.facility_name}`} checked={facilityIds.includes(f.id)} onChange={() => toggleFacility(f.id)} />
              ))}
            </div>
          </fieldset>
        )}
        {role === "carrier_user" && (
          <Field label={t("carrierScope")} htmlFor="u-carrier">
            <Select id="u-carrier" {...register("carrier_id")}>
              <option value="">{t("chooseCarrier")}</option>
              {carriers.data?.items.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.carrier_name}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {scopeError && (
          <p role="alert" className="text-xs text-danger">
            {scopeError}
          </p>
        )}
        {(role === "admin" || role === "coordinator") && <p className="text-xs text-muted">{t("globalScope")}</p>}
      </form>
    </Dialog>
  );
}

export function InviteLinkDialog({ invite, onClose }: { invite: InvitedUser | null; onClose: () => void }) {
  const t = useTranslations("admin.users");
  const c = useTranslations("common");
  const [copied, setCopied] = React.useState(false);
  if (!invite) return null;
  const link = `${window.location.origin}/accept-invite?token=${encodeURIComponent(invite.invite_token)}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      toast.success(t("linkCopied"));
    } catch {
      toast.error(t("copyFailed"));
    }
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={t("inviteCreated")}
      description={t("inviteLinkHint", { email: invite.email })}
      footer={<Button onClick={onClose}>{c("done")}</Button>}
    >
      <label htmlFor="invite-link" className="text-sm font-medium">
        {t("inviteLink")}
      </label>
      <div className="mt-1.5 flex gap-2">
        <Input id="invite-link" readOnly value={link} data-autofocus onFocus={(e) => e.currentTarget.select()} />
        <Button variant="outline" onClick={copy} aria-label={t("copyLink")}>
          {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
          {t("copyLink")}
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted">{t("inviteExpiry")}</p>
    </Dialog>
  );
}

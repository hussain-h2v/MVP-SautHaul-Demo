"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field, FormError } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { errorMessage, useApiMutation } from "@/lib/use-api";

const schema = z
  .object({ password: z.string().min(10, "min10"), confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "mismatch" });
type Values = z.infer<typeof schema>;

function AcceptForm() {
  const t = useTranslations("acceptInvite");
  const router = useRouter();
  const token = useSearchParams().get("token");
  const [err, setErr] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema) });
  const accept = useApiMutation((v: Values) => api<void>("/auth/accept-invite", { method: "POST", body: { token, password: v.password } }), {
    onSuccess: () => {
      toast.success(t("success"));
      router.replace("/login");
    },
  });

  if (!token) {
    return (
      <p role="alert" className="mt-6 text-sm text-danger">
        {t("missingToken")}
      </p>
    );
  }
  return (
    <form
      noValidate
      className="mt-8 space-y-5"
      onSubmit={handleSubmit((v) => {
        setErr(null);
        accept.mutate(v, { onError: (e) => setErr(errorMessage(e, t("failed"))) });
      })}
    >
      <FormError message={err} />
      <Field label={t("password")} htmlFor="ai-pw" error={errors.password?.message} hint={t("hint")}>
        <Input id="ai-pw" type="password" autoComplete="new-password" aria-invalid={!!errors.password} {...register("password")} />
      </Field>
      <Field label={t("confirm")} htmlFor="ai-confirm" error={errors.confirm?.message}>
        <Input id="ai-confirm" type="password" autoComplete="new-password" aria-invalid={!!errors.confirm} {...register("confirm")} />
      </Field>
      <Button type="submit" className="w-full" disabled={accept.isPending}>
        {accept.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
        {t("submit")}
      </Button>
    </form>
  );
}

export default function AcceptInvitePage() {
  const t = useTranslations("acceptInvite");
  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="w-full max-w-sm">
        <h1 className="text-2xl font-semibold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("subtitle")}</p>
        <Suspense>
          <AcceptForm />
        </Suspense>
      </div>
    </main>
  );
}

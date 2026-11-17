"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { useLogin, useMe } from "@/lib/auth";
import { roleHome } from "@/lib/types";

const schema = z.object({ email: z.string().email("invalidEmail"), password: z.string().min(1, "passwordRequired") });
type Form = z.infer<typeof schema>;

function LoginForm() {
  const t = useTranslations("login");
  const router = useRouter();
  const params = useSearchParams();
  const { data: me } = useMe();
  const login = useLogin();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Form>({ resolver: zodResolver(schema) });

  const go = (role: keyof typeof roleHome) => {
    const next = params.get("next");
    router.replace(next && next.startsWith(roleHome[role]) ? next : roleHome[role]);
  };

  useEffect(() => {
    if (me) go(me.role);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me]);

  const err = login.error;
  const message =
    err instanceof ApiError ? (err.status === 423 ? t("locked") : err.status === 401 ? t("invalid") : t("generic")) : err ? t("generic") : null;

  return (
    <form onSubmit={handleSubmit((v) => login.mutate(v))} noValidate className="mt-8 space-y-5">
      {message && (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          {message}
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="email">{t("email")}</Label>
        <Input
          id="email"
          type="email"
          autoComplete="username"
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "email-err" : undefined}
          {...register("email")}
        />
        {errors.email && (
          <p id="email-err" className="text-xs text-danger">
            {t(errors.email.message as "invalidEmail")}
          </p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">{t("password")}</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          aria-invalid={!!errors.password}
          aria-describedby={errors.password ? "pw-err" : undefined}
          {...register("password")}
        />
        {errors.password && (
          <p id="pw-err" className="text-xs text-danger">
            {t(errors.password.message as "passwordRequired")}
          </p>
        )}
      </div>
      <Button type="submit" className="w-full" disabled={login.isPending}>
        {login.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
        {login.isPending ? t("submitting") : t("submit")}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  const t = useTranslations();
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <section className="hidden flex-col justify-between bg-gradient-to-br from-indigo-700 via-indigo-800 to-slate-900 p-12 text-white lg:flex">
        <p className="flex items-center gap-2 text-lg font-semibold">
          <span className="grid size-9 place-items-center rounded-lg bg-white/15">S</span>
          {t("common.appName")}
        </p>
        <div>
          <h2 className="text-4xl font-semibold tracking-tight">{t("common.tagline")}</h2>
          <p className="mt-3 max-w-md text-indigo-100">{t("common.taglineSub")}</p>
        </div>
        <p className="text-sm text-indigo-200">{t("login.driversNote")}</p>
      </section>
      <main className="flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-sm">
          <h1 className="text-2xl font-semibold tracking-tight">{t("login.title")}</h1>
          <p className="mt-1 text-sm text-muted">{t("login.subtitle")}</p>
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </main>
    </div>
  );
}

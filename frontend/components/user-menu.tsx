"use client";

import { Check, LogOut } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { Dropdown, MenuItem, MenuLabel, MenuSeparator } from "@/components/ui/dropdown";
import { useLogout } from "@/lib/auth";
import type { UserOut } from "@/lib/types";

export function setLocaleCookie(locale: string) {
  document.cookie = `NEXT_LOCALE=${locale}; path=/; max-age=31536000; samesite=lax`;
}

export function LocaleSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const t = useTranslations("common");
  return (
    <>
      <MenuLabel>{t("language")}</MenuLabel>
      {[
        ["en", "English"],
        ["hi", "हिन्दी"],
      ].map(([code, name]) => (
        <MenuItem
          key={code}
          checked={locale === code}
          onClick={() => {
            setLocaleCookie(code);
            router.refresh();
          }}
        >
          {name}
          {locale === code && <Check className="size-4" aria-hidden="true" />}
        </MenuItem>
      ))}
    </>
  );
}

export function ThemeSwitcher() {
  const { theme = "system", setTheme } = useTheme();
  const t = useTranslations("common");
  return (
    <>
      <MenuLabel>{t("theme")}</MenuLabel>
      {(["light", "dark", "system"] as const).map((v) => (
        <MenuItem key={v} checked={theme === v} onClick={() => setTheme(v)}>
          {t(v)}
          {theme === v && <Check className="size-4" aria-hidden="true" />}
        </MenuItem>
      ))}
    </>
  );
}

export function UserMenu({ user }: { user: UserOut }) {
  const t = useTranslations();
  const logout = useLogout();
  const initials = user.full_name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <Dropdown
      label={user.full_name}
      trigger={
        <>
          <span className="grid size-8 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground">
            {initials}
          </span>
          <span className="hidden text-left text-sm leading-tight sm:block">
            <span className="block font-medium">{user.full_name}</span>
            <span className="block text-xs text-muted">{t(`roles.${user.role}`)}</span>
          </span>
        </>
      }
    >
      <div className="px-3 py-2 text-sm">
        <p className="font-medium">{user.full_name}</p>
        <p className="text-xs text-muted">{user.email}</p>
      </div>
      <MenuSeparator />
      <LocaleSwitcher />
      <MenuSeparator />
      <ThemeSwitcher />
      <MenuSeparator />
      <MenuItem onClick={() => logout.mutate()}>
        {t("common.signOut")}
        <LogOut className="size-4" aria-hidden="true" />
      </MenuItem>
    </Dropdown>
  );
}

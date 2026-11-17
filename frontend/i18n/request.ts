import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";

export const locales = ["en", "hi"] as const;
export type Locale = (typeof locales)[number];

export default getRequestConfig(async () => {
  const store = await cookies();
  const raw = store.get("NEXT_LOCALE")?.value;
  const locale: Locale = (locales as readonly string[]).includes(raw ?? "") ? (raw as Locale) : "en";
  return { locale, messages: (await import(`../messages/${locale}.json`)).default };
});

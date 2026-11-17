"use client";

import { BellRing, Volume2, VolumeX } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { beep, loadPrefs, savePrefs, useCoordQuery, type AlertPrefs } from "@/lib/coord";
import type { Inbox } from "@/lib/coord-types";

/**
 * Header controls + the watcher that notices new inbox work. Sound and desktop alerts are opt-in; the browser's
 * notification permission is requested only when the coordinator clicks the toggle.
 */
export function CoordAlerts() {
  const t = useTranslations("coord.alerts");
  const [prefs, setPrefs] = React.useState<AlertPrefs>({ sound: false, desktop: false });
  const [hydrated, setHydrated] = React.useState(false);
  React.useEffect(() => {
    setPrefs(loadPrefs());
    setHydrated(true);
  }, []);

  const q = useCoordQuery<Inbox>("/coordinator/inbox?limit=1", { refetchInterval: 20_000 });
  const total = q.data?.counters.total;
  const prev = React.useRef<number | null>(null);

  React.useEffect(() => {
    if (total === undefined) return;
    if (prev.current !== null && total > prev.current) {
      const added = total - prev.current;
      if (prefs.sound) beep();
      if (prefs.desktop && typeof Notification !== "undefined" && Notification.permission === "granted") {
        try {
          new Notification(t("desktopTitle"), { body: t("desktopBody", { count: added }) });
        } catch {
          /* some browsers block constructor use */
        }
      }
    }
    prev.current = total;
  }, [total, prefs.sound, prefs.desktop, t]);

  const update = (next: AlertPrefs) => {
    setPrefs(next);
    savePrefs(next);
  };

  const toggleDesktop = async () => {
    if (prefs.desktop) return update({ ...prefs, desktop: false });
    if (typeof Notification === "undefined") return void toast.error(t("unsupported"));
    const perm = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
    if (perm === "granted") update({ ...prefs, desktop: true });
    else toast.error(t("denied"));
  };

  if (!hydrated) return null;
  return (
    <div className="flex items-center gap-1" role="group" aria-label={t("group")}>
      <Button
        variant={prefs.sound ? "primary" : "outline"}
        size="sm"
        aria-pressed={prefs.sound}
        onClick={() => {
          update({ ...prefs, sound: !prefs.sound });
          if (!prefs.sound) beep();
        }}
      >
        {prefs.sound ? <Volume2 className="size-4" aria-hidden="true" /> : <VolumeX className="size-4" aria-hidden="true" />}
        <span className="hidden sm:inline">{t("sound")}</span>
      </Button>
      <Button variant={prefs.desktop ? "primary" : "outline"} size="sm" aria-pressed={prefs.desktop} onClick={() => void toggleDesktop()}>
        <BellRing className="size-4" aria-hidden="true" />
        <span className="hidden sm:inline">{t("desktop")}</span>
      </Button>
    </div>
  );
}

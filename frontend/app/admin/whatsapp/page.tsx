"use client";

import { Check, CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { SectionHeader } from "@/components/ai/common";
import { Badge, Card } from "@/components/ui/card";
import { CopyButton, QueryState } from "@/components/wa/common";
import { formatDateTime } from "@/lib/format";
import { useWa } from "@/lib/wa-api";
import type { WaStatus } from "@/lib/wa-types";
import { cn } from "@/lib/utils";

function Item({ label, ok, detail }: { label: string; ok: boolean; detail?: React.ReactNode }) {
  const t = useTranslations("wa");
  const Icon = ok ? Check : CircleAlert;
  return (
    <li className="flex items-start justify-between gap-3 py-3">
      <div>
        <p className="text-sm font-medium">{label}</p>
        {detail && <div className="mt-1 text-xs text-muted">{detail}</div>}
      </div>
      <Badge tone={ok ? "success" : "warning"} className="shrink-0 gap-1">
        <Icon className="size-3" aria-hidden="true" />
        {ok ? t("ov.set") : t("ov.missing")}
      </Badge>
    </li>
  );
}

function Stat({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <Card className={cn(warn && "border-amber-400")}>
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </Card>
  );
}

export default function WhatsAppOverview() {
  const t = useTranslations("wa");
  const q = useWa<WaStatus>("/status", { refetchInterval: 15_000 });
  const s = q.data;
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://your-api-host";
  const webhookUrl = s ? `${apiBase}${s.webhook_path}` : "";
  const problems = s ? [s.pending_events > 20, s.failed_events > 0, s.failed_deliveries_24h > 0, s.templates.needs_review > 0, s.mode === "cloud" && !s.configured].filter(Boolean).length : 0;
  return (
    <>
      <SectionHeader title={t("nav.overview")} />
      <QueryState isLoading={q.isLoading} error={q.error} onRetry={() => q.refetch()}>
        {s && (
          <div className="space-y-6">
            <div
              role="status"
              className={cn("rounded-xl border px-4 py-3 text-sm", s.mode === "simulator" ? "border-amber-400 bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-200" : "border-success/50 bg-accent-soft")}
            >
              <p className="font-semibold">{s.mode === "simulator" ? t("ov.modeSimulator") : t("ov.modeCloud")}</p>
              <p className="mt-0.5">{s.mode === "simulator" ? t("ov.modeSimulatorBody") : t("ov.modeCloudBody")}</p>
            </div>

            <Card>
              <h3 className="text-base font-semibold">{t("ov.checklist")}</h3>
              <ul className="mt-2 divide-y divide-border">
                <li className="py-3">
                  <p className="text-sm font-medium">{t("ov.webhook")}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <code className="break-all rounded bg-background px-2 py-1 text-xs">{webhookUrl}</code>
                    <CopyButton value={webhookUrl} label={t("ov.webhook")} />
                  </div>
                  <p className="mt-1 text-xs text-muted">{t("ov.webhookHint")}</p>
                </li>
                <Item label={t("ov.verifyToken")} ok={s.verify_token_set} />
                <Item label={t("ov.appSecret")} ok={s.app_secret_set} />
                <Item
                  label={t("ov.accessToken")}
                  ok={s.configured}
                  detail={s.phone_number_id_masked ? `${t("ov.phoneId")}: ${s.phone_number_id_masked}` : undefined}
                />
              </ul>
            </Card>

            <section aria-labelledby="wa-health">
              <h3 id="wa-health" className="mb-3 text-base font-semibold">
                {t("ov.health")}
              </h3>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <Stat label={t("ov.pendingEvents")} value={s.pending_events} warn={s.pending_events > 20} />
                <Stat label={t("ov.failedEvents")} value={s.failed_events} warn={s.failed_events > 0} />
                <Stat label={t("ov.failedDeliveries")} value={s.failed_deliveries_24h} warn={s.failed_deliveries_24h > 0} />
                <Stat label={t("ov.lastInbound")} value={<span className="text-base">{formatDateTime(s.last_inbound_at)}</span>} />
                <Stat label={t("ov.lastOutbound")} value={<span className="text-base">{formatDateTime(s.last_outbound_at)}</span>} />
                <Stat
                  label={t("ov.templates")}
                  value={<span className="text-base font-medium">{t("ov.templatesLine", { approved: s.templates.approved, total: s.templates.total, review: s.templates.needs_review })}</span>}
                  warn={s.templates.needs_review > 0}
                />
              </div>
              <p className="mt-3 text-sm text-muted" aria-live="polite">
                {problems === 0 ? t("ov.allGood") : t("ov.attention")}
              </p>
            </section>

            <Card>
              <h3 className="text-base font-semibold">{t("ov.windowTitle")}</h3>
              <p className="mt-2 max-w-3xl text-sm text-muted">{t("ov.windowBody")}</p>
              <h3 className="mt-5 text-base font-semibold">{t("ov.voiceTitle")}</h3>
              <p className="mt-2 max-w-3xl text-sm text-muted">{t("ov.voiceBody")}</p>
            </Card>

            <nav aria-label={t("nav.label")} className="flex flex-wrap gap-2">
              {(
                [
                  ["/admin/whatsapp/simulator", "ov.openSimulator"],
                  ["/admin/whatsapp/templates", "ov.openTemplates"],
                  ["/admin/whatsapp/failures", "ov.openFailures"],
                  ["/admin/whatsapp/messages", "ov.openMessages"],
                  ["/admin/whatsapp/opt-ins", "ov.openOptins"],
                ] as const
              ).map(([href, key]) => (
                <Link key={href} href={href} className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent-soft">
                  {t(key)}
                </Link>
              ))}
            </nav>
          </div>
        )}
      </QueryState>
    </>
  );
}

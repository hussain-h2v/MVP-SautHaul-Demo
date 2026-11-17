"use client";

import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { CountdownBadge, describeCoordError, useCoordText } from "@/components/coordinator/shared";
import { QueryState, TableShell, td, th } from "@/components/facility/common";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Select } from "@/components/ui/fields";
import { api } from "@/lib/api";
import { useCoordMutation, useCoordQuery } from "@/lib/coord";
import { useCap, useNow } from "@/lib/fac";
import type { HoldRow } from "@/lib/facility-types";

export default function HoldsPage() {
  const t = useTranslations("coord.holds");
  const common = useTranslations("common");
  const { tc, tf } = useCoordText();
  const canDecide = useCap("booking_decisions") === "W";
  const now = useNow(1000);
  const q = useCoordQuery<HoldRow[]>("/booking/holds", { refetchInterval: 20_000 });
  const [release, setRelease] = React.useState<HoldRow | null>(null);
  const [extend, setExtend] = React.useState<HoldRow | null>(null);
  const [minutes, setMinutes] = React.useState("15");
  const [error, setError] = React.useState<string | null>(null);

  const fail = (e: unknown) => {
    const m = describeCoordError(e, tc, tf);
    setError(m);
    toast.error(m);
  };
  const releaseM = useCoordMutation((h: HoldRow) => api(`/booking/holds/${h.id}/release`, { method: "POST" }), {
    success: t("released"),
    onSuccess: () => setRelease(null),
    onError: fail,
  });
  const extendM = useCoordMutation(
    (v: { h: HoldRow; minutes: number }) => api(`/booking/holds/${v.h.id}/extend`, { method: "POST", body: { minutes: v.minutes } }),
    { success: t("extended"), onSuccess: () => setExtend(null), onError: fail },
  );
  const rows = [...(q.data ?? [])].sort((a, b) => new Date(a.expires_at).getTime() - new Date(b.expires_at).getTime());

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <QueryState isLoading={q.isLoading} isError={q.isError} onRetry={() => q.refetch()} empty={rows.length === 0} emptyText={t("empty")}>
        <TableShell caption={t("title")}>
          <thead>
            <tr className="border-b border-border text-left">
              <th className={th}>{t("shipment")}</th>
              <th className={th}>{t("slots")}</th>
              <th className={th}>{t("expires")}</th>
              <th className={th}>
                <span className="sr-only">{t("actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((h) => (
              <tr key={h.id}>
                <td className={td + " font-mono"}>{h.shipment_code ?? h.shipment_id.slice(0, 8)}</td>
                <td className={td}>{h.slot_ids.length}</td>
                <td className={td}>
                  <CountdownBadge expiresAt={h.expires_at} now={now} />
                </td>
                <td className={td + " text-right"}>
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" disabled={!canDecide} onClick={() => { setError(null); setExtend(h); }}>
                      {t("extend")}
                    </Button>
                    <Button size="sm" variant="outline" disabled={!canDecide} onClick={() => setRelease(h)}>
                      {t("release")}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </TableShell>
      </QueryState>

      <ConfirmDialog
        open={!!release}
        onClose={() => setRelease(null)}
        onConfirm={() => release && releaseM.mutate(release)}
        pending={releaseM.isPending}
        destructive
        title={t("releaseTitle")}
        message={t("releaseMessage", { code: release?.shipment_code ?? "" })}
        confirmLabel={t("release")}
      />
      <Dialog
        open={!!extend}
        onClose={() => setExtend(null)}
        title={t("extendTitle")}
        description={t("policy")}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setExtend(null)}>
              {common("cancel")}
            </Button>
            <Button disabled={extendM.isPending} onClick={() => extend && extendM.mutate({ h: extend, minutes: Number(minutes) })}>
              {t("extend")}
            </Button>
          </>
        }
      >
        <FormError message={error} />
        <Field label={t("minutes")} htmlFor="ext-min">
          <Select id="ext-min" value={minutes} onChange={(e) => setMinutes(e.target.value)}>
            {[5, 10, 15, 30, 45, 60].map((n) => (
              <option key={n} value={n}>
                {n} min
              </option>
            ))}
          </Select>
        </Field>
      </Dialog>
    </>
  );
}

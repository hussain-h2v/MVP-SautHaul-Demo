"use client";

import { useLocale, useTranslations } from "next-intl";
import * as React from "react";
import { KeyValue } from "@/components/facility/common";
import { Badge } from "@/components/ui/card";
import { describeProblem, type Tr } from "@/lib/problems";
import { formatDateTime } from "@/lib/format";
import { useCoordText } from "@/components/coordinator/shared";

type Rec = Record<string, unknown>;

const KNOWN = new Set(["shipment", "eta", "latest_finish", "current_appointment", "rejections", "searched_hours", "summary"]);

function isRec(v: unknown): v is Rec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function plain(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "✓" : "✕";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Renders the escalation hand-off record as readable facts instead of raw JSON. Unknown keys fall into "other details". */
export function HandoffView({ record }: { record: Rec }) {
  const t = useTranslations("coord.handoff");
  const { tf } = useCoordText();
  const locale = useLocale();
  const shipment = isRec(record.shipment) ? record.shipment : null;
  const eta = isRec(record.eta) ? record.eta : null;
  const appt = isRec(record.current_appointment) ? record.current_appointment : null;
  const rejections = isRec(record.rejections) ? (record.rejections as Record<string, number>) : null;
  const other = Object.entries(record).filter(([k]) => !KNOWN.has(k));
  const tfr = tf as Tr;

  return (
    <div className="space-y-5">
      {typeof record.summary === "string" && <p className="rounded-md border-l-4 border-accent bg-background px-4 py-3 text-sm">{record.summary}</p>}

      {shipment && (
        <section aria-label={t("shipment")}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("shipment")}</h3>
          <dl className="grid gap-3 sm:grid-cols-3">
            {shipment.code != null && <KeyValue label={t("code")}>{plain(shipment.code)}</KeyValue>}
            {shipment.priority != null && <KeyValue label={t("priority")}>{plain(shipment.priority)}</KeyValue>}
            {shipment.required_dock_type != null && <KeyValue label={t("dockType")}>{plain(shipment.required_dock_type)}</KeyValue>}
            {shipment.load_weight_kg != null && <KeyValue label={t("weight")}>{`${plain(shipment.load_weight_kg)} kg`}</KeyValue>}
            {shipment.expected_unload_min != null && <KeyValue label={t("unload")}>{`${plain(shipment.expected_unload_min)} min`}</KeyValue>}
            {shipment.temperature_control_required != null && <KeyValue label={t("temperature")}>{plain(shipment.temperature_control_required)}</KeyValue>}
          </dl>
        </section>
      )}

      {(eta || typeof record.latest_finish === "string") && (
        <section aria-label={t("timing")}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("timing")}</h3>
          <dl className="grid gap-3 sm:grid-cols-3">
            {eta && (
              <KeyValue label={t("eta")}>
                {formatDateTime(String(eta.ts ?? ""), locale)}{" "}
                {eta.source != null && <Badge tone="neutral">{plain(eta.source)}</Badge>}{" "}
                {eta.confidence != null && <Badge tone={eta.confidence === "LOW" ? "danger" : "neutral"}>{plain(eta.confidence)}</Badge>}
                {eta.requires_human_review === true && <Badge tone="warning" className="ml-1">{t("needsReview")}</Badge>}
              </KeyValue>
            )}
            {typeof record.latest_finish === "string" && <KeyValue label={t("latestFinish")}>{formatDateTime(record.latest_finish, locale)}</KeyValue>}
            {record.searched_hours != null && <KeyValue label={t("searched")}>{t("searchedHours", { hours: plain(record.searched_hours) })}</KeyValue>}
          </dl>
        </section>
      )}

      {appt && (
        <section aria-label={t("currentAppointment")}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("currentAppointment")}</h3>
          <p className="text-sm">
            <span className="font-mono">{plain(appt.id).slice(0, 8)}</span> <Badge tone="neutral">{plain(appt.status)}</Badge>
          </p>
        </section>
      )}
      {!appt && "current_appointment" in record && <p className="text-sm text-muted">{t("noAppointment")}</p>}

      {rejections && Object.keys(rejections).length > 0 && (
        <section aria-label={t("whyNone")}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("whyNone")}</h3>
          <ul className="space-y-1 text-sm">
            {Object.entries(rejections)
              .sort((a, b) => b[1] - a[1])
              .map(([code, n]) => (
                <li key={code} className="flex items-baseline justify-between gap-4 border-b border-border py-1">
                  <span>{describeProblem(code, tfr)}</span>
                  <span className="tabular-nums text-muted">{t("times", { n })}</span>
                </li>
              ))}
          </ul>
        </section>
      )}

      {other.length > 0 && (
        <section aria-label={t("other")}>
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wider text-muted">{t("other")}</h3>
          <dl className="grid gap-3 sm:grid-cols-2">
            {other.map(([k, v]) => (
              <KeyValue key={k} label={k.replace(/_/g, " ")}>
                {plain(v)}
              </KeyValue>
            ))}
          </dl>
        </section>
      )}
    </div>
  );
}

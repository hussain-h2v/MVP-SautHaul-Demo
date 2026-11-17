"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field, FormError, Select, Textarea } from "@/components/ui/fields";
import { api, ApiError } from "@/lib/api";
import type { DriverRow, Page, Shipment } from "@/lib/admin-types";
import { assignmentMessage, canSubmitAssignment, languageLabel, type Tr } from "@/lib/carrier";
import type { AssignmentCheck, AssignResult, Problem, VehicleRow } from "@/lib/carrier-types";
import { buildQuery } from "@/lib/query";
import { errorMessage, useApiMutation } from "@/lib/use-api";

function useDebounced<V>(value: V, ms: number): V {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** Accept the offer, or decline with a reason (required, min 3 chars). */
export function RespondDialog({ shipment, mode, onClose }: { shipment: Shipment; mode: "accept" | "decline" | null; onClose: () => void }) {
  const t = useTranslations("carrier.respond");
  const c = useTranslations("common");
  const [err, setErr] = React.useState<string | null>(null);
  const schema = z.object({ reason: mode === "decline" ? z.string().trim().min(3, "min3").max(500) : z.string() });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<{ reason: string }>({ resolver: zodResolver(schema), defaultValues: { reason: "" } });
  const respond = useApiMutation(
    (v: { reason: string }) =>
      api<Shipment>(`/shipments/${shipment.id}/respond`, {
        method: "POST",
        body: mode === "accept" ? { accept: true } : { accept: false, reason: v.reason.trim() },
      }),
    {
      success: mode === "accept" ? t("accepted") : t("declined"),
      onSuccess: () => {
        reset();
        onClose();
      },
    },
  );
  const formId = "respond-form";
  return (
    <Dialog
      open={mode !== null}
      onClose={onClose}
      title={mode === "accept" ? t("acceptTitle", { code: shipment.code }) : t("declineTitle", { code: shipment.code })}
      description={mode === "accept" ? t("acceptHint") : t("declineHint")}
      size="sm"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button
            type="submit"
            form={formId}
            disabled={respond.isPending}
            className={mode === "decline" ? "bg-danger text-white hover:opacity-90" : undefined}
          >
            {respond.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {mode === "accept" ? t("accept") : t("decline")}
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
          respond.mutate(v, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
        })}
      >
        <dl className="grid grid-cols-2 gap-2 text-sm">
          <div>
            <dt className="text-xs text-muted">{t("destination")}</dt>
            <dd>{shipment.facility_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">{t("load")}</dt>
            <dd>
              {shipment.load_weight_kg} kg · {shipment.required_dock_type}
            </dd>
          </div>
        </dl>
        {mode === "decline" && (
          <Field label={t("reason")} htmlFor="resp-reason" error={errors.reason?.message ? t(errors.reason.message as "min3") : undefined}>
            <Textarea id="resp-reason" aria-invalid={!!errors.reason} {...register("reason")} />
          </Field>
        )}
      </form>
    </Dialog>
  );
}

function IssueList({ items, tone, t }: { items: Problem[]; tone: "danger" | "warning"; t: Tr }) {
  if (!items.length) return null;
  const Icon = tone === "danger" ? XCircle : AlertTriangle;
  return (
    <ul
      role={tone === "danger" ? "alert" : "status"}
      className={
        tone === "danger"
          ? "space-y-1 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger"
          : "space-y-1 rounded-md border border-amber-400/50 bg-amber-100 px-4 py-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      }
    >
      {items.map((p) => (
        <li key={p.code} className="flex items-start gap-2">
          <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>{assignmentMessage(t, p)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Pick a driver and vehicle; the server checks compatibility live. Blocking problems disable the button. */
export function AssignPanel({ shipment, reassign = false }: { shipment: Shipment; reassign?: boolean }) {
  const t = useTranslations("carrier");
  const c = useTranslations("common");
  const [driverId, setDriverId] = React.useState(reassign ? "" : (shipment.driver_id ?? ""));
  const [vehicleId, setVehicleId] = React.useState(reassign ? "" : (shipment.vehicle_id ?? ""));
  const [reason, setReason] = React.useState("");
  const [reasonErr, setReasonErr] = React.useState(false);
  const [err, setErr] = React.useState<string | null>(null);
  const [submitProblems, setSubmitProblems] = React.useState<Problem[]>([]);
  const [lastWarnings, setLastWarnings] = React.useState<Problem[]>([]);

  const drivers = useQuery<Page<DriverRow>>({
    queryKey: ["carrier", "drivers-active"],
    queryFn: () => api<Page<DriverRow>>(`/drivers${buildQuery({ limit: 200, sort: "driver_name" })}`),
  });
  const vehicles = useQuery<Page<VehicleRow>>({
    queryKey: ["carrier", "vehicles-active"],
    queryFn: () => api<Page<VehicleRow>>(`/vehicles${buildQuery({ limit: 200, active: true, sort: "registration_number" })}`),
  });
  const activeDrivers = (drivers.data?.items ?? []).filter((d) => d.driver_status === "ACTIVE");
  const activeVehicles = (vehicles.data?.items ?? []).filter((v) => v.active_flag);

  const dDriver = useDebounced(driverId, 300);
  const dVehicle = useDebounced(vehicleId, 300);
  const check = useQuery<AssignmentCheck>({
    queryKey: ["carrier", "assignment-check", shipment.id, dDriver, dVehicle],
    queryFn: () => api<AssignmentCheck>(`/shipments/${shipment.id}/assignment-check${buildQuery({ driver_id: dDriver, vehicle_id: dVehicle })}`),
    enabled: !!dDriver && !!dVehicle,
  });
  const settled = driverId === dDriver && vehicleId === dVehicle;
  const current = settled ? check.data : undefined;

  const submit = useApiMutation(
    () =>
      api<AssignResult>(`/shipments/${shipment.id}/${reassign ? "reassign" : "assign"}`, {
        method: "POST",
        body: reassign ? { driver_id: driverId, vehicle_id: vehicleId, reason: reason.trim() } : { driver_id: driverId, vehicle_id: vehicleId },
      }),
    {
      success: reassign ? t("assign.reassigned") : t("assign.assigned"),
      onSuccess: (r) => {
        setLastWarnings(r.warnings ?? []);
        setSubmitProblems([]);
        setErr(null);
      },
    },
  );

  const onSubmit = () => {
    if (reassign && reason.trim().length < 3) {
      setReasonErr(true);
      return;
    }
    setReasonErr(false);
    setErr(null);
    submit.mutate(undefined as never, {
      onError: (e) => {
        if (e instanceof ApiError && Array.isArray(e.details?.problems)) setSubmitProblems(e.details.problems as Problem[]);
        else setErr(errorMessage(e, c("saveFailed")));
      },
    });
  };

  const ok = canSubmitAssignment(driverId, vehicleId, current) && (!reassign || reason.trim().length >= 3);
  const trAssign = ((k: string, v?: Record<string, string | number>) => t(k as "assign.title", v)) as Tr;
  trAssign.has = (k: string) => t.has(k as "assign.title");

  return (
    <Card>
      <h2 className="text-base font-semibold">{reassign ? t("assign.reassignTitle") : t("assign.title")}</h2>
      <p className="mt-1 text-sm text-muted">{reassign ? t("assign.reassignHint") : t("assign.hint")}</p>
      <div className="mt-4 space-y-4">
        <FormError message={err} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("assign.driver")} htmlFor="asg-driver">
            <Select id="asg-driver" value={driverId} onChange={(e) => { setDriverId(e.target.value); setSubmitProblems([]); }}>
              <option value="">{t("assign.chooseDriver")}</option>
              {activeDrivers.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.driver_name} · {d.code}
                  {d.verified ? "" : ` · ${t("drivers.unverified")}`}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("assign.vehicle")} htmlFor="asg-vehicle">
            <Select id="asg-vehicle" value={vehicleId} onChange={(e) => { setVehicleId(e.target.value); setSubmitProblems([]); }}>
              <option value="">{t("assign.chooseVehicle")}</option>
              {activeVehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.registration_number} · {v.vehicle_type_code} · {v.capacity_kg} kg
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {(drivers.isError || vehicles.isError) && <p role="alert" className="text-sm text-danger">{t("assign.loadFailed")}</p>}
        {!drivers.isLoading && activeDrivers.length === 0 && <p className="text-sm text-muted">{t("assign.noDrivers")}</p>}
        {!vehicles.isLoading && activeVehicles.length === 0 && <p className="text-sm text-muted">{t("assign.noVehicles")}</p>}

        {reassign && (
          <Field label={t("assign.reason")} htmlFor="asg-reason" error={reasonErr ? t("assign.reasonRequired") : undefined} hint={t("assign.reasonHint")}>
            <Textarea id="asg-reason" value={reason} aria-invalid={reasonErr} onChange={(e) => setReason(e.target.value)} />
          </Field>
        )}

        <div aria-live="polite" className="space-y-3">
          {driverId && vehicleId && (!settled || check.isFetching) && (
            <p className="flex items-center gap-2 text-sm text-muted">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> {t("assign.checking")}
            </p>
          )}
          {check.isError && <p role="alert" className="text-sm text-danger">{t("assign.checkFailed")}</p>}
          {current && (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {current.driver_language && <Badge tone="accent">{t("assign.driverLanguage", { lang: languageLabel(current.driver_language) })}</Badge>}
                {current.driver_verified !== null && (
                  <Badge tone={current.driver_verified ? "success" : "warning"}>
                    {current.driver_verified ? t("drivers.verified") : t("drivers.unverified")}
                  </Badge>
                )}
                {current.problems.length === 0 && (
                  <span className="inline-flex items-center gap-1 text-sm text-success">
                    <CheckCircle2 className="size-4" aria-hidden="true" /> {t("assign.compatible")}
                  </span>
                )}
              </div>
              <IssueList items={current.problems} tone="danger" t={trAssign} />
              <IssueList items={current.warnings} tone="warning" t={trAssign} />
            </>
          )}
          <IssueList items={submitProblems} tone="danger" t={trAssign} />
          {lastWarnings.length > 0 && <IssueList items={lastWarnings} tone="warning" t={trAssign} />}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!ok || submit.isPending} onClick={onSubmit}>
            {submit.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {reassign ? t("assign.reassign") : shipment.driver_id ? t("assign.update") : t("assign.submit")}
          </Button>
          <p className="flex items-start gap-1.5 text-xs text-muted">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            {t("assign.readOnlyNote")}
          </p>
        </div>
      </div>
    </Card>
  );
}

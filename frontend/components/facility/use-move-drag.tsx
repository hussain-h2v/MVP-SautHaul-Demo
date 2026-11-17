"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useFacMutation } from "@/lib/fac";
import type { MoveResult, Schedule, ScheduleDock, ScheduleSlot, SlotDetail } from "@/lib/facility-types";
import {
  classifyMove, isDropTarget, isFixed, isMovable, slotMinutes, slotsNeeded, targetRun, VERDICT_RING,
  type MoveCheck,
} from "@/lib/move";
import { describeMoveError, describeProblems, type Tr } from "@/lib/problems";
import { hhmm } from "@/lib/time";

interface DragState {
  slot: ScheduleSlot;
  appointmentId: string;
  count: number;
}

interface Target {
  dock: ScheduleDock;
  slotId: string;
}

interface Pending {
  appointmentId: string;
  shipment: string;
  from: string;
  to: string;
  slotIds: string[];
  approval: boolean;
}

export interface MoveGridProps {
  dragFor: (slot: ScheduleSlot, dock: ScheduleDock) => React.HTMLAttributes<HTMLButtonElement> & { draggable?: boolean };
  dropFor: (slot: ScheduleSlot, dock: ScheduleDock) => Partial<React.HTMLAttributes<HTMLButtonElement>>;
  ringFor: (slotId: string) => string | undefined;
}

const key = (appointmentId: string, ids: string[]) => `${appointmentId}:${ids.join(",")}`;

/**
 * Pointer drag-and-drop for the day-schedule grid. While hovering an open slot the target is validated against the
 * server (debounced) and coloured green / amber / red; dropping on a feasible target opens a confirmation, then
 * calls /booking/appointments/{id}/move. The server re-validates, so a stale colour never causes a bad booking.
 */
export function useMoveDrag(schedule: Schedule | undefined, enabled: boolean) {
  const t = useTranslations("facility");
  const tr = t as unknown as Tr;
  const qc = useQueryClient();
  const tz = schedule?.facility.timezone ?? "Asia/Kolkata";
  const [drag, setDrag] = React.useState<DragState | null>(null);
  const [target, setTarget] = React.useState<Target | null>(null);
  const [checks, setChecks] = React.useState<Record<string, MoveCheck | "loading">>({});
  const [pending, setPending] = React.useState<Pending | null>(null);

  const run = React.useMemo(
    () => (drag && target ? targetRun(target.dock, target.slotId, drag.count) : []),
    [drag, target],
  );
  const runKey = drag && run.length ? key(drag.appointmentId, run.map((s) => s.slot_id)) : null;

  const validate = React.useCallback(async (appointmentId: string, ids: string[]): Promise<MoveCheck> => {
    const k = key(appointmentId, ids);
    setChecks((c) => ({ ...c, [k]: "loading" }));
    const res = await api<MoveCheck>(`/booking/appointments/${appointmentId}/validate-move`, { method: "POST", body: { slot_ids: ids } });
    setChecks((c) => ({ ...c, [k]: res }));
    return res;
  }, []);

  React.useEffect(() => {
    if (!drag || !runKey || checks[runKey]) return;
    const timer = setTimeout(() => {
      validate(drag.appointmentId, run.map((s) => s.slot_id)).catch(() => setChecks((c) => ({ ...c, [runKey]: { feasible: false, problems: [], needs_planner_approval: false } })));
    }, 250);
    return () => clearTimeout(timer);
  }, [drag, runKey, run, checks, validate]);

  const move = useFacMutation(
    (v: Pending) => api<MoveResult>(`/booking/appointments/${v.appointmentId}/move`, { method: "POST", body: { slot_ids: v.slotIds } }),
    {
      onSuccess: (res) => {
        toast.success(res.appointment_status === "PENDING_CONFIRMATION" ? t("move.movedPending") : t("move.moved"));
        setPending(null);
        setChecks({});
      },
      onError: (e) => {
        toast.error(describeMoveError(e, tr));
        setPending(null);
        setChecks({});
      },
    },
  );

  const end = () => {
    setDrag(null);
    setTarget(null);
  };

  const startDrag = async (slot: ScheduleSlot, e: React.DragEvent) => {
    const appt = slot.appointment;
    if (!appt) return;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", appt.id);
    setDrag({ slot, appointmentId: appt.id, count: 1 });
    try {
      const detail = await qc.fetchQuery({
        queryKey: ["fac", `/schedule/slots/${slot.slot_id}`],
        queryFn: () => api<SlotDetail>(`/schedule/slots/${slot.slot_id}`),
        staleTime: 30_000,
      });
      const unload = Number((detail.shipment as { expected_unload_min?: number } | null)?.expected_unload_min ?? 0);
      setDrag((d) => (d && d.slot.slot_id === slot.slot_id ? { ...d, count: slotsNeeded(unload, slotMinutes(slot)) } : d));
    } catch {
      /* keep count = 1; the server reports TOO_SHORT if the load needs more */
    }
  };

  const dragFor: MoveGridProps["dragFor"] = (slot) => {
    if (!enabled) return {};
    if (isFixed(slot)) return { title: t("move.fixedTooltip") };
    if (!isMovable(slot)) return {};
    return {
      draggable: true,
      onDragStart: (e) => void startDrag(slot, e),
      onDragEnd: end,
    };
  };

  const dropFor: MoveGridProps["dropFor"] = (slot, dock) => {
    if (!drag || !isDropTarget(slot, drag.slot.slot_id)) return {};
    return {
      onDragEnter: () => setTarget({ dock, slotId: slot.slot_id }),
      onDragOver: (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        if (target?.slotId !== slot.slot_id) setTarget({ dock, slotId: slot.slot_id });
      },
      onDrop: async (e) => {
        e.preventDefault();
        const ids = targetRun(dock, slot.slot_id, drag.count).map((s) => s.slot_id);
        const k = key(drag.appointmentId, ids);
        let check = checks[k];
        if (!check || check === "loading") {
          try {
            check = await validate(drag.appointmentId, ids);
          } catch (err) {
            toast.error(describeMoveError(err, tr));
            end();
            return;
          }
        }
        const from = drag.slot;
        end();
        if (!check.feasible) {
          toast.error(check.problems.length ? describeProblems(check.problems, tr) : t("move.infeasible"));
          return;
        }
        setPending({
          appointmentId: drag.appointmentId,
          shipment: from.appointment?.shipment_code ?? "",
          from: `${hhmm(from.start, tz)} (${schedule?.docks.find((d) => d.slots.some((s) => s.slot_id === from.slot_id))?.dock_code ?? ""})`,
          to: `${hhmm(slot.start, tz)} (${dock.dock_code})`,
          slotIds: ids,
          approval: check.needs_planner_approval,
        });
      },
    };
  };

  const ringFor: MoveGridProps["ringFor"] = (slotId) => {
    if (!drag || !run.some((s) => s.slot_id === slotId)) return undefined;
    const c = runKey ? checks[runKey] : undefined;
    return VERDICT_RING[classifyMove(c === "loading" ? undefined : c, !c || c === "loading")];
  };

  const status = (() => {
    if (!drag || !runKey) return null;
    const c = checks[runKey];
    if (!c || c === "loading") return { verdict: "checking" as const, text: t("move.checking") };
    if (!c.feasible) return { verdict: "infeasible" as const, text: c.problems.length ? describeProblems(c.problems, tr) : t("move.infeasible") };
    return c.needs_planner_approval
      ? { verdict: "approval" as const, text: t("move.needsApproval") }
      : { verdict: "feasible" as const, text: t("move.feasible") };
  })();

  const dialog = (
    <ConfirmDialog
      open={!!pending}
      onClose={() => setPending(null)}
      title={t("move.confirmTitle")}
      message={
        pending ? (
          <>
            <span>{t("move.confirmMessage", { shipment: pending.shipment, from: pending.from, to: pending.to })}</span>
            {pending.approval && <span className="mt-2 block text-amber-700 dark:text-amber-300">{t("move.confirmApproval")}</span>}
          </>
        ) : null
      }
      confirmLabel={t("move.confirmAction")}
      pending={move.isPending}
      onConfirm={() => pending && move.mutate(pending)}
    />
  );

  return { grid: { dragFor, dropFor, ringFor } satisfies MoveGridProps, status, dragging: !!drag, dialog };
}

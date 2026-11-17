import { ApiError } from "./api";

/** Every rule/reason code the scheduling and booking services can return. Strings live in messages/*.json under facility.problems. */
export const PROBLEM_CODES = [
  "BEFORE_ETA",
  "TOO_SHORT",
  "NOT_CONSECUTIVE",
  "SLOT_BLOCKED",
  "OCCUPIED",
  "DOCK_EVENT",
  "OUTSIDE_HOURS",
  "MISSES_DEADLINE",
  "DOCK_NOT_ACTIVE",
  "NEEDS_REEFER_DOCK",
  "NEEDS_HEAVY_DOCK",
  "NEEDS_STANDARD_DOCK",
  "NEEDS_REFRIGERATED_DOCK",
  "LOAD_EXCEEDS_DOCK_LIMIT",
  "VEHICLE_TYPE_NOT_ALLOWED",
  "IN_THE_PAST",
  "SLOT_NOT_FOUND",
  "WRONG_FACILITY_OR_DOCK",
  "COMBINES_N_WINDOWS",
  "NEEDS_PLANNER_APPROVAL",
  "COMPATIBLE_DOCK",
  "FITS_UNLOAD_WINDOW",
  "AFTER_ETA",
  "MEETS_FINISH_DEADLINE",
] as const;

export const MOVE_ERROR_CODES = ["SLOT_TAKEN", "SLOT_UNAVAILABLE", "FIXED_IN_PROGRESS"] as const;

export type Tr = (key: string, values?: Record<string, string | number>) => string;

const COMBINES = /^COMBINES_(\d+)_WINDOWS$/;

/** Message key (inside the `facility` namespace) plus ICU values for a server code. */
export function problemMessage(code: string): { key: string; values?: Record<string, number> } {
  const m = COMBINES.exec(code);
  if (m) return { key: "problems.COMBINES_N_WINDOWS", values: { n: Number(m[1]) } };
  return { key: `problems.${code}` };
}

export function describeProblem(code: string, t: Tr): string {
  const { key, values } = problemMessage(code);
  const known = code in PROBLEM_SET || COMBINES.test(code);
  return known ? t(key, values) : code;
}

const PROBLEM_SET: Record<string, true> = Object.fromEntries(PROBLEM_CODES.map((c) => [c, true]));

export function describeProblems(codes: string[], t: Tr): string {
  return codes.map((c) => describeProblem(c, t)).join(" ");
}

/** Human text for a failed move / confirm / reject call (409 SLOT_TAKEN, SLOT_UNAVAILABLE, FIXED_IN_PROGRESS...). */
export function describeMoveError(e: unknown, t: Tr): string {
  if (!(e instanceof ApiError)) return t("moveErrors.generic");
  if (e.code === "SLOT_UNAVAILABLE") {
    const reasons = Array.isArray(e.details?.reasons) ? (e.details.reasons as string[]) : [];
    return t("moveErrors.SLOT_UNAVAILABLE", { reasons: describeProblems(reasons, t) || e.message });
  }
  if (e.code === "SLOT_TAKEN" || e.code === "FIXED_IN_PROGRESS") return t(`moveErrors.${e.code}`);
  return e.message || t("moveErrors.generic");
}

"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/card";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

const statusTone: Record<string, Tone> = {
  PLANNED: "neutral",
  ASSIGNED: "accent",
  IN_TRANSIT: "accent",
  AT_GATE: "warning",
  WAITING: "warning",
  IN_DOCK: "accent",
  COMPLETED: "success",
  CANCELLED: "danger",
};
const priorityTone: Record<string, Tone> = { LOW: "neutral", NORMAL: "accent", HIGH: "warning", CRITICAL: "danger" };
const offerTone: Record<string, Tone> = { draft: "neutral", offered: "accent", accepted: "success", declined: "danger" };
const userTone: Record<string, Tone> = { active: "success", invited: "warning", disabled: "danger" };

export function StatusBadge({ value }: { value: string }) {
  const t = useTranslations("enums.status");
  return <Badge tone={statusTone[value] ?? "neutral"}>{t.has(value as "PLANNED") ? t(value as "PLANNED") : value}</Badge>;
}

export function PriorityBadge({ value }: { value: string }) {
  const t = useTranslations("enums.priority");
  return <Badge tone={priorityTone[value] ?? "neutral"}>{t.has(value as "LOW") ? t(value as "LOW") : value}</Badge>;
}

export function OfferBadge({ value }: { value: string }) {
  const t = useTranslations("enums.offer");
  return <Badge tone={offerTone[value] ?? "neutral"}>{t.has(value as "draft") ? t(value as "draft") : value}</Badge>;
}

export function UserStatusBadge({ value }: { value: string }) {
  const t = useTranslations("enums.userStatus");
  return <Badge tone={userTone[value] ?? "neutral"}>{t.has(value as "active") ? t(value as "active") : value}</Badge>;
}

export function ActiveBadge({ active }: { active: boolean }) {
  const t = useTranslations("common");
  return <Badge tone={active ? "success" : "neutral"}>{active ? t("active") : t("inactive")}</Badge>;
}

export function YesNo({ value }: { value: boolean }) {
  const t = useTranslations("common");
  return <span>{value ? t("yes") : t("no")}</span>;
}

"use client";

import { useParams } from "next/navigation";
import { RequestDetailView } from "@/components/coordinator/request-detail";

export default function RequestPage() {
  const { id } = useParams<{ id: string }>();
  return <RequestDetailView id={id} />;
}

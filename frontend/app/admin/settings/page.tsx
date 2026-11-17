"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { DataTable, RowActions, type Column } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { FormError, Textarea } from "@/components/ui/fields";
import { Input, Label } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { SettingRow } from "@/lib/admin-types";
import { errorMessage, useApiMutation } from "@/lib/use-api";

function EditSetting({ setting, onClose }: { setting: SettingRow | null; onClose: () => void }) {
  const t = useTranslations("admin.settings");
  const c = useTranslations("common");
  const isNumber = typeof setting?.value === "number";
  const [text, setText] = React.useState(() => (isNumber ? String(setting?.value) : JSON.stringify(setting?.value, null, 2)));
  const [err, setErr] = React.useState<string | null>(null);
  const save = useApiMutation((value: unknown) => api<SettingRow>(`/settings/${setting!.key}`, { method: "PUT", body: { value } }), {
    success: c("saved"),
    onSuccess: onClose,
  });
  if (!setting) return null;

  const submit = () => {
    setErr(null);
    let value: unknown;
    if (isNumber) {
      value = Number(text);
      if (text.trim() === "" || Number.isNaN(value)) return setErr(t("invalidNumber"));
    } else {
      try {
        value = JSON.parse(text);
      } catch {
        return setErr(t("invalidJson"));
      }
    }
    save.mutate(value, { onError: (e) => setErr(errorMessage(e, c("saveFailed"))) });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={t("edit")}
      description={setting.description ?? undefined}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {c("cancel")}
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
            {c("save")}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <Label htmlFor="setting-value" className="font-mono text-xs">
        {setting.key}
      </Label>
      {isNumber ? (
        <Input id="setting-value" type="number" className="mt-1.5" value={text} onChange={(e) => setText(e.target.value)} />
      ) : (
        <>
          <Textarea
            id="setting-value"
            className="mt-1.5 min-h-40 font-mono text-xs"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-describedby="setting-hint"
          />
          <p id="setting-hint" className="mt-1.5 text-xs text-muted">
            {t("jsonHint")}
          </p>
        </>
      )}
    </Dialog>
  );
}

export default function SettingsPage() {
  const t = useTranslations("admin.settings");
  const c = useTranslations("common");
  const settings = useQuery({ queryKey: ["list", "/settings"], queryFn: () => api<SettingRow[]>("/settings") });
  const [editing, setEditing] = React.useState<SettingRow | null>(null);

  const columns: Column<SettingRow>[] = [
    { key: "key", header: t("key"), sortKey: "key", sortValue: (s) => s.key, cell: (s) => <span className="font-mono text-xs font-medium">{s.key}</span> },
    {
      key: "value",
      header: t("value"),
      cell: (s) => <code className="block max-w-xs truncate rounded bg-background px-2 py-1 text-xs">{JSON.stringify(s.value)}</code>,
    },
    { key: "description", header: t("descriptionCol"), cell: (s) => <span className="text-muted">{s.description ?? "—"}</span> },
  ];

  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <DataTable<SettingRow>
        tableId="settings"
        columns={columns}
        rowKey={(s) => s.key}
        rows={settings.data}
        loading={settings.isLoading}
        error={settings.error}
        onRetry={() => void settings.refetch()}
        defaultSort="key"
        searchPlaceholder={t("search")}
        searchText={(s) => `${s.key} ${s.description ?? ""}`}
        actions={(s) => (
          <RowActions>
            <Button variant="ghost" size="sm" onClick={() => setEditing(s)}>
              {c("edit")}
            </Button>
          </RowActions>
        )}
      />
      {editing && <EditSetting setting={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

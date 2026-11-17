"use client";

import { FileUp, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { Badge } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { FormError } from "@/components/ui/fields";
import { api } from "@/lib/api";
import type { ImportResult } from "@/lib/admin-types";
import { previewCsv, type CsvPreview } from "@/lib/csv";
import { errorMessage, useApiMutation } from "@/lib/use-api";

interface Props {
  open: boolean;
  onClose: () => void;
  title: string;
  /** e.g. "/facilities/import" */
  path: string;
  required: string[];
  optional?: string[];
}

export function CsvImportDialog({ open, onClose, title, path, required, optional = [] }: Props) {
  const t = useTranslations("import");
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<CsvPreview | null>(null);
  const [result, setResult] = React.useState<ImportResult | null>(null);
  const [formError, setFormError] = React.useState<string | null>(null);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setFormError(null);
  };
  const close = () => {
    reset();
    onClose();
  };

  const run = useApiMutation(
    (dry: boolean) => {
      const fd = new FormData();
      fd.append("file", file as File);
      return api<ImportResult>(`${path}?dry_run=${dry}`, { method: "POST", formData: fd });
    },
    {
      onSuccess: (res) => {
        setFormError(null);
        setResult(res);
      },
    },
  );

  const choose = async (f: File | null) => {
    reset();
    if (!f) return;
    setFile(f);
    setPreview(previewCsv(await f.text(), required, optional));
  };

  const template = () => {
    const blob = new Blob([[...required, ...optional].join(",") + "\n"], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "template.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const clientBlocked = !preview || preview.missingColumns.length > 0 || preview.rows.length === 0;
  const serverErrors = result?.errors ?? [];
  const checked = result?.dry_run === true && serverErrors.length === 0;
  const imported = result?.dry_run === false;

  const submit = (dry: boolean) => {
    setFormError(null);
    run.mutate(dry, { onError: (e) => setFormError(errorMessage(e, t("failed"))) });
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      description={t("hint")}
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={close}>
            {imported ? t("done") : t("cancel")}
          </Button>
          {!imported && (
            <>
              <Button variant="outline" disabled={clientBlocked || run.isPending} onClick={() => submit(true)}>
                {run.isPending && <Loader2 className="size-4 animate-spin" aria-hidden="true" />}
                {t("check")}
              </Button>
              <Button disabled={!checked || run.isPending} onClick={() => submit(false)}>
                {t("import", { n: result?.created ?? preview?.rows.length ?? 0 })}
              </Button>
            </>
          )}
        </>
      }
    >
      <FormError message={formError} />
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-accent-soft focus-within:outline-2 focus-within:outline-ring">
          <FileUp className="size-4" aria-hidden="true" />
          {file ? file.name : t("choose")}
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => void choose(e.target.files?.[0] ?? null)} />
        </label>
        <Button variant="ghost" size="sm" onClick={template}>
          {t("template")}
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted">
        {t("columns")}: <code>{[...required, ...optional.map((o) => `${o}?`)].join(", ")}</code>
      </p>

      {preview && (
        <div className="mt-5 space-y-4" aria-live="polite">
          <div className="flex flex-wrap gap-2">
            <Badge tone="accent">{t("rows", { n: preview.rows.length })}</Badge>
            {preview.missingColumns.length > 0 && (
              <Badge tone="danger">{t("missingColumns", { cols: preview.missingColumns.join(", ") })}</Badge>
            )}
            {preview.unknownColumns.length > 0 && (
              <Badge tone="warning">{t("unknownColumns", { cols: preview.unknownColumns.join(", ") })}</Badge>
            )}
            {preview.rowErrors.length > 0 && <Badge tone="danger">{t("rowIssues", { n: preview.rowErrors.length })}</Badge>}
          </div>
          {preview.rowErrors.length > 0 && (
            <ul className="max-h-32 overflow-y-auto rounded-md border border-border p-3 text-xs text-danger">
              {preview.rowErrors.slice(0, 20).map((e, i) => (
                <li key={i}>{t("rowError", { row: e.row, message: e.message })}</li>
              ))}
            </ul>
          )}
          {preview.rows.length > 0 && (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted">
                    {preview.headers.map((h) => (
                      <th key={h} scope="col" className="px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 5).map((r, i) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      {preview.headers.map((h) => (
                        <td key={h} className="px-3 py-1.5">
                          {r[h]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {result && (
        <div className="mt-5 rounded-md border border-border p-4 text-sm" role="status">
          {imported ? (
            <p className="font-medium text-success">{t("imported", { n: result.created })}</p>
          ) : serverErrors.length === 0 ? (
            <p className="font-medium text-success">{t("checkOk", { n: result.created })}</p>
          ) : (
            <>
              <p className="font-medium text-danger">{t("checkErrors", { n: serverErrors.length })}</p>
              <ul className="mt-2 max-h-40 overflow-y-auto text-xs text-danger">
                {serverErrors.map((e, i) => (
                  <li key={i}>{t("rowError", { row: e.row, message: e.message })}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

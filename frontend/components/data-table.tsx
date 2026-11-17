"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ArrowUpDown, Bookmark, Download, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import * as React from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Dropdown, MenuItem, MenuLabel, MenuSeparator } from "@/components/ui/dropdown";
import { Select } from "@/components/ui/fields";
import { Input } from "@/components/ui/input";
import { api, downloadCsv } from "@/lib/api";
import type { Page } from "@/lib/admin-types";
import { exportQuery, listQuery, nextSort, sortDirection, viewsKey, type SavedView } from "@/lib/query";
import { errorMessage } from "@/lib/use-api";
import { cn } from "@/lib/utils";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  /** Server sort field. Omit for non-sortable columns. */
  sortKey?: string;
  /** Client-mode sort value. */
  sortValue?: (row: T) => string | number;
  className?: string;
}

export interface FilterDef {
  key: string;
  label: string;
  type: "select" | "text";
  options?: { value: string; label: string }[];
}

interface Props<T> {
  tableId: string;
  columns: Column<T>[];
  rowKey: (row: T) => string;
  filters?: FilterDef[];
  defaultSort?: string;
  searchPlaceholder?: string;
  actions?: (row: T) => React.ReactNode;
  toolbar?: React.ReactNode;
  emptyMessage?: string;
  /** Server mode: GET `${path}?limit&offset&q&sort&filters`. Enables CSV export at `${path}/export.csv`. */
  path?: string;
  exportable?: boolean;
  /** Filter values applied on first render (e.g. from a dashboard link's query string). */
  initialFilters?: Record<string, string>;
  /** Client mode: all rows supplied, filtered/sorted/paged locally. */
  rows?: T[];
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  searchText?: (row: T) => string;
  clientFilter?: (row: T, filters: Record<string, string>) => boolean;
}

const PAGE_SIZES = [10, 25, 50, 100];

function useDebounced<V>(value: V, ms: number): V {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

function loadViews(tableId: string): SavedView[] {
  try {
    return JSON.parse(localStorage.getItem(viewsKey(tableId)) ?? "[]") as SavedView[];
  } catch {
    return [];
  }
}

export function DataTable<T>(props: Props<T>) {
  const { tableId, columns, rowKey, filters = [], defaultSort = "", path, actions, toolbar } = props;
  const { rows: allRows, searchText, clientFilter } = props;
  const t = useTranslations("table");
  const [qInput, setQInput] = React.useState("");
  const q = useDebounced(qInput, 300);
  const [sort, setSort] = React.useState(defaultSort);
  const [filterVals, setFilterVals] = React.useState<Record<string, string>>(props.initialFilters ?? {});
  const [offset, setOffset] = React.useState(0);
  const [limit, setLimit] = React.useState(25);
  const [views, setViews] = React.useState<SavedView[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [viewName, setViewName] = React.useState("");
  const [exporting, setExporting] = React.useState(false);

  React.useEffect(() => setViews(loadViews(tableId)), [tableId]);
  React.useEffect(() => setOffset(0), [q, sort, filterVals, limit]);

  const state = { q, sort, filters: filterVals, offset, limit };
  const serverQuery = useQuery({
    queryKey: ["list", path, listQuery(state)],
    queryFn: () => api<Page<T>>(`${path}${listQuery(state)}`),
    enabled: !!path,
    placeholderData: keepPreviousData,
  });

  // Client mode: filter, sort and page locally.
  const clientRows = React.useMemo(() => {
    if (allRows === undefined) return null;
    const needle = q.trim().toLowerCase();
    let rows = allRows.filter(
      (r) => (!needle || (searchText?.(r) ?? "").toLowerCase().includes(needle)) && (clientFilter?.(r, filterVals) ?? true),
    );
    const field = sort.replace(/^-/, "");
    const col = columns.find((c) => c.sortKey === field);
    if (col?.sortValue) {
      const dir = sort.startsWith("-") ? -1 : 1;
      rows = [...rows].sort((a, b) => {
        const x = col.sortValue!(a);
        const y = col.sortValue!(b);
        return (x < y ? -1 : x > y ? 1 : 0) * dir;
      });
    }
    return rows;
  }, [allRows, searchText, clientFilter, q, filterVals, sort, columns]);

  const total = clientRows ? clientRows.length : (serverQuery.data?.total ?? 0);
  const items = clientRows ? clientRows.slice(offset, offset + limit) : (serverQuery.data?.items ?? []);
  const loading = clientRows ? !!props.loading : serverQuery.isLoading;
  const error = clientRows ? props.error : serverQuery.error;
  const retry = clientRows ? props.onRetry : () => void serverQuery.refetch();
  const hasActive = !!(q || Object.values(filterVals).some(Boolean));

  const saveView = () => {
    const name = viewName.trim();
    if (!name) return;
    const next = [...views.filter((v) => v.name !== name), { name, q: qInput, sort, filters: filterVals }];
    setViews(next);
    try {
      localStorage.setItem(viewsKey(tableId), JSON.stringify(next));
    } catch {
      /* storage unavailable */
    }
    setSaving(false);
    setViewName("");
    toast.success(t("viewSaved"));
  };

  const removeView = (name: string) => {
    const next = views.filter((v) => v.name !== name);
    setViews(next);
    try {
      localStorage.setItem(viewsKey(tableId), JSON.stringify(next));
    } catch {
      /* storage unavailable */
    }
  };

  const applyView = (v: SavedView) => {
    setQInput(v.q);
    setSort(v.sort);
    setFilterVals(v.filters);
  };

  const doExport = async () => {
    if (!path) return;
    setExporting(true);
    try {
      await downloadCsv(`${path}/export.csv${exportQuery({ q, sort, filters: filterVals })}`, `${tableId}.csv`);
    } catch (e) {
      toast.error(errorMessage(e, t("exportFailed")));
    } finally {
      setExporting(false);
    }
  };

  const colCount = columns.length + (actions ? 1 : 0);
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <section className="rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-end gap-3 border-b border-border p-4">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden="true" />
          <Input
            type="search"
            aria-label={t("search")}
            placeholder={props.searchPlaceholder ?? t("search")}
            className="pl-9"
            value={qInput}
            onChange={(e) => setQInput(e.target.value)}
          />
        </div>
        {filters.map((f) => (
          <div key={f.key} className="w-40">
            {f.type === "select" ? (
              <Select
                aria-label={f.label}
                value={filterVals[f.key] ?? ""}
                onChange={(e) => setFilterVals((p) => ({ ...p, [f.key]: e.target.value }))}
              >
                <option value="">{f.label}</option>
                {f.options?.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </Select>
            ) : (
              <Input
                aria-label={f.label}
                placeholder={f.label}
                value={filterVals[f.key] ?? ""}
                onChange={(e) => setFilterVals((p) => ({ ...p, [f.key]: e.target.value }))}
              />
            )}
          </div>
        ))}
        {hasActive && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setQInput("");
              setFilterVals({});
            }}
          >
            {t("clear")}
          </Button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Dropdown
            label={t("views")}
            trigger={
              <span className="flex items-center gap-1.5 text-sm">
                <Bookmark className="size-4" aria-hidden="true" />
                {t("views")}
              </span>
            }
          >
            <MenuLabel>{t("savedViews")}</MenuLabel>
            {views.length === 0 && <p className="px-3 py-2 text-sm text-muted">{t("noViews")}</p>}
            {views.map((v) => (
              <div key={v.name} className="flex items-center">
                <MenuItem onClick={() => applyView(v)}>{v.name}</MenuItem>
                <button
                  type="button"
                  className="mr-1 rounded px-2 py-1 text-xs text-muted hover:text-danger"
                  aria-label={t("deleteView", { name: v.name })}
                  onClick={(e) => {
                    e.stopPropagation();
                    removeView(v.name);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
            <MenuSeparator />
            <MenuItem onClick={() => setSaving(true)}>{t("saveView")}</MenuItem>
          </Dropdown>
          {path && props.exportable !== false && (
            <Button variant="outline" size="sm" onClick={doExport} disabled={exporting}>
              <Download className="size-4" aria-hidden="true" />
              {t("export")}
            </Button>
          )}
          {toolbar}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("caption")}</caption>
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted">
              {columns.map((c) => {
                const field = c.sortKey;
                const dir = field ? sortDirection(sort, field) : "none";
                return (
                  <th key={c.key} scope="col" aria-sort={field ? dir : undefined} className={cn("px-4 py-3 font-medium", c.className)}>
                    {field ? (
                      <button
                        type="button"
                        onClick={() => setSort((s) => nextSort(s, field))}
                        className="inline-flex items-center gap-1 uppercase tracking-wider hover:text-foreground"
                      >
                        {c.header}
                        {dir === "ascending" ? (
                          <ArrowUp className="size-3" aria-hidden="true" />
                        ) : dir === "descending" ? (
                          <ArrowDown className="size-3" aria-hidden="true" />
                        ) : (
                          <ArrowUpDown className="size-3 opacity-50" aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
              {actions && (
                <th scope="col" className="px-4 py-3 text-right font-medium">
                  <span className="sr-only">{t("actions")}</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {loading &&
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i} className="border-b border-border last:border-0">
                  <td colSpan={colCount} className="px-4 py-3">
                    <Skeleton className="h-5 w-full" />
                  </td>
                </tr>
              ))}
            {!loading && !!error && (
              <tr>
                <td colSpan={colCount} className="px-4 py-10 text-center">
                  <p role="alert" className="text-danger">
                    {errorMessage(error, t("error"))}
                  </p>
                  {retry && (
                    <Button variant="outline" size="sm" className="mt-3" onClick={retry}>
                      {t("retry")}
                    </Button>
                  )}
                </td>
              </tr>
            )}
            {!loading && !error && items.length === 0 && (
              <tr>
                <td colSpan={colCount} className="px-4 py-12 text-center text-muted">
                  {hasActive ? t("noMatches") : (props.emptyMessage ?? t("empty"))}
                </td>
              </tr>
            )}
            {!loading &&
              !error &&
              items.map((row) => (
                <tr key={rowKey(row)} className="border-b border-border last:border-0 hover:bg-accent-soft/40">
                  {columns.map((c) => (
                    <td key={c.key} className={cn("px-4 py-3 align-middle", c.className)}>
                      {c.cell(row)}
                    </td>
                  ))}
                  {actions && <td className="px-4 py-2 text-right">{actions(row)}</td>}
                </tr>
              ))}
          </tbody>
        </table>
      </div>

      <nav aria-label={t("pagination")} className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 text-sm">
        <p className="text-muted" aria-live="polite">
          {t("range", { from, to, total })}
        </p>
        <div className="flex items-center gap-2">
          <Select
            aria-label={t("pageSize")}
            className="h-8 w-24"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {t("perPage", { n })}
              </option>
            ))}
          </Select>
          <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
            {t("prev")}
          </Button>
          <Button variant="outline" size="sm" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>
            {t("next")}
          </Button>
        </div>
      </nav>

      <Dialog
        open={saving}
        onClose={() => setSaving(false)}
        title={t("saveView")}
        size="sm"
        footer={
          <>
            <Button variant="outline" onClick={() => setSaving(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={saveView} disabled={!viewName.trim()}>
              {t("save")}
            </Button>
          </>
        }
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveView();
          }}
        >
          <label htmlFor="view-name" className="text-sm font-medium">
            {t("viewName")}
          </label>
          <Input id="view-name" className="mt-1.5" value={viewName} onChange={(e) => setViewName(e.target.value)} data-autofocus />
        </form>
      </Dialog>
    </section>
  );
}

/** Row action buttons, laid out inline (a dropdown would be clipped by the scroll container). */
export function RowActions({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap justify-end gap-1">{children}</div>;
}

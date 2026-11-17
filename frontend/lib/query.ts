export type Primitive = string | number | boolean | null | undefined;

/** "?a=1&b=x%20y" — skips undefined, null and empty-string values; "" when nothing is set. */
export function buildQuery(params: Record<string, Primitive>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export interface ListState {
  q: string;
  sort: string;
  filters: Record<string, string>;
  offset: number;
  limit: number;
}

/** Query string for a paged list request. */
export function listQuery(state: ListState): string {
  return buildQuery({ limit: state.limit, offset: state.offset, q: state.q, sort: state.sort, ...state.filters });
}

/** Query string for CSV export: same filters, no paging. */
export function exportQuery(state: Pick<ListState, "q" | "sort" | "filters">): string {
  return buildQuery({ q: state.q, sort: state.sort, ...state.filters });
}

/** Sort cycle for a column header: none -> asc -> desc -> none. A leading "-" means descending. */
export function nextSort(current: string, field: string): string {
  if (current === field) return `-${field}`;
  if (current === `-${field}`) return "";
  return field;
}

export function sortDirection(current: string, field: string): "ascending" | "descending" | "none" {
  if (current === field) return "ascending";
  if (current === `-${field}`) return "descending";
  return "none";
}

export interface SavedView {
  name: string;
  q: string;
  sort: string;
  filters: Record<string, string>;
}

export function viewsKey(tableId: string): string {
  return `sh.views.${tableId}`;
}

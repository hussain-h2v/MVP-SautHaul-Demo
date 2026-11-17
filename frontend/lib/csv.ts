/** Minimal RFC 4180 parser: quoted fields, escaped quotes, CRLF/LF, blank lines skipped. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (inQuotes) {
      if (c === '"' && src[i + 1] === '"') {
        field += '"';
        i++;
      } else if (c === '"') inQuotes = false;
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ",") {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.some((f) => f.trim() !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((f) => f.trim() !== "")) rows.push(row);
  return rows;
}

export interface CsvPreview {
  headers: string[];
  rows: Record<string, string>[];
  missingColumns: string[];
  unknownColumns: string[];
  /** `row` is the 1-based line number in the file, where the header is row 1. */
  rowErrors: { row: number; message: string }[];
}

export function previewCsv(text: string, required: string[], optional: string[] = []): CsvPreview {
  const parsed = parseCsv(text);
  const headers = (parsed[0] ?? []).map((h) => h.trim());
  const known = new Set([...required, ...optional]);
  const missingColumns = required.filter((c) => !headers.includes(c));
  const unknownColumns = headers.filter((h) => h && !known.has(h));
  const rows: Record<string, string>[] = [];
  const rowErrors: CsvPreview["rowErrors"] = [];
  parsed.slice(1).forEach((cells, i) => {
    const rowNo = i + 2;
    if (cells.length !== headers.length) {
      rowErrors.push({ row: rowNo, message: `Expected ${headers.length} columns, found ${cells.length}` });
    }
    const rec: Record<string, string> = {};
    headers.forEach((h, idx) => (rec[h] = (cells[idx] ?? "").trim()));
    const empty = required.filter((c) => headers.includes(c) && rec[c] === "");
    if (empty.length) rowErrors.push({ row: rowNo, message: `Missing value: ${empty.join(", ")}` });
    rows.push(rec);
  });
  return { headers, rows, missingColumns, unknownColumns, rowErrors };
}

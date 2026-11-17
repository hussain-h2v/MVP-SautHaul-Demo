"""Shared helpers for list endpoints: sorting, text search, CSV export and CSV import."""
import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

from fastapi import UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_

from app.core.errors import ValidationAppError

MAX_IMPORT_ROWS = 5000
MAX_IMPORT_BYTES = 2_000_000


def order_by(sort: str | None, allowed: dict[str, Any], default: Any):
    if not sort:
        return default
    desc = sort.startswith("-")
    col = allowed.get(sort.lstrip("-"))
    if col is None:
        raise ValidationAppError(f"Cannot sort by '{sort.lstrip('-')}'", {"allowed": sorted(allowed)})
    return col.desc() if desc else col.asc()


def search(q: str | None, *cols: Any):
    if not q:
        return None
    term = f"%{q.strip().replace('%', '').replace('_', '')}%"
    return or_(*[c.ilike(term) for c in cols])


def csv_response(filename: str, fields: Sequence[str], rows: Iterable[dict]) -> StreamingResponse:
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(fields)
        yield buf.getvalue()
        for r in rows:
            buf.seek(0)
            buf.truncate()
            w.writerow([_cell(r.get(f)) for f in fields])
            yield buf.getvalue()

    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _cell(v: Any) -> str:
    # Neutralise spreadsheet formula injection in exported text.
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _is_number(s) else s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


class ImportError_(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    dry_run: bool
    created: int
    errors: list[ImportError_]


async def read_csv(file: UploadFile, required: Sequence[str]) -> list[tuple[int, dict[str, str]]]:
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValidationAppError("CSV file too large")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationAppError("CSV must be UTF-8") from None
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in required if c not in (reader.fieldnames or [])]
    if missing:
        raise ValidationAppError(f"Missing CSV columns: {', '.join(missing)}")
    rows = [(i, {k.strip(): (v or "").strip() for k, v in row.items() if k}) for i, row in enumerate(reader, start=2)]
    if len(rows) > MAX_IMPORT_ROWS:
        raise ValidationAppError(f"Too many rows (max {MAX_IMPORT_ROWS})")
    return rows

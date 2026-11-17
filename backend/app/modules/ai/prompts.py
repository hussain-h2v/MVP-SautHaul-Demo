"""Versioned prompts per task and language. Exactly one ACTIVE prompt per (task, language) (partial unique index);
`render` only substitutes {{name}} placeholders: no code, no expressions."""
import difflib
import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.modules.ai.models import TASKS, AIPrompt

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(template: str, variables: dict | None = None) -> str:
    v = variables or {}
    return _VAR.sub(lambda m: str(v[m.group(1)]) if m.group(1) in v else m.group(0), template)


async def get_active(db: AsyncSession, task: str, language: str = "en") -> AIPrompt | None:
    for lang in (language, language.split("-")[0], "en"):
        row = (await db.execute(select(AIPrompt).where(AIPrompt.task == task, AIPrompt.language == lang,
                                                       AIPrompt.status == "active"))).scalar_one_or_none()
        if row is not None:
            return row
    return None


async def next_version(db: AsyncSession, task: str, language: str) -> int:
    n = (await db.execute(select(func.max(AIPrompt.prompt_version)).where(AIPrompt.task == task, AIPrompt.language == language))).scalar()
    return (n or 0) + 1


def _check_task(task: str) -> None:
    if task not in TASKS:
        raise ValidationAppError("Unknown AI task", {"allowed": list(TASKS)})


async def create_draft(db: AsyncSession, task: str, language: str, template: str, notes: str | None, user_id: UUID | None) -> AIPrompt:
    _check_task(task)
    p = AIPrompt(task=task, language=language, prompt_version=await next_version(db, task, language), template=template,
                 status="draft", notes=notes, created_by=user_id)
    db.add(p)
    await db.flush()
    return p


async def get(db: AsyncSession, prompt_id: UUID) -> AIPrompt:
    p = await db.get(AIPrompt, prompt_id)
    if p is None:
        raise NotFoundError("Prompt not found")
    return p


async def update_draft(db: AsyncSession, prompt_id: UUID, template: str | None, notes: str | None) -> AIPrompt:
    p = await get(db, prompt_id)
    if p.status != "draft":
        raise ConflictError("NOT_DRAFT", "Only a draft can be edited; create a new draft from the active version instead")
    if template is not None:
        p.template = template
    if notes is not None:
        p.notes = notes
    return p


async def _archive_active(db: AsyncSession, task: str, language: str, except_id: UUID | None = None) -> None:
    for cur in (await db.execute(select(AIPrompt).where(AIPrompt.task == task, AIPrompt.language == language,
                                                        AIPrompt.status == "active"))).scalars().all():
        if cur.id != except_id:
            cur.status = "archived"
    await db.flush()  # the partial unique index must see the old row archived before the new one becomes active


async def activate(db: AsyncSession, prompt_id: UUID) -> AIPrompt:
    p = await get(db, prompt_id)
    if p.status == "active":
        return p
    if p.status == "archived":
        raise ConflictError("ARCHIVED", "Archived versions are restored with rollback, which keeps the history")
    await _archive_active(db, p.task, p.language, p.id)
    p.status = "active"
    return p


async def archive(db: AsyncSession, prompt_id: UUID) -> AIPrompt:
    p = await get(db, prompt_id)
    p.status = "archived"
    return p


async def rollback(db: AsyncSession, task: str, language: str, version: int, user_id: UUID | None) -> AIPrompt:
    """Re-activate an old version as a NEW active copy, so the history stays intact and linear."""
    src = (await db.execute(select(AIPrompt).where(AIPrompt.task == task, AIPrompt.language == language,
                                                   AIPrompt.prompt_version == version))).scalar_one_or_none()
    if src is None:
        raise NotFoundError("That prompt version does not exist")
    await _archive_active(db, task, language)
    p = AIPrompt(task=task, language=language, prompt_version=await next_version(db, task, language), template=src.template,
                 status="active", notes=f"Rollback to v{version}", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


def diff(a: str, b: str) -> dict:
    al, bl = a.splitlines(), b.splitlines()
    unified = "\n".join(difflib.unified_diff(al, bl, "a", "b", lineterm=""))
    changes: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=al, b=bl).get_opcodes():
        if tag == "equal":
            changes += [{"type": "same", "text": t} for t in al[i1:i2]]
        else:
            changes += [{"type": "del", "text": t} for t in al[i1:i2]] + [{"type": "add", "text": t} for t in bl[j1:j2]]
    return {"unified": unified, "changes": changes}

"""Template lookup and safe rendering ({{variable}} replacement only; no code is ever evaluated)."""
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.whatsapp.models import WhatsAppTemplate
from app.modules.whatsapp.outbound import Button

_SECTION = re.compile(r"\{\{([#^])(\w+)\}\}(.*?)\{\{/\2\}\}", re.S)
_VAR = re.compile(r"\{\{(\w+)\}\}")


def render_body(body: str, variables: dict) -> str:
    def section(m: re.Match) -> str:
        kind, name, inner = m.group(1), m.group(2), m.group(3)
        truthy = bool(variables.get(name))
        return inner if (truthy if kind == "#" else not truthy) else ""

    out = _SECTION.sub(section, body)
    out = _VAR.sub(lambda m: str(variables.get(m.group(1), "")), out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


@dataclass
class Rendered:
    name: str
    language: str  # language actually used (falls back to en)
    requested_language: str
    body: str
    buttons: list[Button]
    variables: dict
    variable_order: list[str]


async def get_template(db: AsyncSession, name: str, language: str) -> WhatsAppTemplate | None:
    for lang in (language, "en"):
        t = (await db.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.name == name, WhatsAppTemplate.language == lang,
                                                            WhatsAppTemplate.approval_status == "approved"))).scalar_one_or_none()
        if t is not None:
            return t
    return None


async def render_template(db: AsyncSession, name: str, language: str, variables: dict) -> Rendered | None:
    """None when no approved template exists at all (the caller treats that as a failed send)."""
    t = await get_template(db, name, language)
    if t is None:
        return None
    buttons = [Button(id=b["id"], title=b["title"]) for b in (t.buttons or []) if not b.get("when") or variables.get(b["when"])]
    return Rendered(name=name, language=t.language, requested_language=language, body=render_body(t.body, variables),
                    buttons=buttons[:3], variables=variables, variable_order=list(t.variables or []))

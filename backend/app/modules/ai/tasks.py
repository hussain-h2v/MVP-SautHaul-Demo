"""Typed AI tasks built on the router. Capacity is never decided here: this only reads text."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.db import async_session_factory
from app.modules.ai import prompts
from app.modules.ai.router import AIResult, run_or_none

Intent = Literal["report_delay", "ask_options", "choose_option", "accept_suggestion", "decline_suggestion", "report_arrival",
                 "ask_status", "ask_gate_info", "safety_issue", "unknown"]


class IntentExtraction(BaseModel):
    intent: Intent
    delay_minutes: int | None = None
    delay_is_repair_time: bool | None = None
    eta_time: str | None = None
    cause: str | None = None
    latest_finish_time: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


async def classify_intent_result(text: str, language: str | None = None, pii_names: list[str] | None = None,
                                 model_id: UUID | None = None) -> AIResult | None:
    """None = AI unavailable: the caller falls back to fixed menus. The driver's text goes ONLY into the user message,
    delimited, and the system prompt tells the model to treat it as data."""
    async with async_session_factory() as db:
        prompt = await prompts.get_active(db, "intent_classify", language or "en")
    system = prompts.render(prompt.template if prompt else "Return only JSON with an `intent` field.", {"language": language or "en"})
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"<driver_message>\n{text}\n</driver_message>"}]
    ctx: dict = {"language": language, "pii_names": pii_names or []}
    if model_id:
        ctx["force_model_id"] = model_id
    return await run_or_none("intent_classify", messages, response_schema=IntentExtraction, context=ctx)


async def classify_intent(text: str, language: str | None = None, pii_names: list[str] | None = None) -> IntentExtraction | None:
    res = await classify_intent_result(text, language, pii_names)
    return res.parsed if res is not None else None

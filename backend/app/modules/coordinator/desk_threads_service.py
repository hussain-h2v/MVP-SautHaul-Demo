from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.outbox import emit
from app.modules.auth.deps import Principal
from app.modules.coordinator import desk_threads_repository as repo
from app.modules.coordinator.desk_threads_schemas import (
    DraftOut, MessageOut, ReplyOut, ThreadItem, ThreadMessages, ThreadPage, UserRef,
)
from app.modules.whatsapp.models import ChatMessage, ChatThread


def _item(row, last_text: str | None) -> ThreadItem:
    t: ChatThread = row[0]
    d = row[1]
    return ThreadItem(
        id=t.id, code=t.code, driver_id=d.id, driver_name=d.driver_name, driver_language=d.preferred_language,
        driver_phone=d.whatsapp_number or d.phone, shipment_code=row.shipment_code, thread_status=t.thread_status,
        thread_intent=t.thread_intent, last_message_text=last_text, last_message_ts=row.last_ts,
        requires_review=bool(row.review),
        taken_over_by=UserRef(id=row.owner_id, name=row.owner_name) if row.owner_id else None,
        bot_paused=t.taken_over_by_user_id is not None)


def _msg(m: ChatMessage) -> MessageOut:
    return MessageOut(id=m.id, sender_type=m.sender_type, text=m.message_text, translation=None, ts=m.message_ts,
                      is_duplicate=m.is_duplicate, parsed_intent=m.parsed_intent, extracted_eta_ts=m.extracted_eta_ts,
                      requires_human_review=m.requires_human_review)


async def list_threads(db: AsyncSession, q, status, taken_over, limit: int, offset: int) -> ThreadPage:
    total, rows = await repo.list_threads(db, q, status, taken_over, limit, offset)
    texts = await repo.last_message_texts(db, [r[0].id for r in rows])
    return ThreadPage(total=total, items=[_item(r, texts.get(r[0].id)) for r in rows])


async def thread_item(db: AsyncSession, thread_id: UUID) -> ThreadItem:
    row = await repo.get_thread_row(db, thread_id)
    if row is None:
        raise NotFoundError("Conversation not found")
    return _item(row, (await repo.last_message_texts(db, [thread_id])).get(thread_id))


async def thread_messages(db: AsyncSession, thread_id: UUID) -> ThreadMessages:
    item = await thread_item(db, thread_id)
    return ThreadMessages(thread=item, messages=[_msg(m) for m in await repo.messages(db, thread_id)])


async def _owner_ref(db: AsyncSession, user_id: UUID) -> dict:
    u = await repo.get_user(db, user_id)
    return {"id": str(user_id), "name": u.full_name if u else "another coordinator"}


async def takeover(db: AsyncSession, p: Principal, thread_id: UUID) -> ThreadItem:
    """Pause the bot for this thread and let this coordinator chat. Idempotent for the owner."""
    t = await repo.lock_thread(db, thread_id)
    if t is None:
        raise NotFoundError("Conversation not found")
    if t.taken_over_by_user_id and t.taken_over_by_user_id != p.user_id:
        raise ConflictError("CLAIMED", "Another coordinator has taken over this conversation",
                            {"claimed_by": await _owner_ref(db, t.taken_over_by_user_id)})
    t.taken_over_by_user_id = p.user_id
    await db.flush()
    return await thread_item(db, thread_id)


async def handback(db: AsyncSession, p: Principal, thread_id: UUID) -> ThreadItem:
    t = await repo.lock_thread(db, thread_id)
    if t is None:
        raise NotFoundError("Conversation not found")
    if t.taken_over_by_user_id is None:
        raise ConflictError("NOT_TAKEN_OVER", "This conversation is not taken over; the bot is already active")
    if t.taken_over_by_user_id != p.user_id:
        raise ConflictError("NOT_OWNER", "Only the coordinator who took over can hand it back",
                            {"claimed_by": await _owner_ref(db, t.taken_over_by_user_id)})
    t.taken_over_by_user_id = None
    await db.flush()
    return await thread_item(db, thread_id)


async def reply(db: AsyncSession, p: Principal, thread_id: UUID, text: str) -> ReplyOut:
    t = await repo.lock_thread(db, thread_id)
    if t is None:
        raise NotFoundError("Conversation not found")
    if t.taken_over_by_user_id != p.user_id:
        raise ConflictError("NOT_TAKEN_OVER", "Take over this conversation before replying")
    driver = await repo.get_driver(db, t.driver_id)
    now = datetime.now(UTC)
    m = ChatMessage(code=f"OPS{uuid4().hex[:12]}", thread_id=t.id, sender_type="OPERATIONS",
                    sender_reference=p.full_name, message_text=text.strip(), message_ts=now, is_duplicate=False,
                    requires_human_review=False)
    db.add(m)
    await db.flush()
    deliverable = bool(driver and driver.whatsapp_number and driver.verified_at and driver.whatsapp_opt_in)
    emit(db, "whatsapp.send", {"thread_id": t.id, "driver_id": t.driver_id, "to": driver.whatsapp_number if driver else None,
                               "text": m.message_text, "language": driver.preferred_language if driver else "en",
                               "sent_by": p.user_id})
    return ReplyOut(message=_msg(m), deliverable=deliverable)


DRAFTS = {
    "delay": {
        "en": "Hello {name}, thanks for the update. Could you tell us your new expected arrival time? Please also say "
              "whether the delay you mentioned is the repair time or the total delay to reach the facility.",
        "hi": "नमस्ते {name}, जानकारी के लिए धन्यवाद। कृपया बताएं कि आप कब तक पहुंचेंगे? और यह भी बताएं कि जो देरी आपने बताई "
              "वह मरम्मत का समय है या सुविधा तक पहुंचने की कुल देरी।",
    },
    "options": {
        "en": "Hello {name}, we can look at later dock slots for you. Please tell us your new arrival time and the "
              "latest time you can finish unloading, and we will share the options.",
        "hi": "नमस्ते {name}, हम आपके लिए बाद के डॉक स्लॉट देख सकते हैं। कृपया अपना नया आगमन समय और उतराई पूरी करने का "
              "आखिरी समय बताएं, हम विकल्प भेज देंगे।",
    },
    "unknown": {
        "en": "Hello {name}, thanks for your message. How can we help you with your delivery?",
        "hi": "नमस्ते {name}, आपके संदेश के लिए धन्यवाद। आपकी डिलीवरी में हम कैसे मदद कर सकते हैं?",
    },
}


def _kind(intent: str | None) -> str:
    i = (intent or "").upper()
    if "DELAY" in i or "EARLY" in i:
        return "delay"
    if "OPTION" in i or "SLOT" in i:
        return "options"
    return "unknown"


async def draft(db: AsyncSession, thread_id: UUID) -> DraftOut:
    """Rule-based, reviewable draft in the driver's language. An AI-written draft replaces it in M7."""
    row = await repo.get_thread_row(db, thread_id)
    if row is None:
        raise NotFoundError("Conversation not found")
    t, d = row[0], row[1]
    intent = await repo.last_driver_intent(db, thread_id)
    kind = _kind(intent) if intent and _kind(intent) != "unknown" else _kind(t.thread_intent)
    lang = d.preferred_language if d.preferred_language in ("en", "hi") else "en"
    return DraftOut(text=DRAFTS[kind][lang].format(name=d.driver_name.split()[0]), language=lang, source="rules")

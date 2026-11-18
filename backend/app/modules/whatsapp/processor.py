"""Webhook ingestion and processing. The HTTP handler only verifies the signature and stores the raw payload; this module
(run by the worker, or inline by the simulator) does the work, and is idempotent: a WhatsApp retry never double-processes
because wa_message_id is unique. Driver text is untrusted data and only ever reaches the agent as data."""
import hashlib
import hmac
import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.idempotency import get_redis
from app.modules.agent import service as agent_service
from app.modules.drivers import service as drivers_service
from app.modules.drivers.models import Driver
from app.modules.whatsapp import sender
from app.modules.whatsapp.models import ChatMessage, ChatThread, WhatsAppMessage, WhatsAppOptEvent, WhatsAppWebhookEvent
from app.modules.whatsapp.outbound import OutboundMessage
from app.modules.whatsapp.service import get_or_create_thread

log = logging.getLogger("whatsapp")

OPT_OUT = {"stop", "unsubscribe", "opt out", "optout", "रोको", "बंद करो", "बंद"}
OPT_IN = {"start", "join", "subscribe", "हाँ चालू", "हां चालू", "चालू"}
RATE_LIMIT_PER_HOUR = 20
UNKNOWN_REPLY_TTL = 24 * 3600
STATUS_RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
INTENT_TO_THREAD = {"report_delay": "REPORT_DELAY", "ask_options": "ASK_SLOT_OPTIONS", "ask_status": "CHECK_STATUS",
                    "report_arrival": "EARLY_ARRIVAL", "ask_gate_info": "GENERAL_QUESTION", "unknown": "UNKNOWN"}

# Fixed replies (reviewed, never model-generated). hi/te are flagged for native-speaker review in docs/DECISIONS.md.
STRINGS: dict[str, dict[str, str]] = {
    "unknown_number": {"en": "This number is not registered with SetuHaul. Please contact your carrier.\n\nयह नंबर SetuHaul में रजिस्टर नहीं है। कृपया अपने कैरियर से संपर्क करें।"},
    "verify_please": {"en": "Please verify your number first. Reply with the 6-digit code your carrier requested for you.",
                      "hi": "कृपया पहले अपना नंबर वेरिफाई करें। आपके कैरियर ने जो 6 अंकों का कोड मंगवाया है, वही भेजें।",
                      "te": "దయచేసి ముందు మీ నంబర్‌ను ధృవీకరించండి. మీ క్యారియర్ అభ్యర్థించిన 6 అంకెల కోడ్‌ను పంపండి."},
    "verify_failed": {"en": "That code did not work. Please ask your carrier to send a new verification code.",
                      "hi": "वह कोड सही नहीं है। कृपया अपने कैरियर से नया वेरिफिकेशन कोड भेजने को कहें।",
                      "te": "ఆ కోడ్ పని చేయలేదు. కొత్త ధృవీకరణ కోడ్ పంపమని మీ క్యారియర్‌ను అడగండి."},
    "verified_ok": {"en": "Thank you, your number is verified. You can now report delays and ask about dock slots here.",
                    "hi": "धन्यवाद, आपका नंबर वेरिफाई हो गया है। अब आप यहाँ देरी बता सकते हैं और डॉक स्लॉट के बारे में पूछ सकते हैं।",
                    "te": "ధన్యవాదాలు, మీ నంబర్ ధృవీకరించబడింది. ఇప్పుడు మీరు ఇక్కడ ఆలస్యాన్ని తెలియజేయవచ్చు, డాక్ స్లాట్ల గురించి అడగవచ్చు."},
    "opt_out_ok": {"en": "You will no longer receive WhatsApp messages from SetuHaul. Reply START to receive them again.",
                   "hi": "अब आपको SetuHaul के WhatsApp संदेश नहीं मिलेंगे। दोबारा पाने के लिए START भेजें।",
                   "te": "ఇకపై మీకు SetuHaul WhatsApp సందేశాలు రావు. మళ్ళీ పొందడానికి START పంపండి."},
    "opt_in_ok": {"en": "Welcome back. You will receive SetuHaul WhatsApp messages again.",
                  "hi": "वापसी पर स्वागत है। आपको फिर से SetuHaul के WhatsApp संदेश मिलेंगे।",
                  "te": "మళ్ళీ స్వాగతం. మీకు మళ్ళీ SetuHaul WhatsApp సందేశాలు వస్తాయి."},
    "too_many": {"en": "You are sending messages very quickly. Please wait a little; a coordinator can help if it is urgent.",
                 "hi": "आप बहुत तेज़ी से संदेश भेज रहे हैं। कृपया थोड़ा रुकें; ज़रूरी हो तो कोऑर्डिनेटर मदद करेंगे।",
                 "te": "మీరు చాలా వేగంగా సందేశాలు పంపుతున్నారు. దయచేసి కొంచెం ఆగండి; అత్యవసరమైతే కోఆర్డినేటర్ సహాయం చేస్తారు."},
    "audio_unsupported": {"en": "Sorry, I cannot listen to voice notes yet. Please type your message.",
                          "hi": "क्षमा करें, मैं अभी वॉइस नोट नहीं सुन सकता। कृपया अपना संदेश लिखकर भेजें।",
                          "te": "క్షమించండి, నేను ఇంకా వాయిస్ నోట్లను వినలేను. దయచేసి మీ సందేశాన్ని టైప్ చేయండి."},
    "agent_fallback": {"en": "Thanks. A coordinator will get back to you shortly.",
                       "hi": "धन्यवाद। कोऑर्डिनेटर जल्द ही आपसे संपर्क करेंगे।",
                       "te": "ధన్యవాదాలు. కోఆర్డినేటర్ త్వరలో మిమ్మల్ని సంప్రదిస్తారు."},
}


def say(key: str, lang: str) -> str:
    d = STRINGS[key]
    return d.get(lang) or d["en"]


class WebhookError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status, self.message = status, message
        super().__init__(message)


def normalise_number(raw: str) -> str:
    return "+" + "".join(c for c in raw if c.isdigit())


def _norm(text: str | None) -> str:
    return re.sub(r"[\s\.\!\?,]+", " ", (text or "").strip().lower()).strip()


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(body: bytes, header: str | None) -> None:
    secret = get_settings().whatsapp_app_secret
    if not secret:
        raise WebhookError(503, "WhatsApp app secret is not configured")
    if not header or not hmac.compare_digest(sign(body, secret), header.strip()):
        raise WebhookError(403, "Invalid signature")


async def ingest(db: AsyncSession, body: bytes, header: str | None, now: datetime | None = None) -> WhatsAppWebhookEvent:
    """Verify the signature, store the raw payload, return. Processing happens later (worker or inline simulator)."""
    import json

    verify_signature(body, header)
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise WebhookError(400, "Body is not valid JSON") from e
    ev = WhatsAppWebhookEvent(signature_ok=True, raw=payload, status="pending", received_at=now or datetime.now(UTC))
    db.add(ev)
    await db.flush()
    return ev


# ---------------------------------------------------------------- processing
async def process_pending(db: AsyncSession, limit: int = 20, now: datetime | None = None) -> int:
    ids = [r[0] for r in (await db.execute(select(WhatsAppWebhookEvent.id).where(WhatsAppWebhookEvent.status == "pending")
                                           .order_by(WhatsAppWebhookEvent.received_at).limit(limit))).all()]
    n = 0
    for i in ids:
        if await process_event(db, i, now):
            n += 1
    return n


async def process_event(db: AsyncSession, event_id, now: datetime | None = None) -> bool:
    ev = (await db.execute(select(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.id == event_id).with_for_update(skip_locked=True)
                           .execution_options(populate_existing=True))).scalar_one_or_none()
    if ev is None or ev.status != "pending":
        return False
    now = now or datetime.now(UTC)
    try:
        # no savepoint: drivers.service.confirm_verification commits to keep the wrong-attempt count
        await handle_payload(db, ev.raw, now)
        ev.status, ev.error = "processed", None
    except Exception as exc:  # noqa: BLE001  (store the reason; the event stays inspectable)
        log.exception("whatsapp event failed", extra={"event_id": str(event_id)})
        await db.rollback()
        ev = (await db.execute(select(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.id == event_id)
                               .execution_options(populate_existing=True))).scalar_one()
        ev.status, ev.error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
    ev.processed_at = now
    await db.commit()
    return True


async def handle_payload(db: AsyncSession, payload: dict, now: datetime) -> None:
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for m in value.get("messages", []) or []:
                await _handle_message(db, m, now)
            for st in value.get("statuses", []) or []:
                await _handle_status(db, st, now)


def _content(m: dict) -> tuple[str | None, str | None, str | None]:
    """(text, button_id, display title) from a Cloud API message."""
    t = m.get("type")
    if t == "text":
        body = (m.get("text") or {}).get("body")
        return body, None, body
    if t == "interactive":
        inter = m.get("interactive") or {}
        reply = inter.get("button_reply") or inter.get("list_reply") or {}
        return None, reply.get("id"), reply.get("title")
    if t == "button":  # template quick-reply button
        b = m.get("button") or {}
        return None, b.get("payload") or b.get("text"), b.get("text")
    return None, None, None


async def _reply(db: AsyncSession, driver: Driver | None, number: str, key: str, lang: str, purpose: str, *, thread_id=None,
                 now: datetime, allow_opted_out: bool = False, allow_unverified: bool = True) -> WhatsAppMessage:
    return await sender.send_message(db, driver=driver, number=number, message=OutboundMessage(kind="text", text=say(key, lang), language=lang, purpose=purpose),
                                     purpose=purpose, thread_id=thread_id, now=now, allow_opted_out=allow_opted_out,
                                     allow_unverified=allow_unverified, language=lang)


async def _redis_flag(key: str, ttl: int) -> bool:
    """True the first time within ttl."""
    r = get_redis()
    try:
        return bool(await r.set(key, "1", nx=True, ex=ttl))
    except Exception:
        return True
    finally:
        await r.aclose()


async def _count(key: str, ttl: int) -> int:
    r = get_redis()
    try:
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, ttl)
        return n
    except Exception:
        return 0
    finally:
        await r.aclose()


async def _handle_message(db: AsyncSession, m: dict, now: datetime) -> None:
    wa_id = m.get("id")
    if not wa_id:
        return
    if (await db.execute(select(WhatsAppMessage.id).where(WhatsAppMessage.wa_message_id == wa_id))).first():
        return  # a WhatsApp retry: already processed
    number = normalise_number(m.get("from", ""))
    mtype = m.get("type", "other")
    text, button_id, title = _content(m)
    driver = await drivers_service.find_by_whatsapp(db, number)
    row = WhatsAppMessage(wa_message_id=wa_id, direction="in", driver_id=driver.id if driver else None, to_number=number,
                          type="text" if mtype == "text" else ("interactive" if mtype in ("interactive", "button") else mtype if mtype in ("audio",) else "other"),
                          text=title or text, delivery_status="received", raw=m, purpose="inbound", created_at=now)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return  # concurrent duplicate delivery of the same wamid
    if driver is None:
        log.info("whatsapp message from unknown number", extra={"number_suffix": number[-4:]})
        if await _redis_flag(f"wa:unknown:{number}", UNKNOWN_REPLY_TTL):
            await _reply(db, None, number, "unknown_number", "en", "unknown_number", now=now)
        return
    lang = driver.preferred_language or "en"
    low = _norm(title or text)

    if low in OPT_OUT:
        driver.whatsapp_opt_in = False
        db.add(WhatsAppOptEvent(driver_id=driver.id, event="opt_out", source="driver_keyword"))
        await db.flush()
        await _reply(db, driver, number, "opt_out_ok", lang, "opt_out_confirmation", now=now, allow_opted_out=True)
        return
    if low in OPT_IN and not driver.whatsapp_opt_in:
        driver.whatsapp_opt_in = True
        db.add(WhatsAppOptEvent(driver_id=driver.id, event="opt_in", source="driver_keyword"))
        await db.flush()
        await _reply(db, driver, number, "opt_in_ok", lang, "opt_in_confirmation", now=now, allow_unverified=driver.verified_at is not None)
        return
    if driver.verified_at is None:
        code = re.sub(r"\s", "", text or "")
        if re.fullmatch(r"\d{6}", code):
            try:
                await drivers_service.confirm_verification(db, driver, code)
            except AppError:
                await _reply(db, driver, number, "verify_failed", lang, "verification_reply", now=now, allow_opted_out=True)
                return
            await _reply(db, driver, number, "verified_ok", lang, "verification_reply", now=now, allow_opted_out=True)
            return
        await _reply(db, driver, number, "verify_please", lang, "verification_reply", now=now, allow_opted_out=True)
        return
    if not driver.whatsapp_opt_in:
        return  # opted out: store, never answer

    thread = await get_or_create_thread(db, driver.id, now)
    row.thread_id = thread.id
    chat = ChatMessage(code=f"WA{hashlib.md5(wa_id.encode()).hexdigest()[:14]}", thread_id=thread.id, sender_type="DRIVER",
                       sender_reference=driver.code, message_text=((title or text) or f"[{mtype}]")[:4000], message_ts=now,
                       external_message_id=wa_id)
    db.add(chat)
    await db.flush()
    await _publish_inbox("whatsapp.inbound", thread)

    if mtype == "audio":
        await _reply(db, driver, number, "audio_unsupported", lang, "audio_unsupported", thread_id=thread.id, now=now)
        return
    n = await _count(f"wa:rl:{driver.id}:{int(now.timestamp() // 3600)}", 3700)
    if n > RATE_LIMIT_PER_HOUR:
        if n == RATE_LIMIT_PER_HOUR + 1:
            await _reply(db, driver, number, "too_many", lang, "rate_limited", thread_id=thread.id, now=now)
        return
    if thread.taken_over_by_user_id is not None:
        return  # a coordinator has the conversation: the bot stays paused, the message is stored and shown live

    try:
        reply = await agent_service.handle_message(db, driver_id=driver.id, thread_id=thread.id, text=text, button_id=button_id,
                                                   wa_message_id=wa_id, now=now)
    except Exception:  # noqa: BLE001
        log.exception("agent failed")
        chat.requires_human_review = True
        await _reply(db, driver, number, "agent_fallback", lang, "agent_fallback", thread_id=thread.id, now=now, allow_unverified=False)
        await _publish_inbox("whatsapp.agent_error", thread)
        return
    chat.parsed_intent = reply.intent
    chat.requires_human_review = bool(reply.requires_human_review)
    if reply.intent in INTENT_TO_THREAD:
        thread.thread_intent = INTENT_TO_THREAD[reply.intent]
    if reply.escalated:
        thread.thread_status = "ESCALATED"
    for om in reply.messages:
        await sender.send_message(db, driver=driver, message=om.validate(), purpose=om.purpose or "agent", thread_id=thread.id,
                                  chat_sender="AGENT", now=now, language=om.language)
    await _publish_inbox("whatsapp.agent_reply", thread)


async def _publish_inbox(reason: str, thread: ChatThread) -> None:
    await events.publish_inbox_changed(reason, thread_id=str(thread.id))


async def _handle_status(db: AsyncSession, st: dict, now: datetime) -> None:
    wa_id, status = st.get("id"), st.get("status")
    if not wa_id or status not in ("sent", "delivered", "read", "failed"):
        return
    row = (await db.execute(select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_id, WhatsAppMessage.direction == "out")
                            .with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        return
    if status == "failed":
        errs = st.get("errors") or []
        detail = "; ".join(f"{e.get('code')} {e.get('title') or e.get('message') or ''}".strip() for e in errs)[:400] or "delivery failed"
        if row.delivery_status != "failed":
            await sender.record_failure(db, row, detail)
        return
    if row.delivery_status != "failed" and STATUS_RANK.get(status, 0) > STATUS_RANK.get(row.delivery_status, 0):  # failed is terminal
        await db.execute(update(WhatsAppMessage).where(WhatsAppMessage.id == row.id).values(delivery_status=status, error=None))

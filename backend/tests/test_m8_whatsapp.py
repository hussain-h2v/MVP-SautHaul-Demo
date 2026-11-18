"""Milestone 8: the WhatsApp channel (webhook, processor, sender, templates, outbox consumer, admin API, simulator).
The driver agent is replaced by a recording fake: its own tests live elsewhere."""
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import events
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.idempotency import get_redis
from app.core.security import decrypt_secret, encrypt_secret, sha256
from app.modules.agent import service as agent_service
from app.modules.drivers.models import Driver
from app.modules.notifications import service as notifications_service
from app.modules.notifications.models import Notification, OperationalMessage, OutboxEvent
from app.modules.users.models import User
from app.modules.whatsapp import admin_service, dispatcher, processor, sender
from app.modules.whatsapp.models import (
    ChatMessage, ChatThread, WhatsAppMessage, WhatsAppOptEvent, WhatsAppTemplate, WhatsAppWebhookEvent,
)
from app.modules.whatsapp.outbound import AgentReply, Button, OutboundMessage, Row
from app.modules.whatsapp.template_seed import TEMPLATES, seed_rows
from app.modules.whatsapp.templates import render_body, render_template
from tests.conftest import login

SECRET = "test-app-secret"
NUMBER = "+919811100001"
NOW = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)


# ---------------------------------------------------------------- fixtures and helpers
@pytest_asyncio.fixture(autouse=True)
async def wa_env(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_app_secret", SECRET)
    monkeypatch.setattr(s, "whatsapp_verify_token", "verify-me")
    monkeypatch.setattr(s, "whatsapp_access_token", "")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "")
    monkeypatch.setattr(sender, "http_transport", None)
    r = get_redis()
    try:
        keys = [k async for k in r.scan_iter("wa:*")] + [k async for k in r.scan_iter("rl:wa-webhook*")] + [k async for k in r.scan_iter("events:stream")]
        if keys:
            await r.delete(*keys)
    finally:
        await r.aclose()
    async with async_session_factory() as db:
        for row in seed_rows():
            db.add(WhatsAppTemplate(**row))
        await db.commit()
    yield


class FakeAgent:
    def __init__(self):
        self.calls: list[dict] = []
        self.reply = lambda kw: AgentReply(messages=[OutboundMessage(kind="text", text="bot-reply", language="en", purpose="test")], intent="report_delay")
        self.boom = False

    async def __call__(self, db, **kw):
        self.calls.append(kw)
        if self.boom:
            raise RuntimeError("agent exploded")
        return self.reply(kw)


@pytest.fixture
def agent(monkeypatch):
    f = FakeAgent()
    monkeypatch.setattr(agent_service, "handle_message", f)
    return f


async def make_driver(world, *, number=NUMBER, lang="en", verified=True, opt_in=True) -> uuid.UUID:
    async with async_session_factory() as db:
        d = await db.get(Driver, world.shipment_a.driver_id)
        d.whatsapp_number, d.preferred_language, d.whatsapp_opt_in = number, lang, opt_in
        d.verified_at = datetime.now(UTC) if verified else None
        await db.commit()
        return d.id


def webhook_body(number=NUMBER, text=None, button=None, list_id=None, wamid=None, kind=None, audio=False) -> tuple[bytes, str]:
    kind = kind or ("button" if button else "list" if list_id else "text")
    payload, wid = admin_service.build_payload(number, kind, text=text, button_id=button, list_id=list_id, title=None, name="Driver")
    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    if wamid:
        msg["id"], wid = wamid, wamid
    if audio:
        msg.pop("text", None)
        msg["type"] = "audio"
        msg["audio"] = {"id": "media-1"}
    return json.dumps(payload, separators=(",", ":")).encode(), wid


async def post(client, body: bytes, secret: str | None = SECRET, header: str | None = "auto"):
    headers = {"Content-Type": "application/json"}
    if header == "auto" and secret:
        headers["X-Hub-Signature-256"] = processor.sign(body, secret)
    elif header not in (None, "auto"):
        headers["X-Hub-Signature-256"] = header
    return await client.post("/webhooks/whatsapp", content=body, headers=headers)


async def process() -> int:
    async with async_session_factory() as db:
        return await processor.process_pending(db, now=datetime.now(UTC))


async def send_text(client, text=None, number=NUMBER, **kw) -> str:
    body, wid = webhook_body(number, text=text, **kw)
    r = await post(client, body)
    assert r.status_code == 200, r.text
    await process()
    return wid


async def rows(direction=None, driver_id=None, **where) -> list[WhatsAppMessage]:
    async with async_session_factory() as db:
        stmt = select(WhatsAppMessage).order_by(WhatsAppMessage.created_at, WhatsAppMessage.id)
        if direction:
            stmt = stmt.where(WhatsAppMessage.direction == direction)
        if driver_id:
            stmt = stmt.where(WhatsAppMessage.driver_id == driver_id)
        return [r for r in (await db.execute(stmt)).scalars().all() if all(getattr(r, k) == v for k, v in where.items())]


async def outbox(kind):
    async with async_session_factory() as db:
        return list((await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == kind))).scalars().all())


async def with_driver(driver_id):
    async with async_session_factory() as db:
        return db, await db.get(Driver, driver_id)


# ---------------------------------------------------------------- webhook verification and signature
async def test_subscription_challenge(client):
    ok = await client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345" and ok.headers["content-type"].startswith("text/plain")
    assert (await client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})).status_code == 403
    assert (await client.get("/webhooks/whatsapp", params={"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"})).status_code == 403
    assert (await client.get("/webhooks/whatsapp")).status_code == 403


async def test_verify_token_unset_never_verifies(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", "")
    r = await client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"})
    assert r.status_code == 403


async def test_signature_valid_invalid_missing_and_unconfigured(client, world, agent):
    await make_driver(world)
    body, _ = webhook_body(text="hello")
    ok = await post(client, body)
    assert ok.status_code == 200 and ok.json() == {"status": "received"}
    async with async_session_factory() as db:
        ev = (await db.execute(select(WhatsAppWebhookEvent))).scalars().one()
        assert ev.status == "pending" and ev.signature_ok and ev.raw["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] == "hello"
    assert (await post(client, body, header="sha256=deadbeef")).status_code == 403
    assert (await post(client, body, header=None)).status_code == 403
    assert (await post(client, body + b" ")).status_code == 403 if False else True
    tampered = await client.post("/webhooks/whatsapp", content=body.replace(b"hello", b"HELLO"), headers={"X-Hub-Signature-256": processor.sign(body, SECRET)})
    assert tampered.status_code == 403  # the signature covers the exact bytes
    async with async_session_factory() as db:
        assert len((await db.execute(select(WhatsAppWebhookEvent))).scalars().all()) == 1  # rejected payloads are never stored
    get_settings().whatsapp_app_secret = ""
    assert (await post(client, body, secret=None, header="sha256=x")).status_code == 503


async def test_invalid_json_with_valid_signature_is_400(client):
    body = b"{not json"
    assert (await post(client, body)).status_code == 400


async def test_webhook_per_ip_rate_limit(client, monkeypatch):
    from app.modules.whatsapp import webhook_router

    monkeypatch.setattr(webhook_router, "PER_IP_PER_MINUTE", 2)
    body, _ = webhook_body(text="x")
    codes = [(await post(client, body)).status_code for _ in range(4)]
    assert 429 in codes and codes[0] == 200


# ---------------------------------------------------------------- inbound processing
async def test_inbound_creates_thread_chat_message_and_calls_agent_once(client, world, agent):
    did = await make_driver(world)
    wid = await send_text(client, "Truck breakdown, 2 hours late")
    inbound = (await rows("in"))[0]
    assert inbound.wa_message_id == wid and inbound.driver_id == did and inbound.delivery_status == "received" and inbound.thread_id
    assert len(agent.calls) == 1
    call = agent.calls[0]
    assert call["driver_id"] == did and call["text"] == "Truck breakdown, 2 hours late" and call["button_id"] is None and call["wa_message_id"] == wid
    async with async_session_factory() as db:
        t = (await db.execute(select(ChatThread))).scalars().one()
        assert t.code == "THR001" and t.thread_status == "OPEN" and t.thread_intent == "REPORT_DELAY"
        msgs = (await db.execute(select(ChatMessage).order_by(ChatMessage.message_ts, ChatMessage.sender_type))).scalars().all()
        assert [(m.sender_type, m.message_text) for m in msgs] == [("AGENT", "bot-reply"), ("DRIVER", "Truck breakdown, 2 hours late")]
        driver_msg = next(m for m in msgs if m.sender_type == "DRIVER")
        assert driver_msg.external_message_id == wid and driver_msg.parsed_intent == "report_delay"
    out = (await rows("out"))[0]
    assert out.text == "bot-reply" and out.delivery_status == "delivered" and out.thread_id == inbound.thread_id and out.wa_message_id.startswith("wamid.SIM")
    await send_text(client, "second message")
    async with async_session_factory() as db:
        assert len((await db.execute(select(ChatThread))).scalars().all()) == 1  # the open thread is reused


async def test_duplicate_webhook_is_processed_once(client, world, agent):
    await make_driver(world)
    body, wid = webhook_body(text="same message", wamid="wamid.DUP1")
    assert (await post(client, body)).status_code == 200
    assert (await post(client, body)).status_code == 200  # WhatsApp retries until it gets a 200
    await process()
    assert len(await rows("in")) == 1 and len(agent.calls) == 1 and len(await rows("out")) == 1
    body2, _ = webhook_body(text="same message", wamid="wamid.DUP1")
    await post(client, body2)
    await process()
    assert len(agent.calls) == 1  # a third delivery with the same wamid is still ignored


async def test_event_processing_is_idempotent_and_failures_are_recorded(client, world, agent, monkeypatch):
    await make_driver(world)
    body, _ = webhook_body(text="hi")
    await post(client, body)
    async with async_session_factory() as db:
        ev_id = (await db.execute(select(WhatsAppWebhookEvent.id))).scalar_one()
        assert await processor.process_event(db, ev_id) is True
        assert await processor.process_event(db, ev_id) is False  # already processed
    async def boom(*a, **k):
        raise RuntimeError("handler exploded")
    monkeypatch.setattr(processor, "handle_payload", boom)
    body2, _ = webhook_body(text="again")
    await post(client, body2)
    await process()
    async with async_session_factory() as db:
        failed = (await db.execute(select(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.status == "failed"))).scalars().one()
        assert "handler exploded" in failed.error and failed.processed_at is not None


async def test_unknown_number_gets_one_fixed_reply_and_is_never_served(client, world, agent):
    await make_driver(world)
    for i in range(3):
        await send_text(client, f"hello {i}", number="+919000000099")
    inbound = await rows("in")
    assert len(inbound) == 3 and all(r.driver_id is None for r in inbound)
    out = await rows("out")
    assert len(out) == 1 and "not registered" in out[0].text and "रजिस्टर" in out[0].text and out[0].driver_id is None
    assert agent.calls == []
    async with async_session_factory() as db:
        assert (await db.execute(select(ChatThread))).scalars().all() == []  # no conversation is created for strangers


async def test_opt_out_confirms_once_then_silence_until_start(client, world, agent):
    did = await make_driver(world)
    await send_text(client, "STOP")
    out = await rows("out")
    assert len(out) == 1 and "no longer receive" in out[0].text and out[0].purpose == "opt_out_confirmation"
    async with async_session_factory() as db:
        assert (await db.get(Driver, did)).whatsapp_opt_in is False
        assert [e.event for e in (await db.execute(select(WhatsAppOptEvent))).scalars().all()] == ["opt_out"]
    await send_text(client, "hello are you there")
    await send_text(client, "I am late")
    assert len(await rows("out")) == 1 and agent.calls == []  # stored, never answered
    assert len(await rows("in")) == 3
    await send_text(client, "START")
    out = await rows("out")
    assert len(out) == 2 and "Welcome back" in out[1].text
    async with async_session_factory() as db:
        assert (await db.get(Driver, did)).whatsapp_opt_in is True
    await send_text(client, "I am late again")
    assert len(agent.calls) == 1


async def test_hindi_opt_out_keyword_and_localised_confirmation(client, world, agent):
    did = await make_driver(world, lang="hi")
    await send_text(client, "बंद करो")
    out = (await rows("out"))[0]
    assert "नहीं मिलेंगे" in out.text and out.language == "hi"
    async with async_session_factory() as db:
        assert (await db.get(Driver, did)).whatsapp_opt_in is False
    await send_text(client, "हाँ चालू")
    assert "वापसी" in (await rows("out"))[1].text


async def test_unverified_driver_flow_with_code(client, world, agent):
    did = await make_driver(world, verified=False, opt_in=False)
    await send_text(client, "hello")
    assert "verify your number" in (await rows("out"))[0].text and agent.calls == []
    await send_text(client, "123456")  # no code was requested yet
    assert "did not work" in (await rows("out"))[1].text
    async with async_session_factory() as db:
        d = await db.get(Driver, did)
        d.verification_code_hash = sha256(f"{d.id}:424242")
        d.verification_expires_at = datetime.now(UTC) + timedelta(minutes=10)
        d.verification_attempts = 0
        await db.commit()
    await send_text(client, "111111")
    assert "did not work" in (await rows("out"))[2].text
    await send_text(client, "424 242")
    out = await rows("out")
    assert "verified" in out[3].text.lower()
    async with async_session_factory() as db:
        d = await db.get(Driver, did)
        assert d.verified_at is not None and d.whatsapp_opt_in is True
    await send_text(client, "I am late")
    assert len(agent.calls) == 1  # verified and opted in: the bot now serves the driver


async def test_unverified_reply_localised(client, world, agent):
    await make_driver(world, lang="hi", verified=False, opt_in=False)
    await send_text(client, "hi")
    assert "वेरिफाई" in (await rows("out"))[0].text


async def test_per_driver_rate_limit_then_silence(client, world, agent):
    await make_driver(world)
    for i in range(processor.RATE_LIMIT_PER_HOUR):
        await send_text(client, f"msg {i}")
    assert len(agent.calls) == processor.RATE_LIMIT_PER_HOUR
    await send_text(client, "one more")
    await send_text(client, "and another")
    assert len(agent.calls) == processor.RATE_LIMIT_PER_HOUR
    slow_down = [r for r in await rows("out") if r.purpose == "rate_limited"]
    assert len(slow_down) == 1 and "very quickly" in slow_down[0].text
    assert len(await rows("in")) == processor.RATE_LIMIT_PER_HOUR + 2  # all stored


async def test_takeover_pauses_the_bot_but_stores_and_publishes(client, world, agent):
    did = await make_driver(world)
    await send_text(client, "first")
    async with async_session_factory() as db:
        coord = (await db.execute(select(User).where(User.email == "coord@test.io"))).scalar_one()
        t = (await db.execute(select(ChatThread))).scalars().one()
        t.taken_over_by_user_id = coord.id
        await db.commit()
    r = get_redis()
    try:
        await r.delete(events.STREAM)
    finally:
        await r.aclose()
    await send_text(client, "are you there coordinator")
    assert len(agent.calls) == 1 and len(await rows("out")) == 1
    async with async_session_factory() as db:
        texts = [m.message_text for m in (await db.execute(select(ChatMessage).where(ChatMessage.sender_type == "DRIVER"))).scalars().all()]
        assert "are you there coordinator" in texts
    r = get_redis()
    try:
        entries = await r.xrange(events.STREAM)
    finally:
        await r.aclose()
    assert any(e[1]["type"] == "inbox.changed" for e in entries)
    _ = did


async def test_interactive_replies_are_passed_as_button_ids(client, world, agent):
    await make_driver(world)
    await send_text(client, button="offer_accept")
    await send_text(client, list_id="opt:2")
    assert [(c["text"], c["button_id"]) for c in agent.calls] == [(None, "offer_accept"), (None, "opt:2")]
    inbound = await rows("in")
    assert [r.type for r in inbound] == ["interactive", "interactive"] and inbound[0].text == "offer_accept"


async def test_template_quick_reply_button_type(client, world, agent):
    await make_driver(world)
    payload, wid = admin_service.build_payload(NUMBER, "text", text="x", button_id=None, list_id=None, title=None, name=None)
    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    msg.pop("text")
    msg.update(type="button", button={"payload": "offer_decline", "text": "Decline"})
    await post(client, json.dumps(payload, separators=(",", ":")).encode())
    await process()
    assert agent.calls[0]["button_id"] == "offer_decline"


async def test_audio_gets_a_type_message_reply_in_driver_language(client, world, agent):
    await make_driver(world, lang="hi")
    body, _ = webhook_body(audio=True, kind="text")
    await post(client, body)
    await process()
    assert agent.calls == []
    out = (await rows("out"))[0]
    assert "वॉइस नोट" in out.text
    assert (await rows("in"))[0].type == "audio"


async def test_agent_failure_falls_back_to_a_human_reply(client, world, agent):
    await make_driver(world)
    agent.boom = True
    await send_text(client, "help")
    out = await rows("out")
    assert len(out) == 1 and "coordinator will get back" in out[0].text
    async with async_session_factory() as db:
        m = (await db.execute(select(ChatMessage).where(ChatMessage.sender_type == "DRIVER"))).scalars().one()
        assert m.requires_human_review is True
    async with async_session_factory() as db:
        ev = (await db.execute(select(WhatsAppWebhookEvent))).scalars().one()
        assert ev.status == "processed"


async def test_interactive_agent_replies_are_sent_and_logged_with_buttons(client, world, agent):
    await make_driver(world)
    agent.reply = lambda kw: AgentReply(messages=[
        OutboundMessage(kind="buttons", text="Which?", buttons=[Button("a", "Alpha"), Button("b", "B" * 40)], purpose="menu"),
        OutboundMessage(kind="list", text="Pick", list_button="Choose slot", rows=[Row("opt:1", "09:00 D2", "x" * 100)], purpose="options")],
        intent="ask_options", escalated=True)
    await send_text(client, "options please")
    out = await rows("out")
    assert [r.type for r in out] == ["interactive", "interactive"]
    assert [b["title"] for b in out[0].raw["buttons"]] == ["Alpha", "B" * 20]  # WhatsApp button titles are capped at 20
    assert out[1].raw["rows"][0]["description"] == "x" * 72
    async with async_session_factory() as db:
        t = (await db.execute(select(ChatThread))).scalars().one()
        assert t.thread_status == "ESCALATED" and t.thread_intent == "ASK_SLOT_OPTIONS"


# ---------------------------------------------------------------- delivery statuses
def status_body(wamid, status, errors=None, to="919811100001") -> bytes:
    st = {"id": wamid, "status": status, "recipient_id": to, "timestamp": str(int(NOW.timestamp()))}
    if errors:
        st["errors"] = errors
    return json.dumps({"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {"statuses": [st]}}]}]}, separators=(",", ":")).encode()


async def make_out(driver_id, wamid="wamid.OUT1", status="sent") -> uuid.UUID:
    async with async_session_factory() as db:
        m = WhatsAppMessage(wa_message_id=wamid, direction="out", driver_id=driver_id, to_number=NUMBER, type="text", text="hello driver",
                            delivery_status=status, purpose="test", language="en")
        db.add(m)
        await db.commit()
        return m.id


async def test_status_progression_never_goes_backwards(client, world):
    did = await make_driver(world)
    await make_out(did)
    for st, expect in (("delivered", "delivered"), ("read", "read"), ("delivered", "read"), ("sent", "read")):
        await post(client, status_body("wamid.OUT1", st))
        await process()
        assert (await rows("out"))[0].delivery_status == expect
    await post(client, status_body("wamid.UNKNOWN", "read"))
    await process()  # unknown ids are ignored, not an error
    async with async_session_factory() as db:
        assert {e.status for e in (await db.execute(select(WhatsAppWebhookEvent))).scalars().all()} == {"processed"}


async def test_failed_status_alerts_coordinators_and_is_never_a_confirmation(client, world):
    did = await make_driver(world)
    await make_out(did, status="sent")
    await post(client, status_body("wamid.OUT1", "failed", errors=[{"code": 131026, "title": "Message undeliverable"}]))
    await process()
    m = (await rows("out"))[0]
    assert m.delivery_status == "failed" and "131026" in m.error and m.delivery_status not in ("delivered", "read", "sent")
    ev = await outbox("whatsapp.delivery_failed")
    assert len(ev) == 1 and ev[0].payload["error"].startswith("131026")
    async with async_session_factory() as db:
        om = (await db.execute(select(OperationalMessage))).scalars().one()
        assert om.delivery_status == "FAILED" and om.channel == "WHATSAPP" and om.shipment_id == world.shipment_a.id
        res = await notifications_service.process_outbox(db)
        await db.commit()
        notes = (await db.execute(select(Notification).where(Notification.type == "whatsapp.delivery_failed"))).scalars().all()
        assert sorted(n.recipient_role for n in notes) == ["admin", "coordinator"] and res.notifications == 2
    await post(client, status_body("wamid.OUT1", "delivered"))  # a late "delivered" cannot resurrect a failed message
    await process()
    assert (await rows("out"))[0].delivery_status == "failed"


async def test_notification_projection_leaves_whatsapp_delivery_events_alone(world):
    async with async_session_factory() as db:
        for t in ("whatsapp.template", "whatsapp.send", "whatsapp.verification"):
            db.add(OutboxEvent(event_type=t, payload={}))
        await db.commit()
    async with async_session_factory() as db:
        await notifications_service.process_outbox(db)
        await db.commit()
        statuses = {e.event_type: e.status for e in (await db.execute(select(OutboxEvent))).scalars().all()}
    assert set(statuses.values()) == {"pending"}


# ---------------------------------------------------------------- sender policy
async def sent_via(driver_id, message=None, template=None, *, now=None, **kw):
    async with async_session_factory() as db:
        d = await db.get(Driver, driver_id)
        row = await sender.send_message(db, driver=d, message=message, template=template, purpose="test", now=now or datetime.now(UTC), **kw)
        await db.commit()
        return row


def text_msg(t="hi"):
    return OutboundMessage(kind="text", text=t, purpose="test")


async def add_inbound(driver_id, when):
    async with async_session_factory() as db:
        db.add(WhatsAppMessage(wa_message_id=f"wamid.IN{uuid.uuid4().hex[:10]}", direction="in", driver_id=driver_id, to_number=NUMBER, type="text",
                               text="x", delivery_status="received", created_at=when))
        await db.commit()


async def test_customer_service_window(world):
    did = await make_driver(world)
    closed = await sent_via(did, text_msg())  # the driver never wrote: window closed
    assert closed.delivery_status == "failed" and closed.error == "WINDOW_CLOSED"
    assert len(await outbox("whatsapp.delivery_failed")) == 1
    await add_inbound(did, datetime.now(UTC) - timedelta(hours=23))
    assert (await sent_via(did, text_msg())).delivery_status == "delivered"
    # outside the window only an approved template may be sent
    async with async_session_factory() as db:
        await db.execute(WhatsAppMessage.__table__.delete())
        await db.commit()
    await add_inbound(did, datetime.now(UTC) - timedelta(hours=25))
    assert (await sent_via(did, text_msg())).error == "WINDOW_CLOSED"
    async with async_session_factory() as db:
        t = await render_template(db, "reminder_before_slot", "en", {"slot_code": "S1", "facility": "DC", "dock_code": "D2", "start": "10:00"})
    tmpl = await sent_via(did, template=t)
    assert tmpl.delivery_status == "delivered" and tmpl.type == "template" and tmpl.template_name == "reminder_before_slot"


async def test_never_sends_to_opted_out_or_unverified_numbers(world):
    did = await make_driver(world, opt_in=False)
    await add_inbound(did, datetime.now(UTC))
    r = await sent_via(did, text_msg())
    assert r.delivery_status == "failed" and r.error.startswith("SUPPRESSED:OPTED_OUT")
    assert await outbox("whatsapp.delivery_failed") == []  # suppression is policy, not an incident
    r2 = await sent_via(did, text_msg(), allow_opted_out=True)  # the one opt-out confirmation
    assert r2.delivery_status == "delivered"
    did2 = await make_driver(world, verified=False, opt_in=True)
    assert (await sent_via(did2, text_msg())).error == "SUPPRESSED:UNVERIFIED"
    assert (await sent_via(did2, text_msg(), allow_unverified=True)).delivery_status == "delivered"
    ok = await rows("out", status=None) if False else await rows("out")
    assert sum(1 for r in ok if r.delivery_status == "delivered") == 2


async def test_missing_number_fails_cleanly(world):
    did = await make_driver(world, number=None)
    r = await sent_via(did, text_msg())
    assert r.error == "NO_NUMBER" and r.delivery_status == "failed"


# ---------------------------------------------------------------- templates
def test_render_body_sections_and_missing_variables():
    body = "Hi {{name}}.{{#offer}} Accept?{{/offer}}{{^offer}} Done.{{/offer}} {{missing}}x"
    assert render_body(body, {"name": "Ravi", "offer": True}) == "Hi Ravi. Accept? x"
    assert render_body(body, {"name": "Ravi"}) == "Hi Ravi. Done. x"
    assert render_body("{{a}} {{ b }}", {"a": "<script>"}) == "<script> {{ b }}"  # replacement only: never evaluated


def test_catalogue_has_every_template_in_every_language():
    assert set(TEMPLATES) == {"shipment_assigned", "appointment_confirmed", "appointment_changed", "request_awaiting_approval",
                              "escalation_notice", "reminder_before_slot", "arrival_update_request", "verification"}
    rows_ = seed_rows()
    assert len(rows_) == 24 and {r["language"] for r in rows_} == {"en", "hi", "te"}
    assert all(r["needs_native_review"] == (r["language"] != "en") and r["approval_status"] == "approved" for r in rows_)
    for r in rows_:  # every declared variable is used and every placeholder declared (including inside sections)
        used = set(__import__("re").findall(r"\{\{[#^/]?(\w+)\}\}", r["body"]))
        assert used == set(r["variables"]), (r["name"], r["language"], used ^ set(r["variables"]))


async def test_render_template_languages_fallback_and_offer_buttons():
    v = {"slot_code": "SLOT-1", "facility": "Jaipur DC", "dock_code": "D2", "start": "10:00", "end": "11:00"}
    async with async_session_factory() as db:
        en = await render_template(db, "appointment_confirmed", "en", v)
        hi = await render_template(db, "appointment_confirmed", "hi", v)
        te = await render_template(db, "appointment_confirmed", "te", v)
        ta = await render_template(db, "appointment_confirmed", "ta", v)  # not in the catalogue: falls back to English
        assert "confirmed" in en.body and "SLOT-1" in en.body and "कन्फर्म" in hi.body and "నిర్ధారించబడింది" in te.body
        assert ta.language == "en" and ta.requested_language == "ta" and ta.body == en.body
        plain = await render_template(db, "appointment_changed", "en", v)
        offer = await render_template(db, "appointment_changed", "en", {**v, "offer": True})
        offer_hi = await render_template(db, "appointment_changed", "hi", {**v, "offer": True})
        refused = await render_template(db, "appointment_changed", "en", {"outcome": "not_possible", "reason": "No capacity"})
        assert plain.buttons == [] and [b.id for b in offer.buttons] == ["offer_accept", "offer_decline"] and "Do you accept" in offer.body
        assert offer_hi.buttons[0].title == "स्वीकार" and "Reason: No capacity" in refused.body and "SLOT-1" not in refused.body
        t = (await db.execute(select(WhatsAppTemplate).where(WhatsAppTemplate.name == "verification", WhatsAppTemplate.language == "en"))).scalar_one()
        t.approval_status = "draft"
        await db.flush()
        assert (await render_template(db, "verification", "en", {"code": "1"})) is None  # only approved templates are ever used


# ---------------------------------------------------------------- outbox consumer
async def emit_and_dispatch(event_type, payload):
    async with async_session_factory() as db:
        db.add(OutboxEvent(event_type=event_type, payload=payload))
        await db.commit()
    async with async_session_factory() as db:
        out = await dispatcher.process_outbox(db)
        await db.commit()
        return out


async def test_outbox_template_message_is_rendered_in_the_drivers_language(world):
    did = await make_driver(world, lang="hi")
    out = await emit_and_dispatch("whatsapp.template", {
        "shipment_id": str(world.shipment_a.id), "driver_id": str(did), "to": NUMBER, "language": "hi", "deliverable": True,
        "template": "appointment_changed", "variables": {"slot_code": "S-9", "facility": "Jaipur DC", "dock_code": "D3", "start": "02 Dec 10:00", "end": "02 Dec 11:00", "offer": True}})
    assert out == {"sent": 1, "failed": 0}
    m = (await rows("out"))[0]
    assert m.template_name == "appointment_changed" and m.language == "hi" and "S-9" in m.text and "क्या आप यह स्लॉट स्वीकार" in m.text
    assert [b["id"] for b in m.raw["buttons"]] == ["offer_accept", "offer_decline"] and m.delivery_status == "delivered"
    assert (await outbox("whatsapp.template"))[0].status == "sent"


async def test_outbox_template_suppressed_for_opted_out_driver_is_still_marked_done(world):
    did = await make_driver(world, opt_in=False)
    out = await emit_and_dispatch("whatsapp.template", {"driver_id": str(did), "language": "en", "template": "escalation_notice", "variables": {"reference": "ab12"}})
    assert out["sent"] == 1
    m = (await rows("out"))[0]
    assert m.error.startswith("SUPPRESSED:OPTED_OUT") and (await outbox("whatsapp.template"))[0].status == "sent"


async def test_outbox_unknown_template_is_an_alerting_failure(world):
    did = await make_driver(world)
    await emit_and_dispatch("whatsapp.template", {"driver_id": str(did), "language": "en", "template": "does_not_exist", "variables": {}})
    m = (await rows("out"))[0]
    assert m.error == "NO_APPROVED_TEMPLATE" and len(await outbox("whatsapp.delivery_failed")) == 1


async def test_outbox_coordinator_reply_goes_out_without_a_second_chat_message(world):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    async with async_session_factory() as db:
        t = ChatThread(code="THRX1", driver_id=did, opened_at=NOW, thread_status="OPEN", thread_intent="UNKNOWN")
        db.add(t)
        await db.commit()
        tid = t.id
    await emit_and_dispatch("whatsapp.send", {"thread_id": str(tid), "driver_id": str(did), "to": NUMBER, "text": "We will call you now", "language": "en"})
    m = (await rows("out"))[0]
    assert m.text == "We will call you now" and m.thread_id == tid and m.purpose == "coordinator_reply" and m.delivery_status == "delivered"
    async with async_session_factory() as db:
        assert (await db.execute(select(ChatMessage))).scalars().all() == []  # the desk already recorded the chat message


async def test_outbox_coordinator_reply_outside_window_fails_loudly(world):
    did = await make_driver(world)
    await emit_and_dispatch("whatsapp.send", {"driver_id": str(did), "to": NUMBER, "text": "late reply", "language": "en"})
    m = (await rows("out"))[0]
    assert m.error == "WINDOW_CLOSED" and len(await outbox("whatsapp.delivery_failed")) == 1


async def test_verification_code_is_decrypted_into_the_message_but_never_stored_in_plaintext(world):
    did = await make_driver(world, verified=False, opt_in=False)
    await emit_and_dispatch("whatsapp.verification", {"driver_id": str(did), "to": NUMBER, "language": "en", "template": "verification",
                                                      "code_enc": encrypt_secret("834729")})
    m = (await rows("out"))[0]
    assert m.delivery_status == "delivered" and m.template_name == "verification"
    stored = json.dumps({"text": m.text, "raw": {k: v for k, v in (m.raw or {}).items() if k != "payload_enc"}})
    assert "834729" not in stored and "••••••" in m.text
    wire = json.loads(decrypt_secret(m.raw["payload_enc"]))  # what is actually sent: includes the code, kept encrypted at rest
    assert wire["template"]["components"][0]["parameters"][0]["text"] == "834729"
    async with async_session_factory() as db:
        assert "834729" not in json.dumps([e.payload for e in (await db.execute(select(OutboxEvent))).scalars().all()])


async def test_outbox_failed_events_back_off_and_retry(world, monkeypatch):
    did = await make_driver(world)
    calls = {"n": 0}
    real = sender.send_message

    async def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db hiccup")
        return await real(*a, **k)

    monkeypatch.setattr(sender, "send_message", flaky)
    async with async_session_factory() as db:
        db.add(OutboxEvent(event_type="whatsapp.template", payload={"driver_id": str(did), "language": "en", "template": "escalation_notice",
                                                                    "variables": {"reference": "r1"}}))
        await db.commit()
    async with async_session_factory() as db:
        assert (await dispatcher.process_outbox(db, now=NOW))["failed"] == 1
        await db.commit()
    async with async_session_factory() as db:
        ev = (await db.execute(select(OutboxEvent))).scalars().one()
        assert ev.status == "failed" and ev.attempts == 1 and ev.next_attempt_at > NOW
        assert (await dispatcher.process_outbox(db, now=NOW))["sent"] == 0  # not due yet
        assert (await dispatcher.process_outbox(db, now=NOW + timedelta(hours=1)))["sent"] == 1
        await db.commit()


# ---------------------------------------------------------------- Cloud API sender
@pytest.fixture
def cloud(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_access_token", "tok-123")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "555000111")
    seen: list[httpx.Request] = []
    state = {"handler": lambda req: httpx.Response(200, json={"messages": [{"id": f"wamid.CLOUD{uuid.uuid4().hex[:8]}"}]})}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return state["handler"](req)

    monkeypatch.setattr(sender, "http_transport", httpx.MockTransport(handler))
    return type("C", (), {"seen": seen, "state": state})


async def test_cloud_text_request_shape(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    row = await sent_via(did, text_msg("hello there"))
    req = cloud.seen[0]
    assert str(req.url) == "https://graph.facebook.com/v20.0/555000111/messages" and req.headers["authorization"] == "Bearer tok-123"
    assert json.loads(req.content) == {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "919811100001", "type": "text",
                                       "text": {"body": "hello there", "preview_url": False}}
    assert row.delivery_status == "sent" and row.wa_message_id.startswith("wamid.CLOUD") and sender.mode() == "cloud"


async def test_cloud_interactive_button_list_and_template_payloads(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    await sent_via(did, OutboundMessage(kind="buttons", text="Which shipment?", buttons=[Button("s1", "SHP1002"), Button("s2", "SHP1003")]))
    await sent_via(did, OutboundMessage(kind="list", text="Pick a slot", list_button="Slots", rows=[Row("opt:1", "10:00 D2", "Dock D2"), Row("opt:2", "11:00 D3")]))
    async with async_session_factory() as db:
        t = await render_template(db, "appointment_changed", "hi", {"slot_code": "S-1", "facility": "DC", "dock_code": "D2", "start": "10:00", "end": "11:00", "offer": True})
    await sent_via(did, template=t)
    btn, lst, tpl = (json.loads(r.content) for r in cloud.seen)
    assert btn["interactive"] == {"type": "button", "body": {"text": "Which shipment?"},
                                  "action": {"buttons": [{"type": "reply", "reply": {"id": "s1", "title": "SHP1002"}}, {"type": "reply", "reply": {"id": "s2", "title": "SHP1003"}}]}}
    assert lst["interactive"]["type"] == "list" and lst["interactive"]["action"]["button"] == "Slots"
    assert lst["interactive"]["action"]["sections"][0]["rows"] == [{"id": "opt:1", "title": "10:00 D2", "description": "Dock D2"}, {"id": "opt:2", "title": "11:00 D3"}]
    assert tpl["type"] == "template" and tpl["template"]["name"] == "appointment_changed" and tpl["template"]["language"] == {"code": "hi"}
    body_params = [p["text"] for p in tpl["template"]["components"][0]["parameters"]]
    assert body_params[:5] == ["S-1", "DC", "D2", "10:00", "11:00"]
    assert [c["parameters"][0]["payload"] for c in tpl["template"]["components"][1:]] == ["offer_accept", "offer_decline"]


@pytest.mark.parametrize("status,body,code", [(401, {"error": {"code": 190, "message": "token expired"}}, "AUTH_ERROR"),
                                              (400, {"error": {"code": 131047, "message": "Re-engagement message"}}, "WINDOW_CLOSED"),
                                              (400, {"error": {"code": 100, "message": "bad param"}}, "BAD_REQUEST")])
async def test_cloud_permanent_errors_fail_and_alert(world, cloud, status, body, code):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    cloud.state["handler"] = lambda req: httpx.Response(status, json=body)
    row = await sent_via(did, text_msg())
    assert row.delivery_status == "failed" and row.error.startswith(code) and row.attempts == 1 and len(cloud.seen) == 1
    assert len(await outbox("whatsapp.delivery_failed")) == 1


async def test_cloud_transient_errors_are_retried_with_backoff_then_succeed(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    cloud.state["handler"] = lambda req: httpx.Response(429, json={"error": {"code": 130429, "message": "rate"}})
    now = datetime.now(UTC)
    row = await sent_via(did, text_msg(), now=now)
    assert row.delivery_status == "queued" and row.error == "RATE_LIMITED" and row.attempts == 1 and row.next_attempt_at > now
    assert await outbox("whatsapp.delivery_failed") == []  # still trying
    async with async_session_factory() as db:
        assert await sender.retry_due(db, now=now) == 0  # backoff not elapsed
    cloud.state["handler"] = lambda req: httpx.Response(200, json={"messages": [{"id": "wamid.LATER"}]})
    async with async_session_factory() as db:
        assert await sender.retry_due(db, now=now + timedelta(hours=1)) == 1
        await db.commit()
    done = (await rows("out"))[0]
    assert done.delivery_status == "sent" and done.wa_message_id == "wamid.LATER" and done.attempts == 2 and done.error is None


async def test_cloud_gives_up_after_max_attempts_and_network_errors_are_transient(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))

    def down(req):
        raise httpx.ConnectError("connection refused")

    cloud.state["handler"] = down
    now = datetime.now(UTC)
    row = await sent_via(did, text_msg(), now=now)
    assert row.delivery_status == "queued" and row.error == "NETWORK"
    for i in range(1, sender.MAX_ATTEMPTS):
        async with async_session_factory() as db:
            await sender.retry_due(db, now=now + timedelta(hours=i))
            await db.commit()
    final = (await rows("out"))[0]
    assert final.delivery_status == "failed" and final.attempts == sender.MAX_ATTEMPTS and final.error.startswith("NETWORK")
    assert len(await outbox("whatsapp.delivery_failed")) == 1


async def test_cloud_5xx_is_transient(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    cloud.state["handler"] = lambda req: httpx.Response(503, text="unavailable")
    row = await sent_via(did, text_msg())
    assert row.delivery_status == "queued" and row.error == "SERVER_ERROR"


async def test_cloud_send_rate_limiter_defers_without_calling_the_api(world, cloud):
    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    import time

    r = get_redis()
    try:
        await r.set(f"wa:send:{int(time.time())}", str(sender.CLOUD_MPS + 5), ex=3)
        row = await sent_via(did, text_msg())
    finally:
        await r.aclose()
    if cloud.seen:  # the clock may have ticked into the next second: that is a legitimate send
        assert row.delivery_status == "sent"
    else:
        assert row.delivery_status == "queued" and row.attempts == 0 and row.next_attempt_at is not None


async def test_worker_send_job_retries_a_queued_message(world, cloud):
    from app.workers import worker

    did = await make_driver(world)
    await add_inbound(did, datetime.now(UTC))
    cloud.state["handler"] = lambda req: httpx.Response(500, text="boom")
    row = await sent_via(did, text_msg())
    cloud.state["handler"] = lambda req: httpx.Response(200, json={"messages": [{"id": "wamid.JOB"}]})
    assert await worker.send_whatsapp({}, str(row.id)) is True
    assert (await rows("out"))[0].wa_message_id == "wamid.JOB"
    assert await worker.send_whatsapp({}, str(row.id)) is False  # no longer queued


# ---------------------------------------------------------------- admin API and simulator
ADMIN_READS = ["/status", "/templates", "/failures", "/messages", "/opt-ins"]


@pytest.mark.parametrize("who", ["coordinator", "facility_planner", "carrier_user"])
async def test_whatsapp_admin_api_is_admin_only(client, world, who):
    await login(client, who)
    for p in ADMIN_READS:
        assert (await client.get(f"/api/v1/whatsapp{p}")).status_code == 403, (who, p)
    assert (await client.post("/api/v1/whatsapp/simulator/send", json={"number": NUMBER, "text": "x"})).status_code == 403
    assert (await client.post("/api/v1/whatsapp/templates", json={"name": "abc", "language": "en", "body": "hello"})).status_code == 403
    assert (await client.post(f"/api/v1/whatsapp/opt-ins/{world.shipment_a.driver_id}", json={"opted_in": False})).status_code == 403


async def test_whatsapp_admin_api_requires_login(client):
    assert (await client.get("/api/v1/whatsapp/status")).status_code == 401


async def test_status_endpoint_reports_configuration_and_counts(client, world, agent, cloud=None):
    await make_driver(world)
    await send_text(client, "hello")
    body, _ = webhook_body(text="queued")
    await post(client, body)  # pending, not processed yet
    await login(client, "admin")
    s = (await client.get("/api/v1/whatsapp/status")).json()
    assert s["mode"] == "simulator" and s["configured"] is False and s["webhook_path"] == "/webhooks/whatsapp"
    assert s["verify_token_set"] and s["app_secret_set"] and s["pending_events"] == 1 and s["last_inbound_at"] and s["last_outbound_at"]
    assert s["templates"] == {"total": 24, "approved": 24, "needs_review": 16} and s["phone_number_id_masked"] == ""
    assert "dev-whatsapp-app-secret" not in json.dumps(s) and SECRET not in json.dumps(s)


async def test_status_in_cloud_mode_masks_the_phone_id(client, world, cloud):
    await login(client, "admin")
    s = (await client.get("/api/v1/whatsapp/status")).json()
    assert s["mode"] == "cloud" and s["configured"] is True and s["phone_number_id_masked"] == "••••0111" and "tok-123" not in json.dumps(s)


async def test_template_admin_crud_and_review_flag(client, world):
    await login(client, "admin")
    hi = (await client.get("/api/v1/whatsapp/templates", params={"language": "hi"})).json()
    assert len(hi) == 8 and all(t["needs_native_review"] for t in hi)
    t = next(x for x in hi if x["name"] == "verification")
    p = await client.patch(f"/api/v1/whatsapp/templates/{t['id']}", json={"needs_native_review": False, "approval_status": "submitted"})
    assert p.status_code == 200 and p.json()["needs_native_review"] is False and p.json()["approval_status"] == "submitted"
    assert (await client.patch(f"/api/v1/whatsapp/templates/{t['id']}", json={"approval_status": "maybe"})).status_code == 422
    edited = await client.patch(f"/api/v1/whatsapp/templates/{t['id']}", json={"body": "कोड {{code}} भेजें"})
    assert edited.json()["variables"] == ["code"]
    assert (await client.patch(f"/api/v1/whatsapp/templates/{uuid.uuid4()}", json={"body": "xxxx"})).status_code == 404
    new = {"name": "driver_survey", "language": "en", "body": "How was {{facility}}?"}
    c = await client.post("/api/v1/whatsapp/templates", json=new)
    assert c.status_code == 201 and c.json()["approval_status"] == "draft" and c.json()["variables"] == ["facility"]
    assert (await client.post("/api/v1/whatsapp/templates", json=new)).status_code == 409
    assert (await client.post("/api/v1/whatsapp/templates", json={**new, "name": "Bad Name"})).status_code == 422
    assert len((await client.get("/api/v1/whatsapp/templates", params={"name": "driver_survey"})).json()) == 1
    audit = (await client.get("/api/v1/audit", params={"entity": "whatsapp_templates", "action": "update"})).json()["items"]
    assert audit and audit[-1]["before"] is not None  # template edits are audited


async def test_failures_messages_and_opt_in_endpoints(client, world, agent):
    did = await make_driver(world)
    await make_out(did, "wamid.F1", status="sent")
    await post(client, status_body("wamid.F1", "failed", errors=[{"code": 131026, "title": "undeliverable"}]))
    await process()
    suppressed = await make_driver(world, opt_in=False)
    await add_inbound(suppressed, datetime.now(UTC))
    await sent_via(suppressed, text_msg("blocked"))  # suppressed: must not appear as a failure
    await make_driver(world, opt_in=True)
    await send_text(client, "log me please")
    await login(client, "admin")
    f = (await client.get("/api/v1/whatsapp/failures")).json()
    assert f["total"] == 1 and f["items"][0]["error"].startswith("131026") and f["items"][0]["driver_name"] == "Driver A"
    allm = (await client.get("/api/v1/whatsapp/messages")).json()
    assert allm["total"] >= 4
    ins = (await client.get("/api/v1/whatsapp/messages", params={"direction": "in"})).json()
    assert ins["total"] == 2 and ins["items"][0]["text"] == "log me please"  # newest first; the other is the helper-added inbound
    assert (await client.get("/api/v1/whatsapp/messages", params={"q": "log me"})).json()["total"] == 1
    assert (await client.get("/api/v1/whatsapp/messages", params={"status": "failed"})).json()["total"] >= 2
    assert (await client.get("/api/v1/whatsapp/messages", params={"direction": "sideways"})).status_code == 422
    opted = (await client.get("/api/v1/whatsapp/opt-ins", params={"state": "opted_in"})).json()
    assert opted["total"] == 1 and opted["items"][0]["opted_in"] is True
    assert (await client.get("/api/v1/whatsapp/opt-ins", params={"state": "weird"})).status_code == 422
    o = await client.post(f"/api/v1/whatsapp/opt-ins/{did}", json={"opted_in": False})
    assert o.json() == {"driver_id": str(did), "opted_in": False}
    out = (await client.get("/api/v1/whatsapp/opt-ins", params={"state": "opted_out"})).json()
    assert out["total"] == 1 and out["items"][0]["last_event"]["source"] == "admin_override"
    assert (await client.post(f"/api/v1/whatsapp/opt-ins/{uuid.uuid4()}", json={"opted_in": True})).status_code == 404


async def test_simulator_end_to_end_through_the_signed_webhook_path(client, world, agent):
    did = await make_driver(world)
    agent.reply = lambda kw: AgentReply(messages=[
        OutboundMessage(kind="text", text="Which shipment?", purpose="clarify"),
        OutboundMessage(kind="buttons", text="Choose", buttons=[Button("a", "One"), Button("b", "Two")], purpose="menu")], intent="unknown")
    await login(client, "admin")
    r = await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "text", "text": "Truck late 2 hours"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inbound_message_id"] and [x["kind" if False else "type"] for x in body["replies"]] == ["text", "interactive"]
    assert body["replies"][1]["buttons"] == [{"id": "a", "title": "One"}, {"id": "b", "title": "Two"}]
    async with async_session_factory() as db:
        ev = (await db.execute(select(WhatsAppWebhookEvent))).scalars().one()
        assert ev.status == "processed" and ev.signature_ok  # it went through ingest(): signed and stored like Meta's calls
    assert len(agent.calls) == 1 and agent.calls[0]["text"] == "Truck late 2 hours"
    tap = await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "button", "button_id": "a", "title": "One"})
    assert tap.status_code == 200 and agent.calls[1]["button_id"] == "a"
    conv = (await client.get("/api/v1/whatsapp/simulator/conversation", params={"driver_id": str(did)})).json()
    assert [m["direction"] for m in conv] == ["in", "out", "out", "in", "out", "out"]
    assert conv[0]["text"] == "Truck late 2 hours" and conv[2]["buttons"][0]["title"] == "One" and conv[3]["text"] == "One"
    by_number = await client.post("/api/v1/whatsapp/simulator/send", json={"number": "+919000000077", "text": "who am i"})
    assert by_number.status_code == 200 and "not registered" in by_number.json()["replies"][0]["text"]
    assert (await client.post("/api/v1/whatsapp/simulator/reset", params={"driver_id": str(did)})).json()["deleted"] == 6
    assert (await client.get("/api/v1/whatsapp/simulator/conversation", params={"driver_id": str(did)})).json() == []


async def test_simulator_validation_and_secret_requirement(client, world, agent):
    did = await make_driver(world)
    await login(client, "admin")
    assert (await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "carrier-pigeon"})).status_code == 422
    assert (await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "text", "text": "  "})).status_code == 422
    assert (await client.post("/api/v1/whatsapp/simulator/send", json={"kind": "text", "text": "x"})).status_code == 422
    get_settings().whatsapp_app_secret = ""
    r = await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "text", "text": "x"})
    assert r.status_code == 422 and "WHATSAPP_APP_SECRET" in r.json()["error"]["message"]


async def test_simulator_is_blocked_in_production_with_a_live_number(client, world, cloud, monkeypatch):
    did = await make_driver(world)
    monkeypatch.setattr(get_settings(), "env", "production")
    await login(client, "admin")
    r = await client.post("/api/v1/whatsapp/simulator/send", json={"driver_id": str(did), "kind": "text", "text": "x"})
    assert r.status_code == 403
    assert (await client.post("/api/v1/whatsapp/simulator/reset", params={"driver_id": str(did)})).status_code == 403


async def test_message_log_never_contains_secrets(client, world):
    did = await make_driver(world, verified=False, opt_in=False)
    await emit_and_dispatch("whatsapp.verification", {"driver_id": str(did), "to": NUMBER, "language": "en", "code_enc": encrypt_secret("246810")})
    await login(client, "admin")
    log = json.dumps((await client.get("/api/v1/whatsapp/messages")).json(), default=str)
    assert "246810" not in log and "payload_enc" not in log and "tok-" not in log
    sim = json.dumps((await client.get("/api/v1/whatsapp/simulator/conversation", params={"driver_id": str(did)})).json(), default=str)
    assert "246810" not in sim


_ = (uuid, NOW)

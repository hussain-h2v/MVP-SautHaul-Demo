"""WhatsApp simulator CLI: sends a signed, Cloud-API-shaped webhook like Meta would, then processes it and prints the bot's replies.

  python -m scripts.wa_simulator --number +919876543210 "Truck broke down, 2 hours late"
  python -m scripts.wa_simulator --number +919876543210 --button offer_accept
  python -m scripts.wa_simulator --number +919876543210 --list opt:1

With --base-url the payload is POSTed to <base-url>/webhooks/whatsapp (the real endpoint); pending events are then processed
in-process (so it works without a running worker) and the replies read from the database."""
import argparse
import asyncio
import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.core import audit_events
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.modules.whatsapp import admin_service, processor
from app.modules.whatsapp.models import WhatsAppMessage


def _fmt(m: WhatsAppMessage) -> str:
    raw = m.raw or {}
    lines = [f"  bot [{m.language or '-'}] ({m.delivery_status}): {m.text}"]
    for b in raw.get("buttons") or []:
        lines.append(f"      [button] {b['id']}: {b['title']}")
    for r in raw.get("rows") or []:
        lines.append(f"      [row] {r['id']}: {r['title']}" + (f" - {r['description']}" if r.get("description") else ""))
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="?", help="message text")
    ap.add_argument("--number", required=True, help="driver WhatsApp number, e.g. +919876543210")
    ap.add_argument("--button", help="tap a reply button (its id)")
    ap.add_argument("--list", dest="list_id", help="pick a list row (its id)")
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()
    kind = "button" if args.button else "list" if args.list_id else "text"
    if kind == "text" and not args.text:
        ap.error("give message text, --button or --list")
    secret = get_settings().whatsapp_app_secret
    if not secret:
        raise SystemExit("WHATSAPP_APP_SECRET is not set")
    audit_events.install()
    payload, wamid = admin_service.build_payload(args.number, kind, text=args.text, button_id=args.button, list_id=args.list_id,
                                                 title=None, name=None)
    body = json.dumps(payload, separators=(",", ":")).encode()
    start = datetime.now(UTC)
    r = httpx.post(f"{args.base_url.rstrip('/')}/webhooks/whatsapp", content=body,
                   headers={"Content-Type": "application/json", "X-Hub-Signature-256": processor.sign(body, secret)}, timeout=20)
    print(f"webhook -> {r.status_code} {r.text}")
    async with async_session_factory() as db:
        n = await processor.process_pending(db)
        replies = list((await db.execute(select(WhatsAppMessage).where(
            WhatsAppMessage.direction == "out", WhatsAppMessage.to_number == processor.normalise_number(args.number),
            WhatsAppMessage.created_at >= start).order_by(WhatsAppMessage.created_at))).scalars().all())
    print(f"processed {n} event(s); {len(replies)} repl{'y' if len(replies) == 1 else 'ies'}:")
    for m in replies:
        print(_fmt(m))
    _ = wamid


if __name__ == "__main__":
    asyncio.run(main())

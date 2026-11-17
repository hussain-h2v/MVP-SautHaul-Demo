"""Create one demo user per role on top of the seeded reference data (dev/demo only).
Usage: python -m scripts.seed_demo_users   (password from DEMO_PASSWORD or a documented dev default)"""
import asyncio
import os

from sqlalchemy import select

from app.core import audit_events
from app.core.db import async_session_factory
from app.core.security import hash_password
from app.modules.carriers.models import Carrier
from app.modules.facilities.models import Facility
from app.modules.users.models import User, UserScope

PASSWORD = os.environ.get("DEMO_PASSWORD", "SetuHaul-Demo-2026")


async def main() -> None:
    audit_events.install()
    async with async_session_factory() as db:
        fac = (await db.execute(select(Facility).order_by(Facility.code))).scalars().first()
        car = (await db.execute(select(Carrier).order_by(Carrier.code))).scalars().first()
        if fac is None or car is None:
            raise SystemExit("Run scripts.seed_reference first")
        spec = [
            ("admin@setuhaul.demo", "Asha Admin", "admin", None, None),
            ("planner@setuhaul.demo", f"Priya Planner ({fac.code})", "facility_planner", fac.id, None),
            ("coordinator@setuhaul.demo", "Rahul Coordinator", "coordinator", None, None),
            ("carrier@setuhaul.demo", f"Karan Carrier ({car.code})", "carrier_user", None, car.id),
        ]
        for email, name, role, fid, cid in spec:
            if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
                continue
            u = User(email=email, full_name=name, role=role, status="active", password_hash=hash_password(PASSWORD))
            db.add(u)
            await db.flush()
            if fid:
                db.add(UserScope(user_id=u.id, facility_id=fid))
            if cid:
                db.add(UserScope(user_id=u.id, carrier_id=cid))
            print("created", email, role)
        await db.commit()
    print(f"demo password: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())

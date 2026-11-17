from tests.conftest import EMAILS, PASSWORD, login


async def test_login_sets_cookies_and_me(client, world):
    resp = await login(client, "admin")
    body = resp.json()
    assert body["role"] == "admin" and body["scopes"]["all_facilities"] is True
    assert body["capabilities"]["system_settings"] == "W"
    set_cookie = resp.headers.get_list("set-cookie")
    assert any("access_token" in c and "HttpOnly" in c for c in set_cookie)
    assert any("csrf_token" in c and "HttpOnly" not in c for c in set_cookie)
    assert (await client.get("/api/v1/auth/me")).json()["email"] == EMAILS["admin"]


async def test_wrong_password_and_unknown_user_are_401(client, world):
    for email in (EMAILS["admin"], "nobody@test.io"):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401


async def test_account_locks_after_repeated_failures(client, world):
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"email": EMAILS["admin"], "password": "wrong-password"})
    r = await client.post("/api/v1/auth/login", json={"email": EMAILS["admin"], "password": PASSWORD})
    assert r.status_code == 423


async def test_login_is_rate_limited(client, world):
    codes = [
        (await client.post("/api/v1/auth/login", json={"email": "nobody@test.io", "password": "x"})).status_code
        for _ in range(25)
    ]
    assert 429 in codes


async def test_me_requires_login(client, world):
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_csrf_required_on_cookie_writes(client, world):
    await login(client, "admin")
    del client.headers["X-CSRF-Token"]
    r = await client.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "x" * 12})
    assert r.status_code == 403


async def test_logout_revokes_session(client, world):
    await login(client, "admin")
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.set("access_token", "stale")  # even a captured access token must not work after revoke
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_refresh_rotates_token(client, world):
    await login(client, "admin")
    old = client.cookies.get("refresh_token")
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 204
    assert client.cookies.get("refresh_token") != old
    client.cookies.set("refresh_token", old, path="/api/v1/auth")
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_force_logout_kills_live_access_token(client, world):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as victim:
        await login(victim, "carrier_user")
        await login(client, "admin")
        users = (await client.get("/api/v1/users")).json()
        uid = next(u["id"] for u in users if u["email"] == EMAILS["carrier_user"])
        assert (await client.post(f"/api/v1/users/{uid}/force-logout")).status_code == 204
        assert (await victim.get("/api/v1/auth/me")).status_code == 401


async def test_invite_accept_login_flow(client, world):
    await login(client, "admin")
    fid = str(world.facility_a.id)
    r = await client.post("/api/v1/users", json={
        "email": "New.Planner@test.io", "full_name": "New Planner", "role": "facility_planner", "facility_ids": [fid]})
    assert r.status_code == 201
    token = r.json()["invite_token"]
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/login", json={"email": "new.planner@test.io", "password": "x" * 12})).status_code == 401
    assert (await client.post("/api/v1/auth/accept-invite", json={"token": token, "password": "BrandNewPass123"})).status_code == 204
    assert (await client.post("/api/v1/auth/accept-invite", json={"token": token, "password": "AnotherPass1234"})).status_code == 403
    ok = await client.post("/api/v1/auth/login", json={"email": "new.planner@test.io", "password": "BrandNewPass123"})
    assert ok.status_code == 200 and ok.json()["scopes"]["facility_ids"] == [fid]


async def test_planner_invite_requires_facility(client, world):
    await login(client, "admin")
    r = await client.post("/api/v1/users", json={"email": "x@test.io", "full_name": "X", "role": "facility_planner"})
    assert r.status_code == 422

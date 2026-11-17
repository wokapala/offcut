"""Uwierzytelnianie, CSRF, role i izolacja warsztatów."""

from tests.conftest import PASSWORD


def test_register_login_me(api):
    api.register("a@test.pl", "Warsztat A")
    me = api.ok("GET", "/api/auth/me")
    assert me["email"] == "a@test.pl"
    assert me["memberships"][0]["role"] == "OWNER"
    data = api.login("A@Test.pl")  # e-mail normalizowany
    assert data["csrf_token"]


def test_session_cookie_is_httponly(client):
    r = client.post("/api/auth/register", json={"email": "c@test.pl", "password": PASSWORD,
                                                 "full_name": "C", "workshop_name": "W"})
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("offcut_session="))
    assert "httponly" in session.lower() and "samesite=lax" in session.lower()
    csrf = next(c for c in cookies if c.startswith("offcut_csrf="))
    assert "httponly" not in csrf.lower()


def test_password_is_hashed(api, db):
    from app.models import User

    api.register("h@test.pl")
    user = db.query(User).filter_by(email="h@test.pl").one()
    assert user.password_hash.startswith("$argon2") and PASSWORD not in user.password_hash


def test_bad_credentials(api, client):
    api.register("a@test.pl")
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": "a@test.pl", "password": "zle-haslo"})
    assert r.status_code == 401 and r.json()["code"] == "BAD_CREDENTIALS"
    r = client.post("/api/auth/login", json={"email": "nie@ma.pl", "password": "zle-haslo"})
    assert r.status_code == 401


def test_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/workshops/1/stock").status_code == 401


def test_csrf_required_for_mutations(api, client):
    ws = api.register("a@test.pl")
    del client.headers["X-CSRF-Token"]
    r = client.post(f"/api/workshops/{ws}/materials", json={"material": "Sosna", "section": "40x20"})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_FAILED"
    client.headers["X-CSRF-Token"] = "falszywy"
    r = client.post(f"/api/workshops/{ws}/materials", json={"material": "Sosna", "section": "40x20"})
    assert r.status_code == 403
    assert client.get(f"/api/workshops/{ws}/materials").status_code == 200  # GET bez CSRF


def test_validation_errors(api):
    ws = api.register("a@test.pl")
    spec = api.spec(ws)
    r = api.c.post(f"/api/workshops/{ws}/stock", json={"material_spec_id": spec, "length_mm": 0})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    pid = api.project(ws)
    r = api.c.post(f"/api/projects/{pid}/demand", json={"material_spec_id": spec, "length_mm": 500,
                                                         "quantity": 0})
    assert r.status_code == 422
    r = api.c.post(f"/api/workshops/{ws}/projects", json={"name": "X", "kerf_mm": -1})
    assert r.status_code == 422


def test_other_workshop_is_invisible_also_by_direct_id(api, demo):
    plans = api.ok("POST", f"/api/projects/{demo['project']}/optimize")
    plan_id = plans["branch_and_bound"]["plan"]["id"]
    stock_id = demo["stock"][0]

    api.c.cookies.clear()
    other_ws = api.register("obcy@test.pl", "Obcy warsztat")
    other_spec = api.spec(other_ws)
    for url in (f"/api/workshops/{demo['ws']}/stock", f"/api/workshops/{demo['ws']}/projects",
                f"/api/projects/{demo['project']}", f"/api/plans/{plan_id}", f"/api/stock/{stock_id}",
                f"/api/projects/{demo['project']}/plans"):
        assert api.c.get(url).status_code == 404, url
    assert api.c.post(f"/api/plans/{plan_id}/reserve").status_code == 404
    assert api.c.post(f"/api/plans/{plan_id}/execute").status_code == 404
    assert api.c.delete(f"/api/stock/{stock_id}").status_code == 404
    assert api.c.post(f"/api/projects/{demo['project']}/demand",
                      json={"material_spec_id": other_spec, "length_mm": 100, "quantity": 1}).status_code == 404
    # własny projekt nie może użyć specyfikacji z cudzego warsztatu
    own = api.project(other_ws)
    r = api.c.post(f"/api/projects/{own}/demand",
                   json={"material_spec_id": demo["spec"], "length_mm": 100, "quantity": 1})
    assert r.status_code == 404


def test_operator_role_limits(api, demo):
    api.login("operator@test.pl")
    ws, pid = demo["ws"], demo["project"]
    assert api.c.get(f"/api/workshops/{ws}/stock").status_code == 200
    assert api.c.get(f"/api/projects/{pid}").status_code == 200
    forbidden = [
        ("POST", f"/api/workshops/{ws}/stock", {"material_spec_id": demo["spec"], "length_mm": 100}),
        ("POST", f"/api/workshops/{ws}/materials", {"material": "Buk", "section": "20x20"}),
        ("POST", f"/api/workshops/{ws}/projects", {"name": "X"}),
        ("POST", f"/api/projects/{pid}/demand", {"material_spec_id": demo["spec"], "length_mm": 1, "quantity": 1}),
        ("POST", f"/api/projects/{pid}/optimize", None),
        ("DELETE", f"/api/stock/{demo['stock'][0]}", None),
    ]
    for method, url, body in forbidden:
        r = api.c.request(method, url, json=body)
        assert r.status_code == 403, (url, r.text)
        assert r.json()["code"] == "OWNER_REQUIRED"


def test_operator_can_execute_but_not_reserve(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.login("operator@test.pl")
    assert api.c.post(f"/api/plans/{plan['id']}/reserve").status_code == 403
    api.login("owner@test.pl")
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    api.login("operator@test.pl")
    out = api.ok("POST", f"/api/plans/{plan['id']}/execute")
    assert out["plan"]["status"] == "EXECUTED"
    assert out["plan"]["execution"]["executed_by"] == "Operator"

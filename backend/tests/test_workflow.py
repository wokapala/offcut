"""Optymalizacja przez API, rezerwacja, wykonanie, resztki, konflikty i transakcje."""

import threading

import pytest
from sqlalchemy import func, select


def stock_by_id(api, ws):
    return {s["id"]: s for s in api.ok("GET", f"/api/workshops/{ws}/stock?status=ALL")}


def test_full_flow_login_demand_optimize_reserve_execute_remnants(api, demo):
    ws, pid = demo["ws"], demo["project"]
    api.login("owner@test.pl")

    result = api.ok("POST", f"/api/projects/{pid}/optimize")
    greedy, bnb = result["greedy"], result["branch_and_bound"]
    assert greedy["status"] == "HEURISTIC" and bnb["status"] == "OPTIMAL"
    assert greedy["plan"]["total_stock_mm"] == 5450 and greedy["plan"]["stock_count"] == 4
    assert bnb["plan"]["total_stock_mm"] == 4900 and bnb["plan"]["stock_count"] == 2
    assert result["comparison"]["stock_saved_mm"] == 550
    assert result["shortages"] == []
    plan = bnb["plan"]
    # bilans każdego odcinka i całości
    for bar in plan["bars"]:
        assert bar["stock_length_mm"] == sum(p["length_mm"] for p in bar["pieces"]) \
            + bar["kerf_loss_mm"] + bar["remainder_mm"]
    assert plan["total_stock_mm"] == plan["pieces_mm"] + plan["kerf_loss_mm"] \
        + plan["usable_remnant_mm"] + plan["scrap_mm"]

    reserved = api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    assert reserved["status"] == "RESERVED"
    used_ids = [b["stock_item_id"] for b in plan["bars"]]
    stock = stock_by_id(api, ws)
    assert all(stock[i]["status"] == "RESERVED" and stock[i]["reserved_plan_id"] == plan["id"] for i in used_ids)
    assert api.ok("GET", f"/api/projects/{pid}")["state"] == "RESERVED"

    out = api.ok("POST", f"/api/plans/{plan['id']}/execute")
    assert out["already_executed"] is False
    assert sorted(r["length_mm"] for r in out["remnants"]) == [344, 358]
    stock = stock_by_id(api, ws)
    assert all(stock[i]["status"] == "CONSUMED" for i in used_ids)
    for r in out["remnants"]:
        s = stock[r["id"]]
        assert s["status"] == "AVAILABLE" and s["is_remnant"]
        assert s["parent_stock_id"] in used_ids and s["source_plan_id"] == plan["id"]
    assert api.ok("GET", f"/api/projects/{pid}")["state"] == "EXECUTED"
    # nowe resztki są widoczne w filtrze resztek magazynu
    remnants = api.ok("GET", f"/api/workshops/{ws}/stock?remnants_only=true")
    assert {r["id"] for r in out["remnants"]} <= {r["id"] for r in remnants}


def test_execute_retry_does_not_consume_twice(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    first = api.ok("POST", f"/api/plans/{plan['id']}/execute")
    before = stock_by_id(api, demo["ws"])
    second = api.ok("POST", f"/api/plans/{plan['id']}/execute")
    assert second["already_executed"] is True
    assert [r["id"] for r in second["remnants"]] == [r["id"] for r in first["remnants"]]
    assert stock_by_id(api, demo["ws"]) == before


def test_double_reservation_of_same_stock_is_blocked(api, demo):
    ws, spec = demo["ws"], demo["spec"]
    plan_a = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    other = api.project(ws, "Drugi projekt", demand=[(spec, 560, 3), (spec, 950, 2), (spec, 600, 1)])
    plan_b = api.ok("POST", f"/api/projects/{other}/optimize")["branch_and_bound"]["plan"]
    assert {b["stock_item_id"] for b in plan_a["bars"]} == {b["stock_item_id"] for b in plan_b["bars"]}

    api.ok("POST", f"/api/plans/{plan_a['id']}/reserve")
    r = api.c.post(f"/api/plans/{plan_b['id']}/reserve")
    assert r.status_code == 409 and r.json()["code"] == "STOCK_UNAVAILABLE"
    assert r.json()["problems"]
    # po zwolnieniu rezerwacji A plan B można zarezerwować
    released = api.ok("POST", f"/api/plans/{plan_a['id']}/release")
    assert released["status"] == "DRAFT"
    api.ok("POST", f"/api/plans/{plan_b['id']}/reserve")


def test_only_one_active_plan_per_project(api, demo):
    result = api.ok("POST", f"/api/projects/{demo['project']}/optimize")
    api.ok("POST", f"/api/plans/{result['branch_and_bound']['plan']['id']}/reserve")
    r = api.c.post(f"/api/plans/{result['greedy']['plan']['id']}/reserve")
    assert r.status_code == 409


def test_stale_plan_cannot_be_reserved(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/projects/{demo['project']}/demand", 201,
           json={"material_spec_id": demo["spec"], "length_mm": 400, "quantity": 1})
    assert api.ok("GET", f"/api/plans/{plan['id']}")["is_current"] is False
    r = api.c.post(f"/api/plans/{plan['id']}/reserve")
    assert r.status_code == 409 and r.json()["code"] == "STALE_PLAN"


def test_parameter_change_invalidates_plan(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("PATCH", f"/api/projects/{demo['project']}", json={"kerf_mm": 4})
    r = api.c.post(f"/api/plans/{plan['id']}/reserve")
    assert r.status_code == 409 and r.json()["code"] == "STALE_PLAN"
    # zmiana samej nazwy nie unieważnia planu
    plan2 = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("PATCH", f"/api/projects/{demo['project']}", json={"name": "Nowa nazwa"})
    api.ok("POST", f"/api/plans/{plan2['id']}/reserve")


def test_project_locked_while_reserved(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    r = api.c.post(f"/api/projects/{demo['project']}/demand",
                   json={"material_spec_id": demo["spec"], "length_mm": 400, "quantity": 1})
    assert r.status_code == 409 and r.json()["code"] == "PROJECT_LOCKED"
    assert api.c.post(f"/api/projects/{demo['project']}/optimize").status_code == 409


def test_execute_requires_reservation(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    r = api.c.post(f"/api/plans/{plan['id']}/execute")
    assert r.status_code == 409 and r.json()["code"] == "PLAN_NOT_RESERVED"


def test_discarded_stock_makes_draft_plan_unreservable(api, demo):
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("DELETE", f"/api/stock/{plan['bars'][0]['stock_item_id']}")
    r = api.c.post(f"/api/plans/{plan['id']}/reserve")
    assert r.status_code == 409 and r.json()["code"] == "STOCK_UNAVAILABLE"


def test_not_enough_material_reports_shortage(api):
    ws = api.register("a@test.pl")
    spec = api.spec(ws)
    api.stock(ws, spec, [3000, 3000])
    pid = api.project(ws, demand=[(spec, 2900, 3)])
    result = api.ok("POST", f"/api/projects/{pid}/optimize")
    assert result["branch_and_bound"]["status"] == "INFEASIBLE"
    assert result["greedy"]["plan"] is None and result["branch_and_bound"]["plan"] is None
    assert result["shortages"][0]["available_count"] == 2
    assert "nie wystarczy" in result["shortages"][0]["message"]
    assert api.ok("GET", f"/api/projects/{pid}/plans") == []


def test_incompatible_material_is_not_used(api):
    ws = api.register("a@test.pl")
    pine, oak = api.spec(ws, "Sosna"), api.spec(ws, "Dąb")
    api.stock(ws, oak, [3000])
    pid = api.project(ws, demand=[(pine, 500, 1)])
    result = api.ok("POST", f"/api/projects/{pid}/optimize")
    assert result["branch_and_bound"]["status"] == "INFEASIBLE"
    assert result["shortages"][0]["available_count"] == 0


def test_empty_demand_rejected(api):
    ws = api.register("a@test.pl")
    pid = api.project(ws)
    r = api.c.post(f"/api/projects/{pid}/optimize")
    assert r.status_code == 422 and r.json()["code"] == "EMPTY_DEMAND"


def test_manual_plan_uses_same_validator(api, demo):
    ws, spec, pid = demo["ws"], demo["spec"], demo["project"]
    project = api.ok("GET", f"/api/projects/{pid}")
    d = {item["length_mm"]: item["id"] for item in project["demand_items"]}
    s = {v["length_mm"]: k for k, v in stock_by_id(api, ws).items()}
    good = {"bars": [
        {"stock_item_id": s[3000], "demand_item_ids": [d[950], d[950], d[560]]},
        {"stock_item_id": s[1900], "demand_item_ids": [d[560], d[560], d[600]]},
    ]}
    plan = api.ok("POST", f"/api/projects/{pid}/plans/manual", 201, json=good)
    assert plan["method"] == "MANUAL" and plan["total_stock_mm"] == 4900

    oak = api.spec(ws, "Dąb")
    oak_stock = api.stock(ws, oak, [3000])[0]
    bad = {"bars": [{"stock_item_id": oak_stock, "demand_item_ids": [d[950], d[950], d[560], d[560], d[560], d[600]]}]}
    r = api.c.post(f"/api/projects/{pid}/plans/manual", json=bad)
    assert r.status_code == 422 and any("innego materiału" in p for p in r.json()["problems"])

    overfull = {"bars": [{"stock_item_id": s[900], "demand_item_ids": [d[950]]}]}
    r = api.c.post(f"/api/projects/{pid}/plans/manual", json=overfull)
    assert r.status_code == 422
    problems = " ".join(r.json()["problems"])
    assert "zajmują" in problems and "wymagane" in problems


def test_execution_rolls_back_completely_on_error(api, demo, monkeypatch, db):
    from app.models import CuttingPlan, PlanExecution, StockItem
    from app.services import workflow

    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")

    def boom(*_args, **_kwargs):
        raise RuntimeError("awaria w trakcie zapisu resztek")

    monkeypatch.setattr(workflow, "create_remnants", boom)
    with pytest.raises(RuntimeError):
        api.c.post(f"/api/plans/{plan['id']}/execute")

    db.expire_all()
    assert db.get(CuttingPlan, plan["id"]).status == "RESERVED"
    assert db.scalar(select(func.count()).select_from(PlanExecution)) == 0
    statuses = db.scalars(select(StockItem.status).where(
        StockItem.id.in_([b["stock_item_id"] for b in plan["bars"]]))).all()
    assert statuses == ["RESERVED", "RESERVED"]
    assert db.scalar(select(func.count()).select_from(StockItem).where(StockItem.status == "CONSUMED")) == 0

    monkeypatch.undo()
    out = api.ok("POST", f"/api/plans/{plan['id']}/execute")
    assert len(out["remnants"]) == 2


def _run_parallel(fns):
    barrier = threading.Barrier(len(fns))
    results: list = [None] * len(fns)

    def wrap(i, fn):
        barrier.wait()
        try:
            results[i] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001
            results[i] = ("err", exc)

    threads = [threading.Thread(target=wrap, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results


def test_concurrent_reservations_only_one_wins(api, demo, db):
    """Dwie równoległe transakcje rezerwujące te same odcinki – wygrywa dokładnie jedna."""
    from app.db import SessionLocal
    from app.errors import Conflict
    from app.models import StockItem, User
    from app.services import workflow

    plan_a = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    other = api.project(demo["ws"], "Drugi", demand=[(demo["spec"], 560, 3), (demo["spec"], 950, 2),
                                                     (demo["spec"], 600, 1)])
    plan_b = api.ok("POST", f"/api/projects/{other}/optimize")["branch_and_bound"]["plan"]
    owner_id = db.scalar(select(User.id).where(User.email == "owner@test.pl"))

    def reserve(plan_id):
        def run():
            with SessionLocal() as s:
                return workflow.reserve_plan(s, s.get(User, owner_id), plan_id).id
        return run

    results = _run_parallel([reserve(plan_a["id"]), reserve(plan_b["id"])])
    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1 and len(errs) == 1
    assert isinstance(errs[0][1], Conflict)
    winner = oks[0][1]
    db.expire_all()
    reserved = db.scalars(select(StockItem.reserved_plan_id).where(StockItem.status == "RESERVED")).all()
    assert reserved and set(reserved) == {winner}


def test_concurrent_execute_consumes_once(api, demo, db):
    from app.db import SessionLocal
    from app.models import PlanExecution, StockItem, User
    from app.services import workflow

    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    owner_id = db.scalar(select(User.id).where(User.email == "owner@test.pl"))

    def execute():
        with SessionLocal() as s:
            _, remnants, already = workflow.execute_plan(s, s.get(User, owner_id), plan["id"])
            return already, sorted(r.id for r in remnants)

    results = _run_parallel([execute, execute, execute])
    assert all(r[0] == "ok" for r in results), results
    flags = sorted(r[1][0] for r in results)
    assert flags == [False, True, True]
    assert len({tuple(r[1][1]) for r in results}) == 1  # te same resztki dla każdego wywołania
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(PlanExecution)) == 1
    assert db.scalar(select(func.count()).select_from(StockItem).where(StockItem.is_remnant,
                                                                       StockItem.parent_stock_id.isnot(None))) == 2



def test_requests_waiting_for_project_lock_see_the_committed_revision(api, demo, db):
    """Wyścig: inna transakcja trzyma blokadę projektu i zmienia zapotrzebowanie (rewizja +1).

    Rezerwacja starego planu i dodanie pozycji czekają na blokadę. Po jej zwolnieniu muszą widzieć
    nową rewizję: rezerwacja -> 409 STALE_PLAN, a podbicie rewizji nie może zginąć.
    """
    import time

    from app.db import SessionLocal
    from app.models import Project

    pid = demo["project"]
    plan = api.ok("POST", f"/api/projects/{pid}/optimize")["branch_and_bound"]["plan"]
    start = plan["project_revision"]
    results = {}

    def run(name, method, url, body=None):
        results[name] = api.c.request(method, url, json=body)

    with SessionLocal() as other:
        other.scalar(select(Project).where(Project.id == pid).with_for_update()).revision += 1
        other.flush()
        threads = [
            threading.Thread(target=run, args=("reserve", "POST", f"/api/plans/{plan['id']}/reserve")),
            threading.Thread(target=run, args=("demand", "POST", f"/api/projects/{pid}/demand",
                                                 {"material_spec_id": demo["spec"], "length_mm": 300, "quantity": 1})),
        ]
        for t in threads:
            t.start()
        time.sleep(1.0)  # oba żądania czekają teraz na blokadę wiersza projektu
        other.commit()
    for t in threads:
        t.join(timeout=30)

    assert results["reserve"].status_code == 409, results["reserve"].text
    assert results["reserve"].json()["code"] == "STALE_PLAN"
    assert results["demand"].status_code == 201
    db.expire_all()
    assert db.get(Project, pid).revision == start + 2  # obie zmiany policzone

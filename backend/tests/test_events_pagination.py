"""Paginacja, filtrowanie i asynchroniczny dziennik zdarzeń (event system)."""

from fastapi import BackgroundTasks

from app.events import ALL, DomainEvent, _handlers, publish, subscribe


def test_publish_runs_handlers_as_background_tasks():
    """Szyna zdarzeń: handler nie wykonuje się od razu, tylko jako zadanie w tle; błąd handlera
    nie przerywa pozostałych."""
    received = []

    @subscribe("TEST_EVENT")
    def ok_handler(event):
        received.append(event.message)

    @subscribe("TEST_EVENT")
    def failing_handler(event):
        raise RuntimeError("awaria skutku ubocznego")

    try:
        background = BackgroundTasks()
        publish(background, DomainEvent("TEST_EVENT", 1, None, "zdarzenie testowe"))
        assert received == []  # jeszcze nic się nie wykonało
        assert len(background.tasks) == 2 + len(_handlers[ALL])
        for task in background.tasks[:2]:
            task.func(*task.args, **task.kwargs)  # błąd failing_handler jest przechwycony
        assert received == ["zdarzenie testowe"]
    finally:
        _handlers.pop("TEST_EVENT", None)


def test_stock_list_is_paginated_with_total_header(api):
    ws = api.register("a@test.pl")
    spec = api.spec(ws)
    api.stock(ws, spec, [1000 + i * 10 for i in range(7)])
    r = api.c.get(f"/api/workshops/{ws}/stock?limit=3&offset=0")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "7"
    first = [s["id"] for s in r.json()]
    second = [s["id"] for s in api.c.get(f"/api/workshops/{ws}/stock?limit=3&offset=3").json()]
    last = [s["id"] for s in api.c.get(f"/api/workshops/{ws}/stock?limit=3&offset=6").json()]
    assert len(first) == 3 and len(second) == 3 and len(last) == 1
    assert not set(first) & set(second)
    assert api.c.get(f"/api/workshops/{ws}/stock?limit=0").status_code == 422
    # filtrowanie wpływa na łączną liczbę
    api.ok("DELETE", f"/api/stock/{first[0]}")
    assert api.c.get(f"/api/workshops/{ws}/stock?status=DISCARDED").headers["X-Total-Count"] == "1"


def test_domain_events_are_logged_asynchronously(api, demo):
    ws = demo["ws"]
    plan = api.ok("POST", f"/api/projects/{demo['project']}/optimize")["branch_and_bound"]["plan"]
    api.ok("POST", f"/api/plans/{plan['id']}/reserve")
    api.login("operator@test.pl")
    api.ok("POST", f"/api/plans/{plan['id']}/execute")
    api.ok("POST", f"/api/plans/{plan['id']}/execute")  # ponowienie – bez drugiego zdarzenia

    page = api.ok("GET", f"/api/workshops/{ws}/events")
    types = [e["type"] for e in page["items"]]
    assert types[:3] == ["PLAN_EXECUTED", "PLAN_RESERVED", "OPTIMIZATION_FINISHED"]  # od najnowszych
    assert types.count("PLAN_EXECUTED") == 1
    executed = page["items"][0]
    assert executed["actor"] == "Operator"
    assert "344 mm" in executed["message"] and "358 mm" in executed["message"]
    assert page["total"] == len(types) and types.count("STOCK_RECEIVED") == 7  # fixture przyjmuje 7 odcinków osobno


def test_event_log_pagination_filter_and_isolation(api, demo):
    ws = demo["ws"]
    page = api.ok("GET", f"/api/workshops/{ws}/events?limit=1&offset=0")
    assert page["total"] == 7 and len(page["items"]) == 1 and page["limit"] == 1
    page2 = api.ok("GET", f"/api/workshops/{ws}/events?limit=1&offset=1")
    assert page2["items"][0]["id"] != page["items"][0]["id"]
    filtered = api.ok("GET", f"/api/workshops/{ws}/events?type=PLAN_EXECUTED")
    assert filtered["total"] == 0 and filtered["items"] == []
    assert api.c.get(f"/api/workshops/{ws}/events?type=NIEZNANY").status_code == 422

    api.c.cookies.clear()
    api.register("obcy@test.pl", "Obcy")
    assert api.c.get(f"/api/workshops/{ws}/events").status_code == 404

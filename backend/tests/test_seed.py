"""Dane demo: ponowne uruchomienie seeda nie duplikuje danych."""

from sqlalchemy import func, select

from app.models import MaterialSpec, Membership, Project, StockItem, User, Workshop
from app.seed import seed


def _counts(db):
    return {m.__name__: db.scalar(select(func.count()).select_from(m))
            for m in (User, Workshop, Membership, MaterialSpec, StockItem, Project)}


def test_seed_is_idempotent(db):
    seed(db)
    first = _counts(db)
    seed(db)
    assert _counts(db) == first
    assert first["User"] == 3 and first["Project"] == 4 and first["StockItem"] == 22


def test_demo_projects_give_documented_results(db, api):
    seed(db)
    api.login("wlasciciel@offcut.demo", "Demo1234!")
    projects = {p["name"]: p["id"] for p in api.ok("GET", "/api/workshops/1/projects")}
    expected = {
        "Regał na narzędzia": ((5450, 4), (4900, 2)),
        "Stojak na drewno kominkowe": ((14150, 8), (10200, 4)),
        "Wsporniki z profilu": ((2200, 1), (2200, 1)),
    }
    for name, (greedy, bnb) in expected.items():
        result = api.ok("POST", f"/api/projects/{projects[name]}/optimize")
        g, b = result["greedy"]["plan"], result["branch_and_bound"]["plan"]
        assert (g["total_stock_mm"], g["stock_count"]) == greedy, name
        assert (b["total_stock_mm"], b["stock_count"]) == bnb, name
        assert result["branch_and_bound"]["status"] == "OPTIMAL"
    short = api.ok("POST", f"/api/projects/{projects['Listwy przypodłogowe (za mało materiału)']}/optimize")
    assert short["branch_and_bound"]["status"] == "INFEASIBLE" and short["shortages"]

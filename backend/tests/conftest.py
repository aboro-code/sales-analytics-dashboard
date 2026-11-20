"""
Fixtures.

* ``client`` - API over a tiny synthetic dataset built with the *real* ETL code,
  so totals can be checked by hand. Timestamps are DD-MM-YYYY strings (the
  format the brief documents) to exercise the day-first parser.
* ``real_client`` - API over the full built database, skipped if it hasn't been built.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "etl"))

import build_db  # noqa: E402
from app.main import create_app  # noqa: E402

B = "Burger Town"
# BillNo, Outlet, Datetime (DD-MM-YYYY), Group, Order_Type, Item, Price, Qty, Settlement, Brand
ROWS = [
    (1, "Koramangala", "01-02-2026 12:30:00", "Burgers", "Dine-In", "Burger A", 100, 2, "Cash/Card/Coupon", B),
    (1, "Koramangala", "01-02-2026 12:30:00", "Drinks", "Dine-In", "Coke", 50, 1, "Cash/Card/Coupon", B),
    (1, "Koramangala", "01-02-2026 12:30:00", "Extras", "Dine-In", "Dip - Mayo", 0, 1, "Cash/Card/Coupon", B),
    (2, "MG Road", "03-02-2026 20:15:00", "Burgers", "Delivery", "Burger A", 100, 1, "ZomatoPay", B),
    (2, "MG Road", "03-02-2026 20:15:00", "Sides", "Delivery", "Fries", 80, 2, "ZomatoPay", B),
    (3, "Koramangala", "15-03-2026 19:00:00", "Drinks", "Takeaway", "Coke", 50, 2, "Dineout", B),
    (4, "MG Road", "20-03-2026 13:05:00", "Burgers", "Delivery", "Burger B", 150, 1, "SwiggyPay", B),
    (4, "MG Road", "20-03-2026 13:05:00", "Drinks", "Delivery", "Coke", 50, 1, "SwiggyPay", B),
]
# Hand-computed expectations. Bill values: 1 -> 250, 2 -> 260, 3 -> 100, 4 -> 200.
TOTAL_REVENUE = 810
TOTAL_ORDERS = 4
TOTAL_LINES = 8
TOTAL_QTY = 11


def raw_frame(rows=ROWS) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=build_db.EXPECTED_COLUMNS)


def build(raw: pd.DataFrame, out: Path) -> build_db.Report:
    rep = build_db.Report()
    df, orders = build_db.transform(raw, rep)
    assert not rep.failed, [c.name for c in rep.failed]
    build_db.load(df, orders, out, rep, Path("synthetic.xlsx"))
    assert not rep.failed, [c.name for c in rep.failed]
    return rep


@pytest.fixture(scope="session")
def synthetic_db(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("db") / "test.duckdb"
    build(raw_frame(), out)
    return out


@pytest.fixture(scope="session")
def client(synthetic_db) -> TestClient:
    return TestClient(create_app(str(synthetic_db), warm_cache=False))


@pytest.fixture(scope="session")
def real_client() -> TestClient:
    path = ROOT / "data" / "sales.duckdb"
    if not path.exists():
        pytest.skip("full database not built (run `python etl/build_db.py`)")
    return TestClient(create_app(str(path), warm_cache=False))

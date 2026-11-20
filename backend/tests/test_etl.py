import pandas as pd

import build_db
from conftest import ROWS, raw_frame


def run(raw: pd.DataFrame):
    rep = build_db.Report()
    df, orders = build_db.transform(raw, rep)
    return rep, df, orders


def test_parses_day_first_strings():
    _, df, _ = run(raw_frame())
    # '03-02-2026' must be 3 February (day-first), not 2 March.
    assert df.loc[df.bill_no == 2, "order_date"].iloc[0] == "2026-02-03"
    assert df.loc[df.bill_no == 2, "hour"].iloc[0] == 20


def test_native_datetimes_pass_through():
    raw = raw_frame()
    raw["Order_Datetime"] = pd.to_datetime(raw["Order_Datetime"], dayfirst=True)
    rep, df, _ = run(raw)
    assert not rep.failed
    assert df.loc[df.bill_no == 3, "order_date"].iloc[0] == "2026-03-15"


def test_derived_columns_and_orders():
    _, df, orders = run(raw_frame())
    assert df["revenue"].sum() == 810
    assert len(orders) == 4
    bill1 = orders.set_index("bill_no").loc[1]
    assert bill1.order_value == 250 and bill1.item_count == 4 and bill1.line_count == 3
    # weekday 0 = Monday; 2026-02-01 is a Sunday; its ISO week starts Monday 26 Jan.
    row = df[df.bill_no == 1].iloc[0]
    assert row.weekday == 6 and row.week == "2026-01-26" and row.month == "2026-02"


def test_zero_price_is_a_soft_finding():
    rep, _, _ = run(raw_frame())
    check = next(c for c in rep.checks if c.name.startswith("price = 0"))
    assert check.ok and not check.hard


def test_inconsistent_bill_fails_hard():
    rows = list(ROWS)
    rows[1] = (1, "MG Road", *rows[1][2:])  # same bill, different outlet
    rep, _, _ = run(raw_frame(rows))
    assert any(c.name == "bill-level consistency" for c in rep.failed)


def test_nulls_and_bad_dates_fail_hard():
    raw = raw_frame()
    raw.loc[0, "Item"] = None
    raw.loc[1, "Order_Datetime"] = "not a date"
    rep, _, _ = run(raw)
    names = {c.name for c in rep.failed}
    assert {"nulls", "datetime parse"} <= names


def test_missing_column_fails():
    rep, _, _ = run(raw_frame().drop(columns=["Settlement"]))
    assert rep.failed and rep.failed[0].name == "schema"

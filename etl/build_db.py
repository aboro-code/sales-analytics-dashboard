"""
ETL: data/data.xlsx  ->  data/sales.duckdb (DuckDB)

Reads the raw Excel export once, validates it, normalises it and writes a
read-optimised, embedded DuckDB database file that the API serves from
(read-only). See DECISIONS.md (D4) for why DuckDB rather than SQLite.

    python etl/build_db.py                       # defaults
    python etl/build_db.py --src data/data.xlsx --out data/sales.duckdb --report etl/REPORT.md

The script fails (non-zero exit) if any *hard* validation check fails, so a bad
file can never be deployed silently. *Soft* findings (e.g. Price = 0 rows) are
reported but do not fail the build.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_COLUMNS = [
    "BillNo", "Outlet_Name", "Order_Datetime", "Group", "Order_Type",
    "Item", "Price", "Quantity", "Settlement", "Brand",
]
# Raw column -> clean snake_case column used everywhere downstream.
RENAME = {
    "BillNo": "bill_no",
    "Outlet_Name": "outlet",
    "Order_Datetime": "order_ts",
    "Group": "item_group",   # "group" is an SQL keyword
    "Order_Type": "order_type",
    "Item": "item",
    "Price": "price",
    "Quantity": "quantity",
    "Settlement": "settlement",
    "Brand": "brand",
}
# Attributes that describe the *order*, so they must be identical on every line of a bill.
BILL_LEVEL = ["outlet", "order_type", "settlement", "order_ts"]
TEXT_COLS = ["outlet", "item_group", "order_type", "item", "settlement", "brand"]


# --------------------------------------------------------------------------- #
# Validation bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hard: bool = True  # hard checks fail the build


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    profile: dict[str, object] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str, hard: bool = True) -> None:
        self.checks.append(Check(name, bool(ok), detail, hard))
        mark = "PASS" if ok else ("FAIL" if hard else "WARN")
        print(f"  [{mark}] {name}: {detail}")

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.hard and not c.ok]


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #
def extract(src: Path) -> pd.DataFrame:
    if src.suffix.lower() == ".csv":
        return pd.read_csv(src)
    return pd.read_excel(src, engine="openpyxl")


def parse_datetimes(s: pd.Series) -> pd.Series:
    """
    The brief documents Order_Datetime as 'DD-MM-YYYY HH:MM:SS' text, but the
    provided workbook stores genuine Excel datetimes. Handle both: native
    datetimes pass through; strings are parsed day-first so '03-04-2026' is
    3 April, not 4 March.
    """
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    parsed = pd.to_datetime(s, dayfirst=True, errors="coerce", format="mixed")
    return parsed


# --------------------------------------------------------------------------- #
# Transform + validate
# --------------------------------------------------------------------------- #
def transform(raw: pd.DataFrame, rep: Report) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Validating …")
    missing = [c for c in EXPECTED_COLUMNS if c not in raw.columns]
    rep.check("schema", not missing, f"missing columns: {missing}" if missing else f"all {len(EXPECTED_COLUMNS)} expected columns present")
    if missing:
        return raw, raw

    df = raw[EXPECTED_COLUMNS].rename(columns=RENAME).copy()
    rep.check("row count", len(df) > 0, f"{len(df):,} rows")

    nulls = int(df.isna().sum().sum())
    rep.check("nulls", nulls == 0, f"{nulls} null cells")

    dups = int(df.duplicated().sum())
    rep.check("duplicate rows", dups == 0, f"{dups} fully duplicated rows")

    # Normalise text (trim whitespace, collapse internal runs of spaces).
    for c in TEXT_COLS:
        df[c] = df[c].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

    # Datetimes
    df["order_ts"] = parse_datetimes(df["order_ts"])
    bad_ts = int(df["order_ts"].isna().sum())
    rep.check("datetime parse", bad_ts == 0, f"{bad_ts} unparseable timestamps (raw dtype: {raw['Order_Datetime'].dtype})")

    # Numerics
    for c in ["bill_no", "price", "quantity"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad_num = int(df[["bill_no", "price", "quantity"]].isna().sum().sum())
    rep.check("numeric columns", bad_num == 0, f"{bad_num} non-numeric BillNo/Price/Quantity values")
    df = df.astype({"bill_no": "int64", "quantity": "int64"})
    df["price"] = df["price"].astype("float64")

    rep.check("price >= 0", (df["price"] >= 0).all(), f"min price {df['price'].min():g}, max {df['price'].max():g}")
    rep.check("quantity >= 1", (df["quantity"] >= 1).all(), f"quantity range {df['quantity'].min()}–{df['quantity'].max()}")

    # Each menu item should have a single list price (no hidden discounts / typos).
    prices_per_item = df.groupby("item")["price"].nunique()
    multi = prices_per_item[prices_per_item > 1]
    rep.check("one price per item", multi.empty, f"{df['item'].nunique()} items; {len(multi)} with >1 price", hard=False)

    # Each item should belong to exactly one group.
    groups_per_item = df.groupby("item")["item_group"].nunique()
    rep.check("one group per item", (groups_per_item == 1).all(), f"{int((groups_per_item > 1).sum())} items in >1 group")

    # Bill-level attributes must be constant within a bill, otherwise order-level
    # metrics (orders by outlet, AOV by channel, …) would double count.
    per_bill = df.groupby("bill_no")[BILL_LEVEL].nunique()
    inconsistent = {c: int((per_bill[c] > 1).sum()) for c in BILL_LEVEL}
    rep.check("bill-level consistency", sum(inconsistent.values()) == 0, f"bills with conflicting values: {inconsistent}")

    # Zero-priced lines: expected to be complimentary add-ons. Report what they are.
    zero = df[df["price"] == 0]
    zero_items = zero["item"].value_counts().to_dict()
    rep.check(
        "price = 0 rows are free add-ons",
        set(zero["item_group"].unique()) <= {"Extras"},
        f"{len(zero):,} rows, items {zero_items}",
        hard=False,
    )

    # Stop before deriving anything if the data is not trustworthy: the caller
    # reports every failed check at once instead of crashing on the first bad value.
    if rep.failed:
        return df, df.iloc[0:0]

    # ---- Derived columns -------------------------------------------------- #
    ts = df["order_ts"]
    df["revenue"] = df["price"] * df["quantity"]
    df["order_date"] = ts.dt.strftime("%Y-%m-%d")
    df["week"] = (ts.dt.normalize() - pd.to_timedelta(ts.dt.day_of_week, unit="D")).dt.strftime("%Y-%m-%d")  # ISO week start (Mon)
    df["month"] = ts.dt.strftime("%Y-%m")
    df["hour"] = ts.dt.hour.astype("int64")
    df["weekday"] = ts.dt.day_of_week.astype("int64")  # 0 = Monday
    df["order_ts"] = ts.dt.strftime("%Y-%m-%d %H:%M:%S")  # cast to TIMESTAMP on load

    # ---- Orders (one row per bill) --------------------------------------- #
    orders = (
        df.groupby("bill_no", sort=True)
        .agg(
            outlet=("outlet", "first"),
            order_type=("order_type", "first"),
            settlement=("settlement", "first"),
            order_ts=("order_ts", "first"),
            order_date=("order_date", "first"),
            week=("week", "first"),
            month=("month", "first"),
            hour=("hour", "first"),
            weekday=("weekday", "first"),
            line_count=("item", "size"),
            item_count=("quantity", "sum"),
            order_value=("revenue", "sum"),
        )
        .reset_index()
    )

    # ---- Profile ----------------------------------------------------------- #
    total_rev = float(df["revenue"].sum())
    rep.profile = {
        "rows": len(df),
        "bills": int(df["bill_no"].nunique()),
        "lines_per_bill": round(len(df) / df["bill_no"].nunique(), 2),
        "date_min": df["order_ts"].min(),
        "date_max": df["order_ts"].max(),
        "hours": f"{df['hour'].min()}:00–{df['hour'].max()}:59",
        "total_revenue": total_rev,
        "aov": round(total_rev / len(orders), 2),
        "items_sold": int(df["quantity"].sum()),
        "distinct_items": int(df["item"].nunique()),
        "zero_price_rows": len(zero),
        "outlets": df["outlet"].value_counts().to_dict(),
        "groups": df["item_group"].value_counts().to_dict(),
        "order_types": df["order_type"].value_counts().to_dict(),
        "settlements": df["settlement"].value_counts().to_dict(),
        "brands": df["brand"].value_counts().to_dict(),
        "type_x_settlement": pd.crosstab(df["order_type"], df["settlement"]),
    }
    return df, orders


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
# Tables are created with explicit types. Rows are physically ordered by
# timestamp: DuckDB keeps min/max "zone maps" per row group, so a date-range
# filter skips whole row groups without needing a secondary index. (DuckDB's
# ART indexes help point lookups, not these analytical scans, so none are created.)
LINE_ITEMS_SQL = """
CREATE TABLE line_items AS
SELECT
    CAST(row_number() OVER (ORDER BY order_ts, bill_no) AS INTEGER) AS id,
    CAST(bill_no AS INTEGER)       AS bill_no,
    outlet,
    CAST(order_ts AS TIMESTAMP)    AS order_ts,
    CAST(order_date AS DATE)       AS order_date,
    CAST(week AS DATE)             AS week,        -- Monday of the ISO week
    month,                                          -- 'YYYY-MM'
    CAST(hour AS TINYINT)          AS hour,
    CAST(weekday AS TINYINT)       AS weekday,     -- 0 = Monday
    item_group,
    item,
    CAST(price AS DOUBLE)          AS price,
    CAST(quantity AS INTEGER)      AS quantity,
    CAST(revenue AS DOUBLE)        AS revenue,     -- price * quantity
    order_type,
    settlement,
    brand
FROM df_lines
ORDER BY order_ts, bill_no
"""

ORDERS_SQL = """
CREATE TABLE orders AS
SELECT
    CAST(bill_no AS INTEGER)       AS bill_no,
    outlet, order_type, settlement,
    CAST(order_ts AS TIMESTAMP)    AS order_ts,
    CAST(order_date AS DATE)       AS order_date,
    CAST(week AS DATE)             AS week,
    month,
    CAST(hour AS TINYINT)          AS hour,
    CAST(weekday AS TINYINT)       AS weekday,
    CAST(line_count AS INTEGER)    AS line_count,
    CAST(item_count AS INTEGER)    AS item_count,  -- total quantity on the bill
    CAST(order_value AS DOUBLE)    AS order_value
FROM df_orders
ORDER BY order_ts, bill_no
"""


def load(df: pd.DataFrame, orders: pd.DataFrame, out: Path, rep: Report, src: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp))
    try:
        con.register("df_lines", df)
        con.register("df_orders", orders)
        con.execute(LINE_ITEMS_SQL)
        con.execute(ORDERS_SQL)
        con.unregister("df_lines")
        con.unregister("df_orders")

        p = rep.profile
        info = {
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_file": src.name,
            "rows": str(p["rows"]),
            "bills": str(p["bills"]),
            "total_revenue": f"{p['total_revenue']:.2f}",
            "brand": ", ".join(p["brands"].keys()),
            "engine": f"duckdb {duckdb.__version__}",
        }
        con.execute("CREATE TABLE build_info (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
        con.executemany("INSERT INTO build_info VALUES (?, ?)", list(info.items()))

        # Post-load reconciliation: what's in the DB must match what we computed.
        db_rows, db_rev = con.execute("SELECT COUNT(*), SUM(revenue) FROM line_items").fetchone()
        db_orders, db_ov = con.execute("SELECT COUNT(*), SUM(order_value) FROM orders").fetchone()
        rep.check("db reconciliation: rows", db_rows == p["rows"], f"{db_rows:,} rows in line_items")
        rep.check("db reconciliation: orders", db_orders == p["bills"], f"{db_orders:,} rows in orders")
        rep.check(
            "db reconciliation: revenue",
            abs(db_rev - p["total_revenue"]) < 0.01 and abs(db_ov - p["total_revenue"]) < 0.01,
            f"line_items ₹{db_rev:,.0f} = orders ₹{db_ov:,.0f}",
        )
        con.execute("CHECKPOINT")
    finally:
        con.close()

    out.with_name(out.name + ".wal").unlink(missing_ok=True)
    os.replace(tmp, out)  # atomic swap: the API never sees a half-built DB


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def write_report(rep: Report, path: Path, db_path: Path) -> None:
    p = rep.profile
    lines: list[str] = []
    w = lines.append
    w("# ETL validation report")
    w("")
    w("_Generated by `etl/build_db.py`. Re-run the ETL to refresh._")
    w("")
    w("## Validation checks")
    w("")
    w("| Check | Result | Detail |")
    w("|---|---|---|")
    for c in rep.checks:
        mark = "✅ pass" if c.ok else ("❌ fail" if c.hard else "⚠️ warn")
        w(f"| {c.name} | {mark} | {c.detail} |")
    w("")
    w("## Dataset profile")
    w("")
    w("| Metric | Value |")
    w("|---|---|")
    w(f"| Line items (rows) | {p['rows']:,} |")
    w(f"| Orders (unique BillNo) | {p['bills']:,} |")
    w(f"| Lines per order | {p['lines_per_bill']} |")
    w(f"| Date range | {p['date_min']} → {p['date_max']} |")
    w(f"| Trading hours seen | {p['hours']} |")
    w(f"| Total revenue (Σ price × qty) | {_inr(p['total_revenue'])} |")
    w(f"| Average order value | ₹{p['aov']:,.2f} |")
    w(f"| Units sold (Σ qty) | {p['items_sold']:,} |")
    w(f"| Distinct menu items | {p['distinct_items']} |")
    w(f"| Price = 0 rows (free dips) | {p['zero_price_rows']:,} |")
    w("")
    for title, key in [("Outlets", "outlets"), ("Groups", "groups"), ("Order types", "order_types"),
                       ("Settlement / channel", "settlements"), ("Brand", "brands")]:
        w(f"### {title} (line items)")
        w("")
        w("| Value | Rows | Share |")
        w("|---|---:|---:|")
        for k, v in p[key].items():
            w(f"| {k} | {v:,} | {v / p['rows']:.1%} |")
        w("")
    w("### Order type × settlement (line items)")
    w("")
    ct: pd.DataFrame = p["type_x_settlement"]
    w("| Order type | " + " | ".join(ct.columns) + " |")
    w("|---|" + "---:|" * len(ct.columns))
    for idx, row in ct.iterrows():
        w(f"| {idx} | " + " | ".join(f"{v:,}" for v in row) + " |")
    w("")
    w("Aggregator settlements (ZomatoPay, SwiggyPay) only ever appear on Delivery; Dineout only on Dine-In/Takeaway. "
      "Delivery also has direct Cash/Card/Coupon orders, so aggregators are most but not all of delivery.")
    w("")
    w("## Timings")
    w("")
    w("| Stage | Seconds |")
    w("|---|---:|")
    for k, v in rep.timings.items():
        w(f"| {k} | {v:.1f} |")
    if db_path.exists():
        w(f"| _DuckDB file size_ | {db_path.stat().st_size / 1e6:.1f} MB |")
    w("")
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=ROOT / "data" / "data.xlsx")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "sales.duckdb")
    ap.add_argument("--report", type=Path, default=ROOT / "etl" / "REPORT.md", help="write markdown report here ('' to skip)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # ₹ on Windows consoles

    rep = Report()
    t0 = time.perf_counter()
    print(f"Extracting {args.src} …")
    raw = extract(args.src)
    rep.timings["extract (read xlsx)"] = time.perf_counter() - t0

    t1 = time.perf_counter()
    df, orders = transform(raw, rep)
    rep.timings["transform + validate"] = time.perf_counter() - t1
    if rep.failed:
        print(f"\n{len(rep.failed)} hard check(s) failed; database NOT written.")
        return 1

    t2 = time.perf_counter()
    print(f"Loading {args.out} …")
    load(df, orders, args.out, rep, args.src)
    rep.timings["load (DuckDB)"] = time.perf_counter() - t2
    rep.timings["total"] = time.perf_counter() - t0

    if rep.failed:
        print(f"\n{len(rep.failed)} hard check(s) failed after load.")
        args.out.unlink(missing_ok=True)
        return 1

    p = rep.profile
    print(f"\nOK  {p['rows']:,} rows · {p['bills']:,} orders · revenue {_inr(p['total_revenue'])} · AOV ₹{p['aov']:,.2f}")
    print(f"    {args.out} ({args.out.stat().st_size / 1e6:.1f} MB) in {rep.timings['total']:.1f}s")
    if str(args.report):
        write_report(rep, args.report, args.out)
        print(f"    report -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

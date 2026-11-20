# Decision log

A running record of technical decisions, what was measured, and why. Newest last.
The README summarises these; this file has the detail.

## D1: Pre-process with an ETL step; never read the xlsx per request

- Reading `data.xlsx` with pandas/openpyxl took **21–44 s** on a dev laptop.
  Doing that per request (or even per cold start on a free-tier box) is not viable.
- The ETL reads the file once, validates it (hard checks fail the build), derives
  columns (`revenue`, `order_date`, `week`, `month`, `hour`, `weekday`) and writes
  an embedded database file the API opens read-only.
- The parser accepts real Excel datetimes (what the file contains) **and**
  `DD-MM-YYYY HH:MM:SS` strings (what the brief documents), parsed `dayfirst=True`.

## D2: Build the database at deploy time, don't commit it

- The raw xlsx is 13 MB and is committed once. The built DB is a reproducible
  artifact. Committing a binary that changes with every ETL tweak would bloat history.
- Render's build command and the Dockerfile both run the ETL, so a deploy is
  reproducible from source.

## D3: Group/item filters re-derive orders

- `Outlet_Name`, `Order_Type`, `Settlement` and `Order_Datetime` are constant within
  a bill (verified: 0 conflicting bills), so these filters are order-level.
- `Group` and `Item` vary within a bill. With a group/item filter:
  - an order counts if it has **at least one matching line**;
  - revenue and order value include only the **matching lines**.
  So with `groups=Drinks`, AOV is "average drinks spend per order that contained a drink".
- Implementation: every order-level query reads from one CTE `o`. Without line
  filters, `o` is the prebuilt `orders` table. With them, `o` is matching line
  items grouped by `bill_no`. The downstream SQL is identical, so semantics can't drift.

## D4: SQLite → DuckDB for the serving database (measured)

The first backend used SQLite (read-only, `immutable=1`, mmap, indexes on the
filter columns). Benchmarked on the real 300K rows, warm, median of 5 runs:

| Query (no filters) | SQLite | SQLite + covering indexes | DuckDB (1 thread) |
|---|---:|---:|---:|
| Item breakdown (`SUM`, `COUNT(DISTINCT bill_no)` by item) | 271 ms | 127 ms | 68 ms |
| Line-item totals | 28 ms | 36 ms | 3 ms |
| Order totals | 32 ms | 17 ms | 9 ms |
| Orders by outlet | 45 ms | 73 ms | 5 ms |
| Weekday × hour heatmap | 52 ms | 90 ms | 3 ms |
| Records page at offset 250K | 10 ms | – | 171 ms |
| **File size** | **101 MB** | larger | **7 MB** |

End to end, the SQLite `/api/summary` took ~240 ms and `/api/breakdown?dim=group`
~440 ms on a laptop. Render's free tier has ~0.1 vCPU, so expect several times worse.

**Decision:** switch to DuckDB. It is still embedded, a single read-only file
and needs no server, so the architecture is unchanged. Its columnar, vectorised
execution suits this workload, which is almost entirely `GROUP BY` and
`COUNT(DISTINCT)` over a few columns.

**Trade-off accepted:** deep `OFFSET` pagination is slower (no B-tree row order),
but realistic pages (first few hundred) are fast, and keyset pagination is the
known fix if needed. SQLite remains the better choice for an OLTP or write-heavy app.

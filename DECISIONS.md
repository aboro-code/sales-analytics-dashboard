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

## D5: Two-level caching, warmed at startup

- **Server:** an in-process LRU+TTL cache (512 entries, 1 h) keyed by endpoint plus
  *normalised* filters, so `outlets=B,A` and `outlets=A&outlets=B` hit the same entry.
  The default (unfiltered) dashboard is pre-computed in a background thread at
  startup, so the first visitor after a cold start gets cache hits.
- **Client:** TanStack Query dedupes concurrent identical requests and keeps
  results for 5 minutes, and `Cache-Control: public, max-age=300` lets the browser
  reuse responses too.
- **Why not Redis:** single instance, immutable data and a small key space. A
  miss costs 5–40 ms. Redis (or a CDN in front of the GET API) is the next step
  only if this scales to several instances.

## D6: Partial periods are flagged, not hidden

The data ends on Tuesday 16 June 2026, so the last ISO week has 2 days and the
weekly revenue line "crashes" by ~70%. The API returns `days`, `period_days` and
`partial` per point, and the chart draws partial edge periods as a dashed
continuation with "partial, 2 of 7 days" in the tooltip. I kept the data rather
than dropping it, because hiding data is worse than labelling it.

## D7: Date presets anchor to the end of the data, not today

"Last 30 days" relative to the wall clock would be empty, since the data ends
June 2026. Presets (7d / 30d / 90d / this year / all) are computed from
`max_date` returned by `/api/meta`.

## D8: Rule-based insights instead of an LLM

Insights are computed from the same SQL as the charts and rendered with
templates: top outlet, peak hour and lunch/dinner share, weekend vs weekday,
delivery share, aggregator dependence, fastest-growing category, hero item and
free add-ons. They respect filters, cost nothing, need no API key and **cannot
hallucinate a number**.

- "Fastest-growing category" compares the last two *complete* months inside the
  selected range, and ignores categories under 5% of revenue. Otherwise Extras
  (≈1% of revenue) "wins" on noise.
- An LLM layer could later rephrase or rank these facts, but it would be fed
  the computed facts and never asked to compute them.

## D9: Charts follow a validated palette and avoid dual axes

- Revenue and orders differ by ~600×, so the trend chart toggles the measure
  instead of using two y-axes.
- Single-series bars use one colour.
- Mix charts (≤ 4 slices) use fixed per-entity colours, so filtering never
  repaints a category. They also carry a value legend, since two light-mode
  slots are below 3:1 contrast.
- The heatmap uses a single-hue sequential ramp.
- Colours were checked with a colour-vision-deficiency validator in both themes.

## D10: Deployment

- **API on Render (Docker, free plan, Singapore region).** The multi-stage
  Dockerfile runs the ETL in a build stage (pandas + openpyxl) and ships only
  FastAPI, DuckDB and the 6 MB database (image ~340 MB). A failed validation fails
  the deploy.
- **Frontend on Vercel** with `VITE_API_URL`.
- **CORS:** an origin regex admits the production URL and Vercel preview URLs,
  so there's no chicken-and-egg ordering between the two deploys.
- **Cold starts:** the free tier sleeps after ~15 minutes idle. The frontend pings
  `/health` first and shows a "waking the server" state with a timer instead
  of a blank page.

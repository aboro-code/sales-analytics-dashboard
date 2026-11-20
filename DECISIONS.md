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
- An LLM layer can rephrase or rank these facts, but it is fed the computed
  facts and never asked to compute them. That is now built: see D11.

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
- **Frontend on Vercel.** `vercel.json` rewrites `/api/*` and `/health` to the
  Render API, so the browser only ever talks to its own origin. The first
  version called Render directly (cross-origin, `VITE_API_URL`). It worked in
  Chrome but failed in Brave: Shields drops cross-site requests that match
  tracker filter lists, and the API host contains "analytics". The same-origin
  proxy fixes this, and also removes CORS preflights. The cost is one extra hop
  through Vercel's edge (a few ms).
- **CORS** (kept for direct cross-origin use and local dev against Render): an origin regex admits the production URL and Vercel preview URLs,
  so there's no chicken-and-egg ordering between the two deploys.
- **Cold starts:** the free tier sleeps after ~15 minutes idle. The frontend pings
  `/health` first and shows a "waking the server" state with a timer instead
  of a blank page.

## D11: AI summary on top of the rule-based facts

- **What:** `GET /api/ai-summary` sends this view's pre-formatted facts (KPIs,
  monthly revenue, the outlet / order-type / channel / category mix, and the 8
  D8 insights) to an LLM, which returns `{headline, points[], actions[]}`.
- **Guardrails against made-up numbers:**
  - The model never sees raw rows.
  - Every number arrives already formatted, and the prompt says to copy
    numbers, not compute them.
  - Structured outputs (a JSON schema) fix the shape of the reply.
  - The UI labels the summary as AI-written and keeps the exact rule-based
    cards next to it.
- **Provider is a setting (`AI_PROVIDER`):**
  - **Groq**, with `openai/gpt-oss-120b`, strict JSON schema and low reasoning
    effort. It's free, so it runs the live demo with no billing account.
  - **Anthropic**, with `claude-opus-5-5` at low effort and server-side refusal
    fallbacks.
  - Rewording a page of facts needs little reasoning. A grounded,
    schema-constrained task like this is where a free open-weights model is
    good enough, and the design (pre-formatted facts plus strict schema) is
    what keeps quality up, not the model choice.
  - Malformed output, refusals and truncation all return an error, never a
    broken "summary".
- **Number verification on the server:**
  - The first live Groq summary said "top three outlets contribute over 63%".
    That figure is a correct sum, but the model computed it, against the
    prompt.
  - Every number in the brief is now matched by value against the facts.
  - A mismatch triggers one corrective retry that names the numbers. If they
    are still unmatched, the brief is flagged (`verified: false`) and the UI
    lists them.
  - Prompts state intent; code enforces it.
- **Cost control for a public URL:**
  - Called only on click.
  - Cached per normalised filter set (immutable data, so it never needs
    regenerating).
  - A sliding-window cap on uncached calls (`AI_MAX_CALLS_PER_HOUR=30`).
- **Optional by design:**
  - Without `ANTHROPIC_API_KEY`, `/api/meta` reports `ai_summary: false` and
    the button is hidden.
  - Tests use a fake client, so CI needs no secret.
- **Rejected:** letting the model query the data itself (text-to-SQL or tools).
  It's useful for open questions, but for a summary it only adds ways to be
  wrong.

## D12: No authentication (deliberate)

- The deliverable is a public, read-only demo with one brand's sample data.
  A login wall would block reviewers and protect nothing.
- Auth only matters together with authorisation (a manager sees only their
  outlets). The plan:
  - an OIDC provider on the frontend;
  - JWT verification (JWKS) in a FastAPI dependency;
  - intersecting an `outlets` claim with the requested filter inside
    `FilterParser`, so every query is tenant-scoped through the existing
    `Filters` path;
  - the user in cache keys and per-user rate limits.
- The details are in the README ("Why no authentication").

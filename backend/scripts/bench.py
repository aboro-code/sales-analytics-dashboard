"""
Latency benchmark against a running API.

    python backend/scripts/bench.py http://127.0.0.1:8000 [runs]

For each endpoint it reports:
  * uncached - a unique, never-seen filter combination each run, so every
    request hits DuckDB (the cache can't help);
  * cached   - the same request repeated (served from the response cache).

Uses the server-reported X-Query-Time-ms header (handler time) and the
client round-trip time.
"""
import statistics
import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 15

ENDPOINTS = {
    "summary": ("/api/summary", {}),
    "timeseries (week)": ("/api/timeseries", {"granularity": "week"}),
    "breakdown outlet": ("/api/breakdown", {"dim": "outlet"}),
    "breakdown item top10": ("/api/breakdown", {"dim": "item", "limit": 10}),
    "heatmap": ("/api/heatmap", {}),
    "insights": ("/api/insights", {}),
    "records page 1": ("/api/records", {"page_size": 25}),
    "summary + group filter": ("/api/summary", {"groups": "Drinks"}),
}


def unique_dates(i: int) -> dict[str, str]:
    # Different (but nearly full-range) start dates -> distinct cache keys, same work.
    day = 1 + i % 28
    return {"start": f"2025-06-{17 + (i % 13):02d}" if i % 2 else f"2025-07-{day:02d}"}


def measure(client: httpx.Client, path: str, params: dict, cached: bool) -> tuple[float, float]:
    server, total = [], []
    if cached:
        client.get(path, params=params)  # prime
    for i in range(RUNS):
        p = dict(params) if cached else {**params, **unique_dates(i + int(time.time()) % 1000)}
        t0 = time.perf_counter()
        r = client.get(path, params=p)
        total.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        server.append(float(r.headers["X-Query-Time-ms"]))
    return statistics.median(server), statistics.median(total)


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=60) as c:
        c.get("/health").raise_for_status()
        print(f"{'endpoint':26s} {'uncached p50':>14s} {'cached p50':>12s}   (server ms / round-trip ms)")
        for name, (path, params) in ENDPOINTS.items():
            us, ut = measure(c, path, params, cached=False)
            cs, ct = measure(c, path, params, cached=True)
            print(f"{name:26s} {us:7.1f} / {ut:5.1f} {cs:6.1f} / {ct:4.1f}")
        t0 = time.perf_counter()
        r = c.get("/api/export.csv")
        print(f"\nfull CSV export: {len(r.content) / 1e6:.1f} MB, {r.text.count(chr(10)) - 1:,} rows in {time.perf_counter() - t0:.2f} s")


if __name__ == "__main__":
    main()

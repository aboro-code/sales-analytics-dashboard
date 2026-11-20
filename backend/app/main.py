"""FastAPI application: read-only analytics API over the DuckDB build."""

import csv
import io
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Any, Callable, Literal

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse

from . import insights as insights_mod
from . import queries
from .cache import TTLCache
from .db import Database
from .filters import Filters, FilterParser

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Responses are immutable for a given build, so browsers/CDNs may cache them briefly.
CACHE_CONTROL = "public, max-age=300"


def create_app(db_path: str | None = None, *, warm_cache: bool | None = None) -> FastAPI:
    db = Database(db_path)
    meta_cache = queries.meta(db)  # dimension values never change for a given build
    parse_filters = FilterParser({
        "outlets": set(meta_cache["outlets"]),
        "groups": set(meta_cache["groups"]),
        "items": {i["item"] for i in meta_cache["items"]},
        "order_types": set(meta_cache["order_types"]),
        "settlements": set(meta_cache["settlements"]),
    })
    FilterDep = Annotated[Filters, Depends(parse_filters)]
    cache = TTLCache(
        maxsize=int(os.environ.get("CACHE_MAXSIZE", 512)),
        ttl_seconds=float(os.environ.get("CACHE_TTL_SECONDS", 3600)),
    )

    def cached(response: Response, key: tuple[Any, ...], fn: Callable[[], Any]) -> Any:
        hit, value = cache.get_or_compute(key, fn)
        response.headers["X-Cache"] = "HIT" if hit else "MISS"
        response.headers["Cache-Control"] = CACHE_CONTROL
        return value

    def warm() -> None:
        """Pre-compute the default (unfiltered) dashboard so the first visitor after a
        cold start gets cache hits. Runs in a background thread so startup isn't delayed."""
        t0 = time.perf_counter()
        f = Filters()
        k = f.key()
        cache.set(("summary", k), queries.summary(db, f))
        for g in ("day", "week", "month"):
            cache.set(("timeseries", k, g), {"granularity": g, "points": queries.timeseries(db, f, g)})
        for dim in queries.DIMENSIONS:
            cache.set(("breakdown", k, dim, None), {"dim": dim, "rows": queries.breakdown(db, f, dim, None)})
        cache.set(("breakdown", k, "item", 10), {"dim": "item", "rows": queries.breakdown(db, f, "item", 10)})
        cache.set(("heatmap", k), {"cells": queries.heatmap(db, f)})
        cache.set(("insights", k), {"insights": insights_mod.generate(db, f)})
        log.info("cache warmed in %.0f ms", (time.perf_counter() - t0) * 1000)

    should_warm = warm_cache if warm_cache is not None else os.environ.get("WARM_CACHE", "1") == "1"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        b = meta_cache["build"]
        log.info("serving %s (%s rows, built %s, %s)", db.path, b.get("rows"), b.get("built_at"), b.get("engine"))
        if should_warm:
            threading.Thread(target=warm, daemon=True, name="cache-warm").start()
        yield

    app = FastAPI(
        title="Sales Analytics API",
        version="1.0.0",
        description="Read-only analytics over 300K restaurant line items. All data endpoints share the same filters.",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
        allow_methods=["GET"],
        allow_headers=["*"],
        expose_headers=["X-Query-Time-ms", "X-Cache", "Content-Disposition"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.middleware("http")
    async def timing(request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - t0) * 1000
        response.headers["X-Query-Time-ms"] = f"{ms:.1f}"
        if request.url.path.startswith("/api/"):
            log.info("%s %s?%s -> %s %.1f ms cache=%s", request.method, request.url.path, request.url.query,
                     response.status_code, ms, response.headers.get("X-Cache", "-"))
        return response

    # ------------------------------------------------------------------ #
    @app.get("/health", tags=["ops"])
    def health():
        """Cheap liveness probe (used by Render and by the frontend's wake-up check)."""
        b = meta_cache["build"]
        return {"status": "ok", "rows": int(b.get("rows", 0)), "built_at": b.get("built_at"), "cache": cache.stats()}

    @app.get("/api/meta", tags=["data"])
    def meta(response: Response):
        """Filter options and dataset bounds."""
        response.headers["Cache-Control"] = CACHE_CONTROL
        return meta_cache

    @app.get("/api/summary", tags=["data"])
    def summary(f: FilterDep, response: Response):
        """KPI cards: records, orders, revenue, AOV, items sold, top outlet and item."""
        return cached(response, ("summary", f.key()), lambda: queries.summary(db, f))

    @app.get("/api/timeseries", tags=["data"])
    def timeseries(f: FilterDep, response: Response, granularity: Literal["day", "week", "month"] = "day"):
        """Revenue, orders and AOV per day, ISO week (Monday start) or month."""
        return cached(response, ("timeseries", f.key(), granularity),
                      lambda: {"granularity": granularity, "points": queries.timeseries(db, f, granularity)})

    @app.get("/api/breakdown", tags=["data"])
    def breakdown(
        f: FilterDep,
        response: Response,
        dim: Literal["outlet", "group", "item", "order_type", "settlement"],
        limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    ):
        """Revenue, orders, quantity, share and AOV per category, sorted by revenue."""
        return cached(response, ("breakdown", f.key(), dim, limit),
                      lambda: {"dim": dim, "rows": queries.breakdown(db, f, dim, limit)})

    @app.get("/api/heatmap", tags=["data"])
    def heatmap(f: FilterDep, response: Response):
        """Orders and revenue by weekday (0 = Monday) × hour of day."""
        return cached(response, ("heatmap", f.key()), lambda: {"cells": queries.heatmap(db, f)})

    @app.get("/api/insights", tags=["data"])
    def insights(f: FilterDep, response: Response):
        """Rule-based, plain-English insights for the current filters."""
        return cached(response, ("insights", f.key()), lambda: {"insights": insights_mod.generate(db, f)})

    @app.get("/api/records", tags=["data"])
    def records(
        f: FilterDep,
        response: Response,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 25,
        sort: Literal[tuple(queries.SORTABLE)] = "order_ts",  # type: ignore[valid-type]
        order: Literal["asc", "desc"] = "desc",
    ):
        """Paginated, sortable raw line items (server-side pagination)."""
        return cached(response, ("records", f.key(), page, page_size, sort, order),
                      lambda: queries.records(db, f, page, page_size, sort, order))

    @app.get("/api/export.csv", tags=["data"], response_class=StreamingResponse)
    def export_csv(f: FilterDep):
        """Stream the filtered line items as CSV (constant memory: batches of 5,000 rows)."""

        def generate():
            buf = io.StringIO()
            writer = csv.writer(buf)
            header_written = False
            for cols, rows in queries.export_rows(db, f):
                if not header_written:
                    writer.writerow(cols)
                    header_written = True
                writer.writerows(
                    [v.isoformat(sep=" ") if isinstance(v, datetime) else v for v in row] for row in rows
                )
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate(0)
            if not header_written:
                writer.writerow(queries.RECORD_COLUMNS)
                yield buf.getvalue()

        name = f"sales_export_{f.start or 'all'}_{f.end or 'all'}_{date.today():%Y%m%d}.csv"
        return StreamingResponse(
            generate(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    return app


app = create_app()

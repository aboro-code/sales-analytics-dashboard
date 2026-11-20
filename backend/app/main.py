"""FastAPI application: read-only analytics API over the SQLite build."""

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from . import queries
from .db import Database
from .filters import Filters, FilterParser

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(db_path: str | None = None) -> FastAPI:
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        log.info("serving %s (%s rows, built %s)", db.path, meta_cache["build"].get("rows"), meta_cache["build"].get("built_at"))
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
            log.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, ms)
        return response

    # ------------------------------------------------------------------ #
    @app.get("/health", tags=["ops"])
    def health():
        """Cheap liveness probe (used by Render and by the frontend's wake-up check)."""
        return {"status": "ok", "rows": int(meta_cache["build"].get("rows", 0)), "built_at": meta_cache["build"].get("built_at")}

    @app.get("/api/meta", tags=["data"])
    def meta():
        """Filter options and dataset bounds."""
        return meta_cache

    @app.get("/api/summary", tags=["data"])
    def summary(f: FilterDep):
        return queries.summary(db, f)

    @app.get("/api/timeseries", tags=["data"])
    def timeseries(f: FilterDep, granularity: Literal["day", "week", "month"] = "day"):
        return {"granularity": granularity, "points": queries.timeseries(db, f, granularity)}

    @app.get("/api/breakdown", tags=["data"])
    def breakdown(
        f: FilterDep,
        dim: Literal["outlet", "group", "item", "order_type", "settlement"],
        limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    ):
        return {"dim": dim, "rows": queries.breakdown(db, f, dim, limit)}

    @app.get("/api/heatmap", tags=["data"])
    def heatmap(f: FilterDep):
        """Orders by weekday (0 = Monday) × hour of day."""
        return {"cells": queries.heatmap(db, f)}

    @app.get("/api/records", tags=["data"])
    def records(
        f: FilterDep,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=200)] = 25,
        sort: Literal[tuple(queries.SORTABLE)] = "order_ts",  # type: ignore[valid-type]
        order: Literal["asc", "desc"] = "desc",
    ):
        return queries.records(db, f, page, page_size, sort, order)

    return app


app = create_app()

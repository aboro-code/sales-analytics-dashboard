# syntax=docker/dockerfile:1
#
# Build from the repository root (the ETL needs /etl and /data):
#   docker build -f backend/Dockerfile -t sales-api .
#   docker run -p 8000:8000 sales-api
#
# Stage 1 runs the ETL (pandas + openpyxl, ~30 s) to produce the DuckDB file.
# Stage 2 is the slim runtime: FastAPI + DuckDB only, no pandas, plus the 6 MB database.

FROM python:3.12-slim AS etl
WORKDIR /src
COPY etl/requirements.txt etl/requirements.txt
RUN pip install --no-cache-dir -r etl/requirements.txt
COPY etl/build_db.py etl/build_db.py
COPY data/data.xlsx data/data.xlsx
RUN python etl/build_db.py --report /tmp/REPORT.md

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SALES_DB_PATH=/app/data/sales.duckdb
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=etl /src/data/sales.duckdb /app/data/sales.duckdb

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# $PORT is injected by Render/Railway/Cloud Run; default to 8000 locally.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

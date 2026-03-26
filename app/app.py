from __future__ import annotations

import json
import logging
import os
import random
import time
from logging.handlers import RotatingFileHandler

from flask import Flask, Response, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

SERVICE_NAME = os.getenv("SERVICE_NAME", "demo-api")
PORT = int(os.getenv("PORT", "8000"))
LOG_DIR = os.getenv("LOG_DIR", "/var/log/app")
ACCESS_LOG_PATH = os.path.join(LOG_DIR, "access.jsonl")

app = Flask(__name__)

REQUEST_COUNT = Counter(
    "demo_http_requests_total",
    "Total HTTP requests handled by the demo API",
    ["service", "method", "route", "status_code", "status_class"],
)

REQUEST_DURATION = Histogram(
    "demo_http_request_duration_seconds",
    "HTTP request latency seconds",
    ["service", "method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5),
)

INPROGRESS = Gauge(
    "demo_http_inprogress_requests",
    "In-flight HTTP requests",
    ["service"],
)


def _setup_access_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    open(ACCESS_LOG_PATH, "a", encoding="utf-8").close()
    log = logging.getLogger("access")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = RotatingFileHandler(ACCESS_LOG_PATH, maxBytes=5_000_000, backupCount=2)
    fh.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(fh)
    log.propagate = False
    return log


ACCESS_LOG = _setup_access_logger()


@app.before_request
def _before_request() -> None:
    request._start_ts = time.time()
    INPROGRESS.labels(service=SERVICE_NAME).inc()


@app.after_request
def _after_request(response: Response) -> Response:
    start_ts = getattr(request, "_start_ts", time.time())
    elapsed = max(time.time() - start_ts, 0)
    route = request.url_rule.rule if request.url_rule else "unknown"
    if route == "/metrics":
        INPROGRESS.labels(service=SERVICE_NAME).dec()
        return response

    status_code = str(response.status_code)
    status_class = f"{status_code[0]}xx"

    REQUEST_COUNT.labels(
        service=SERVICE_NAME,
        method=request.method,
        route=route,
        status_code=status_code,
        status_class=status_class,
    ).inc()

    REQUEST_DURATION.labels(
        service=SERVICE_NAME,
        method=request.method,
        route=route,
    ).observe(elapsed)

    INPROGRESS.labels(service=SERVICE_NAME).dec()

    line = json.dumps(
        {
            "ts": time.time(),
            "service": SERVICE_NAME,
            "method": request.method,
            "route": route,
            "status": response.status_code,
            "latency_ms": round(elapsed * 1000, 3),
            "msg": "http_request",
        },
        separators=(",", ":"),
    )
    ACCESS_LOG.info(line)

    return response


def _simulate_work(delay_ms: int, failure_rate: float) -> tuple[dict, int]:
    delay_s = max(delay_ms, 0) / 1000
    time.sleep(delay_s)

    if random.random() < failure_rate:
        return {"status": "error", "service": SERVICE_NAME}, 500

    return {"status": "ok", "service": SERVICE_NAME, "delay_ms": delay_ms}, 200


@app.get("/")
def root() -> tuple[dict, int]:
    return {"message": "demo api up", "service": SERVICE_NAME}, 200


@app.get("/health")
def health() -> tuple[dict, int]:
    return {"status": "up", "service": SERVICE_NAME}, 200


@app.get("/api/items")
def api_items() -> tuple[dict, int]:
    delay_ms = int(request.args.get("delay_ms", random.randint(10, 120)))
    failure_rate = float(request.args.get("failure_rate", "0.02"))
    return _simulate_work(delay_ms=delay_ms, failure_rate=failure_rate)


@app.get("/api/flaky")
def api_flaky() -> tuple[dict, int]:
    delay_ms = int(request.args.get("delay_ms", random.randint(40, 300)))
    failure_rate = float(request.args.get("failure_rate", "0.25"))
    return _simulate_work(delay_ms=delay_ms, failure_rate=failure_rate)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)

import uuid
import time
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ── configuration ────────────────────────────────────────────────────────────
EMAIL = "24f3005134@ds.study.iitm.ac.in"
ALLOWED_ORIGIN = "https://app-6ro6fy.example.com"
RATE_LIMIT_MAX = 14
RATE_LIMIT_WINDOW = 10

app = FastAPI()

rate_buckets: dict[str, deque] = defaultdict(deque)


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 3 — Per-client rate limiter (defined first = runs last)
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    bucket = rate_buckets[client_id]
    while bucket and bucket[0] < window_start:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_MAX:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Try again later."},
            headers={
                "Retry-After": str(RATE_LIMIT_WINDOW),
                "X-RateLimit-Limit": str(RATE_LIMIT_MAX),
                "X-RateLimit-Remaining": "0",
            },
        )

    bucket.append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_MAX)
    response.headers["X-RateLimit-Remaining"] = str(RATE_LIMIT_MAX - len(bucket))
    return response


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 2 — Scoped CORS policy (defined second = runs second)
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    origin = request.headers.get("origin", "")

    allowed_origins = {
        ALLOWED_ORIGIN,
        "https://exam.sanand.workers.dev",
    }

    origin_allowed = origin in allowed_origins

    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "X-Request-ID, X-Client-Id, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if origin_allowed:
            headers["Access-Control-Allow-Origin"] = origin
        return JSONResponse(status_code=200, content={}, headers=headers)

    response = await call_next(request)

    if origin_allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = (
            "X-Request-ID, X-Client-Id, Content-Type"
        )

    return response


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 1 — Request-context propagator (defined last = runs first)
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)

    # This must run outermost so it always sets the header
    response.headers["X-Request-ID"] = request_id
    return response


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping(request: Request):
    return {
        "email": EMAIL,
        "request_id": request.state.request_id,
    }

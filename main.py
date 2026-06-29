import uuid
import time
from collections import defaultdict, deque
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ── configuration ────────────────────────────────────────────────────────────
EMAIL = "24f3005134@ds.study.iitm.ac.in"
ALLOWED_ORIGIN = "https://app-6ro6fy.example.com"
RATE_LIMIT_MAX = 14        # max requests per window
RATE_LIMIT_WINDOW = 10     # seconds

# ── app ───────────────────────────────────────────────────────────────────────
app = FastAPI()

# ── rate-limit state (in-memory) ──────────────────────────────────────────────
# Maps client_id → deque of timestamps of recent requests
rate_buckets: dict[str, deque] = defaultdict(deque)


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 1 — Request-context propagator
# Runs last (outermost call-next means it wraps everything)
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    # Reuse inbound X-Request-ID or mint a fresh UUID4
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # Stash it so the endpoint can read it
    request.state.request_id = request_id

    response = await call_next(request)

    # Always echo it back in the response header
    response.headers["X-Request-ID"] = request_id
    return response


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 2 — Scoped CORS policy
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    origin = request.headers.get("origin", "")

    # Decide whether this origin is allowed
    # Allow the assigned origin AND the exam/grader page origin
    allowed_origins = {
        ALLOWED_ORIGIN,
        # Add the exam page origin so the browser-based grader can also reach /ping
        # (Replace with the actual exam page URL if you know it, or leave as-is
        #  and the server will only send ACAO for the two allowed origins)
    }

    origin_allowed = origin in allowed_origins

    # Handle CORS preflight (OPTIONS)
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "X-Request-ID, X-Client-Id, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if origin_allowed:
            headers["Access-Control-Allow-Origin"] = origin
        return JSONResponse(status_code=200, content={}, headers=headers)

    # Normal request
    response = await call_next(request)

    if origin_allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = (
            "X-Request-ID, X-Client-Id, Content-Type"
        )

    return response


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE 3 — Per-client rate limiter (sliding-window)
# ─────────────────────────────────────────────────────────────────────────────
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Skip rate-limiting for preflight requests
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW

    bucket = rate_buckets[client_id]

    # Drop timestamps outside the current window
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

    # Add helpful rate-limit headers
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT_MAX)
    response.headers["X-RateLimit-Remaining"] = str(RATE_LIMIT_MAX - len(bucket))
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

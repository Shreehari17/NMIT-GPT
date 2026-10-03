import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.ask import router as ask_router
from backend.routes.admin_upload import router as admin_router
from backend.routes.admin_calendar import router as admin_calendar_router
from backend.routes.admin_circulars import router as admin_circulars_router
from backend.routes.debug import router as debug_router
from backend.routes.auth import router as auth_router
from backend.routes.health import router as health_router

app = FastAPI(title="Faculty-GPT Backend")

# Wildcard origins let ANY website read responses that include the user's
# Bearer token flows (CSRF-adjacent risk, and trivially allows a malicious
# site to hit your API using a visitor's stored token if it ever leaks into
# JS scope). Restrict to an explicit allow-list instead; override in
# production via the ALLOWED_ORIGINS env var (comma-separated).
_default_origins = "http://localhost:8000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(ask_router)
app.include_router(admin_router)
app.include_router(admin_calendar_router)  # was never registered — calendar upload was dead code
app.include_router(admin_circulars_router)
app.include_router(debug_router)
app.include_router(auth_router)
app.include_router(health_router)
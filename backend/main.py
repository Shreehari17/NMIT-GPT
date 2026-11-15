import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.ask import router as ask_router
from backend.routes.debug import router as debug_router
from backend.routes.auth import router as auth_router
from backend.routes.health import router as health_router

app = FastAPI(title="NMIT-GPT Backend")

# Wildcard origins let ANY website read responses that include the user's
# Bearer token flows (CSRF-adjacent risk, and trivially allows a malicious
# site to hit your API using a visitor's stored token if it ever leaks into
# JS scope). Restrict to an explicit allow-list instead; override in
# production via the ALLOWED_ORIGINS env var (comma-separated).
_default_origins = "http://localhost:8000,http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
]
print("Allowed CORS origins:", ALLOWED_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(ask_router)
# Heavy admin-processing modules are excluded from lightweight hosting.
LITE_MODE = os.getenv("LITE_MODE", "false").lower() == "true"

if not LITE_MODE:
    from backend.routes.admin_upload import router as admin_router
    from backend.routes.admin_calendar import router as admin_calendar_router
    from backend.routes.admin_circulars import router as admin_circulars_router
    from backend.routes.admin_timetable import router as admin_timetable_router

    app.include_router(admin_router)
    app.include_router(admin_calendar_router)
    app.include_router(admin_circulars_router)
    app.include_router(admin_timetable_router)
if os.getenv("ENABLE_DEBUG_ROUTES", "false").lower() == "true":
    app.include_router(debug_router)
app.include_router(auth_router)
app.include_router(health_router)

# Serve the frontend from the same origin as the API.
from pathlib import Path
from fastapi.responses import FileResponse

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@app.get("/", include_in_schema=False)
@app.get("/nmit-gpt.html", include_in_schema=False)
def student_frontend():
    return FileResponse(FRONTEND_DIR / "nmit-gpt.html")


@app.get("/admin", include_in_schema=False)
@app.get("/admin.html", include_in_schema=False)
def admin_frontend():
    return FileResponse(FRONTEND_DIR / "admin.html")

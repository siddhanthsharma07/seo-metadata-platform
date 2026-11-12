import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import ai, auth, crawls, dashboard, exports, pages, projects, settings
from app.config import get_settings
from app.db import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

cfg = get_settings()
if cfg.environment == "production" and cfg.secret_key.startswith("change-me"):
    raise RuntimeError("SECRET_KEY must be set to a strong random value in production")

app = FastAPI(title=cfg.app_name, version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware, allow_origins=cfg.cors_origin_list, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"],
)

for r in (auth.router, projects.router, crawls.router, pages.router, ai.router, dashboard.router, exports.router, settings.router):
    app.include_router(r, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    msg = "; ".join(f"{e['field']}: {e['message']}" for e in errors[:5])
    return JSONResponse(status_code=422, content={"detail": f"Invalid input. {msg}", "errors": errors})


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Unexpected server error. Check the server logs for details."})


@app.get("/api/health")
def health():
    db_ok = True
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "task_backend": cfg.task_backend}

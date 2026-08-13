import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api
from app.core.db import SessionLocal, engine
from app.core.errors import AppError
from app.models import Base
from app.services import calendar_service
from app.ws import manager
from scripts.seed import seed_if_empty

logger = logging.getLogger("jieqi")


def init_db() -> None:
    Base.metadata.create_all(engine)


async def term_broadcast_loop() -> None:
    """节气切换广播:每轮(默认 5 分钟)推一次 solar_term_change。"""
    while True:
        try:
            with SessionLocal() as db:
                remaining = calendar_service.next_switch_in(db)
            await asyncio.sleep(max(1, remaining + 1))
            with SessionLocal() as db:
                cal = calendar_service.current_calendar(db)
            await manager.broadcast(
                {"type": "solar_term_change", "payload": cal, "ts": int(time.time())}
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.exception("节气广播异常: %s", e)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
    task = asyncio.create_task(term_broadcast_loop())
    yield
    task.cancel()


app = FastAPI(title="jieqi_backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "error_code": exc.error_code, "message": exc.message},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 90000, "error_code": "INTERNAL_ERROR", "message": "服务器内部错误"},
    )

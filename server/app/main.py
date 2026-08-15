import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text

from app.api.router import api
from app.core.db import SessionLocal, engine
from app.core.errors import AppError
from app.models import Base
from app.ws import manager
from scripts.seed import seed_if_empty

logger = logging.getLogger("jieqi")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _ensure_player_world_columns()
    _ensure_crop_columns()
    _ensure_weed_columns()
    _ensure_wilted_columns()
    _ensure_users_name_nonunique()


def _ensure_player_world_columns() -> None:
    """老 dev.db 无每用户世界/虫害列:幂等 ALTER 补齐(新库 create_all 已建)。"""
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("players")}
        with engine.begin() as conn:
            if "world_accum" not in cols:
                conn.execute(text("ALTER TABLE players ADD COLUMN world_accum REAL DEFAULT 0"))
            if "world_last_sync" not in cols:
                conn.execute(text("ALTER TABLE players ADD COLUMN world_last_sync DATETIME"))
            if "next_pest_at" not in cols:
                conn.execute(text("ALTER TABLE players ADD COLUMN next_pest_at DATETIME"))
    except Exception as e:  # noqa: BLE001 迁移失败不阻塞启动(测试库重建不受影响)
        logger.warning("玩家世界/虫害列迁移跳过: %s", e)
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("crop_instances")}
        with engine.begin() as conn:
            if "destroyed_at" not in cols:
                conn.execute(
                    text("ALTER TABLE crop_instances ADD COLUMN destroyed_at DATETIME")
                )
            # 部分唯一索引重建:未收获且未摧毁
            conn.execute(text("DROP INDEX IF EXISTS uq_crop_inst_active_plot"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_crop_inst_active_plot ON crop_instances (plot_id) "
                    "WHERE harvested_at IS NULL AND destroyed_at IS NULL"
                )
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("crop_instances 摧毁列迁移跳过: %s", e)


def _ensure_crop_columns() -> None:
    """老 dev.db 无作物高级设定列:幂等 ALTER 补齐。"""
    try:
        cols = {c["name"] for c in inspect(engine).get_columns("crops")}
        with engine.begin() as conn:
            if "unlock_exp" not in cols:
                conn.execute(text("ALTER TABLE crops ADD COLUMN unlock_exp INTEGER DEFAULT 0"))
            if "settings" not in cols:
                conn.execute(text("ALTER TABLE crops ADD COLUMN settings JSON"))
    except Exception as e:
        logger.warning("crops 高级设定列迁移跳过: %s", e)


def _ensure_weed_columns() -> None:
    """杂草系统列:plots.weeded + players.weed_scheduled_accum(幂等 ALTER)。"""
    try:
        with engine.begin() as conn:
            cols = {c["name"] for c in inspect(engine).get_columns("plots")}
            if "weeded" not in cols:
                conn.execute(text("ALTER TABLE plots ADD COLUMN weeded BOOLEAN DEFAULT 0"))
            cols = {c["name"] for c in inspect(engine).get_columns("players")}
            if "weed_scheduled_accum" not in cols:
                conn.execute(
                    text("ALTER TABLE players ADD COLUMN weed_scheduled_accum FLOAT")
                )
    except Exception as e:
        logger.warning("杂草系统列迁移跳过: %s", e)


def _ensure_users_name_nonunique() -> None:
    """放开用户名重名(班级同名场景):删除 users.name 的唯一索引。

    老库曾以 unique=True 建出唯一索引 ix_users_name;新库 create_all 已不再建。
    SQLite 无 DROP CONSTRAINT,唯一性由唯一索引承担 → 删索引即放开。
    """
    with engine.begin() as conn:
        idxs = conn.execute(text("PRAGMA index_list('users')")).fetchall()
        for name, _, unique in [(r[1], r[2], r[3]) for r in idxs]:
            if name == "ix_users_name" and unique:
                conn.execute(text("DROP INDEX ix_users_name"))
                break


def _ensure_wilted_columns() -> None:
    """枯萎改状态列:crop_instances.wilted_at + crop_storage.wilted_quantity(幂等 ALTER)。"""
    try:
        with engine.begin() as conn:
            cols = {c["name"] for c in inspect(engine).get_columns("crop_instances")}
            if "wilted_at" not in cols:
                conn.execute(
                    text("ALTER TABLE crop_instances ADD COLUMN wilted_at DATETIME")
                )
            cols = {c["name"] for c in inspect(engine).get_columns("crop_storage")}
            if "wilted_quantity" not in cols:
                conn.execute(
                    text("ALTER TABLE crop_storage ADD COLUMN wilted_quantity INTEGER DEFAULT 0")
                )
    except Exception as e:
        logger.warning("枯萎列迁移跳过: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
    manager.loop = asyncio.get_running_loop()  # 供同步 handler 线程安全推送(资源变更等)
    yield


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

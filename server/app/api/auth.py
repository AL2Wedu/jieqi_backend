from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_player, get_db
from app.core.errors import AppError, ok
from app.core.ratelimit import login_limiter, register_limiter
from app.models import Player
from app.schemas import DeactivateRequest, LoginRequest, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _trusted_proxies() -> set[str]:
    """可信反代 IP 集合(配置 trusted_proxies,逗号分隔)。"""
    return {p.strip() for p in settings.trusted_proxies.split(",") if p.strip()}


def _client_ip(request: Request) -> str | None:
    """取客户端真实 IP。

    安全:仅当请求来自可信反代(trusted_proxies 白名单)时才信任 X-Forwarded-For;
    否则一律用直连地址(request.client.host),防伪造 IP 污染注册/登录数据。
    """
    client_host = request.client.host if request.client else None
    trusted = _trusted_proxies()
    if client_host in trusted:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return client_host


@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request) or "unknown"
    if settings.rate_limit_enabled and not register_limiter.allow(f"register:{ip}"):
        raise AppError(
            "RATE_LIMITED", "注册过于频繁,请稍后再试", http_status=429, code=10003
        )
    return ok(auth_service.register(db, req.name, req.password, ip))


@router.post("/deactivate")
def deactivate(
    req: DeactivateRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """注销账号(留档冻结):需当前密码 + confirm=true;注销后无法登录,世界冻结。"""
    return ok(auth_service.deactivate(db, player, req.password, req.confirm))


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request) or "unknown"
    if settings.rate_limit_enabled and not login_limiter.allow(f"login:{ip}:{req.name}"):
        raise AppError(
            "RATE_LIMITED", "登录尝试过于频繁,请稍后再试", http_status=429, code=10003
        )
    return ok(auth_service.login(db, req.name, req.password, ip))

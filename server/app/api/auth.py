from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import DeactivateRequest, LoginRequest, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """取客户端真实 IP:优先 X-Forwarded-For(反代后),回退直连地址。"""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    return ok(auth_service.register(db, req.name, req.password, _client_ip(request)))


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
    return ok(auth_service.login(db, req.name, req.password, _client_ip(request)))

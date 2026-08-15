"""玩家端兑换码兑换:POST /v1/redeem(限速 + 哈希匹配 + 原子抢占)。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import ok
from app.models import Player
from app.schemas import RedeemRequest
from app.services import redeem_service

router = APIRouter(prefix="/redeem", tags=["redeem"])


@router.post("")
def redeem(
    req: RedeemRequest,
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """兑换码兑换:奖励(金币/经验/道具)走账本;无效/过期/停用统一 20010,防枚举。"""
    return ok(redeem_service.redeem(db, player, req.code))

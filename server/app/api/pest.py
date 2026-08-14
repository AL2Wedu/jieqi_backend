"""虫害系统 API:大虫害成绩提交 / 小虫害驱赶 / 玩家虫害状态。"""
import uuid

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_player, get_db
from app.core.errors import AppError, ok
from app.models import Player
from app.schemas import PestDriveAwayRequest, PestResultRequest
from app.services import pest_service

router = APIRouter(tags=["pest"])


@router.get("/pest/state")
def pest_state(player: Player = Depends(get_current_player), db: Session = Depends(get_db)):
    """我的虫害状态:下次触发时间 / 进行中的大虫害 / 寄生中地块与倒计时。"""
    return ok(pest_service.player_state(db, player))


@router.post("/farm/pest/{pest_id}/result")
def submit_result(
    pest_id: str,
    req: PestResultRequest = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """大虫害:前端音游结束后提交成绩(score/max_score/miss_count)。

    防作弊:广播到提交的时间间隔 < 音游时长 × min_elapsed_factor → 拒绝(28006)。
    达标 → 奖励(金币 + 随机道具);不达标 → miss//2 个随机田块寄生小虫害。
    """
    return ok(
        pest_service.submit_big_result(
            db, player, pest_id, req.score, req.max_score, req.miss_count
        )
    )


@router.post("/farm/pest/{pest_id}/drive-away")
def drive_away(
    pest_id: str,
    req: PestDriveAwayRequest = Body(...),
    player: Player = Depends(get_current_player),
    db: Session = Depends(get_db),
):
    """小虫害:驱赶成功 → 即刻消除对应地块的虫害(前端完成交互后调用)。"""
    return ok(pest_service.drive_away(db, player, pest_id, req.plot_id))


def _to_uuid(s: str) -> uuid.UUID:
    try:
        return uuid.UUID(s)
    except ValueError:
        raise AppError("INVALID_PARAMS", "无效的 ID", code=10001)

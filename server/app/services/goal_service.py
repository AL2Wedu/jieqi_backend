"""通用目标求值器:任务与成就共用。

条件格式(objective / target)为一个 JSON 对象:
  {"type": "sow", "count": 3}              累计播种次数
  {"type": "harvest", "count": 5}          累计收获次数
  {"type": "spend_coins", "amount": 100}   累计消费金币
  {"type": "level", "level": 2}            达到等级
  {"type": "friend", "count": 1}           好友数量
  {"type": "counter", "key": "ai_requests", "count": 10}  通用计数器(由业务事件累加)
  {"type": "any", "count": 1}              占位(直接达成)

进度一律由服务器从真实数据计算(不依赖客户端上报),新增条件类型只需扩展本文件。
"""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import (
    AiUsage,
    CoinTransaction,
    CropInstance,
    Farm,
    Friendship,
    Item,
    ItemTransaction,
    Player,
    Plot,
    UserItem,
)


def evaluate(db: Session, player: Player, condition: dict) -> tuple[int, int]:
    """返回 (当前值, 目标值)。"""
    condition = condition or {"type": "any"}
    ctype = condition.get("type", "any")
    target = int(
        condition.get("count")
        or condition.get("amount")
        or condition.get("level")
        or 1
    )
    if ctype == "sow":
        cur = (
            db.query(func.count(CropInstance.id))
            .join(Plot, CropInstance.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .filter(Farm.owner_id == player.id)
            .scalar()
            or 0
        )
    elif ctype == "harvest":
        cur = (
            db.query(func.count(CropInstance.id))
            .join(Plot, CropInstance.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .filter(Farm.owner_id == player.id, CropInstance.harvested_at.isnot(None))
            .scalar()
            or 0
        )
    elif ctype == "spend_coins":
        spent = (
            db.query(func.coalesce(func.sum(CoinTransaction.amount), 0))
            .filter(CoinTransaction.player_id == player.id, CoinTransaction.amount < 0)
            .scalar()
            or 0
        )
        cur = abs(int(spent))
    elif ctype == "level":
        cur = player.level
    elif ctype == "friend":
        cur = (
            db.query(func.count(Friendship.player_a))
            .filter(
                or_(
                    Friendship.player_a == player.id,
                    Friendship.player_b == player.id,
                ),
                Friendship.status == 1,
            )
            .scalar()
            or 0
        )
    elif ctype == "counter":
        key = condition.get("key", "")
        if key == "ai_requests":
            cur = (
                db.query(func.coalesce(func.sum(AiUsage.requests), 0))
                .filter(AiUsage.player_id == player.id)
                .scalar()
                or 0
            )
        elif key == "ai_tokens":
            cur = (
                db.query(func.coalesce(func.sum(AiUsage.total_tokens), 0))
                .filter(AiUsage.player_id == player.id)
                .scalar()
                or 0
            )
        else:
            cur = 0
    else:  # any 或未知类型:直接视为达成
        cur = target
    return cur, target


def grant_reward(db: Session, player: Player, reward: dict | None, reason: str) -> dict:
    """发放奖励(金币/经验/道具),全部走账本。返回奖励明细。"""
    reward = reward or {}
    coins = int(reward.get("coins", 0))
    exp = int(reward.get("exp", 0))
    items = reward.get("items", []) or []
    granted = {"coins": coins, "exp": exp, "items": []}
    if coins:
        player.coins += coins
        db.add(
            CoinTransaction(player_id=player.id, amount=coins, reason=reason)
        )
    if exp:
        player.exp += exp
    for it in items:
        code = it.get("code")
        qty = int(it.get("quantity", 1))
        item = db.query(Item).filter(Item.code == code).first()
        if not item:
            continue
        ui = (
            db.query(UserItem)
            .filter(UserItem.player_id == player.id, UserItem.item_id == item.id)
            .first()
        )
        if ui:
            ui.quantity += qty
        else:
            db.add(UserItem(player_id=player.id, item_id=item.id, quantity=qty))
        db.add(
            ItemTransaction(
                player_id=player.id, item_id=item.id, delta=qty, reason=reason
            )
        )
        granted["items"].append({"code": code, "quantity": qty})
    return granted

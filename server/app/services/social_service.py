"""社交系统:好友申请 / 接受 / 拒绝 / 列表 / 删除。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Farm, Friendship, Player, User


def _utcnow():
    return datetime.now(timezone.utc)


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if a < b else (b, a)


def _player_name(db: Session, player_id) -> str:
    p = db.query(Player).filter(Player.id == player_id).first()
    u = db.query(User).filter(User.id == p.user_id).first() if p else None
    return u.name if u else "?"


def send_request(db: Session, player: Player, target_id: str) -> dict:
    try:
        target_uuid = uuid.UUID(target_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    if target_uuid == player.id:
        raise AppError("INVALID_PARAMS", "不能添加自己为好友", code=10001)
    target = db.query(Player).filter(Player.id == target_uuid).first()
    if not target:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    a, b = _pair(player.id, target_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b)
        .first()
    )
    if fs:
        if fs.status == 1:
            raise AppError("ALREADY_FRIENDS", "你们已经是好友", code=27001)
        if fs.status == 0:
            raise AppError("REQUEST_EXISTS", "申请已发送,等待对方处理", code=27002)
        # 曾被拒绝:允许重新申请
        fs.status = 0
        fs.responded_at = None
        fs.created_at = _utcnow()
    else:
        db.add(
            Friendship(
                player_a=a,
                player_b=b,
                requester=player.id,
                status=0,
            )
        )
    db.commit()
    return {"status": 0, "target_player_id": str(target_uuid)}


def list_friends(db: Session, player: Player) -> dict:
    rows = (
        db.query(Friendship)
        .filter(
            or_(Friendship.player_a == player.id, Friendship.player_b == player.id),
            Friendship.status == 1,
        )
        .all()
    )
    ids = [r.player_b if r.player_a == player.id else r.player_a for r in rows]
    return {
        "items": [
            {"player_id": str(pid), "name": _player_name(db, pid)} for pid in ids
        ]
    }


def list_requests(db: Session, player: Player) -> dict:
    """发给我的待处理申请(requester 不是我),按申请时间倒序。"""
    rows = (
        db.query(Friendship)
        .filter(
            or_(Friendship.player_a == player.id, Friendship.player_b == player.id),
            Friendship.status == 0,
            Friendship.requester != player.id,
        )
        .order_by(Friendship.created_at.desc())
        .all()
    )
    # 有序去重:同一 requester 只取最新一条,保持 created_at 倒序(set 会破坏顺序)
    seen: set[uuid.UUID] = set()
    items = []
    for r in rows:
        if r.requester in seen:
            continue
        seen.add(r.requester)
        items.append(
            {
                "player_id": str(r.requester),
                "name": _player_name(db, r.requester),
                "created_at": r.created_at.isoformat(),
            }
        )
    return {"items": items}


def respond(db: Session, player: Player, requester_id: str, accept: bool) -> dict:
    try:
        requester_uuid = uuid.UUID(requester_id)
    except ValueError:
        raise AppError("REQUEST_NOT_FOUND", "申请不存在", code=27003)
    a, b = _pair(player.id, requester_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b)
        .first()
    )
    if not fs or fs.status != 0:
        raise AppError("REQUEST_NOT_FOUND", "申请不存在", code=27003)
    if fs.requester != requester_uuid:
        raise AppError("NOT_YOUR_REQUEST", "该申请不是发给你的", code=27004)
    fs.status = 1 if accept else 2
    fs.responded_at = _utcnow()
    db.commit()
    return {"status": fs.status, "target_player_id": str(requester_uuid)}


def remove_friend(db: Session, player: Player, other_id: str) -> dict:
    try:
        other_uuid = uuid.UUID(other_id)
    except ValueError:
        raise AppError("FRIEND_NOT_FOUND", "好友不存在", code=27005)
    a, b = _pair(player.id, other_uuid)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b, Friendship.status == 1)
        .first()
    )
    if not fs:
        raise AppError("FRIEND_NOT_FOUND", "好友不存在", code=27005)
    db.delete(fs)
    db.commit()
    return {"removed_player_id": str(other_uuid)}


# ---------- 查询与资料卡 ----------

def _relation(db: Session, me: Player, other_id: uuid.UUID) -> str:
    """我与目标的关系:none / pending_out / pending_in / friends。"""
    if other_id == me.id:
        return "self"
    a, b = _pair(me.id, other_id)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b)
        .first()
    )
    if not fs:
        return "none"
    if fs.status == 1:
        return "friends"
    if fs.status == 0:
        return "pending_out" if fs.requester == me.id else "pending_in"
    return "none"  # 已拒绝


def _profile_view(db: Session, target: Player) -> dict:
    u = db.query(User).filter(User.id == target.user_id).first()
    farm = db.query(Farm).filter(Farm.owner_id == target.id).first()
    return {
        "player_id": str(target.id),
        "uid_num": u.uid_num if u else None,  # 对外纯数字 ID
        "name": u.name if u else "?",
        "level": target.level,
        "unlocked_term_index": target.unlocked_term_index,
        "farm_name": farm.name if farm else None,
        "last_active_at": (
            target.last_active_at.isoformat(timespec="seconds")
            if target.last_active_at
            else None
        ),
    }


def _get_player(db: Session, player_id: str) -> Player:
    try:
        pid = uuid.UUID(player_id)
    except ValueError:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    p = db.query(Player).filter(Player.id == pid).first()
    if not p:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    return p


def search_players(db: Session, player: Player, q: str, limit: int = 20, exact: bool = False) -> dict:
    """按名字查询玩家(排除自己),返回公开资料。

    exact=True → 精确匹配用户名(重名全部返回,limit 内);False → 模糊包含匹配。
    """
    q = (q or "").strip()
    if not q:
        raise AppError("INVALID_PARAMS", "搜索词不能为空", code=10001)
    # 转义 LIKE 通配符,避免 % 和 _ 被当通配符(搜"100%"应精确匹配字面百分号)
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    cond = User.name == q if exact else User.name.like(like, escape="\\")
    rows = (
        db.query(Player, User)
        .join(User, User.id == Player.user_id)
        .filter(cond, Player.id != player.id)
        .order_by(Player.last_active_at.desc())
        .limit(max(1, min(int(limit), 50)))
        .all()
    )
    # 一次查出全部农场,避免逐条 N+1(用户已 join,不必再查 User)
    farm_map = {
        f.owner_id: f
        for f in db.query(Farm)
        .filter(Farm.owner_id.in_([p.id for p, _ in rows]))
        .all()
    }
    items = []
    for p, u in rows:
        f = farm_map.get(p.id)
        items.append(
            {
                "player_id": str(p.id),
                "name": u.name,
                "level": p.level,
                "unlocked_term_index": p.unlocked_term_index,
                "farm_name": f.name if f else None,
                "last_active_at": (
                    p.last_active_at.isoformat(timespec="seconds")
                    if p.last_active_at
                    else None
                ),
            }
        )
    return {"items": items}


def get_player_profile(db: Session, player: Player, target_id: str) -> dict:
    """UUID 查询:任意玩家的公开资料 + 与我方关系。"""
    target = _get_player(db, target_id)
    view = _profile_view(db, target)
    view["relation"] = _relation(db, player, target.id)
    return view


def get_friend_profile(db: Session, player: Player, friend_id: str) -> dict:
    """好友资料卡(须已是好友):公开资料 + 好友关系时间。"""
    target = _get_player(db, friend_id)
    a, b = _pair(player.id, target.id)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b, Friendship.status == 1)
        .first()
    )
    if not fs:
        raise AppError("FRIEND_NOT_FOUND", "对方不是你的好友", code=27005)
    view = _profile_view(db, target)
    view["relation"] = "friends"
    view["friends_since"] = fs.created_at.isoformat(timespec="seconds")
    return view


def _farm_snapshot(db: Session, target: Player) -> dict:
    """农场参观快照(只读,无任何副作用:不触发枯萎/杂草/虫害判定)。

    返回田格数据:每格 plot_id/idx/土壤肥力/锁定/杂草 + 作物状态
    (stage/status/water_level/water_need/growth_progress/wilted),
    供访客模式与"帮忙浇水"等互动功能读取。
    """
    from app.models import Crop, CropInstance, Plot
    from app.services.farm_service import crop_view

    farm = db.query(Farm).filter(Farm.owner_id == target.id).first()
    if not farm:
        return {"farm": None, "plots": []}
    plots = db.query(Plot).filter(Plot.farm_id == farm.id).order_by(Plot.idx).all()
    active = {
        ci.plot_id: ci
        for ci in db.query(CropInstance)
        .filter(
            CropInstance.plot_id.in_([p.id for p in plots]),
            CropInstance.harvested_at.is_(None),
            CropInstance.destroyed_at.is_(None),
        )
        .all()
    }
    crops = {c.id: c for c in db.query(Crop).all()}
    return {
        "farm": {
            "farm_id": str(farm.id),
            "name": farm.name,
            "plot_count": farm.plot_count,
            "owner": _profile_view(db, target),
        },
        "plots": [
            {
                "plot_id": str(p.id),
                "idx": p.idx,
                "soil_quality": p.soil_quality,
                "locked": p.locked,
                "weeded": bool(p.weeded),
                "crop": crop_view(
                    active[p.id],
                    crops.get(active[p.id].crop_id),
                    weeded=bool(p.weeded),  # 与主人视图一致:杂草地块按减速算进度
                )
                if p.id in active
                else None,
            }
            for p in plots
        ],
    }


def get_friend_farm(db: Session, player: Player, friend_id: str) -> dict:
    """好友农场参观(须已是好友;只读快照,无任何副作用)。"""
    target = _get_player(db, friend_id)
    a, b = _pair(player.id, target.id)
    fs = (
        db.query(Friendship)
        .filter(Friendship.player_a == a, Friendship.player_b == b, Friendship.status == 1)
        .first()
    )
    if not fs:
        raise AppError("FRIEND_NOT_FOUND", "对方不是你的好友", code=27005)
    return _farm_snapshot(db, target)


def get_player_farm(db: Session, player: Player, target_id: str) -> dict:
    """公开访客模式:任意玩家农场参观(只读快照,含田格数据)。

    不要求好友关系 —— 找到对方(用户名查询/UUID 查询)即可参观其田格,
    为"帮忙浇水"等互动功能提供前置数据;浇水/偷菜等副作用仍仅限好友。
    """
    target = _get_player(db, target_id)
    return _farm_snapshot(db, target)


# ---------- 预留互动契约(接口已定,功能待上线) ----------

def water_friend(db: Session, player: Player, friend_id: str) -> dict:
    """互助浇水(预留):接口契约已定,功能开发中。
    未来契约:POST /v1/social/friends/{player_id}/water
    → {friend_player_id, watered_plot_count, cooldown_seconds}
    """
    get_friend_profile(db, player, friend_id)  # 校验是好友
    return {
        "feature": "water",
        "enabled": False,
        "message": "互助浇水开发中,敬请期待",
    }


def steal_from_friend(db: Session, player: Player, friend_id: str, plot_idx: int) -> dict:
    """偷菜(预留):接口契约已定,功能开发中。
    未来契约:POST /v1/social/friends/{player_id}/plots/{plot_idx}/steal
    → {friend_player_id, plot_idx, stolen_crop, stolen_quantity, daily_remaining}
    """
    get_friend_profile(db, player, friend_id)  # 校验是好友
    return {
        "feature": "steal",
        "enabled": False,
        "message": "偷菜玩法开发中,敬请期待",
    }

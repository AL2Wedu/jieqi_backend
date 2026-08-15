from datetime import datetime, timezone
import random

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.iploc import resolve as resolve_location
from app.core.security import create_token, hash_password, verify_password
from app.models import CoinTransaction, Farm, Player, Plot, User
from app.services import world_service

START_COINS = 200
START_PLOTS = 20  # 田地格子:横 4 × 竖 5


def gen_uid_num(db: Session) -> int:
    """生成对外纯数字 ID(随机,防枚举):先试 7 位,碰撞重试 5 次后扩到 8 位。"""
    for bits in (7, 8):
        for _ in range(5):
            n = random.randint(10 ** (bits - 1), 10**bits - 1)
            if not db.query(User.id).filter(User.uid_num == n).first():
                return n
    raise AppError("UID_GEN_FAILED", "数字 ID 生成失败,请重试", code=20014)


def backfill_uid_nums(db: Session) -> None:
    """老用户补分配 uid_num(幂等:只处理 NULL,启动迁移时调用)。"""
    rows = db.query(User).filter(User.uid_num.is_(None)).all()
    for u in rows:
        u.uid_num = gen_uid_num(db)
    if rows:
        db.commit()


def player_summary(player: Player, farm: Farm | None, user: User) -> dict:
    return {
        "player_id": str(player.id),
        "uid_num": user.uid_num,  # 对外纯数字 ID(查询/展示用)
        "name": user.name,
        "level": player.level,
        "exp": player.exp,
        "coins": player.coins,
        "head_title_id": str(player.head_title_id) if player.head_title_id else None,
        "unlocked_term_index": player.unlocked_term_index,
        "farm_id": str(farm.id) if farm else None,
        "plot_count": farm.plot_count if farm else 0,
        "register_location": user.register_location,
        "last_login_location": user.last_login_location,
        "tutorial": bool(getattr(player, "tutorial", True)),  # 新手教学状态
    }


def register(db: Session, name: str, password: str, ip: str | None) -> dict:
    # 允许重名(班级同名场景):登录按"名字+密码"双匹配,见 login
    user = User(
        name=name,
        password_hash=hash_password(password),
        uid_num=gen_uid_num(db),  # 对外纯数字 ID
        register_ip=ip,
        register_location=resolve_location(ip),
    )
    db.add(user)
    db.flush()
    player = Player(user_id=user.id, coins=START_COINS)
    db.add(player)
    db.flush()
    farm = Farm(owner_id=player.id, name=f"{name}的农场")
    db.add(farm)
    db.flush()
    for i in range(1, START_PLOTS + 1):
        db.add(Plot(farm_id=farm.id, idx=i))
    world_service.sync_world(db, player)  # 初始化每用户世界(继承全局纪元位置)
    db.add(CoinTransaction(player_id=player.id, amount=START_COINS, reason="register"))
    db.commit()
    return {
        "token": create_token(str(user.id)),
        "player": player_summary(player, farm, user),
    }


def login(db: Session, name: str, password: str, ip: str | None) -> dict:
    # 名字可重名 → 密码双匹配:同名的账号里,密码匹配且唯一命中的那个才登录
    candidates = db.query(User).filter(User.name == name).all()
    matched = [u for u in candidates if verify_password(password, u.password_hash)]
    if not matched:
        raise AppError("BAD_CREDENTIALS", "用户名或密码错误", code=20003)
    if len(matched) > 1:
        raise AppError(
            "NAME_CONFLICT",
            "该名字有多个账号且密码相同,请修改其中一个账号的密码",
            code=20006,
        )
    user = matched[0]
    if user.status == 2:
        raise AppError("USER_DEACTIVATED", "账号已注销,无法登录", http_status=403, code=20007)
    if user.status != 1:
        raise AppError("USER_BANNED", "账号已被封禁", http_status=403, code=20004)
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    user.last_login_location = resolve_location(ip)
    player = db.query(Player).filter(Player.user_id == user.id).first()
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    world_service.sync_world(db, player)  # 登录即心跳,恢复每用户世界累计
    db.commit()
    return {
        "token": create_token(str(user.id)),
        "player": player_summary(player, farm, user),
    }


def deactivate(db: Session, player: Player, password: str, confirm: bool) -> dict:
    """注销账号(留档冻结):status=2 + deactivated_at,数据绝不删除。

    安全:需当前密码(防盗号注销)+ confirm=true 二次确认;
    注销后登录与存量 token 均被拒(20007),世界时钟冻结在注销时刻。
    """
    user = db.query(User).filter(User.id == player.user_id).first()
    if not user:
        raise AppError("USER_NOT_FOUND", "用户不存在", code=20002)
    if not verify_password(password, user.password_hash):
        raise AppError("BAD_CREDENTIALS", "密码错误", code=20003)
    if not confirm:
        raise AppError("INVALID_PARAMS", "需传 confirm=true 确认注销", code=10001)
    if user.status == 2:
        raise AppError("USER_DEACTIVATED", "账号已注销", code=20007)
    user.status = 2
    user.deactivated_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "user_id": str(user.id),
        "name": user.name,
        "status": 2,
        "deactivated_at": user.deactivated_at.isoformat(timespec="seconds"),
    }

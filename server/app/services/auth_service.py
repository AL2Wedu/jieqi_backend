from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.iploc import resolve as resolve_location
from app.core.security import create_token, hash_password, verify_password
from app.models import CoinTransaction, Farm, Player, Plot, User
from app.services import world_service

START_COINS = 200
START_PLOTS = 20  # 田地格子:横 4 × 竖 5


def player_summary(player: Player, farm: Farm | None, user: User) -> dict:
    return {
        "player_id": str(player.id),
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
    }


def register(db: Session, name: str, password: str, ip: str | None) -> dict:
    # 允许重名(班级同名场景):登录按"名字+密码"双匹配,见 login
    user = User(
        name=name,
        password_hash=hash_password(password),
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

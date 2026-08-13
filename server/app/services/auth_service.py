from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import create_token, hash_password, verify_password
from app.models import CoinTransaction, Farm, Player, Plot, User

START_COINS = 200
START_PLOTS = 6


def player_summary(player: Player, farm: Farm | None, name: str) -> dict:
    return {
        "player_id": str(player.id),
        "name": name,
        "level": player.level,
        "exp": player.exp,
        "coins": player.coins,
        "head_title_id": str(player.head_title_id) if player.head_title_id else None,
        "unlocked_term_index": player.unlocked_term_index,
        "farm_id": str(farm.id) if farm else None,
        "plot_count": farm.plot_count if farm else 0,
    }


def register(db: Session, name: str, password: str, ip: str | None) -> dict:
    if db.query(User).filter(User.name == name).first():
        raise AppError("USER_EXISTS", "用户名已存在", code=20001)
    user = User(name=name, password_hash=hash_password(password), register_ip=ip)
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
    db.add(CoinTransaction(player_id=player.id, amount=START_COINS, reason="register"))
    db.commit()
    return {
        "token": create_token(str(user.id)),
        "player": player_summary(player, farm, name),
    }


def login(db: Session, name: str, password: str, ip: str | None) -> dict:
    user = db.query(User).filter(User.name == name).first()
    if not user or not verify_password(password, user.password_hash):
        raise AppError("BAD_CREDENTIALS", "用户名或密码错误", code=20003)
    user.last_login_at = datetime.now(timezone.utc)
    user.last_login_ip = ip
    player = db.query(Player).filter(Player.user_id == user.id).first()
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    db.commit()
    return {
        "token": create_token(str(user.id)),
        "player": player_summary(player, farm, user.name),
    }

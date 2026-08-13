from sqlalchemy.orm import Session

from app.models import Farm, Player, User
from app.services.auth_service import player_summary


def get_me(db: Session, player: Player) -> dict:
    user = db.query(User).filter(User.id == player.user_id).first()
    farm = db.query(Farm).filter(Farm.owner_id == player.id).first()
    return player_summary(player, farm, user.name if user else "")

"""P0 数据模型(与 docs/02-数据库Schema设计.md 对应)。

当前实现 SQLite 兼容:
- UUID 用 sqlalchemy.Uuid(存 CHAR(32))
- JSON 用 sqlalchemy.JSON(PostgreSQL 上可平滑切换 JSONB)
- IP 用 String(45)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    SmallInteger,
    String,
    text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# ---------- 账号与玩家 ----------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[int] = mapped_column(SmallInteger, default=1)  # 1正常 0封禁
    register_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    register_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_login_location: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    exp: Mapped[int] = mapped_column(BigInteger, default=0)
    coins: Mapped[int] = mapped_column(BigInteger, default=0)
    head_title_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    unlocked_term_index: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 每用户世界时钟:world_accum 为相对全局纪元的累计世界秒(在线 1× / 离线 offline_factor)
    world_accum: Mapped[float] = mapped_column(Float, default=0.0)
    world_last_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 虫害调度:下一次虫害触发时间(每用户隔离,均摊在窗口节气数内)
    next_pest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoinTransaction(Base):
    __tablename__ = "coin_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("idx_coin_tx_player", CoinTransaction.player_id, CoinTransaction.created_at.desc())


# ---------- 头衔与成就 ----------

class Title(Base):
    __tablename__ = "titles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(32))
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unlock_condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserTitle(Base):
    __tablename__ = "user_titles"

    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), primary_key=True)
    title_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("titles.id"), primary_key=True)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(16))
    target: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 通用条件(见 goal_service)
    reward: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), primary_key=True)
    achievement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("achievements.id"), primary_key=True)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ---------- 农田与作物 ----------

class Farm(Base):
    __tablename__ = "farms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), unique=True)
    name: Mapped[str] = mapped_column(String(32), default="我的农场")
    plot_count: Mapped[int] = mapped_column(SmallInteger, default=20)  # 4 列 × 5 行
    theme: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Plot(Base):
    __tablename__ = "plots"
    __table_args__ = (UniqueConstraint("farm_id", "idx", name="uq_plot_farm_idx"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"))
    idx: Mapped[int] = mapped_column(SmallInteger)
    soil_quality: Mapped[int] = mapped_column(SmallInteger, default=1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)


class Crop(Base):
    __tablename__ = "crops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sow_window: Mapped[dict] = mapped_column(JSON, default=dict)
    grow_seconds: Mapped[int] = mapped_column(Integer)
    yield_base: Mapped[int] = mapped_column(Integer)
    base_price: Mapped[int] = mapped_column(Integer)
    unlock_level: Mapped[int] = mapped_column(SmallInteger, default=1)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    art: Mapped[dict] = mapped_column(JSON, default=dict)  # {"seed":path, "stages":[3个阶段图]}
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CropInstance(Base):
    __tablename__ = "crop_instances"
    # 一地一株(部分唯一索引):同一地块最多一个"未收获且未摧毁"作物;已收获/已摧毁的行保留为历史
    __table_args__ = (
        Index(
            "uq_crop_inst_active_plot",
            "plot_id",
            unique=True,
            sqlite_where=text("harvested_at IS NULL AND destroyed_at IS NULL"),
            postgresql_where=text("harvested_at IS NULL AND destroyed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    plot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plots.id"))
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"))
    sowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sowed_term_index: Mapped[int] = mapped_column(SmallInteger)
    stage: Mapped[int] = mapped_column(SmallInteger, default=1)
    water_level: Mapped[int] = mapped_column(SmallInteger, default=100)
    growth_progress: Mapped[int] = mapped_column(Integer, default=0)
    predicted_harvest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    term_bonus_applied: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    harvested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 虫害摧毁
    yield_actual: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


Index("idx_crop_inst_plot", CropInstance.plot_id)


# ---------- 道具系统 ----------

class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(16))
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stackable: Mapped[bool] = mapped_column(Boolean, default=True)
    max_stack: Mapped[int] = mapped_column(Integer, default=999)
    effect: Mapped[dict] = mapped_column(JSON, default=dict)
    buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sell_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unlock_level: Mapped[int] = mapped_column(SmallInteger, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserItem(Base):
    __tablename__ = "user_items"

    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"), primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ItemTransaction(Base):
    __tablename__ = "item_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("idx_item_tx_player", ItemTransaction.player_id, ItemTransaction.created_at.desc())


# ---------- 节气轮转时钟 ----------

class TermConfig(Base):
    __tablename__ = "term_config"

    term_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(8))
    icon: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=300)
    sort_order: Mapped[int] = mapped_column(SmallInteger)


class GameClock(Base):
    __tablename__ = "game_clock"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    time_scale: Mapped[float] = mapped_column(Float, default=1.0)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GameConfig(Base):
    __tablename__ = "game_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------- 任务 / 社交 / AI 用量 ----------


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str] = mapped_column(String(16), default="daily")  # daily/once/story
    objective: Mapped[dict] = mapped_column(JSON, default=dict)  # 通用条件 {"type":"sow","count":3}
    reward: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"coins":50,"exp":10,"items":[...]}
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserQuest(Base):
    __tablename__ = "user_quests"
    __table_args__ = (UniqueConstraint("player_id", "quest_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    quest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quests.id"))
    status: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0进行中 1已完成 2已领取
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Friendship(Base):
    __tablename__ = "friendships"

    player_a: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), primary_key=True)  # 排序后的较小 id
    player_b: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), primary_key=True)  # 排序后的较大 id
    requester: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"))  # 发起方
    status: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0待确认 1好友 2已拒绝
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("player_id", "model", "stat_date"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    stat_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    requests: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------- 商店(每用户隔离)/ 收成仓 ----------


class ShopSettings(Base):
    """全局商店默认(单例 id=1),管理端可改:库存/补货周期/价格系数。"""

    __tablename__ = "shop_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_stock: Mapped[int] = mapped_column(Integer, default=5)
    restock_seconds: Mapped[int] = mapped_column(Integer, default=300)
    sell_factor: Mapped[float] = mapped_column(Float, default=0.8)  # 农作物收购价系数
    item_factor: Mapped[float] = mapped_column(Float, default=1.0)  # 道具/种子售价系数
    season_effect: Mapped[dict] = mapped_column(
        JSON, default=lambda: {"spring": 1.1, "summer": 1.0, "autumn": 1.2, "winter": 0.9}
    )
    category_factor: Mapped[dict] = mapped_column(
        JSON, default=lambda: {"谷物": 1.0, "蔬菜": 1.1, "花卉": 1.25}
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserShop(Base):
    """每用户一个商店实例(隔离),记录上次补货时间。"""

    __tablename__ = "user_shops"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), unique=True)
    restocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserShopItem(Base):
    """用户商店内的单个商品:库存(可售空)+ 管理端价格覆盖。"""

    __tablename__ = "user_shop_items"
    __table_args__ = (UniqueConstraint("player_id", "item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id"))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 覆盖价(玩家买入)
    sell_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 覆盖价(卖回给商店)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class CropStorage(Base):
    """收成仓:收获的作物先入仓,玩家可择机出售(价格随季节涨降)。"""

    __tablename__ = "crop_storage"
    __table_args__ = (UniqueConstraint("player_id", "crop_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------- 虫害系统(每用户隔离) ----------


class PestEvent(Base):
    """一次虫害事件:大虫害(音游对抗)或小虫害(定时寄生)。"""

    __tablename__ = "pest_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    type: Mapped[str] = mapped_column(String(8))  # big / small
    status: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0进行中 1已结束(成功/驱赶) 2已过期
    broadcast_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 大虫害音游时长
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 大虫害成绩
    max_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    miss_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reward: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 奖励明细
    penalty: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 惩罚明细(寄生目标数)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PestTarget(Base):
    """小虫害的单个寄生目标:一块田地一个计时器,时间到摧毁作物。"""

    __tablename__ = "pest_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=gen_uuid)
    pest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pest_events.id"), index=True)
    player_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("players.id"), index=True)
    plot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plots.id"))
    crop_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crop_instances.id"), nullable=True
    )
    ready_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 到点摧毁
    status: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0寄生中 1已驱赶 2已摧毁
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

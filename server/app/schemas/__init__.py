from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32, description="登录名(也是显示名)")
    password: str = Field(min_length=6, max_length=64)


class LoginRequest(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class SowRequest(BaseModel):
    crop_id: str = Field(description="作物 id(从商店种子道具的 effect.crop_id 获取)")


class BuyRequest(BaseModel):
    quantity: int = Field(default=1, ge=1, le=999)


class UseTarget(BaseModel):
    plot_id: str | None = None


class UseItemRequest(BaseModel):
    target: UseTarget | None = None


class DebugConfigRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    value: dict | list | str | int | float | bool | None = None


class DebugGrowRequest(BaseModel):
    plot_id: str


class FriendRequest(BaseModel):
    player_id: str


class SellCropRequest(BaseModel):
    quantity: int = 1


class AdminAiConfigPayload(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class PestResultRequest(BaseModel):
    score: int
    max_score: int
    miss_count: int = 0


class PestDriveAwayRequest(BaseModel):
    plot_id: str


class PestTriggerRequest(BaseModel):
    type: str = "big"  # big / small


class AdminShopSettingsPayload(BaseModel):
    default_stock: int | None = None
    restock_seconds: int | None = None
    sell_factor: float | None = None
    item_factor: float | None = None
    season_effect: dict | None = None
    category_factor: dict | None = None


class AdminUserShopItemPayload(BaseModel):
    stock: int | None = None
    buy_price: int | None = None
    sell_price: int | None = None


# ---------- 管理后台 ----------

class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class AdminStatusRequest(BaseModel):
    status: int = Field(ge=0, le=1)


class AdminConfigValue(BaseModel):
    value: dict | list | str | int | float | bool | None = None


class AdminCropPayload(BaseModel):
    name: str | None = None
    category: str | None = None
    sow_window: dict | None = None
    grow_seconds: int | None = None
    yield_base: int | None = None
    base_price: int | None = None
    unlock_level: int | None = None
    description: str | None = None
    art: dict | None = None
    sort_order: int | None = None
    active: bool | None = None
    auto_seed: bool = False


class AdminItemPayload(BaseModel):
    code: str | None = None
    name: str | None = None
    category: str | None = None
    stackable: bool | None = None
    max_stack: int | None = None
    effect: dict | None = None
    buy_price: int | None = None
    sell_price: int | None = None
    unlock_level: int | None = None
    sort_order: int | None = None
    active: bool | None = None


class AdminTermDuration(BaseModel):
    duration_seconds: int = Field(ge=10, le=86400)


class AdminClockPayload(BaseModel):
    time_scale: float | None = Field(default=None, gt=0, le=100)
    paused: bool | None = None
    reset_epoch: bool = False


class AdminPlayerAssetsPayload(BaseModel):
    """玩家资产编辑(全可选,仅改提供的字段)。"""

    coins: int | None = Field(default=None, ge=0)
    level: int | None = Field(default=None, ge=1)
    exp: int | None = Field(default=None, ge=0)
    unlocked_term_index: int | None = Field(default=None, ge=1, le=24)


class AdminPlotPayload(BaseModel):
    """农场地块管理:解锁/土壤肥力。"""

    locked: bool | None = None
    soil_quality: int | None = Field(default=None, ge=1, le=5)


class AdminWorldPayload(BaseModel):
    """每用户世界覆盖:reset 回到纪元起点(立春);或设定累计世界秒。"""

    accum: float | None = Field(default=None, ge=0)
    reset: bool = False


class AdminPlotCropPayload(BaseModel):
    """地块作物控制:种植/替换指定作物(管理端不消耗种子、不校验节气窗)。"""

    crop_id: str
    growth_progress: int = Field(default=0, ge=0, le=100)
    water_level: int = Field(default=100, ge=0, le=100)


class AdminPlotGrowthPayload(BaseModel):
    """调整已有作物生长进度% / 浇水。"""

    growth_progress: int | None = Field(default=None, ge=0, le=100)
    water_level: int | None = Field(default=None, ge=0, le=100)


class AdminQuantityPayload(BaseModel):
    """设定数量(绝对值;0=清空)。用于背包道具 / 收成仓作物。"""

    quantity: int = Field(ge=0)

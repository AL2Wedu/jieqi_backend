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
    thinking: bool | None = None  # 思考模式开关(关闭时转发剥离 reasoning)


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
    # 合法值由服务层校验(0 封禁 / 1 正常 / 2 注销),schema 只做类型
    status: int


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
    unlock_exp: int | None = Field(default=None, ge=0)
    settings: dict | None = None
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
    """每用户世界覆盖:reset 回到立春;或设定累计世界秒;或覆盖速率。"""

    accum: float | None = Field(default=None, ge=0)
    reset: bool = False
    time_scale: float | None = Field(default=None, gt=0, le=100, description="覆盖该玩家世界速率;None 不改")
    clear_override: bool = Field(False, description="清除速率覆盖,恢复用全局 time_scale")


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


class RenameRequest(BaseModel):
    """玩家改名:1-16 字符,服务端限速(rename.cooldown_seconds)。"""

    new_name: str = Field(..., min_length=1, max_length=16, description="新名字(1-16 字符)")


class DeactivateRequest(BaseModel):
    """账号注销:需当前密码 + confirm 二次确认(防盗号)。"""

    password: str = Field(..., min_length=6, max_length=64, description="当前密码")
    confirm: bool = Field(False, description="必须传 true 确认注销")


class RedeemRequest(BaseModel):
    """兑换码兑换:码值仅 [A-Z0-9] 6-24 位。"""

    code: str = Field(..., min_length=6, max_length=24, description="兑换码")


class AdminRedeemCreatePayload(BaseModel):
    """管理端发布兑换码:reward 与任务奖励同构 {coins, exp, items:[{code,quantity}]}。"""

    reward: dict = Field(..., description="奖励:{coins, exp, items:[{code,quantity}]}")
    count: int = Field(1, ge=1, le=100, description="批量生成数量(仅未指定 code 时)")
    code: str | None = Field(None, min_length=6, max_length=24, description="指定码值(单个时);省略则随机生成")
    batch_name: str | None = Field(None, max_length=64, description="批次名(运营备注)")
    max_uses: int = Field(1, ge=0, description="总使用次数上限,0=不限")
    per_player_limit: int = Field(1, ge=1, description="每人限领次数")
    expires_at: str | None = Field(None, description="过期时间 ISO8601,省略=不过期")


class AdminRedeemUpdatePayload(BaseModel):
    """管理端更新兑换码:停用/启用、改次数上限、改过期时间。"""

    active: bool | None = Field(None, description="None 不改;true 启用 / false 停用")
    max_uses: int | None = Field(None, ge=0, description="总次数上限,0=不限")
    per_player_limit: int | None = Field(None, ge=1, description="每人限领次数")
    expires_at: str | None = Field(None, description="过期时间 ISO8601,null=改为不过期")


class AdminRenamePayload(BaseModel):
    """管理端改名(无限速)。"""

    new_name: str = Field(..., min_length=1, max_length=16, description="新名字(1-16 字符)")

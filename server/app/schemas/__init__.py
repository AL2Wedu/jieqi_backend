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

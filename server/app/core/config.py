import logging
import secrets
import string

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("jieqi")

# 管理员密码未配置时随机生成的字符数
_ADMIN_RANDOM_PASSWORD_LEN = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "jieqi_backend"
    database_url: str = "sqlite:///./dev.db"
    jwt_secret: str = "dev-secret-change-me-please-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    debug_enabled: bool = True
    term_default_duration: int = 300
    admin_username: str = "admin"
    admin_password: str = ""
    admin_enabled: bool = True
    dev_token: str = ""  # 开发接口门控:Authorization: Bearer <dev_token>(为空则开发接口禁用)


settings = Settings()

# 密码不应为空:未配置(或 .env 未加载)时随机生成,并在终端显示,避免登录永久失败
if not settings.admin_password:
    settings.admin_password = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(_ADMIN_RANDOM_PASSWORD_LEN)
    )
    print(
        f"[jieqi] 未检测到 ADMIN_PASSWORD,已随机生成管理员密码: {settings.admin_password}\n"
        f"[jieqi] 请用 用户名 '{settings.admin_username}' + 上述密码 登录管理后台;重启服务会重新生成"
    )
    logger.warning("ADMIN_PASSWORD 未配置,已随机生成管理员密码")
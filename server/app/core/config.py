import logging
import secrets
import string

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("jieqi")

# 管理员密码未配置时随机生成的字符数
_ADMIN_RANDOM_PASSWORD_LEN = 16
# JWT 密钥未配置/仍为默认值时随机生成的字符数
_JWT_RANDOM_SECRET_LEN = 48
# 出厂默认密钥(仅用于检测"未显式配置",绝不作为实际签名密钥)
_DEFAULT_JWT_SECRET = "dev-secret-change-me-please-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "jieqi_backend"
    database_url: str = "sqlite:///./dev.db"
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    debug_enabled: bool = False  # 调试接口默认关闭(上线安全);需显式 DEBUG_ENABLED=true 开启
    term_default_duration: int = 300
    admin_username: str = "admin"
    admin_password: str = ""
    admin_enabled: bool = True
    # 可信反代 IP 白名单(逗号分隔):仅当请求来自这些反代时才信任 X-Forwarded-For
    trusted_proxies: str = ""
    # CORS 允许来源(逗号分隔);空 = 仅同源(不跨域)
    cors_origins: str = ""
    # 登录/注册限速总开关(测试环境关闭;生产保持 true)
    rate_limit_enabled: bool = True


settings = Settings()

# 密码不应为空:未配置(或 .env 未加载)时随机生成,并在终端显示,避免登录永久失败
if not settings.admin_password:
    settings.admin_password = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(_ADMIN_RANDOM_PASSWORD_LEN)
    )
    # 纯 ASCII 输出:避免 Windows 终端(GBK)对 UTF-8 中文 print 乱码
    print(
        f"[jieqi] ADMIN_PASSWORD not set, generated random admin password: {settings.admin_password}\n"
        f"[jieqi] Login with username '{settings.admin_username}' + above password; regenerated on restart"
    )
    logger.warning("ADMIN_PASSWORD 未配置,已随机生成管理员密码")

# JWT 密钥安全:未配置或仍为出厂默认值 → 随机生成并警告(防伪造 token 接管)
if not settings.jwt_secret or settings.jwt_secret == _DEFAULT_JWT_SECRET:
    settings.jwt_secret = "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(_JWT_RANDOM_SECRET_LEN)
    )
    # 纯 ASCII 输出:避免 Windows 终端(GBK)对 UTF-8 中文 print 乱码
    print(
        f"[jieqi] JWT_SECRET not set (or still default), generated random signing key: {settings.jwt_secret}\n"
        f"[jieqi] Write it to .env JWT_SECRET, otherwise all issued tokens invalidate on restart"
    )
    logger.warning("JWT_SECRET 未配置或为默认值,已随机生成(重启后旧 token 失效)")

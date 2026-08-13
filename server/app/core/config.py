from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()

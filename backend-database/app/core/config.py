from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Smart Observability Backend"
    APP_VERSION: str = "1.0.0"
    DATABASE_URL: str = "sqlite:///./local.db"
    SECRET_KEY: str = "change-this-secret-before-deployment"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    COLLECTOR_TOKEN: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
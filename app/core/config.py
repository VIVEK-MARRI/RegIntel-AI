from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "RegIntel AI Document Registry"
    ENV: str = "development"
    
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:admin@localhost:5432/regintel_db",
        description="Async PostgreSQL Database URL"
    )
    
    DATABASE_URL_SYNC: str = Field(
        default="postgresql+psycopg2://postgres:admin@localhost:5432/regintel_db",
        description="Sync PostgreSQL Database URL for migrations"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

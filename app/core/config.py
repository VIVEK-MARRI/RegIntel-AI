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

    # Storage
    STORAGE_ROOT: str = Field(
        default="storage",
        description="Local storage base directory path"
    )

    # Embeddings
    EMBEDDING_MODEL_NAME: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Name or path of the transformer model for embeddings"
    )
    EMBEDDING_DEVICE: str | None = Field(
        default=None,
        description="Computation device (cpu, cuda). Auto-detected if None"
    )
    EMBEDDING_NORMALIZE: bool = Field(
        default=True,
        description="Whether to normalize output embeddings to unit vectors"
    )
    EMBEDDING_QUERY_INSTRUCTION: str = Field(
        default="represent this query for retrieving relevant documents: ",
        description="Instruction prefix prepended to queries for BGE asymmetric retrieval"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

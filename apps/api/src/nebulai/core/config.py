from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[5]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001,"
        "http://localhost:3002,http://127.0.0.1:3002,"
        "http://localhost:3003,http://127.0.0.1:3003,"
        "http://localhost:3004,http://127.0.0.1:3004"
    )
    testing: bool = False
    auth_required: bool = True
    auth_cookie_name: str = "nebulai_session"
    auth_session_secret: str = "dev-nebulai-session-secret-change-me"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    app_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    email_login_from: str = "nebulai bot <no-reply@nebulai.dev>"
    email_login_dev_mode: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    runtime_mode: str = "mock"
    redis_url: str = "redis://localhost:6379/0"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "nebulai_chunks"
    milvus_timeout_seconds: float = 3.0
    embedding_provider: str = "mock-hash"
    embedding_dimension: int = 384
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_send_dimensions: bool = True
    embedding_timeout_seconds: float = 15.0
    openai_api_key: str = ""
    siliconflow_api_key: str = ""
    llm_provider: str = "mock"
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 60.0
    rerank_provider: str = "jina"
    rerank_api_key: str = ""
    rerank_url: str = ""
    rerank_model: str = ""
    rerank_timeout_seconds: float = 15.0
    rerank_instruction: str = ""
    rerank_max_chunks_per_doc: int | None = None
    rerank_overlap_tokens: int | None = None
    jina_api_key: str = ""
    jina_rerank_url: str = "https://api.jina.ai/v1/rerank"
    jina_rerank_model: str = ""
    jina_rerank_timeout_seconds: float = 15.0
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "nebulai"
    postgres_user: str = "nebulai"
    postgres_password: str = "nebulai"

    @cached_property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @cached_property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def effective_embedding_api_key(self) -> str:
        return self.embedding_api_key or self.openai_api_key or self.siliconflow_api_key

    @property
    def effective_llm_api_key(self) -> str:
        return self.llm_api_key or self.openai_api_key or self.siliconflow_api_key

    @property
    def effective_rerank_provider(self) -> str:
        if self.rerank_api_key or self.rerank_url or self.rerank_model:
            return self.rerank_provider
        return "jina"

    @property
    def effective_rerank_api_key(self) -> str:
        return self.rerank_api_key or self.jina_api_key or self.siliconflow_api_key

    @property
    def effective_rerank_url(self) -> str:
        return self.rerank_url or self.jina_rerank_url

    @property
    def effective_rerank_model(self) -> str:
        return self.rerank_model or self.jina_rerank_model

    @property
    def effective_rerank_timeout_seconds(self) -> float:
        if self.rerank_api_key or self.rerank_url or self.rerank_model:
            return self.rerank_timeout_seconds
        return self.jina_rerank_timeout_seconds



settings = Settings()

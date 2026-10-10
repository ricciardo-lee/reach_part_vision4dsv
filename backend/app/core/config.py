"""Application settings loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROTECTED_DATABASES = {
    "ReachMDM_LMR",
    "reachmdm_lmr",
    "Reach_CN_Catalogue",
    "mysql",
    "information_schema",
    "performance_schema",
    "sys",
}

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_NAME: str = "Reach Part Vision"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me"
    CORS_ORIGINS: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
        ]
    )

    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "reach_part_vision4dsv"

    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://127.0.0.1:6379/2"
    # 推荐开启：识别走本地 Celery 异步；需同时启动 worker
    CELERY_ENABLED: bool = True
    # true 时无 worker 会降级到 API 内同步；false 时无 worker 直接报错提示启动
    CELERY_ALLOW_INLINE_FALLBACK: bool = False

    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "part-vision"
    MINIO_SECURE: bool = False
    MINIO_PUBLIC_BASE_URL: str = ""
    # auto: development 用本地磁盘，production 用 MinIO。也可显式设 local | minio。
    STORAGE_BACKEND: str = "auto"
    LOCAL_STORAGE_DIR: str = "uploads"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-v4-flash-vision-exp"
    DEEPSEEK_TIMEOUT_SECONDS: int = 60
    DEEPSEEK_MAX_RETRIES: int = 2

    MAX_UPLOAD_MB: int = 10
    MAX_IMAGES_PER_SESSION: int = 8
    IMAGE_RETENTION_DAYS: int = 30
    DEVICE_SESSION_TTL_HOURS: int = 72
    # Recognition starts per user per minute.
    RATE_LIMIT_PER_MINUTE: int = 30
    EVAL_REJECT_CONFIDENCE: float = 0.45

    # 360 SKU retrieval (DINOv2 + Qdrant)
    RETRIEVAL_ENABLED: bool = True
    EMBEDDING_BACKEND: str = "dinov2"
    EMBEDDING_MODEL_ID: str = "facebook/dinov2-base"
    VECTOR_BACKEND: str = "qdrant"  # qdrant | memory
    QDRANT_URL: str = "http://127.0.0.1:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "parts_360_current"
    # Local Photo360 root: category folders, then SKU folders, then r*.jpg.
    PHOTO360_ROOT: str = ""
    SEARCH_INDEX_DIR: str = "data/indexes"
    # Separate BiRefNet white-cutout dump. Empty keeps foreground search on the full index.
    SEARCH_WHITE_INDEX_DIR: str = ""
    SEARCH_INDEX_VERSION: str | None = None
    SEARCH_AGGREGATE: str = "topm_mean"
    SEARCH_TOPM: int = 3
    SEARCH_PER_IMAGE_TOP_K: int = 30
    SEARCH_HIGH_SCORE: float = 0.72
    SEARCH_MEDIUM_SCORE: float = 0.55
    SEARCH_MIN_MARGIN: float = 0.03
    # Category-level match: keep same-category SKUs when SKU gate fails but retrieval is medium+.
    SEARCH_CATEGORY_MIN_SCORE: float = 0.55
    SEARCH_CATEGORY_TOP_N: int = 5
    SEARCH_CATEGORY_RELATIVE_FLOOR: float = 0.85  # keep SKU if score >= top_in_category * floor
    SEARCH_VISION_CATEGORY_MIN_CONFIDENCE: float = 0.6
    SEARCH_ENABLE_DUAL_PATH: bool = False
    SEARCH_TARGET_SIZE: int = 224
    SEARCH_ENABLE_FOREGROUND: bool = True
    SEARCH_SEGMENT_ENABLED: bool = True
    SEARCH_SEGMENT_DEVICE: str = "auto"
    SEARCH_SEGMENT_MIN_AREA: float = 0.02
    SEARCH_SEGMENT_MAX_AREA: float = 0.92
    SEARCH_SEGMENT_CROP_MARGIN: float = 0.05
    SEARCH_MATTING_MODEL_ID: str = "ZhengPeng7/BiRefNet"
    SEARCH_MATTING_INPUT_SIZE: int = 1024
    CELERY_WORKER_CONCURRENCY: int = 1

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "Admin@123456"
    ADMIN_DISPLAY_NAME: str = "系统管理员"

    @field_validator("MYSQL_DATABASE")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("MYSQL_DATABASE is required")
        if name in PROTECTED_DATABASES or name.lower() in {x.lower() for x in PROTECTED_DATABASES}:
            raise ValueError(
                f"Refusing to use protected database '{name}'. "
                "This service must use an independent database such as reach_part_vision4dsv."
            )
        return name

    @model_validator(mode="after")
    def validate_secret(self) -> "Settings":
        if self.APP_ENV == "production" and self.SECRET_KEY in {"change-me", "change-me-to-a-long-random-string"}:
            raise ValueError("SECRET_KEY must be set in production")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def resolved_storage_backend(self) -> str:
        """local | minio. auto 在非 production 环境不连接 MinIO。"""
        raw = (self.STORAGE_BACKEND or "auto").strip().lower()
        if raw in {"local", "minio"}:
            return raw
        if (self.APP_ENV or "").strip().lower() == "production":
            return "minio"
        return "local"

    @property
    def resolved_embedding_model_id(self) -> str:
        if self.EMBEDDING_MODEL_ID:
            return self.EMBEDDING_MODEL_ID
        if self.EMBEDDING_BACKEND.lower() == "dinov2":
            return "facebook/dinov2-base"
        return "facebook/dinov2-base"

    @property
    def tortoise_config(self) -> dict:
        return {
            "connections": {
                "default": {
                    "engine": "tortoise.backends.mysql",
                    "credentials": {
                        "host": self.MYSQL_HOST,
                        "port": self.MYSQL_PORT,
                        "user": self.MYSQL_USER,
                        "password": self.MYSQL_PASSWORD,
                        "database": self.MYSQL_DATABASE,
                        "charset": "utf8mb4",
                    },
                }
            },
            "apps": {
                "models": {
                    "models": ["app.models", "aerich.models"],
                    "default_connection": "default",
                }
            },
            "use_tz": False,
            "timezone": "Asia/Shanghai",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Aerich expects TORTOISE_ORM at module level via pyproject / aerich.ini
TORTOISE_ORM = settings.tortoise_config

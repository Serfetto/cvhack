from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Общие настройки. Сервисы наследуют и добавляют свои поля; всё берётся из переменных окружения."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "service"
    log_level: str = "INFO"
    log_json: bool = True
    # Префикс, под которым шлюз публикует сервис (/api/auth и т. п.) — нужен Swagger за шлюзом
    root_path: str = ""
    cors_origins: list[str] = ["*"]

    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+asyncpg://linq:linq@localhost:5432/linq"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_bucket: str = "linq"
    # Как браузер видит MinIO: шлюз проксирует /media/* → minio:9000/*
    media_public_base: str = "/media"

    auth_jwks_url: str = "http://auth:8000/.well-known/jwks.json"
    jwt_issuer: str = "linq-auth"
    jwt_audience: str = "linq"

    app_tz: str = "Europe/Moscow"
    # Конфигурация камер до появления camera-service (и seed для него)
    cameras_yaml: str | None = None
    frame_shards: int = 1

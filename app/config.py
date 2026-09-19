from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, populated from environment variables.

    Spec 9.4: DB接続情報・認証設定・内部APIの接続先は環境変数等で設定し、
    パスワードや秘密鍵をソースコードへ埋め込まない。
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/employee_id"

    # Dev-mode auth. Real deployments must replace this with the corporate
    # SSO / OAuth2 integration described in spec 7.1 and 10 (open item, spec 13).
    auth_secret_key: str = "dev-only-secret-change-me"
    auth_algorithm: str = "HS256"
    auth_token_expire_minutes: int = 480

    # Idempotency-Key retention (spec 7.1 / 7.4.6): tentative 7 days.
    idempotency_ttl_days: int = 7

    # CSV bulk import limits (spec 6.1): tentative.
    csv_max_rows: int = 50_000
    csv_max_bytes: int = 50 * 1024 * 1024
    import_storage_dir: str = "./data/imports"

    # JSON bulk import limits (spec 7.4.2): tentative.
    batch_max_records: int = 1_000
    batch_max_bytes: int = 10 * 1024 * 1024

    # Result/upload file & job data retention (spec 6, 7.4.6): tentative.
    job_result_retention_days: int = 7

    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

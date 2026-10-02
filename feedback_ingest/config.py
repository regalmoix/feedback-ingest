from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FI_")

    database_url: str = "sqlite:///./feedback.db"
    worker_enabled: bool = True
    worker_poll_seconds: float = 1.0
    lease_seconds: int = 30
    claim_batch: int = 10
    max_attempts: int = 5
    backoff_cap_seconds: int = 300
    pull_interval_seconds: int = 300
    bootstrap_token: str = "change-me"  # noqa: S105  documented default; startup warns while unchanged

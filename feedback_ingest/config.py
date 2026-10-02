from pydantic import PositiveFloat, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FI_")

    database_url: str = "sqlite:///./feedback.db"
    worker_enabled: bool = True
    worker_poll_seconds: PositiveFloat = 1.0
    lease_seconds: PositiveInt = 30
    claim_batch: PositiveInt = 10
    max_attempts: PositiveInt = 5
    backoff_cap_seconds: PositiveInt = 300
    pull_interval_seconds: int = 300
    bootstrap_token: str = "change-me"  # noqa: S105  documented default; startup warns while unchanged

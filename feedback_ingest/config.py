from pydantic import PositiveFloat, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_BOOTSTRAP_TOKEN = "change-me"  # noqa: S105  refused: POST /admin/tenants needs a real one


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FI_")

    database_url: str = "sqlite:///./feedback.db"
    worker_enabled: bool = True
    worker_poll_seconds: PositiveFloat = 1.0
    lease_seconds: PositiveInt = 30
    claim_batch: PositiveInt = 10
    max_attempts: PositiveInt = 5
    backoff_cap_seconds: PositiveInt = 300
    pull_interval_seconds: PositiveFloat = 300
    pull_deadline_seconds: PositiveFloat = 60
    http_max_bytes: PositiveInt = 2_000_000
    scheduler_enabled: bool = True
    bootstrap_token: SecretStr = SecretStr(DEFAULT_BOOTSTRAP_TOKEN)

    @property
    def bootstrap_open(self) -> bool:
        return self.bootstrap_token.get_secret_value() not in {"", DEFAULT_BOOTSTRAP_TOKEN}

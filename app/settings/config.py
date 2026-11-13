from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        # в .env могут быть и другие переменные (например, для контейнера postgres)
        extra="ignore",
    )

    bot_token: SecretStr
    # postgresql+asyncpg://user:password@host:5432/dbname; если не задан — собирается из DB_*
    database_url: SecretStr | None = None
    db_host: str | None = None
    db_port: int = 5432
    db_user: str | None = None
    db_pass: SecretStr | None = None
    db_name: str | None = None
    # ADMIN_IDS=111,222 или ADMIN_IDS=[111,222]
    admin_ids: Annotated[frozenset[int], NoDecode]
    support_url: str = "https://t.me/Mishanya_B"

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_admin_ids(cls, value):
        if isinstance(value, str):
            value = value.strip().strip("[]")
            return frozenset(int(part) for part in value.replace(" ", "").split(",") if part)
        return value

    @model_validator(mode="after")
    def _build_database_url(self):
        if self.database_url is None:
            if not (self.db_host and self.db_user and self.db_pass and self.db_name):
                raise ValueError("Задайте DATABASE_URL или DB_HOST/DB_USER/DB_PASS/DB_NAME")
            self.database_url = SecretStr(
                f"postgresql+asyncpg://{self.db_user}:{self.db_pass.get_secret_value()}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        return self


# объект конфигурации
settings = Settings()

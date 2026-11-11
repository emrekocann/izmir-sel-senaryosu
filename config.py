from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str
    tomtom_api_key: Optional[str] = None     # yoksa rota trafik cezasız çalışır

    # .env'de artık kullanılmayan anahtarlar (eski katmanlar) hata vermesin
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

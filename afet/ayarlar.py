"""Ortam ayarları (.env): veritabanı bağlantısı ve isteğe bağlı API anahtarları."""
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Ayarlar(BaseSettings):
    # alan adları .env anahtarlarıdır (DB_HOST, DB_PORT, …)
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_pass: str
    tomtom_api_key: Optional[str] = None     # yoksa rota trafik cezasız çalışır

    # .env'de artık kullanılmayan anahtarlar (eski katmanlar) hata vermesin
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


ayarlar = Ayarlar()

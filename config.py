from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BOT_TOKEN: str = "YOUR_BOT_TOKEN_HERE"
    DATABASE_URL: str = "sqlite+aiosqlite:///./casting_bot.db"
    GEMINI_API_KEY: str = ""
    API_ID: int = 0
    API_HASH: str = ""
    PHONE_NUMBER: str = ""
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    ADMIN_IDS: list[int] = [1761156821, 149445533]
    ADMIN_KEY: str = "admin_casting"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def database_url(self) -> str:
        return self.DATABASE_URL

settings = Settings()

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: SecretStr = Field(..., env="OPENAI_API_KEY")
    mistral_api_key: SecretStr = Field(..., env="MISTRAL_API_KEY")
    database_url: str = Field(..., env="DATABASE_URL")
    api_key: SecretStr = Field(..., env="API_KEY")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: SecretStr = Field(..., env="OPENAI_API_KEY")
    mistral_api_key: SecretStr = Field(..., env="MISTRAL_API_KEY")
    database_url: str = Field(..., env="DATABASE_URL")
    api_key: SecretStr = Field(..., env="API_KEY")
    imap_enabled: bool = Field(default=False, env="IMAP_ENABLED")
    imap_host: str | None = Field(default=None, env="IMAP_HOST")
    imap_port: int = Field(default=993, env="IMAP_PORT")
    imap_username: str | None = Field(default=None, env="IMAP_USERNAME")
    imap_user: str | None = Field(default=None, env="IMAP_USER")
    imap_email: str | None = Field(default=None, env="IMAP_EMAIL")
    imap_password: SecretStr | None = Field(default=None, env="IMAP_PASSWORD")
    imap_folder: str = Field(default="INBOX", env="IMAP_FOLDER")
    imap_search_criteria: str = Field(default="UNSEEN", env="IMAP_SEARCH_CRITERIA")
    imap_mark_seen: bool = Field(default=True, env="IMAP_MARK_SEEN")
    imap_poll_interval_seconds: int = Field(default=60, env="IMAP_POLL_INTERVAL_SECONDS")
    imap_attachments_dir: str = Field(default="/tmp/gocomet_imap_attachments", env="IMAP_ATTACHMENTS_DIR")
    smtp_enabled: bool = Field(default=True, env="SMTP_ENABLED")
    smtp_host: str = Field(default="smtp.gmail.com", env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_username: str | None = Field(default=None, env="SMTP_USERNAME")
    smtp_password: SecretStr | None = Field(default=None, env="SMTP_PASSWORD")
    smtp_from_email: str | None = Field(default=None, env="SMTP_FROM_EMAIL")
    smtp_use_tls: bool = Field(default=True, env="SMTP_USE_TLS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

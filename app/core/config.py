from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = ""
    gcp_upload_bucket: str = ""
    gcp_service_account: str = ""
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://shiftready-ui-7nkqrak2ta-ts.a.run.app",
        "https://shiftready-ui-12644234558.australia-southeast1.run.app",
    ]
    api_version: str = "1.1.0"
    allow_dev_tokens: bool = False  # Set to true in local .env only — never in prod
    port: int = 8080

    # Gemini / Vertex AI
    gemini_model_id: str = "gemini-3.1-flash-lite"
    gemini_location: str = "global"

    google_application_credentials: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    ffmpeg_path: str | None = None
    sentry_dsn: str = ""


settings = Settings()

import os
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    # GCP Configuration
    PROJECT_ID: Optional[str] = None
    REGION: str = "us-west4"
    VERTEX_LOCATION: Optional[str] = None
    
    # Model Configuration
    MODEL_ID: str = "gemini-2.5-pro"
    TEMPERATURE: float = 0.2
    MAX_TOKENS: int = 2048
    MODEL_FALLBACKS: List[str] = ["gemini-2.5-pro-001", "gemini-2.5-pro"]
    AUTO_CONTINUE_ON_MAX_TOKENS: bool = True
    MAX_CONTINUATIONS: int = 2
    SUPPRESS_VERTEXAI_DEPRECATION: bool = True
    VALIDATE_MODEL_ON_STARTUP: bool = True

    # App Settings
    PORT: int = 8080
    LOG_LEVEL: str = "INFO"
    DEBUG_MODE: bool = False
    ALLOWED_ORIGINS: List[str] = []
    
    # Logging configuration
    LOG_REQUEST_BODY_MAX: int = 1024
    LOG_HEADERS: bool = False
    LOG_RESPONSE_PREVIEW_MAX: int = 512
    SAFETY_LOG_CAP: int = 16384
    EXPOSE_UPSTREAM_ERROR: bool = False
    
    # AIMS Coaching configuration
    AIMS_COACHING_ENABLED: bool = True
    AIMS_CLASSIFIER_MODE: str = "hybrid"
    AIMS_CLASSIFY_CONTEXT_TURNS: int = 6
    AIMS_CLASSIFY_MAX_CONCERNS: int = 3
    
    # Memory and Session configuration
    MEMORY_ENABLED: bool = True
    MEMORY_MAX_TURNS: int = 8
    MEMORY_TTL_SECONDS: int = 3600
    MEMORY_BACKEND: str = "memory"  # memory or redis
    REDIS_URL: Optional[str] = None
    REDIS_HOST: Optional[str] = None
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_PREFIX: str = "aims:session:"
    
    # Session cookie configuration
    SESSION_COOKIE_NAME: str = "sessionId"
    SESSION_COOKIE_SECURE: bool = True
    SESSION_COOKIE_SAMESITE: str = "lax"
    SESSION_COOKIE_MAX_AGE: Optional[int] = None
    
    # Chainlit specific UI configuration
    CHAINLIT_AUTH_SECRET: Optional[str] = None
    CHAINLIT_COACH_DEFAULT: Optional[bool] = None
    BACKEND_URL: Optional[str] = None
    CHAINLIT_HTTP_TIMEOUT: float = 15.0
    ENABLE_PASSWORD_AUTH: bool = False
    
    # Session and Persona overrides
    FIXED_SESSION_ID: Optional[str] = None
    SESSION_ID: Optional[str] = None
    PERSONA_INDEX: Optional[int] = None
    CHARACTER_SYSTEM: Optional[str] = None
    SCENE_OBJECTIVES: Optional[str] = None
    
    # Avatar configuration
    PATIENT_AVATAR_PATH: Optional[str] = None
    PATIENT_AVATAR_URL: Optional[str] = None
    DOCTOR_AVATAR_PATH: Optional[str] = None
    DOCTOR_AVATAR_URL: Optional[str] = None
    COACH_AVATAR_PATH: Optional[str] = None
    COACH_AVATAR_URL: Optional[str] = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("PROJECT_ID", mode="before")
    @classmethod
    def validate_project_id(cls, v):
        if not v:
            # 1. Check common environment variables
            v = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or os.getenv("GCP_PROJECT_ID")
            
        if not v:
            # 2. Try to get it from Google Auth default (if available)
            try:
                import google.auth
                _, project = google.auth.default()
                v = project
            except Exception:
                pass
        return v

    @field_validator("REGION", mode="before")
    @classmethod
    def validate_region(cls, v):
        if not v:
            # Fallback to common region environment variables
            v = os.getenv("GOOGLE_CLOUD_REGION") or os.getenv("GCP_REGION") or os.getenv("REGION")
        return v or "us-central1"

    @field_validator("VERTEX_LOCATION", mode="before")
    @classmethod
    def validate_vertex_location(cls, v, info):
        if v:
            return v
        return os.getenv("REGION") or os.getenv("GCP_REGION") or "us-west4"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def validate_allowed_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v or []

    @field_validator("MODEL_FALLBACKS", mode="before")
    @classmethod
    def validate_model_fallbacks(cls, v):
        if isinstance(v, str):
            return [m.strip() for m in v.split(",") if m.strip()]
        return v or ["gemini-2.5-pro-001", "gemini-2.5-pro"]

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def validate_log_level(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v or "INFO"

    @field_validator("SESSION_COOKIE_MAX_AGE", mode="before")
    @classmethod
    def validate_cookie_max_age(cls, v, info):
        if v is not None:
            return v
        ttl = info.data.get("MEMORY_TTL_SECONDS", 3600)
        return ttl if ttl > 0 else 30*24*60*60

settings = Settings()

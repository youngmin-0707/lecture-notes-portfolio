"""애플리케이션 설정 (환경변수 로더).

민감정보(외부 API 키 등)는 로그·응답에 노출되지 않도록 `pydantic.SecretStr`로 감싼다.
값을 사용할 때는 반드시 `.get_secret_value()`를 명시적으로 호출해야 하며, 그냥 로깅하거나
`str(settings)`를 출력해도 `**********`만 노출된다.

DB URL 등은 코드에 하드코딩하지 않고 환경변수에서 읽는다.
`tests/conftest.py`가 app을 import하기 전에 os.environ에 기본값을 세팅해두므로,
테스트 실행 시에도 이 설정이 정상적으로 채워진다 (§0 D9: 실사용 SQLite / 테스트 기존 PostgreSQL).
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "development"

    # --- DB (§0 D9, §2.3) ---
    # 실사용 기본값은 로컬 SQLite 파일. 테스트 하니스는 conftest.py가 이 값을
    # PostgreSQL 테스트 DB URL로 오버라이드한다.
    DATABASE_URL: str = "sqlite:///./data/lecture_notes.db"

    # --- 네트워크 바인딩 (§3.7, §6, US-11) ---
    # 0.0.0.0으로 설정하면 앱 기동 자체를 거부한다 (app/main.py의 validate_bind_host).
    BIND_HOST: str = "127.0.0.1"
    BIND_PORT: int = 8765

    # --- 저장 경로 (§2.2) ---
    DATA_DIR: str = "data"
    AUDIO_STORAGE_DIR: str = "data/audio"
    MODEL_CACHE_DIR: str = "data/models"

    # --- 업로드 정책 (§3.1) ---
    MAX_UPLOAD_SIZE_BYTES: int = 500 * 1024 * 1024  # 500MB
    MIN_AUDIO_DURATION_SECONDS: float = 1.0  # 이 값 "초과"만 허용 (1초 이하는 AUDIO_TOO_SHORT)
    MAX_AUDIO_DURATION_SECONDS: float = 240 * 60  # 240분
    MIN_DISK_FREE_BYTES: int = 1 * 1024 * 1024 * 1024  # 1GB

    # --- STT (§0 D3, §3.2) ---
    STT_PROVIDER: str = "local_whisper"
    STT_MODEL: str = "large-v3-turbo"
    STT_LANGUAGE: str = "ko"

    # --- LLM (§0 D5, §3.4) ---
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "qwen3:14b"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    # 처리 종료 직후 RAM을 반환하기 위해 짧게 유지한다 (§0 D13).
    OLLAMA_KEEP_ALIVE: str = "30s"

    # --- 무료 티어 대안 Provider (§0 D4/D5, 그룹 E/T-29에서 사용) ---
    # 절대 로그/응답에 노출하지 않는다 (§3.4, §6 보안).
    GROQ_API_KEY: SecretStr | None = None
    GEMINI_API_KEY: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

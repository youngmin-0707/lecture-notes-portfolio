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

    # --- Tailscale 원격 접속 (2026-08-29) ---
    # `tailscale serve`가 127.0.0.1로 리버스 프록시하므로 BIND_HOST는 그대로 두고, CORS만
    # 자기 tailnet 서브도메인(*.<내 tailnet>.ts.net)에 한해 허용한다. 기본 False — 켜지
    # 않으면 예전처럼 127.0.0.1/localhost만 허용된다(§3.7 원칙 그대로 유지).
    ALLOW_TAILSCALE_ORIGINS: bool = False

    # --- 저장 경로 (§2.2) ---
    DATA_DIR: str = "data"
    AUDIO_STORAGE_DIR: str = "data/audio"
    MODEL_CACHE_DIR: str = "data/models"

    # --- 오디오 보관 정책 (2026-08-29) ---
    # 요약까지 끝나면(DONE) 텍스트(전사+요약)만 남기고 원본 오디오는 지운다 — 사용자가 오디오
    # 재생 기능을 거의 안 쓰고 텍스트만 본다고 확인함. 되돌리기 불가능한 동작이라 껐다 켤 수
    # 있게 설정으로 뺐다: False로 두면 예전처럼 오디오를 계속 보관한다.
    DELETE_AUDIO_AFTER_PROCESSING: bool = True

    # --- 업로드 정책 (§3.1) ---
    MAX_UPLOAD_SIZE_BYTES: int = 500 * 1024 * 1024  # 500MB
    MIN_AUDIO_DURATION_SECONDS: float = 1.0  # 이 값 "초과"만 허용 (1초 이하는 AUDIO_TOO_SHORT)
    MAX_AUDIO_DURATION_SECONDS: float = 240 * 60  # 240분
    MIN_DISK_FREE_BYTES: int = 1 * 1024 * 1024 * 1024  # 1GB

    # --- STT (§0 D3, §3.2) ---
    STT_PROVIDER: str = "local_whisper"
    STT_MODEL: str = "large-v3-turbo"
    # CPU 바운드 로컬 추론이라 동시에 여러 개 돌리면 서로 코어를 다퉈 전체적으로 더 느려진다
    # (2026-08-30 실사용 중 9개 동시 업로드로 실측). 기본 1 = 완전 순차 처리.
    MAX_CONCURRENT_TRANSCRIPTIONS: int = 1
    STT_LANGUAGE: str = "ko"

    # --- LLM (§0 D5, §3.4) ---
    LLM_PROVIDER: str = "ollama"
    # M4 Pro/24GB 기준 권장값 (§0 D5). 2026-08-22 세션 중 네트워크 지연으로 qwen3:8b로 임시
    # 하향했었으나, 이후 회선 정상화되어 qwen3:14b로 복원함.
    LLM_MODEL: str = "qwen3:14b"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    # 처리 종료 직후 RAM을 반환하기 위해 짧게 유지한다 (§0 D13).
    OLLAMA_KEEP_ALIVE: str = "30s"
    # 60분 강의 전사(약 1.5~2.5만 토큰)를 감안해 넉넉히 잡는다 (§3.4, T-17). map-reduce(T-21)
    # 도입 전까지는 이 값이 사실상 유일한 여유분이다.
    OLLAMA_NUM_CTX: int = 8192
    # 로컬 8B/14B 모델의 긴 프롬프트 생성은 수 분이 걸릴 수 있다.
    OLLAMA_TIMEOUT_SECONDS: float = 600.0
    # qwen3는 reasoning 모델이다. think=False로 사고 과정을 끄면 응답은 빨라지지만 뭉뚱그려진
    # 표면적 요약이 나오는 경향이 있어(2026-08-29 실사용 피드백) 기본을 True로 바꿨다.
    # False로 되돌리면 다시 빨라지는 대신 요약이 일반적으로 변한다.
    OLLAMA_THINK: bool = True
    # 기본값(약 0.8)은 사실 기반 구조화 요약에는 다소 높아 재현성이 떨어진다. 낮게 고정해
    # 같은 강의를 다시 요약해도 핵심 내용이 흔들리지 않게 한다.
    OLLAMA_TEMPERATURE: float = 0.3

    # --- 요약 재시도 정책 (§3.4 Provider 정책, T-18) ---
    # 429/5xx/타임아웃만 지수 백오프로 재시도한다. 4xx(프롬프트/형식 오류)는 즉시 실패.
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BASE_DELAY_SECONDS: float = 1.0

    # --- map-reduce 긴 전사 요약 (§3.4, T-21) ---
    # 전사를 이 크기(토큰 근사치) 단위로 나눠 부분 요약 후 합친다. 오버랩을 둬 청크 경계에서
    # 문맥이 잘려 내용이 통째로 누락되는 것을 막는다. Ollama(OLLAMA_NUM_CTX=8192)처럼 컨텍스트가
    # 좁은 로컬 모델을 위한 값이다.
    SUMMARY_CHUNK_SIZE_TOKENS: int = 4000
    SUMMARY_CHUNK_OVERLAP_TOKENS: int = 200
    # 부분 요약은 순차 호출한다 — 무료 티어 LLM에 병렬로 쏘면 즉시 429이므로 호출 간 간격을 둔다.
    SUMMARY_MAP_CALL_INTERVAL_SECONDS: float = 1.0
    # OpenAI(2026-08-29~)는 컨텍스트가 1.05M 토큰이라(공식 문서 확인) 이 앱이 허용하는 최장
    # 강의(240분, 실측상 넉넉잡아 4~5만 토큰)도 통째로 한 번에 들어간다 — 그런데도 위 좁은
    # 값으로 청크를 나누면, 요약 단계가 매번 필요 없이 2~3번 호출돼 시간이 2~3배 걸리고(각
    # 호출마다 고정 지시문 ~1,700토큰이 반복 전송됨) 청크 경계 때문에 맥락도 끊긴다 —
    # 2026-08-30 실사용 중 이 낭비를 실제로 겪은 뒤 provider별로 분리했다(2026-08-30).
    # 실제 컨텍스트(1.05M)보다 훨씬 낮게 잡아 출력 토큰·프롬프트 오버헤드 여유를 넉넉히 둔다.
    OPENAI_SUMMARY_CHUNK_SIZE_TOKENS: int = 200_000

    # --- 무료 티어 대안 Provider (§0 D4/D5, 그룹 E/T-29에서 사용) ---
    # 절대 로그/응답에 노출하지 않는다 (§3.4, §6 보안).
    GROQ_API_KEY: SecretStr | None = None
    GEMINI_API_KEY: SecretStr | None = None

    # --- OpenAI 요약 Provider (2026-08-29, 로컬 Ollama 메모리 압박 회피) ---
    # 로컬 STT는 그대로 두고 요약 단계만 클라우드로 옮긴다. 절대 로그/응답에 노출하지 않는다.
    OPENAI_API_KEY: SecretStr | None = None
    # gpt-4o-mini보다 설명 풍부도가 나아 2026-08-29 실사용 비교 후 변경.
    OPENAI_MODEL: str = "gpt-5.6-luna"
    OPENAI_TIMEOUT_SECONDS: float = 120.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

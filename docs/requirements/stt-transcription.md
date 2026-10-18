# 강의 녹음 → STT 전사 → LLM 요약 도구 요구사항 정의서

- 문서 상태: **초안 확정 (Draft-Final) — 사용자 검토/승인 대기**
- 작성일: 2026-08-20
- 작성 주체: product-planner
- 대상 독자: 사용자(본인), backend-implementer, frontend-implementer, tester
- 코드네임: **`lecture-notes`** (클로바노트 유사 개인용 도구)

> **이 문서에 대해**
> - 사용자 요청: *"내 데스크탑에서 프로그래밍 수업 내용을 녹음해서 텍스트로 전사하고 LLM으로
>   요약하는 기능. 클로바노트처럼. 되도록 무료로."*
> - product-planner에게 대화형 질의 도구가 없어, **불확실한 항목은 질문 대신 §0에서 기본값을
>   자율 결정**하고 근거를 명시했습니다. 승인 전 §0만 훑어도 방향을 판단할 수 있습니다.
> - **변경을 원하는 항목이 있으면 §0의 번호로 알려주시면 됩니다.** 그대로 진행해도 무방합니다.
> - 회원가입/인증 기능은 백엔드에서 전부 제거되었습니다. 이 문서는 **인증에 어떤 의존도 두지
>   않으며**, 현재의 빈 FastAPI 스켈레톤(`/health`만 존재) 위에 구축하는 것을 전제로 합니다.

---

## 0. 결정 사항 (product-planner 자율 결정)

| # | 항목 | **결정** | 근거 / 비고 |
|---|------|---------|------------|
| D1 | 입력 방식 (P0) | **오디오 파일 업로드** | 가장 빨리 동작하는 형태. OS 오디오 권한·드라이버 문제를 P0에서 배제 |
| D2 | 입력 방식 (P1) | **브라우저 내장 녹음** (MediaRecorder API) | 로컬 웹앱이므로 브라우저가 마이크를 다룬다. 네이티브 오디오 라이브러리 불필요 |
| D3 | STT 엔진 | **로컬 `faster-whisper`, 모델 `large-v3-turbo`** | **완전 무료·무제한·오프라인.** 정확도는 large-v3와 사실상 동급이면서 훨씬 빠름 |
| D4 | STT 대안 | Groq `whisper-large-v3` **무료 티어** (어댑터로 교체 가능) | 하드웨어가 느릴 때의 탈출구. 무료 티어 일 8시간(28,800 오디오초), 파일당 25MB |
| D5 | 요약 LLM | **로컬 Ollama (`qwen3:14b` 계열) 기본**, **Gemini/Groq 무료 티어** 선택 가능 | 둘 다 $0. 로컬은 오프라인·무제한, 무료 티어는 빠르지만 쿼터·프라이버시 이슈. 사용자 하드웨어(M4 Pro/24GB, 2026-08-22 확인)에서 `8b`보다 한국어·기술용어 품질이 낫고도 메모리 여유 충분해 `14b`로 상향 |
| D13 | 멀티태스크 메모리 여유 | **파이프라인 순차 실행 + LLM `keep_alive` 짧게(요약 직후 언로드)** | 사용자 요구: "멀티태스크 사용에 제약 없어야 함". 전사(Whisper)·요약(Ollama)이 동시에 메모리를 쓰지 않게 하고, Ollama 기본 5분 유휴 보관을 끄거나 단축해 처리 종료 즉시 RAM을 반환 |
| D6 | 앱 형태 | **로컬 웹앱** — FastAPI(`127.0.0.1:8765`) + 단일 페이지 UI | 기존 FastAPI 스켈레톤을 그대로 활용. 브라우저 녹음(D2)의 전제이기도 함 |
| D7 | 프로젝트 위치 | **기존 `backend/`에 구축** (`app/` 하위에 모듈 추가) | 빈 스켈레톤·DB 세션·pytest 하니스가 이미 동작 중. 새로 만들 이유 없음 |
| D8 | 인증 | **없음.** `127.0.0.1` 바인딩 단일 사용자 | 개인 도구. 외부 노출이 필요해지면 그때 별도 요구사항으로 논의 |
| D9 | DB | **SQLAlchemy 유지, dialect 중립 스키마**. 실사용 SQLite / 테스트 기존 PostgreSQL | 실사용에 도커를 강제하지 않으면서 기존 테스트 하니스도 그대로 살림 (§2.3) |
| D10 | 강의 언어 | **한국어 + 영어 기술 용어 혼용** (`language="ko"` 고정) | 프로그래밍 수업 특성. 자동 판별은 코드 구간에서 언어를 잘못 잡음 |
| D11 | 강의 길이 | 60~180분 가정, 최대 240분 | |
| D12 | 비동기 처리 | FastAPI `BackgroundTasks` + 상태 폴링 | 개인 도구에 Celery/Redis는 과함. 유실은 복구 스윕으로 대응 (§3.6) |

### 0.1 남은 가정 (Assumption) — 틀리면 알려주세요

| # | 가정 | 틀릴 경우 영향 |
|---|------|--------------|
| A1 | ~~실행 환경은 macOS (Darwin 25.6), Apple Silicon, RAM 16GB 이상~~ → **확인됨: M4 Pro / RAM 24GB** (2026-08-22 사용자 확인) | 가정이 아닌 확정 사양. 피크 메모리(요약 시 `qwen3:14b` Q4 ~9GB)로도 24GB 중 ~15GB가 항상 여유 → 멀티태스크 제약 없음(D13). 향후 다른 Mac에서 돌릴 경우에만 `small`/`medium`·`8b` 하향 재검토 |
| A2 | 강의 녹음은 **본인 학습용**이며 녹음 자체의 허용 여부는 사용자 책임 | 법적/윤리 이슈. README에 명시 (§8) |
| A3 | 수업은 **온라인이 아닌 대면**(마이크로 수음 가능) | 온라인 강의라면 시스템 오디오 캡처가 필요 → macOS에선 BlackHole 등 가상 오디오 장치 설치 필요 (P2, F-4) |
| A4 | 동시에 처리할 강의는 1건 | 다건 동시 처리가 필요하면 큐 도입 검토 |
| A5 | 모델명·무료 티어 쿼터는 2026-08 웹 조사 기준 | 착수 시 공식 문서로 재확인 (T-01) |

### 0.2 "무료"를 어떻게 보장하는가 — 이 설계의 핵심

비용이 발생하는 지점은 **STT**와 **요약** 딱 두 곳입니다. 둘 다 $0 경로가 실재합니다.

| 단계 | 기본 경로 (완전 무료·오프라인) | 대안 (무료 티어) | 유료 (미채택) |
|------|------------------------------|-----------------|-------------|
| STT | **로컬 faster-whisper** — 무제한, $0, 인터넷 불필요 | Groq whisper-large-v3 — 일 8시간 | OpenAI ~$0.006/분 |
| 요약 | **로컬 Ollama** — 무제한, $0 | Gemini Flash / Groq Llama 무료 티어 | Claude/GPT API |

**무료 티어를 기본이 아니라 "대안"에 둔 이유**: 무료 티어는 사전 통보 없이 축소·중단됩니다
(2025년 12월 Gemini 무료 쿼터가 대폭 축소된 사례). 로컬을 기본으로 두면 **무료 티어가 사라져도
도구가 죽지 않습니다.** 그래서 `SttProvider` / `LlmProvider` **어댑터 인터페이스**가 이 설계의
가장 중요한 구조적 결정입니다 — 설정 한 줄로 경로를 갈아끼울 수 있어야 합니다.

---

## 1. 개요 및 목표

### 1.1 배경
프로그래밍 수업은 정보 밀도가 높다. 코드, 명령어, 에러 메시지, 과제 공지가 말로 지나가면 그대로
유실된다. 녹음 파일은 남지만 60분짜리 오디오는 다시 듣기 전에는 검색도 복습도 불가능하다.
**전사 → 구조화된 요약**까지 자동화하면 수업 직후 복습 가능한 노트가 생기고, "그때 교수님이 뭐라고
했더라"를 검색으로 해결할 수 있다.

### 1.2 목표
1. 오디오를 올리면 **전사와 요약이 자동으로** 완료된다.
2. **월 비용 0원**으로 동작한다. `[핵심 제약]`
3. 요약은 줄글이 아니라 **복습 가능한 구조**(핵심 주제 / 개념 / 코드 / 과제 / 키워드)로 나온다.
4. 한국어 속 **영어 기술 용어가 정확히 표기**된다.
5. 과거 수업 노트를 **검색**할 수 있다.
6. **강의 음성이 내 컴퓨터를 벗어나지 않는 모드**를 선택할 수 있다.

### 1.3 성공 기준 (측정 가능)
| 지표 | 목표 |
|------|------|
| 60분 강의 전체 처리 시간 | 로컬 경로 20분 이내 / 무료 티어 경로 5분 이내 |
| 월 운영 비용 | **0원** |
| 기술 용어 정확 표기율 | 용어집 적용 후 **90% 이상** (샘플 강의 3회로 측정) |
| 수업 1회당 수동 조작 | **3회 이하** (업로드 / 결과 확인 / 내보내기) |
| 과제·공지 누락 | 0건 (샘플 3회 기준) |

### 1.4 범위

**포함 (In Scope)**
- 오디오 파일 업로드 및 검증 (P0)
- 브라우저 내장 녹음 (P1)
- 로컬 Whisper 전사 (타임스탬프 세그먼트 포함)
- 용어집 기반 기술 용어 보정
- LLM 구조화 요약 (map-reduce로 긴 강의 대응)
- 세션 관리: 목록 / 상세 / 편집 / 삭제
- 전문 검색
- 내보내기 (Markdown / txt / srt)
- STT·LLM 어댑터 교체 구조
- 로컬 웹 UI

**미포함 (Out of Scope)**
- 다중 사용자, 로그인/회원가입, 권한 `[D8]`
- 클라우드 동기화, 외부 배포, 모바일 앱
- 실시간 라이브 자막 `[F-1]`
- 화자 분리 `[F-2]`
- 슬라이드 캡처/OCR `[F-3]`
- 시스템 오디오 캡처(온라인 강의) `[F-4]`
- 전사 텍스트 편집기 (내보내 외부 에디터 사용)

### 1.5 용어
| 용어 | 정의 |
|------|------|
| 세션(session) | 수업 1회차. 오디오 1건 + 전사 1건 + 요약 N건 |
| 세그먼트 | 전사의 시간 구간 (시작/끝 초 + 텍스트) |
| 용어집(glossary) | 강의 빈출 기술 용어 목록. 전사 보정에 사용 |
| Provider | 실제 작업 수행 엔진 어댑터 (`SttProvider`, `LlmProvider`) |
| map-reduce 요약 | 긴 전사를 조각내 부분 요약 후 합쳐 최종 요약 |

---

## 2. 시스템 설계

### 2.1 파이프라인
```
오디오 업로드 ──> 검증 ──> [UPLOADED]
                              │ BackgroundTasks
                              ▼
                         [TRANSCRIBING] ── 로컬 Whisper ──> 텍스트 + 세그먼트
                              │                                    │
                              ▼                              용어집 보정
                        [TRANSCRIBED]                              │
                              │                                    ▼
                              ▼                              (보정 텍스트 저장)
                        [SUMMARIZING] ── LLM(map-reduce) ──> 구조화 요약
                              │
                              ▼
                           [DONE]
```

### 2.2 모듈 구조 (기존 `backend/app/` 위에 추가) `[D7]`
```
backend/app/
├── core/
│   ├── config.py        (기존) + STT/LLM/스토리지 설정 추가
│   └── errors.py        (신규) AppError + 에러 코드 + 전역 핸들러
├── db/                  (기존) session.py, base.py
├── models/              (신규) session.py, transcript.py, summary.py, glossary.py
├── schemas/             (신규) Pydantic 요청/응답 스키마
├── api/v1/              (신규) sessions.py, search.py, glossary.py, health.py
├── stt/                 (신규) base.py(SttProvider) + local_whisper.py / groq.py / fake.py
├── llm/                 (신규) base.py(LlmProvider) + ollama.py / gemini.py / groq.py / fake.py
├── audio/               (신규) 형식 검증, 길이 추출, 변환
├── pipeline/            (신규) 상태 전이 + 전사→요약 오케스트레이션
├── export/              (신규) markdown / txt / srt 렌더러
└── main.py              (기존) 라우터 등록 + 127.0.0.1 바인딩 검증
backend/data/            (gitignore) audio/, models/, lecture_notes.db
frontend/                (신규, P1) 단일 페이지 UI
```

**설계 원칙**
- `pipeline/`은 `stt/`·`llm/`의 **구체 구현을 절대 알지 못한다.** 인터페이스에만 의존한다.
- API 라우터에는 비즈니스 로직을 두지 않는다. 전부 `pipeline/`·서비스 계층에 둔다.
- 무거운 모델 로딩은 **첫 사용 시점에 지연 로딩**한다. 서버 기동 때 로드하면 `/health`조차 느려진다.

### 2.3 데이터 모델 `[D9]`

**dialect 중립 규칙 (중요)**
실사용은 SQLite, 테스트 하니스는 기존 PostgreSQL을 그대로 쓰기 위해 **양쪽에서 동작하는 타입만** 쓴다.

| 금지 | 대신 사용 |
|------|----------|
| `postgresql.UUID` | `String(36)` + 애플리케이션에서 `uuid4()` 생성 |
| `JSONB` | `JSON` (SQLAlchemy 일반 타입) |
| 네이티브 `ENUM` | `String(20)` + 애플리케이션 레벨 Enum 검증 |
| `TIMESTAMPTZ` 의존 | `DateTime(timezone=True)` + **항상 UTC aware datetime 저장** |

#### `sessions`
| 컬럼 | 타입 | 제약 | 설명 |
|------|------|------|------|
| `id` | String(36) | PK | UUID |
| `title` | String(200) | NOT NULL | 기본 `"YYYY-MM-DD 수업"` |
| `course` | String(100) | NULL | 과목명 |
| `status` | String(20) | NOT NULL | §2.4 |
| `source` | String(20) | NOT NULL | `UPLOAD` / `RECORD` |
| `audio_path` | String(512) | NULL | 로컬 경로 |
| `original_filename` | String(255) | NOT NULL | |
| `mime_type` | String(100) | NOT NULL | 실제 감지된 형식 |
| `file_size_bytes` | BigInteger | NOT NULL | |
| `duration_seconds` | Float | NULL | |
| `error_code` | String(50) | NULL | |
| `error_message` | Text | NULL | 사용자용. 스택트레이스 금지 |
| `recorded_at` | DateTime(tz) | NOT NULL | |
| `created_at` / `updated_at` | DateTime(tz) | NOT NULL | |

인덱스: `INDEX(recorded_at DESC)`, `INDEX(status)`, `INDEX(course)`

#### `transcripts`
| 컬럼 | 타입 | 제약 |
|------|------|------|
| `id` | String(36) | PK |
| `session_id` | String(36) | FK → sessions.id **ON DELETE CASCADE**, **UNIQUE** |
| `text_raw` | Text | NOT NULL — 원본 전사 |
| `text_corrected` | Text | NULL — 용어집 보정본 |
| `language` | String(10) | NOT NULL |
| `provider` / `provider_model` | String(50)/String(100) | NOT NULL |
| `elapsed_seconds` | Float | NULL — 전사 소요 시간 |
| `created_at` | DateTime(tz) | NOT NULL |

> **원본과 보정본을 둘 다 저장하는 이유**: 용어집 치환은 오작동할 수 있다. 원본이 없으면
> 잘못된 보정을 되돌릴 방법이 없어진다.

#### `transcript_segments`
| 컬럼 | 타입 | 제약 |
|------|------|------|
| `id` | Integer | PK autoincrement |
| `transcript_id` | String(36) | FK → transcripts.id ON DELETE CASCADE |
| `seq` | Integer | NOT NULL, `UNIQUE(transcript_id, seq)` |
| `start_seconds` / `end_seconds` | Float | NOT NULL |
| `text` | Text | NOT NULL |

#### `summaries`
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | String(36) | PK |
| `session_id` | String(36) | FK → sessions.id ON DELETE CASCADE (세션당 **N건 허용**) |
| `content_markdown` | Text | 요약 본문 |
| `key_points` | JSON | `[{text, atSeconds}]` |
| `concepts` | JSON | `[{term, description}]` |
| `code_snippets` | JSON | `[{language, code, description}]` |
| `action_items` | JSON | `[{text, dueDate}]` |
| `keywords` | JSON | `[string]` |
| `provider` / `provider_model` | String | |
| `created_at` | DateTime(tz) | |

- 세션당 여러 건을 허용해 **다른 모델로 재요약 후 비교**할 수 있게 한다. 최신 1건이 기본 표시.

#### `glossary_terms`
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | Integer | PK |
| `term` | String(100) | 정식 표기 (예: `PostgreSQL`) |
| `aliases` | JSON | 오인식 패턴 (예: `["포스트그레스큐엘","포스트그레"]`) |
| `course` | String(100) NULL | NULL이면 전역 |

### 2.4 세션 상태 전이
```
UPLOADED ──> TRANSCRIBING ──성공──> TRANSCRIBED ──> SUMMARIZING ──성공──> DONE
                  │                                      │
                실패│                                  실패│
                  ▼                                      ▼
               FAILED ◄──────────────────────────────────┘
               (error_code로 어느 단계에서 실패했는지 구분)

FAILED / DONE / TRANSCRIBED ──재실행──> 해당 단계부터 다시
```

**핵심 규칙**
- **요약이 실패해도 전사는 절대 삭제하지 않는다.** 전사가 가장 비싼 산출물이다.
- `FAILED`에서 재시도할 때, 전사가 이미 있으면 **요약만** 다시 실행한다.
- `DONE`에서도 재요약을 허용한다 (다른 모델 비교).

---

## 3. 상세 정책

### 3.1 업로드 검증
| 항목 | 규칙 | 위반 시 |
|------|------|---------|
| 형식 | mp3, m4a, wav, webm, ogg, flac, mp4, mpeg | 415 `UNSUPPORTED_AUDIO_FORMAT` |
| 용량 | 최대 **500MB** (로컬 전사라 25MB 제약 없음) | 413 `FILE_TOO_LARGE` |
| 길이 | 1초 초과 ~ **240분** | 400 `AUDIO_TOO_SHORT` / `AUDIO_TOO_LONG` |
| 무결성 | 디코딩 가능한 오디오 스트림 존재 | 400 `INVALID_AUDIO_FILE` |
| 디스크 | 여유 공간 1GB 이상 | 507 `INSUFFICIENT_DISK_SPACE` |

- **확장자를 신뢰하지 않는다.** 매직 넘버/컨테이너 헤더로 실제 형식을 판별한다.
- 용량 검사는 **스트리밍 중 누적 바이트로** 한다. 전체를 메모리에 올린 뒤 검사하면 500MB 파일에
  메모리가 터진다.
- 저장 경로는 **서버가 생성한 UUID 기반**으로만 만든다. 원본 파일명을 경로에 쓰면 경로 순회 취약점이 된다.
- `[D4 사용 시]` Groq 무료 티어로 전환하면 **파일당 25MB 제한**이 적용되므로, 그때는 분할 업로드가
  필요하다 (F-5).

### 3.2 전사 정책 `[D3]`
| 항목 | 정책 |
|------|------|
| 엔진 | `faster-whisper`, 모델 `large-v3-turbo` (설정으로 변경 가능) |
| 언어 | `ko` 고정 `[D10]` |
| VAD | **활성화** — 강의 중 침묵이 길어 처리 시간을 크게 줄인다 |
| 세그먼트 | 타임스탬프 포함 저장 (복습 시 해당 지점으로 점프) |
| 모델 로딩 | **지연 로딩 + 프로세스 내 캐시** (매 요청 재로딩 금지 — 수십 초 낭비) |
| 모델 다운로드 | 최초 1회. 진행률 노출. `data/models/`에 캐시 |
| 진행률 | 세그먼트 단위로 `processed_seconds / duration` 갱신 |

- **`large-v3-turbo`를 고른 이유**: `large-v3` 대비 정확도 손실이 거의 없으면서 훨씬 빠르다.
  60분 강의를 실용적인 시간 안에 처리하려면 turbo 급이 사실상 필수다.
- 하드웨어가 못 따라가면 `medium` → `small`로 낮춘다. **T-15 벤치마크에서 결정**한다.

### 3.3 기술 용어 보정 (이 도구의 차별점)
프로그래밍 수업 전사에서 가장 크게 체감되는 문제는 **영어 기술 용어 오인식**이다.
("깃허브"→"긴 허브", "널 포인터"→"눌 포인터", "쿼리"→"코리")

2단계로 대응한다.
1. **전사 전 프롬프트 바이어싱** — 용어집의 `term` 목록을 Whisper initial prompt로 전달해
   해당 표기가 나오도록 유도.
2. **전사 후 규칙 치환** — `aliases` → `term` 치환. **단어 경계를 지켜** 과잉 치환을 막는다.
   (예: "자바" 치환이 "자바스크립트"를 깨뜨리면 안 된다 → 긴 별칭부터 우선 매칭.)

- 원본(`text_raw`)과 보정본(`text_corrected`)을 **둘 다 보존**한다.
- **기본 용어집 100개를 시드로 제공**한다. 빈 상태로 두면 아무도 채우지 않아 기능이 죽는다.

### 3.4 요약 정책 `[D5]`

**고정 출력 스키마**
```markdown
## 한 줄 요약
## 핵심 주제        (3~7개, 각각 대략적 타임스탬프 병기)
## 개념 정리        (용어: 설명)
## 코드 / 명령어    (언급된 코드·CLI·문법)
## 과제 및 공지     (마감일 포함, 없으면 "없음" 명시)
## 복습 키워드
```
- **줄글 요약을 만들지 않는다.** 복습에 필요한 건 문단이 아니라 "무엇을 다시 볼지"의 목록이다.
- **과제·공지 누락은 치명적**이므로 별도 섹션으로 강제하고, 없으면 "없음"을 반드시 쓰게 한다.
- 각 핵심 주제에 타임스탬프를 붙여 **원문 대조가 가능**하게 한다 (환각 방어).

**긴 강의 처리 (map-reduce, 필수)**
- 60분 강의 전사는 대략 1.5만~2.5만 토큰이다. 로컬 8B 모델의 실용적 컨텍스트와 무료 티어 TPM을
  함께 고려하면 **통째로 넣는 방식은 언젠가 반드시 깨진다.**
- 전사를 **약 4,000토큰 단위 + 200토큰 오버랩**으로 분할 → 부분 요약 → 부분 요약들을 합쳐 최종 요약.
- 오버랩을 두는 이유: 청크 경계에서 문맥이 잘려 내용이 통째로 누락되는 것을 막는다.
- **부분 요약은 순차 호출**한다. 무료 티어에 병렬로 쏘면 즉시 429다. 호출 간 간격을 설정값으로 둔다.

**Provider 정책**
- 429/5xx/타임아웃만 지수 백오프로 최대 3회 재시도. 4xx(프롬프트/형식 오류)는 즉시 실패.
- LLM이 형식을 어긴 응답을 줄 수 있으므로 **파싱 실패 시 1회 재요청**, 그래도 실패하면
  `LLM_INVALID_RESPONSE`로 명확히 실패시킨다. 깨진 요약을 저장하지 않는다.
- API 키는 환경변수로만 주입. 코드·로그·응답·내보내기 파일 어디에도 넣지 않는다.
- **`[D13]` Ollama 로컬 호출 시 `keep_alive`를 짧게 설정**(예: `"30s"` 또는 요약 완료 직후 명시적 언로드
  요청)한다. Ollama 기본값(5분 유휴 보관)을 그대로 두면 강의 처리 후에도 `qwen3:14b`(~9GB)가
  메모리에 남아 있어 다른 앱의 가용 RAM을 불필요하게 줄인다.

### 3.5 검색
- 1차: **DB `LIKE` 기반 단순 검색**으로 시작한다 (세션 수가 수백 건 규모라 충분하다).
- 2차: 체감 성능이 떨어지면 SQLite FTS5로 교체 (F-6). **처음부터 FTS를 넣지 않는다** — dialect
  중립 규칙(D9)과 충돌하고, 개인 규모에서 조기 최적화다.
- 전사(보정본)와 요약 본문을 모두 검색 대상으로 하고, 매칭 스니펫과 타임스탬프를 함께 반환한다.

### 3.6 비정상 종료 복구 `[D12]`
- `BackgroundTasks`는 서버 재시작 시 진행 중 작업이 유실된다. 따라서 **복구 스윕이 필수다.**
- 서버 기동 시 `TRANSCRIBING`/`SUMMARIZING` 상태로 남은 세션을 스캔해
  `FAILED`(`error_code=INTERRUPTED`)로 전이시키고, 사용자가 재실행할 수 있게 한다.
- 전사가 이미 저장되어 있으면 **요약 단계부터** 재개한다. 전사를 다시 돌리는 것은 순수한 낭비다.
- 30분 이상 `TRANSCRIBING`에 머문 세션도 동일하게 처리한다.

### 3.7 보안·프라이버시 `[D8]`
- **인증 없음.** 대신 **`127.0.0.1` 바인딩을 강제**한다. 설정이 `0.0.0.0`이면 **기동을 거부**한다.
  같은 와이파이의 타인이 내 강의 녹음과 전사를 열람할 수 있게 되는 것은 심각한 사고다.
- CORS는 `http://127.0.0.1:*`, `http://localhost:*`만 허용한다.
- `data/` 디렉토리는 소유자 전용 권한(0700)으로 생성한다.
- **로그에 전사·요약 본문을 남기지 않는다.** 길이와 소요 시간만 기록한다.
- **오프라인 모드**(로컬 Whisper + 로컬 Ollama)에서는 외부 네트워크 요청이 0건이어야 하며,
  이를 테스트로 검증한다. 강의에는 제3자 음성이 포함되므로 이 모드가 유지되는 것이 중요하다.
- 현재 모드가 "오프라인"인지 "클라우드 전송"인지 UI/`/health`에 **명확히 표시**한다.

---

## 4. User Story (Given-When-Then)

### US-01. 오디오 업로드 → 세션 생성 — P0
```
Given 사용자가 로컬 웹앱을 실행했고 디스크 여유 공간이 충분하다
  And 60분 분량의 정상적인 m4a 강의 녹음 파일을 갖고 있다
When 사용자가 해당 파일을 title="자료구조 7주차", course="자료구조"로 업로드하면
Then 서버는 201 Created와 함께 sessionId, status="UPLOADED", durationSeconds를 반환하고
  And 오디오가 data/audio/ 아래 서버 생성 UUID 경로로 저장되며
  And 원본 파일명이 저장 경로에 사용되지 않고
  And 응답이 파일 전체를 메모리에 적재하지 않고 처리된다
```

### US-02. 전사 → 요약 자동 실행 — P0
```
Given status="UPLOADED"인 세션이 있다
When 사용자가 처리 실행을 요청하면
Then 서버는 202 Accepted를 반환하고 즉시 응답하며 (전사 완료를 기다리지 않는다)
  And 세션이 TRANSCRIBING으로 전이되어 로컬 Whisper 전사가 수행되고
  And 전사 성공 시 transcripts 1건과 transcript_segments N건이 저장되어 TRANSCRIBED가 되고
  And 이어서 SUMMARIZING으로 전이되어 요약이 생성되고
  And summaries 1건이 저장되며 최종 status가 DONE이 되고
  And 이 과정에서 사용자의 추가 조작이 필요 없다
```

### US-03. 처리 진행 상황 확인 — P0
```
Given 세션의 전사가 진행 중이다
When 사용자가 세션 상세를 조회하면
Then 200 OK와 status="TRANSCRIBING"이 반환되고
  And progress에 stage, percent, etaSeconds가 포함되며
  And transcript.available은 false이고 summary는 null이며
  And pollAfterSeconds가 함께 반환되어 다음 폴링 시점을 안내한다
```

### US-04. 전사 결과에 타임스탬프 세그먼트가 포함된다 — P0
```
Given 세션의 전사가 완료되었다
When 사용자가 전사 결과를 조회하면
Then 전체 텍스트와 세그먼트 목록이 seq 오름차순으로 반환되고
  And 각 세그먼트에 startSeconds와 endSeconds가 있으며
  And 세그먼트 시작 시각이 단조 증가하고 구간이 서로 겹치지 않는다
```

### US-05. 요약이 정해진 구조로 생성된다 — P0
```
Given 프로그래밍 수업의 전사가 완료되었다
When 요약이 생성되면
Then "한 줄 요약", "핵심 주제", "개념 정리", "코드/명령어", "과제 및 공지", "복습 키워드"
     6개 섹션이 모두 존재하고
  And keyPoints의 각 항목에 atSeconds가 포함되며
  And 과제나 공지가 없었던 경우 actionItems가 빈 배열이고 본문에 "없음"이 명시된다
```

### US-06. 지원하지 않는 파일 거부 — P0
```
Given 사용자가 오디오가 아닌 파일(report.pdf)을 갖고 있다
When 해당 파일을 업로드하면
Then 서버는 415와 code="UNSUPPORTED_AUDIO_FORMAT"을 반환하고
  And 세션이 생성되지 않으며
  And 파일이 저장소에 저장되지 않고
  And 전사가 시작되지 않는다
```

### US-07. 확장자 위장 파일 거부 — P0
```
Given 사용자가 PDF 파일의 이름만 "lecture.mp3"로 바꿔 준비했다
When 해당 파일을 업로드하면
Then 서버는 확장자가 아닌 실제 파일 내용으로 판별해
     415 UNSUPPORTED_AUDIO_FORMAT 또는 400 INVALID_AUDIO_FILE을 반환하고
  And 세션이 생성되지 않는다
```

### US-08. 요약이 실패해도 전사는 보존된다 — P0
```
Given 세션의 전사는 성공했고 요약 단계에서 LLM이 계속 실패한다
When 재시도(최대 3회)까지 모두 실패하면
Then 세션 status는 FAILED, errorCode는 "LLM_FAILED"(또는 LLM_QUOTA_EXCEEDED)로 기록되고
  And transcripts와 transcript_segments는 그대로 남아 있으며
  And 사용자는 전사 텍스트를 정상적으로 조회하고 내보낼 수 있고
  And 이후 요약만 다시 실행할 수 있다
```

### US-09. 완전 오프라인 동작 — P0
```
Given 설정이 STT=local_whisper, LLM=ollama이고 Whisper 모델이 이미 캐시되어 있다
When 인터넷이 차단된 상태에서 업로드 → 전사 → 요약을 실행하면
Then 전체 파이프라인이 DONE까지 정상 완료되고
  And 외부 네트워크 요청이 한 건도 발생하지 않으며
  And 강의 오디오와 전사 텍스트가 로컬을 벗어나지 않는다
```

### US-10. 서버 재시작으로 중단된 작업 복구 — P0
```
Given 어떤 세션이 TRANSCRIBING 상태일 때 서버가 재시작되었다
When 서버가 다시 기동되면
Then 복구 스윕이 해당 세션을 FAILED(errorCode="INTERRUPTED")로 전이시키고
  And 사용자가 재실행할 수 있는 상태가 되며
  And 전사가 이미 저장되어 있던 경우에는 요약 단계부터 재개할 수 있다
```

### US-11. 외부 노출 차단 — P0
```
Given 설정에서 바인딩 호스트를 "0.0.0.0"으로 지정했다
When 서버를 기동하면
Then 서버가 기동을 거부하고 명확한 오류 메시지를 출력하며
  And 기본 설정에서는 127.0.0.1에만 바인딩되어 외부 접근이 불가능하다
```

### US-12. 긴 강의 map-reduce 요약 — P1
```
Given 180분 분량 강의의 전사가 단일 LLM 호출 한도를 초과한다
When 요약이 실행되면
Then 전사가 오버랩을 둔 청크로 분할되어 부분 요약이 순차 수행되고
  And 부분 요약들이 합쳐져 최종 요약 1건이 생성되며
  And 무료 티어 RPM 제한에 걸리지 않도록 호출 간 간격이 유지되고
  And 최종 요약에 강의 전반부와 후반부 내용이 모두 반영된다
```

### US-13. 기술 용어 보정 — P1
```
Given 용어집에 term="PostgreSQL", aliases=["포스트그레스큐엘","포스트그레"]가 등록되어 있다
When 전사 결과에 "포스트그레스큐엘에서 조인을 하면"이 포함되면
Then 보정본에는 "PostgreSQL에서 조인을 하면"이 저장되고
  And 원본 전사(text_raw)도 그대로 보존되며
  And 단어 경계를 벗어난 과잉 치환이 발생하지 않고
  And 긴 별칭이 짧은 별칭보다 우선 매칭된다
```

### US-14. 세션 목록 조회 — P1
```
Given 여러 회차의 수업 세션이 저장되어 있다
When 사용자가 세션 목록을 조회하면
Then 최근 녹음순으로 정렬되어 반환되고
  And 각 항목에 제목, 과목, 상태, 길이, 녹음일시, 요약 미리보기(최대 200자)가 포함되며
  And 전체 전사 텍스트는 목록 응답에 포함되지 않고
  And 과목·상태로 필터링하고 페이징할 수 있다
```

### US-15. 전문 검색 — P1
```
Given 3주 전 수업에서 "이진 탐색 트리"를 다뤘고 전사와 요약이 저장되어 있다
When 사용자가 "이진 탐색"으로 검색하면
Then 해당 세션이 결과에 포함되고
  And 매칭 위치(TRANSCRIPT/SUMMARY)와 문맥 스니펫, 타임스탬프가 함께 반환되며
  And 검색어가 2자 미만이면 400 VALIDATION_ERROR가 반환된다
```

### US-16. 내보내기 — P1
```
Given 세션이 DONE 상태다
When 사용자가 Markdown 내보내기를 요청하면
Then 제목/과목/날짜/요약/전사 전문이 담긴 .md가 반환되고
  And Content-Disposition에 "YYYY-MM-DD_과목_제목.md" 형식 파일명이 포함되며
  And srt 형식 요청 시 타임코드가 "HH:MM:SS,mmm --> HH:MM:SS,mmm" 규격을 따르고
  And 전사가 완료되지 않은 세션에 요청하면 409 TRANSCRIPT_NOT_READY가 반환된다
```

### US-17. 재요약 — P1
```
Given 세션이 DONE 또는 요약 단계 FAILED 상태다
When 사용자가 재요약을 요청하면
Then 기존 전사를 그대로 사용해 요약만 다시 수행되고 (전사를 재실행하지 않는다)
  And 새 summaries 레코드가 추가되며 기존 요약도 보존되고
  And 조회 시 최신 요약이 기본으로 표시된다
```

### US-18. 세션 삭제 — P1
```
Given 더 이상 필요 없는 세션이 있다
When 사용자가 해당 세션을 삭제하면
Then sessions, transcripts, transcript_segments, summaries가 모두 삭제되고
  And 로컬 오디오 파일도 삭제되며
  And 이후 조회 시 404 SESSION_NOT_FOUND가 반환되고
  And 처리 중(TRANSCRIBING/SUMMARIZING)인 세션 삭제는 409 INVALID_SESSION_STATE로 거부된다
```

### US-19. 브라우저에서 직접 녹음 — P1 (프론트엔드)
```
Given 사용자가 로컬 웹앱 메인 화면에 있다
When "녹음 시작"을 누르면
Then 브라우저가 마이크 권한을 요청하고 승인 시 녹음이 시작되며
  And 경과 시간이 실시간으로 표시되고
When "녹음 종료"를 누르면
Then 녹음된 오디오가 자동으로 업로드되어 세션이 생성되고 처리가 시작되며
  And 마이크 권한이 거부되면 "마이크 권한이 필요합니다" 안내가 표시된다
```

### US-20. 메인 화면 UX — P1 (프론트엔드)
```
Given 사용자가 로컬 웹앱을 열었다
When 메인 화면이 렌더되면
Then 업로드 영역(드래그앤드롭)과 최근 세션 목록이 보이고
  And 형식·용량 위반 파일은 업로드 전에 걸러지며
  And 업로드 중에는 진행률이 표시되고 중복 제출이 차단되고
  And 처리 중인 세션은 자동으로 상태가 갱신되며(폴링)
  And 처리 실패 시 사유와 함께 "다시 시도" 버튼이 노출된다
```

### US-21. 세션 상세 화면 — P2 (프론트엔드)
```
Given 처리가 완료된 세션을 열었다
When 상세 화면이 렌더되면
Then 요약과 전사를 탭으로 전환해 볼 수 있고
  And 세그먼트를 클릭하면 해당 시점의 오디오가 재생되며
  And 요약의 핵심 주제 타임스탬프로도 점프할 수 있고
  And md/txt/srt 다운로드 버튼이 동작하고
  And 375px/1440px 뷰포트에서 레이아웃이 깨지지 않으며 콘솔 에러가 0건이다
```

---

## 5. API 설계

### 5.1 공통 규약
- Base URL: `http://127.0.0.1:8765/api/v1`
- **인증 없음** `[D8]`
- 요청/응답 필드: **camelCase**
- Content-Type: `application/json; charset=utf-8` (업로드만 `multipart/form-data`)
- 시각은 모두 ISO8601 UTC

**공통 에러 응답 포맷**
```json
{
  "error": {
    "code": "UNSUPPORTED_AUDIO_FORMAT",
    "message": "지원하지 않는 오디오 형식입니다.",
    "details": [
      { "field": "file", "reason": "UNSUPPORTED_AUDIO_FORMAT", "message": "mp3, m4a, wav 등만 지원합니다." }
    ]
  },
  "requestId": "b0f1c2d3-..."
}
```

**에러 코드 전체**

| code | HTTP | 메시지 |
|------|------|--------|
| `VALIDATION_ERROR` | 400 | 입력값이 올바르지 않습니다. |
| `INVALID_AUDIO_FILE` | 400 | 오디오 파일을 읽을 수 없습니다. |
| `AUDIO_TOO_SHORT` | 400 | 오디오가 너무 짧습니다. |
| `AUDIO_TOO_LONG` | 400 | 오디오 길이가 최대 240분을 초과합니다. |
| `SESSION_NOT_FOUND` | 404 | 세션을 찾을 수 없습니다. |
| `INVALID_SESSION_STATE` | 409 | 현재 상태에서는 수행할 수 없습니다. |
| `TRANSCRIPT_NOT_READY` | 409 | 전사가 아직 완료되지 않았습니다. |
| `FILE_TOO_LARGE` | 413 | 파일 크기가 최대 500MB를 초과합니다. |
| `UNSUPPORTED_AUDIO_FORMAT` | 415 | 지원하지 않는 오디오 형식입니다. |
| `STT_MODEL_UNAVAILABLE` | 503 | 음성 인식 모델을 준비할 수 없습니다. |
| `STT_FAILED` | 500 | 전사에 실패했습니다. |
| `LLM_NOT_CONFIGURED` | 503 | 요약 엔진이 설정되지 않았습니다. |
| `LLM_QUOTA_EXCEEDED` | 429 | 요약 API 사용 한도를 초과했습니다. |
| `LLM_INVALID_RESPONSE` | 502 | 요약 결과 형식이 올바르지 않습니다. |
| `LLM_FAILED` | 502 | 요약 생성에 실패했습니다. |
| `INSUFFICIENT_DISK_SPACE` | 507 | 디스크 여유 공간이 부족합니다. |
| `INTERNAL_ERROR` | 500 | 서버 오류가 발생했습니다. |

> `INTERRUPTED`는 HTTP 에러 코드가 아니라 **세션의 `errorCode` 값**이다 (§3.6).

### 5.2 엔드포인트 목록

| # | Method | Path | 우선순위 | 설명 |
|---|--------|------|---------|------|
| 1 | POST | `/api/v1/sessions` | P0 | 오디오 업로드 → 세션 생성 |
| 2 | POST | `/api/v1/sessions/{id}/process` | P0 | 전사 + 요약 실행 |
| 3 | GET | `/api/v1/sessions/{id}` | P0 | 세션 상세 (상태/진행률/요약) |
| 4 | GET | `/api/v1/sessions/{id}/transcript` | P0 | 전사 전문 + 세그먼트 |
| 5 | GET | `/api/v1/sessions` | P1 | 세션 목록 (필터/페이징) |
| 6 | POST | `/api/v1/sessions/{id}/summarize` | P1 | 요약만 재실행 |
| 7 | GET | `/api/v1/sessions/{id}/export` | P1 | 내보내기 (md/txt/srt) |
| 8 | DELETE | `/api/v1/sessions/{id}` | P1 | 세션 삭제 |
| 9 | GET | `/api/v1/search` | P1 | 전문 검색 |
| 10 | GET/POST/DELETE | `/api/v1/glossary` | P1 | 용어집 관리 |
| 11 | PATCH | `/api/v1/sessions/{id}` | P2 | 제목/과목 수정 |
| 12 | GET | `/health` | P0 | 환경 점검 (기존 확장) |

---

### 5.3 상세 명세

#### ① POST `/api/v1/sessions` — 오디오 업로드

**Content-Type**: `multipart/form-data`

| 필드 | 타입 | 필수 | 제약 |
|------|------|------|------|
| `file` | file | O | §3.1 규칙 |
| `title` | string | X | 최대 200자. 미지정 시 `"YYYY-MM-DD 수업"` |
| `course` | string | X | 최대 100자 |
| `autoProcess` | boolean | X | 기본 `true` — 업로드 즉시 전사·요약 시작 |

**Response 201 Created**
```json
{
  "sessionId": "3f2a1b90-4c5d-4e6f-8a9b-0c1d2e3f4a5b",
  "title": "자료구조 7주차",
  "course": "자료구조",
  "status": "TRANSCRIBING",
  "source": "UPLOAD",
  "originalFilename": "lecture-0820.m4a",
  "fileSizeBytes": 57344000,
  "durationSeconds": 3612.4,
  "recordedAt": "2026-08-20T09:00:00Z",
  "createdAt": "2026-08-20T10:00:00Z",
  "pollAfterSeconds": 10
}
```
- `autoProcess=true`면 응답 시점 status가 `TRANSCRIBING`, `false`면 `UPLOADED`.

| Status | code | 조건 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | `file` 누락, title/course 길이 초과 |
| 400 | `INVALID_AUDIO_FILE` | 디코딩 불가 |
| 400 | `AUDIO_TOO_SHORT` / `AUDIO_TOO_LONG` | 1초 이하 / 240분 초과 |
| 413 | `FILE_TOO_LARGE` | 500MB 초과 |
| 415 | `UNSUPPORTED_AUDIO_FORMAT` | 실제 형식이 허용 목록 외 |
| 507 | `INSUFFICIENT_DISK_SPACE` | 여유 공간 1GB 미만 |
| 500 | `INTERNAL_ERROR` | 저장 실패 (레코드·파일 모두 롤백) |

---

#### ② POST `/api/v1/sessions/{id}/process` — 전사 + 요약 실행

**Request Body** (전부 선택)
```json
{ "sttModel": "large-v3-turbo", "llmProvider": "ollama", "skipSummary": false }
```

**Response 202 Accepted**
```json
{ "sessionId": "3f2a1b90-...", "status": "TRANSCRIBING", "pollAfterSeconds": 10 }
```
> **202인 이유**: 전사는 수 분이 걸린다. 동기 응답으로 만들면 타임아웃이 나고 UI가 멈춘다.
> 접수만 하고 ③으로 폴링한다.

| Status | code | 조건 |
|--------|------|------|
| 404 | `SESSION_NOT_FOUND` | 없는 id |
| 409 | `INVALID_SESSION_STATE` | 이미 `TRANSCRIBING`/`SUMMARIZING` 진행 중 |
| 503 | `STT_MODEL_UNAVAILABLE` | 모델 다운로드/로드 실패 |

---

#### ③ GET `/api/v1/sessions/{id}` — 세션 상세

**Response 200 OK (DONE)**
```json
{
  "sessionId": "3f2a1b90-...",
  "title": "자료구조 7주차",
  "course": "자료구조",
  "status": "DONE",
  "durationSeconds": 3612.4,
  "recordedAt": "2026-08-20T09:00:00Z",
  "transcript": {
    "available": true,
    "provider": "local_whisper",
    "providerModel": "large-v3-turbo",
    "characterCount": 18420,
    "elapsedSeconds": 412.7
  },
  "summary": {
    "summaryId": "b1c2d3e4-...",
    "contentMarkdown": "## 한 줄 요약\n이진 탐색 트리의 구조와 순회 방식...",
    "keyPoints": [
      { "text": "BST 삽입/탐색은 평균 O(log n), 최악 O(n)", "atSeconds": 420.0 }
    ],
    "concepts": [
      { "term": "중위 순회", "description": "왼쪽 → 루트 → 오른쪽 순회. BST에서 정렬된 순서를 얻는다." }
    ],
    "codeSnippets": [
      { "language": "python", "code": "def inorder(node):\n    ...", "description": "중위 순회 재귀 구현" }
    ],
    "actionItems": [ { "text": "과제 3번 제출", "dueDate": "2026-08-27" } ],
    "keywords": ["이진 탐색 트리", "중위 순회", "시간 복잡도"],
    "provider": "ollama",
    "providerModel": "qwen3:14b",
    "createdAt": "2026-08-20T10:12:00Z"
  }
}
```

**Response 200 OK (처리 중)**
```json
{
  "sessionId": "3f2a1b90-...",
  "status": "TRANSCRIBING",
  "progress": { "stage": "TRANSCRIBING", "percent": 42.5, "etaSeconds": 260 },
  "transcript": { "available": false },
  "summary": null,
  "pollAfterSeconds": 10
}
```

**Response 200 OK (FAILED)**
```json
{
  "sessionId": "3f2a1b90-...",
  "status": "FAILED",
  "errorCode": "LLM_QUOTA_EXCEEDED",
  "errorMessage": "요약 API 사용 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
  "transcript": { "available": true, "characterCount": 18420 },
  "summary": null
}
```
> **FAILED여도 HTTP는 200이다.** 조회 자체는 성공했다. 처리 실패는 body의 `status`로 표현한다.
> 여기서 4xx/5xx를 내면 클라이언트가 "조회 실패"와 "처리 실패"를 구분할 수 없다.

| Status | code | 조건 |
|--------|------|------|
| 404 | `SESSION_NOT_FOUND` | 없는 id |

---

#### ④ GET `/api/v1/sessions/{id}/transcript`

**Query**: `corrected` (boolean, 기본 `true`) — 용어집 보정본 / 원본 선택

**Response 200 OK**
```json
{
  "sessionId": "3f2a1b90-...",
  "language": "ko",
  "corrected": true,
  "text": "오늘은 이진 탐색 트리에 대해 알아보겠습니다...",
  "segments": [
    { "seq": 0, "startSeconds": 0.0, "endSeconds": 5.2, "text": "오늘은 이진 탐색 트리에 대해 알아보겠습니다." },
    { "seq": 1, "startSeconds": 5.2, "endSeconds": 11.8, "text": "먼저 삽입 연산부터 보겠습니다." }
  ]
}
```

| Status | code | 조건 |
|--------|------|------|
| 404 | `SESSION_NOT_FOUND` | 없는 id |
| 409 | `TRANSCRIPT_NOT_READY` | 전사 미완료 |

---

#### ⑤ GET `/api/v1/sessions` — 목록 (P1)

**Query**: `course`(선택), `status`(선택), `page`(기본 1, ≥1), `size`(기본 20, 1~100)

**Response 200 OK**
```json
{
  "items": [
    {
      "sessionId": "3f2a1b90-...",
      "title": "자료구조 7주차",
      "course": "자료구조",
      "status": "DONE",
      "durationSeconds": 3612.4,
      "recordedAt": "2026-08-20T09:00:00Z",
      "summaryPreview": "이진 탐색 트리의 구조와 순회 방식을 다룸..."
    }
  ],
  "page": 1, "size": 20, "totalCount": 1, "totalPages": 1
}
```
- `summaryPreview`는 최대 200자. **전체 전사/요약 본문을 목록에 싣지 않는다** — 응답이 수 MB가 된다.

| Status | code | 조건 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | page/size 범위 위반, 정의되지 않은 status |

---

#### ⑥ POST `/api/v1/sessions/{id}/summarize` — 재요약 (P1)

**Request Body**: `{ "llmProvider": "gemini" }` (선택)

**Response 202 Accepted**
```json
{ "sessionId": "3f2a1b90-...", "status": "SUMMARIZING", "pollAfterSeconds": 5 }
```

| Status | code | 조건 |
|--------|------|------|
| 404 | `SESSION_NOT_FOUND` | 없는 id |
| 409 | `TRANSCRIPT_NOT_READY` | 전사 결과 없음 |
| 409 | `INVALID_SESSION_STATE` | 이미 `SUMMARIZING` 진행 중 |
| 503 | `LLM_NOT_CONFIGURED` | Ollama 미기동 / API 키 미설정 |

---

#### ⑦ GET `/api/v1/sessions/{id}/export` — 내보내기 (P1)

**Query**: `format` — `md`(기본) / `txt` / `srt`

| format | Content-Type | 내용 |
|--------|--------------|------|
| `md` | `text/markdown; charset=utf-8` | 메타데이터 + 요약 + 전사 전문 |
| `txt` | `text/plain; charset=utf-8` | 전사 전문 |
| `srt` | `application/x-subrip; charset=utf-8` | 세그먼트 자막 |

- `Content-Disposition: attachment; filename="2026-08-20_자료구조_7주차.md"`
- 파일명에 경로 구분자·제어문자가 들어가지 않도록 **정규화(sanitize)** 한다.

| Status | code | 조건 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | 허용 목록 외 format |
| 404 | `SESSION_NOT_FOUND` | 없는 id |
| 409 | `TRANSCRIPT_NOT_READY` | 전사 미완료 |

---

#### ⑧ DELETE `/api/v1/sessions/{id}` — 삭제 (P1)

**Response 204 No Content**

| Status | code | 조건 |
|--------|------|------|
| 404 | `SESSION_NOT_FOUND` | 없는 id |
| 409 | `INVALID_SESSION_STATE` | `TRANSCRIBING`/`SUMMARIZING` 진행 중 |

---

#### ⑨ GET `/api/v1/search` — 검색 (P1)

**Query**: `q`(필수, 2자 이상), `course`(선택), `limit`(기본 20, 최대 100)

**Response 200 OK**
```json
{
  "query": "이진 탐색",
  "results": [
    {
      "sessionId": "3f2a1b90-...",
      "title": "자료구조 7주차",
      "course": "자료구조",
      "recordedAt": "2026-08-20T09:00:00Z",
      "matchedIn": "TRANSCRIPT",
      "snippet": "...오늘은 이진 탐색 트리에 대해 알아보겠습니다...",
      "atSeconds": 12.4
    }
  ],
  "totalCount": 1
}
```

| Status | code | 조건 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | `q` 누락 또는 2자 미만 |

---

#### ⑩ 용어집 (P1)

| Method | Path | Request | Response |
|--------|------|---------|----------|
| GET | `/api/v1/glossary?course=자료구조` | - | `{ "items": [{ "id":1, "term":"PostgreSQL", "aliases":["포스트그레"], "course":null }] }` 200 |
| POST | `/api/v1/glossary` | `{ "term":"PostgreSQL", "aliases":["포스트그레"], "course":null }` | 201 생성된 항목 |
| DELETE | `/api/v1/glossary/{id}` | - | 204 |

| Status | code | 조건 |
|--------|------|------|
| 400 | `VALIDATION_ERROR` | `term` 누락/길이 초과, `aliases`가 배열이 아님 |
| 404 | `SESSION_NOT_FOUND`(재사용 대신 `NOT_FOUND`) | 없는 용어 id |

---

#### ⑫ GET `/health` — 환경 점검 (기존 확장)

**Response 200 OK**
```json
{
  "status": "ok",
  "checks": {
    "database": { "ok": true },
    "diskFreeBytes": { "ok": true, "value": 8589934592 },
    "stt": { "ok": true, "provider": "local_whisper", "model": "large-v3-turbo", "modelCached": true },
    "llm": { "ok": true, "provider": "ollama", "model": "qwen3:14b", "configured": true, "reachable": true },
    "offlineMode": true,
    "bindHost": "127.0.0.1"
  }
}
```
- 하나라도 실패면 `status: "degraded"`이되 **HTTP는 200** (점검 조회 자체는 성공).
- **API 키 값을 절대 반환하지 않는다.** 설정 여부(`configured`)만 노출한다.

---

## 6. 비기능 요구사항 (NFR)

| 구분 | 요구사항 |
|------|----------|
| 비용 | **월 0원.** 유료 API 없이 전 파이프라인이 동작하는 경로가 항상 존재 |
| 성능 | 업로드 응답 p95 < 3s(500MB 기준), 세션 조회 p95 < 200ms, 목록/검색 p95 < 500ms |
| 성능 | 60분 강의 전체 처리: 로컬 20분 / 무료 티어 5분 이내 (**T-15에서 실측 후 확정**) |
| 메모리 | 500MB 업로드 시에도 스트리밍 처리로 메모리 사용량이 파일 크기에 비례하지 않을 것 |
| 모델 | Whisper 모델은 프로세스 내 1회 로드 후 재사용 (요청마다 재로딩 금지) |
| 오프라인 | 로컬 모드에서 네트워크 없이 전 기능 동작 (모델 최초 다운로드 제외) |
| 보안 | `127.0.0.1` 바인딩 강제. `0.0.0.0` 설정 시 기동 거부 |
| 보안 | API 키는 환경변수로만 로드. 로그·응답·내보내기 파일에 미포함 |
| 보안 | 저장 경로는 서버 생성 UUID 기반. 사용자 입력이 파일 경로에 반영되지 않을 것 |
| 프라이버시 | 오프라인 모드 시 외부 네트워크 요청 0건임을 테스트로 검증 |
| 프라이버시 | 로그에 전사·요약 본문 미기록 (길이·소요 시간만) |
| 이식성 | DB 스키마는 dialect 중립 (SQLite / PostgreSQL 양쪽 동작) |
| 테스트성 | 전체 스위트가 **외부 API 미호출 + 실제 모델 미로드**로 수 초 내 완료 |
| 관측성 | 단계별 소요 시간·모델·오디오 길이를 requestId·sessionId와 함께 구조화 로깅 |
| 설치성 | README의 절차 + `/health` 통과로 사용 준비 완료 |

---

## 7. Task 분해

우선순위: **P0 = 없으면 도구가 성립 안 됨**, **P1 = 실사용에 필요**, **P2 = 이후 개선**
TDD 흐름(tester가 red 작성 → implementer가 green)을 전제로 한다.

### 그룹 A. 기반 (P0)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-01 | 엔진 사양 재확인 + 의존성 확정 (faster-whisper / Ollama 모델 / 무료 티어 쿼터) | - | backend | 2026-08 기준 공식 문서로 모델명·쿼터·설치법 확인. 결정 사항을 본 문서 §0에 갱신 기록 |
| T-02 | 설정 확장 (`config.py`) — STT/LLM provider·모델, 저장 경로, 임계값, BIND_HOST | T-01 | backend | 모든 값이 하드코딩 없이 환경변수에서 로드. `.env.example` 갱신. **API 키가 로그에 안 찍힘** |
| T-03 | 공통 에러 체계 (`core/errors.py`) — AppError + §5.1 코드 전체 + 전역 핸들러 + requestId | - | backend | 17개 코드가 지정 HTTP status로 직렬화. 스택트레이스가 클라이언트로 새지 않음. 모든 응답에 requestId |
| T-04 | ORM 모델 4종 + Alembic 마이그레이션 (dialect 중립) | T-02 | backend | §2.3 전 테이블 생성/롤백 동작. **SQLite와 PostgreSQL 양쪽에서 마이그레이션 성공**. FK CASCADE·UNIQUE 확인 |
| T-05 | 테스트 하니스 확장 (Fake Provider 픽스처, 오디오 픽스처) | T-04 | tester | 기존 conftest 픽스처 재사용. Fake STT/LLM 주입 가능. 정상/위장/손상/긴 오디오 픽스처 준비(대용량은 런타임 생성) |
| T-06 | `127.0.0.1` 바인딩 강제 + CORS 제한 | T-02 | backend | US-11 통과. `0.0.0.0` 설정 시 기동 거부. localhost 외 origin의 CORS 요청 차단 |

### 그룹 B. 오디오 입력 (P0)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-07 | 오디오 검증 유틸 (매직 넘버 형식 판별·길이 추출·무결성) | T-02 | backend | §3.1 규칙 단위 테스트 통과. **확장자 위장 파일 탐지**(US-07). 디코딩 불가 파일 거부 |
| T-08 | 스트리밍 업로드 저장 (UUID 경로, 용량 누적 검사, 디스크 체크) | T-07, T-04 | backend | 500MB 파일 업로드 시 메모리 사용량이 파일 크기에 비례하지 않음. 경로 순회 차단 테스트 통과 |
| T-09 | `POST /sessions` 구현 | T-08, T-03 | backend | US-01, US-06, US-07 통과. 검증 실패 시 파일 미저장·세션 미생성. 저장 실패 시 레코드·파일 모두 롤백 |

### 그룹 C. 전사 (P0)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-10 | `SttProvider` 인터페이스 + Fake 구현 | T-02 | backend | 인터페이스 확정. Fake로 성공/실패/타임아웃/진행률을 결정론적으로 재현. **테스트가 실제 모델 미로드** |
| T-11 | 로컬 Whisper 구현체 (지연 로딩·캐시·VAD·진행률) | T-10, T-01 | backend | 실제 오디오 전사 성공. 모델이 프로세스 내 1회만 로드됨. 최초 다운로드 진행률 노출. `data/models/` 캐시 재사용 |
| T-12 | 전사 실행 + 세그먼트 저장 + 상태 전이 | T-10, T-04 | backend | US-04 통과. `UPLOADED→TRANSCRIBING→TRANSCRIBED/FAILED` 전이 검증. 세그먼트 시각이 단조 증가·비중첩 |
| T-13 | `GET /sessions/{id}` + `GET /sessions/{id}/transcript` | T-12, T-03 | backend | US-03 통과. 처리 중 progress 반환, **FAILED도 HTTP 200**. 전사 미완료 시 409 |

### 그룹 D. 요약 (P0)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-14 | `LlmProvider` 인터페이스 + Fake 구현 | T-02 | backend | 인터페이스 확정. Fake로 정상/429/타임아웃/형식위반 재현 가능 |
| T-15 | **성능 벤치마크 및 모델 확정** | T-11, T-17 | tester | 실제 60분 강의로 단계별 소요 시간 실측. §1.3 목표 대비 결과 기록. 미달 시 모델 다운그레이드/무료 티어 전환 **결정을 문서화** |
| T-16 | 요약 프롬프트 + 출력 스키마 파싱 | T-14 | backend | US-05 통과. 6개 섹션 항상 존재. 형식 위반 시 1회 재요청 후 `LLM_INVALID_RESPONSE`. **깨진 요약을 저장하지 않음** |
| T-17 | 로컬 Ollama 구현체 (기본 경로) | T-14, T-01 | backend | US-09 통과. Ollama 미기동 시 `LLM_NOT_CONFIGURED`. 네트워크 차단 상태에서 요약 성공 |
| T-18 | 요약 실행 + 상태 전이 + **전사 보존** | T-16, T-12 | backend | US-08 통과. 요약 실패해도 transcripts 온전. 429/5xx만 최대 3회 백오프 |
| T-19 | 파이프라인 오케스트레이션 + `POST /sessions/{id}/process` | T-12, T-18 | backend | US-02 통과. 202 즉시 응답. 전사→요약 자동 연결. 진행 중 중복 실행은 409 |
| T-20 | 복구 스윕 (기동 시 + 30분 초과) | T-19 | backend | US-10 통과. 중단된 세션이 `FAILED(INTERRUPTED)`로 전이. 전사가 있으면 요약부터 재개 가능 |

### 그룹 E. 실사용 기능 (P1)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-21 | map-reduce 긴 전사 요약 | T-16 | backend | US-12 통과. 오버랩 분할·순차 호출·간격 유지. 180분 전사의 전·후반이 모두 최종 요약에 반영 |
| T-22 | 용어집 CRUD + 기본 용어 100개 시드 | T-04 | backend | 추가/조회/삭제 동작. 초기 마이그레이션 시 기본 용어집이 채워짐 |
| T-23 | 용어 보정 (프롬프트 바이어싱 + 경계 안전 치환) | T-22, T-11 | backend | US-13 통과. 원본·보정본 동시 보존. 과잉 치환 차단. 긴 별칭 우선 매칭 |
| T-24 | `GET /sessions` 목록 + `DELETE /sessions/{id}` | T-13 | backend | US-14, US-18 통과. 목록에 본문 미포함. 삭제 시 오디오 파일까지 제거. 처리 중 삭제는 409 |
| T-25 | `POST /sessions/{id}/summarize` 재요약 | T-18 | backend | US-17 통과. 전사 재실행 없음. 기존 요약 보존, 최신 요약 기본 표시 |
| T-26 | 검색 (`GET /search`) | T-24 | backend | US-15 통과. 전사·요약 모두 대상. 스니펫·타임스탬프 반환. 2자 미만 400 |
| T-27 | 내보내기 (md/txt/srt) | T-13 | backend | US-16 통과. SRT 타임코드 규격 정확. 파일명 sanitize |
| T-28 | `/health` 확장 + 구조화 로깅 | T-11, T-17 | backend | ⑫ 응답 스키마대로 동작. **API 키 미노출**. 전사/요약 본문이 로그에 없음을 테스트로 확인 |
| T-29 | (선택) 무료 티어 STT/LLM 구현체 | T-10, T-14 | backend | 설정 변경만으로 로컬↔클라우드 전환. 키 미설정 시 명확한 오류. `[T-15 결과에 따라 생략 가능]` |

### 그룹 F. 프론트엔드 (P1~P2)

| ID | Task | 우선 | 의존 | 담당 | Definition of Done |
|----|------|------|------|------|--------------------|
| T-30 | 프론트 초기화 + API 클라이언트 + 라우팅 | P1 | T-09 | frontend | 로컬에서 빌드·실행. API base URL 환경변수화. 에러 응답 → 화면 메시지 매핑 |
| T-31 | 메인 화면 (드래그앤드롭 업로드 + 세션 목록 + 폴링) | P1 | T-30, T-24 | frontend | US-20 통과. 클라이언트 사전 검증, 진행률 표시, 중복 제출 차단, 처리 중 자동 갱신, 실패 시 재시도 버튼 |
| T-32 | 브라우저 녹음 (MediaRecorder) | P1 | T-31 | frontend | US-19 통과. 권한 요청/거부 처리. 경과 시간 표시. 종료 시 자동 업로드 |
| T-33 | 세션 상세 화면 (요약/전사 탭, 오디오 점프, 다운로드) | P2 | T-31, T-27 | frontend | US-21 통과. 세그먼트 클릭 시 해당 시점 재생. 375/1440px 정상. 콘솔 에러 0건 |
| T-34 | 검색 화면 + 용어집 관리 + 메타데이터 편집 | P2 | T-26, T-22 | frontend | US-15 결과 표시, 용어 추가/삭제, 제목·과목 수정 반영 |

### 그룹 G. 검증 (P0~P1)

| ID | Task | 의존 | 담당 | Definition of Done |
|----|------|------|------|--------------------|
| T-35 | 핵심 시나리오 red 테스트 선작성 (US-01~US-11) | T-05 | tester | 대응 테스트 존재. 구현 전 "기능 부재"로 실패함이 로그로 확인됨 |
| T-36 | 오프라인 동작 검증 | T-17, T-11 | tester | US-09 통과. **네트워크 차단 상태에서 전 파이프라인 성공**, 외부 요청 0건 확인 |
| T-37 | 복구·중단 테스트 | T-20 | tester | US-10 통과. 처리 중 서버를 실제로 재시작한 뒤 복구 검증 |
| T-38 | 보안·프라이버시 점검 | 전체 | tester | 체크리스트: 127.0.0.1 바인딩, API 키 미노출, 로그 본문 미기록, 경로 순회 차단, 위장 파일 차단, `data/` 권한. 항목별 통과/근거 보고, 미통과는 이슈 등록 |
| T-39 | 전사 품질 평가 | T-23 | tester | 실제 수업 녹음 3회로 기술 용어 정확 표기율 측정. §1.3의 90% 목표 달성 여부 보고. 미달 시 용어집 보강 |
| T-40 | E2E (Playwright): 업로드 → 폴링 → 요약 확인 → 내보내기 | T-31, T-27 | tester | 전체 플로우가 실제 브라우저에서 통과. 콘솔 에러·실패 네트워크 요청 0건 |
| T-41 | 실사용 리허설 | T-31 | tester/사용자 | 실제 수업 1회를 처음부터 끝까지 도구로 처리. 수동 조작 횟수와 마찰 지점 기록 → 개선 항목 도출 |

### 그룹 H. 이후 개선 (P2)
- **F-1**: 실시간 라이브 전사 (녹음과 동시에 자막 표시)
- **F-2**: 화자 분리 (교수/학생 구분)
- **F-3**: 슬라이드 화면 캡처 + OCR 연계
- **F-4**: 시스템 오디오 캡처 (온라인 강의, macOS 가상 오디오 장치) `[A3이 틀리면 P1로 상향]`
- **F-5**: 대용량 파일 분할 업로드 (무료 티어 STT의 25MB 제한 대응)
- **F-6**: SQLite FTS5 전문 검색으로 교체
- **F-7**: 과목별 누적 지식 노트 (여러 회차 요약 통합)
- **F-8**: 복습 퀴즈 자동 생성
- **F-9**: Obsidian/Notion 내보내기 연동
- **F-10**: 전사 완료 후 오디오 자동 정리 정책 (디스크 절약)

### 7.1 권장 구현 순서
```
1) T-01 → T-02 → T-03 → T-04 → T-05 → T-06        (기반)
2) T-35(red)                                       (테스트 선작성)
3) T-07 → T-08 → T-09                              (업로드)
4) T-10 → T-12 → T-14 → T-16 → T-18 → T-19         (Fake로 파이프라인 전체 완성)
5) T-11 → T-17 → T-15                              (실제 엔진 연결 + 성능 실측 ★분기점)
6) T-13 → T-20 → T-36 → T-37                       (조회·복구·오프라인 검증)
7) T-22 → T-23 → T-21 → T-24 → T-25 → T-26 → T-27  (실사용 기능)
8) T-30 → T-31 → T-32                              (화면)
9) T-28 → T-38 → T-39 → T-40 → T-41                (품질·보안·리허설)
10) T-33 → T-34 → T-29 → F-*                       (이후)
```

**왜 이 순서인가**
- **Fake Provider로 파이프라인을 먼저 완성**(4단계)한다. 실제 Whisper 모델 로딩은 느리고 무겁다.
  Fake로 전체 흐름을 끝내두면 테스트가 몇 초 만에 돌고, 엔진 교체도 자유로워진다.
- **T-15(벤치마크)가 이 프로젝트의 분기점**이다. 여기서 "로컬이 너무 느리다"가 드러나면 모델을
  낮추거나 무료 티어(T-29)로 전환해야 한다. **UI까지 만든 뒤에 알게 되면 늦는다.**
- **오프라인 검증(T-36)을 UI보다 먼저** 한다. 무료·프라이버시가 이 도구의 존재 이유인데,
  나중에 검증하면 이미 그 전제를 깨는 코드가 쌓여 있을 수 있다.

### 7.2 전체 기능 완료 조건 (Feature-level DoD)
- [ ] US-01 ~ US-18의 모든 시나리오에 대응하는 자동화 테스트가 존재하고 통과한다.
- [ ] E2E로 "업로드 → 처리 → 요약 확인 → 내보내기"가 한 번에 통과한다.
- [ ] 실제 수업 1회를 도구로 완주했다 (T-41).
- [ ] **월 비용이 0원**이며, 유료 API 없이 동작하는 경로가 README에 문서화되어 있다.
- [ ] **네트워크 차단 상태에서 전 파이프라인이 성공**한다 (T-36).
- [ ] 전체 테스트 스위트가 외부 API를 호출하지 않고 실제 모델을 로드하지 않는다.
- [ ] 요약이 실패해도 전사가 보존됨을 테스트로 확인했다.
- [ ] API 키가 로그·응답·내보내기 파일 어디에도 나타나지 않는다.
- [ ] 서버가 `127.0.0.1` 외부로 노출되지 않으며, `0.0.0.0` 설정 시 기동을 거부한다.
- [ ] 마이그레이션이 SQLite와 PostgreSQL 양쪽에서 동작한다.
- [ ] `/health`가 모든 항목 통과를 보고한다.
- [ ] README에 설치·모델 준비·실행·문제 해결 절차가 기재되어 있다.

---

## 8. 리스크

| 리스크 | 영향 | 대응 |
|--------|------|------|
| **로컬 전사가 너무 느림** (60분 강의에 1시간 이상) | 도구를 안 쓰게 됨 — 프로젝트 실패 | T-15에서 조기 실측. 미달 시 `turbo`→`medium`→`small` 다운그레이드, 또는 Groq 무료 티어(T-29) 전환 |
| **하드웨어 가정(A1) 오류** — RAM 부족/Intel Mac | 로컬 모델 구동 불가 | T-01/T-15에서 즉시 드러남. 무료 티어 경로로 전환 (어댑터 구조라 코드 변경 최소) |
| **무료 티어의 갑작스러운 축소/중단** | 요약 기능 정지 | 로컬 Ollama를 **기본 경로**로 유지. 무료 티어는 어디까지나 옵션 |
| **LLM 요약의 환각·과제 누락** | 잘못된 복습, 마감 놓침 | 핵심 주제에 타임스탬프 병기해 원문 대조 가능하게. 과제 섹션 프롬프트 강제. **요약을 원문의 대체가 아닌 색인으로 취급** |
| **기술 용어 오인식으로 전사 품질 저하** | 요약 품질까지 연쇄 하락 | 2단계 보정(T-23), 기본 용어 100개 시드, T-39에서 정량 측정 |
| **강의 녹음의 프라이버시** (교수·타 수강생 음성) | 법적·윤리 문제 | 오프라인 모드 상시 제공(§3.7). 녹음 허용 여부는 **사용자 책임**임을 README에 명시 `[A2]` |
| **BackgroundTasks 유실** (서버 재시작) | 처리 중 작업 증발 | 복구 스윕(T-20) 필수. 실제 재시작 테스트(T-37). 규모가 커지면 큐 도입 검토 |
| **디스크 용량 잠식** (60분 m4a ≈ 55MB, 원본 보관 누적) | 저장 공간 부족 | 업로드 전 여유 공간 검사. 자동 정리 정책은 F-10에서 검토 |
| **500MB 업로드 메모리 초과** | 서버 크래시 | 스트리밍 저장(T-08)을 P0에 배치하고 테스트로 검증 |
| 조사한 모델·쿼터·가격이 착수 시점과 다름 | 구현 실패 | T-01에서 공식 문서로 재확인 후 §0 갱신 |

---

## 9. 승인 요청

이 문서대로 진행해도 되는지 확인 부탁드립니다. **변경을 원하면 §0의 번호(D1~D12) 또는
§0.1의 가정 번호(A1~A5)로 알려주시면** 해당 부분만 수정합니다.

특히 확인해주시면 좋은 3가지:
1. **D1/D2** — P0을 "파일 업로드"로, 브라우저 녹음을 P1로 둔 순서가 괜찮은지
2. **D5** — 요약을 로컬 Ollama 기본으로 할지, 무료 티어 API(Gemini/Groq) 기본으로 할지
3. **A1** — 사용 중인 Mac의 칩(Apple Silicon 여부)과 RAM. **로컬 모델 크기 결정에 직결**됩니다

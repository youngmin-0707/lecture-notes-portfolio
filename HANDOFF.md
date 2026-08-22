# 인수인계 — `lecture-notes` (2026-08-22~23 연속 세션 갱신)

이 문서는 다음 세션(사람이든 새 Claude Code 세션이든)이 이어받을 때 참고할 현재 상태 요약이다.
전체 요구사항은 `/Users/son/개발/연습장/docs/requirements/stt-transcription.md`가 원본이며,
이 문서는 그 문서의 "지금 어디까지 됐는가"만 다룬다. **백엔드(`backend/`)와 프론트엔드
(`frontend/`)는 별도 git 저장소다** — 각자 `git log`로 확인할 것.

## -2. 2026-08-23 갱신 (T-34 검색 화면 + T-38 보안 체크리스트 보고서)

- **T-34 완료 (그룹 F 마지막 항목)**: 검색 화면(US-15) + 용어집 관리(§5.3⑨/⑩) +
  세션 메타데이터(제목/과목) 인라인 편집을 프론트에 붙였다. `frontend/src/pages/search.ts`가
  더 이상 placeholder가 아니다. 실제 브라우저(Playwright MCP)로 검색 결과 스니펫/타임코드,
  용어집 추가·삭제, 2자 미만 검색어의 HTML5 네이티브 검증(`minlength`), 375px 모바일 레이아웃,
  콘솔 에러 0건까지 확인했고 T-40 E2E도 재실행해 회귀 없음을 확인했다.
  - **진행 중 백엔드에 실제로 빠져 있던 것 발견**: 프론트 `api/sessions.ts`가 예전부터
    `PATCH /sessions/{id}`를 호출하고 있었는데 백엔드에 그 라우트 자체가 없었다. `app/schemas/
    session.py`에 `UpdateSessionRequest`, `app/api/v1/sessions.py`에
    `update_session_metadata` 라우트를 추가해 해결(제목/과목 부분 업데이트, 처리 중에도 허용,
    GET 상세와 동일한 응답 구조). 테스트 10개 신규(`tests/test_sessions_update_api.py`).
  - 이 작업으로 `formatTimestamp`/`formatDuration`/`formatDate`/`STATUS_LABELS`/
    `PROCESSING_STATUSES`를 `frontend/src/utils/format.ts`·`utils/status.ts`로 뽑아
    `home.ts`/`sessionDetail.ts`/`search.ts` 세 페이지가 공유하도록 정리했다(중복 제거).
- **T-38 마무리 완료**: 체크리스트 6개 항목(127.0.0.1 바인딩, API 키 미노출, 로그 본문 미기록,
  경로 순회 차단, 위장 파일 차단, `data/` 권한) 전부 통과/근거를 정리한 공식 보고서를
  `backend/SECURITY_REVIEW.md`로 작성했다. 관련 테스트 50개를 이 세션에서 재실행해 전부
  통과 확인. 미통과 항목 없음 — 신규 이슈 등록 없음.
- **의도적으로 보류한 것 (사용자 명시적 지시)**:
  - **T-39(용어 정확도 측정)**: 실제 수업 녹음 2회분이 아직 없어서 다음으로 미룸.
  - **T-41(실사용 리허설)**: 사용자가 직접 테스트하기로 함 — 손대지 말 것.
- 테스트: 백엔드 **331 passed / 4 skipped** (T-34 선행 PATCH 작업으로 321→331), 프론트는
  기존 6 passed(vitest) + 1 E2E passed(playwright) 유지, 회귀 없음.

## -1. 2026-08-23 갱신 (그룹 E 마무리 + 그룹 G 일부 + 프론트 시작)

- **그룹 E(P1) 전부 완료**: T-24(세션 목록/삭제) → T-25(재요약) → T-26(검색) →
  T-27(내보내기) → T-28(`/health` 확장) 순서로 구현. T-29(무료 티어 어댑터)는 **의도적으로
  건너뜀** — 사용자가 "선택사항은 제외하고 우선순위 작업만" 진행하라고 명시함. 로컬 경로가
  이미 성능 목표를 만족해 필요성도 낮다(§1 T-15 실측 참고).
- **T-38(보안 점검) 진행 중 실제 취약점 발견·수정**: `data/` 디렉토리가 0755, DB 파일이
  0644(월드 리더블)로 새고 있었다 — 다른 로컬 계정이 강의 데이터를 읽을 수 있는 상태였다.
  `app/core/fs.py`로 통일해 고침 (커밋 `f56a6f9`). 체크리스트 전체 항목별 통과/근거를 담은
  공식 보고서는 **아직 안 만들었음** — 다음 세션에서 마저 정리할 것(§3 참고).
- **T-36(오프라인 동작 검증) 진행 중 실제 오프라인 위반 발견·수정**: socket 레벨에서 외부
  연결을 감시하는 실통합 테스트를 처음 돌렸더니, `WhisperModel()`을 만들 때마다
  huggingface_hub이 캐시된 모델이 최신인지 확인하려고 CloudFront로 접속을 시도하고 있었다
  (4건 실측). `local_files_only=True` 우선 시도 → 캐시 없을 때만 네트워크 폴백하도록 고침
  (커밋 `ddb7bd6`). **이 클래스의 문제(써드파티 라이브러리의 숨은 네트워크 호출)는 코드
  리뷰로는 못 잡고 실제로 소켓을 감시해야만 드러난다** — 비슷한 라이브러리를 새로 붙일 때
  이 패턴(`tests/integration/test_offline_mode.py`의 `block_external_network()`)을 재사용할 것.
- **T-37(서버 재시작 복구 검증) 완료**: 실제 uvicorn 프로세스를 SIGKILL로 죽이고 재기동해
  복구되는지 확인하는 통합 테스트 추가 (커밋 `67bf960`).
- **프론트엔드 그룹 F 대부분 완료**: T-30(초기화, Vite+TS vanilla, API 클라이언트, 해시
  라우터) → T-31(메인 화면: 드래그앤드롭 업로드 + 세션 목록 + 5초 폴링 + 실패 재시도) →
  T-32(브라우저 녹음, MediaRecorder) → T-33(세션 상세: 요약/전사 탭 + 오디오 재생·탐색 +
  md/txt/srt 다운로드). 전부 실제 브라우저(Playwright)로 검증 완료. `frontend/`에 **새로
  git 저장소를 만들고** 작업 단위로 커밋함 — 이전엔 버전 관리가 전혀 안 되고 있었다.
  T-30 담당 에이전트가 계정 사용량 제한으로 한 번 중단된 적 있음(작업 자체는 재시작 후
  내가 직접 이어받아 완료) — 프론트 서브에이전트를 다시 쓸 땐 참고할 것.
- **T-33 진행 중 백엔드에 실제로 빠져 있던 것 2개 발견·수정**:
  1. **오디오 스트리밍 엔드포인트 자체가 없었다** — §5.2 원 스펙 12개 엔드포인트 중
     오디오 파일을 내려주는 경로가 아예 없어서, `<audio>` 재생이 애초에 불가능했다.
     `GET /api/v1/sessions/{id}/audio`를 새로 추가함(Starlette `FileResponse`가 Range
     요청을 자동 처리해줘서 탐색(seek)도 별도 구현 없이 됨).
  2. **CORS `expose_headers` 미설정으로 `Content-Disposition`을 프론트가 못 읽고
     있었다** — 내보내기 다운로드 파일명이 항상 "download"로만 나오는 걸 실브라우저로
     확인하다 발견. `app/main.py`의 CORSMiddleware에 `expose_headers=["Content-Disposition",
     "X-Request-Id"]` 추가로 해결.
- **T-40(E2E) 완료**: `frontend/`에 `@playwright/test`를 새로 추가했다(이전엔 프론트에
  E2E 테스트 도구가 전혀 없었음). `frontend/playwright.config.ts`가 백엔드(uvicorn)와
  프론트(vite dev) 둘 다 자동으로 띄운다 — `cd frontend && npx playwright test` 한
  줄이면 전체 스택이 뜨고 테스트가 돈다. `frontend/e2e/upload-to-export.spec.ts` 하나가
  업로드(무음 WAV를 코드로 생성) → 세션 목록 반영 → 실제 STT+LLM 처리 완료(DONE) 폴링
  대기 → 요약/전사 탭 확인 → MD 다운로드까지 실제로 통과시키고, 콘솔 에러/실패 네트워크
  요청이 0건인지 확인한다. 로컬에서 2회 연속 실행해 재현성 확인함(약 16~20초/회).
  ⚠️ vitest의 기본 include 패턴이 `*.spec.ts`와 겹쳐서 `frontend/vite.config.ts`에
  `test.exclude: ["e2e/**"]`를 추가해야 했다 — 이 설정 지우면 `npm run test`(vitest)가
  `e2e/`의 playwright 스펙을 자기 테스트로 착각해서 깨진다.
- 테스트: 백엔드 **321 passed / 4 skipped**(무거운 실제-모델/서버재시작 테스트, 명시적
  실행 필요), 프론트 **6 passed**(vitest) + **1 E2E passed**(playwright) + `npm run build`
  통과.

## 0. 2026-08-22 야간 세션에서 갱신된 내용 (요약)

- **LLM_MODEL을 계획대로 `qwen3:14b`로 복원**했다 (`ollama pull qwen3:14b` 완료, `.env`/
  `.env.example`/`app/core/config.py` 3곳 갱신). §2의 옛 "임시 하향" 서술은 더 이상 유효하지
  않다 — 지금은 원래 계획값이 기본값이다.
- **T-22 완료**: 용어집 CRUD(`GET`/`POST /api/v1/glossary`, `DELETE /api/v1/glossary/{id}`) +
  기본 용어 100개 시드 마이그레이션(`0d2fdadd5067_seed_default_glossary_terms.py`).
- **T-23 완료**: 용어집 기반 전사 보정. 전사 전 `initial_prompt` 자동 생성(session.course
  전용 + 전역 용어) + 전사 후 `text_corrected` 자동 채움(`app/glossary/correction.py`).
  **`text_corrected`가 더 이상 항상 NULL이 아니다** — §4의 옛 "항상 NULL" 서술은 이제
  틀렸다. 용어집이 비어 있으면 원본과 동일한 값이 채워진다(그래도 NULL은 아님).
  - 설계 노트: 영어식 `\b` 단어 경계를 의도적으로 안 썼다. 한국어는 조사가 공백 없이
    바로 붙어서("자바는", "자바가") `\b`를 걸면 정상 매칭까지 실패하는 걸 테스트로
    확인했다 — 대신 "긴 별칭 우선 매칭" 정렬만으로 과잉 치환을 막는다.
- 부수 발견: `tests/test_migrations.py`의 postgres 통합 테스트가 `conftest.py`의 세션
  스코프 `engine` 픽스처와 같은 DB(`TEST_DATABASE_URL`)를 공유해, 새 테스트 파일 추가로
  수집 순서가 바뀌면 서로의 테이블을 깨뜨리는 문제가 있었다. **전용 DB
  (`<원래DB이름>_migrations_test`)를 런타임에 만들어 완전히 격리**하도록 고쳤다. 앞으로
  이 파일을 건드릴 때는 이 격리 방식을 유지할 것 — 원래 DB를 다시 공유하게 되돌리면 같은
  문제가 재발한다.
- **T-21 완료**: map-reduce 긴 전사 요약(`app/llm/chunking.py` + `app/llm/map_reduce.py`).
  세그먼트를 약 4,000토큰(문자 수 근사) + 200토큰 오버랩 청크로 나눠, 청크가 2개 이상이면
  부분 요약을 순차 호출(간격 `SUMMARY_MAP_CALL_INTERVAL_SECONDS`) 후 최종 요약 1회로 합친다.
  청크가 1개면 기존과 동일한 단일 호출.
  - **부수 효과로 §5의 "미해결" atSeconds 환각 문제도 함께 해결됨** (아래 §5 참고, 실측 완료).
    전사를 평문이 아니라 `[MM:SS] 발화내용` 줄 단위로 LLM에 넘기도록 바꿨다 — 이제 청크
    분할 여부와 무관하게 **모든 요약이 이 형식을 쓴다** (단일 호출도 포함).
- 테스트: **224 passed / 1 skipped** (T-22 시작 시점 169 → 55개 순증).

## 1. 완료 상태: P0(그룹 A~D) 전부 + P1 그룹 E 전부(T-29 제외) + 그룹 G 대부분(T-34·T-36·T-37·T-38·T-40, T-39/T-41만 남음)

**백엔드** (`backend/`, 최근 순):
```
6a13903 T-34선행  PATCH /sessions/{id} 제목/과목 수정 추가
72ac42a fix      CORS expose_headers 누락으로 Content-Disposition 못 읽던 문제 (T-33 진행 중 발견)
87e99f2 T-33선행  GET /sessions/{id}/audio 스트리밍 엔드포인트 (§5.2에 없던 것, 신규 추가)
ddb7bd6 T-36     오프라인 모드 실제 위반 발견·수정 (huggingface_hub 접속 차단)
f56a6f9 T-38     data/ 디렉토리·DB 파일 권한 실제 취약점 발견·수정
67bf960 T-37     실제 서버 재시작 복구 검증 (통합 테스트)
2debb75 T-28     /health 확장 + 로그 프라이버시 검증
1f44c83 T-27     세션 내보내기 md/txt/srt
3642808 T-26     전문 검색
62f617f T-25     요약 재실행
df75585 T-24     세션 목록 조회 + 삭제
29c49f8 T-21     map-reduce 긴 전사 요약 + atSeconds 환각 문제 해결
96680fd T-23     용어집 기반 전사 보정 (프롬프트 바이어싱 + text_corrected)
4ea677e T-22     용어집 CRUD + 기본 용어 100개 시드
fe40604 chore    LLM_MODEL qwen3:8b → qwen3:14b 복원 (회선 정상화)
1d534b1 T-14~20  LlmProvider(Ollama) + 요약 오케스트레이션 + POST /process + 복구 스윕
74ed93b T-13     GET /sessions/{id}, GET /sessions/{id}/transcript
16a5696 T-12     전사 오케스트레이션 + 상태 전이
a0a5bcd T-11     로컬 faster-whisper 실제 구현체
686b0bb T-10     SttProvider 인터페이스 + Fake
096eec5 T-09     POST /sessions (업로드)
040e93e T-05~08  오디오 검증/스트리밍 저장/네트워크 바인딩
6dd876e T-01~04  기반 (설정/에러체계/ORM/마이그레이션)
```

**프론트엔드** (`frontend/`, 별도 git 저장소, 최근 순):
```
7e7e440 T-34     검색 화면 + 용어집 관리 + 메타데이터 편집
16e1732 T-40     E2E - 업로드→폴링→요약확인→내보내기 (@playwright/test 신규 도입)
cf63072 T-33     세션 상세 - 요약/전사 탭 + 오디오 재생 + 다운로드
908fae6 T-32     브라우저 녹음 (MediaRecorder)
de53abc T-31     메인 화면 - 업로드 + 세션 목록 + 폴링
1a6fb96 T-30     초기화 + API 클라이언트 + 라우팅
```

**실제 파일(`docs/녹음.m4a`, 18.3분 실사용 녹음)로 업로드→전사→요약 전체 파이프라인을 끝까지
검증 완료** (session id `008e4c1f-bbcb-4819-8927-815f2f33902a`, status `DONE`):
- 전사: 272.6초 소요 (약 4배속), 5,411자, 세그먼트 338개, "LLM"/"백엔드"/"프롬프트" 등 기술 용어 정확 인식
- 요약: `qwen3:8b`로 6개 섹션 전부 생성, 코드/과제 없는 경우 "없음" 정확히 표기 확인 (US-05)
- 60분 강의 환산 시 처리시간 17~20분대 예상 — §1.3 목표(로컬 20분 이내)에 근접
- **T-21 이후 이 세션으로 `qwen3:14b` + 새 타임코드 프롬프트로 재요약 실측 완료**: 6섹션 전부
  정상 생성, `atSeconds`가 실제 세그먼트 시각과 1~2초 오차로 일치함을 DB에서 직접 대조 확인
  (예: `atSeconds=105.0` → 실제 세그먼트 시작 98.98초). 이 세션은 청크 1개짜리(5,411자 ≈
  2,459토큰 추정 < 4,000)라 map-reduce 분기 자체는 아직 **실제 모델로는** 실측 안 됨 — 그건
  60분급 이상 실제 녹음이 있어야 자연스럽게 검증된다(T-39/T-15류 벤치마크에서 확인 권장).
  map-reduce 분기·오버랩·순차호출 로직 자체는 Fake Provider로 55개 테스트가 커버한다.

## 2. 지금 바로 알아야 할 것

- **Ollama 실행 중** (`ollama serve`, 백그라운드 nohup 프로세스, `127.0.0.1:11434`). CLI는 PATH에 없고
  `/Applications/Ollama.app/Contents/Resources/ollama` 절대경로로만 존재 — 앱 코드는 CLI가 아니라
  **HTTP API로만** 통신하도록 짜여 있다 (그대로 유지할 것).
- **LLM_MODEL은 `qwen3:14b`(원래 계획값, M4 Pro 24GB 기준 권장)로 복원 완료됨** (§0 참고).
  2026-08-22 세션 초반엔 네트워크 불안정으로 `qwen3:8b`로 임시 하향했었으나, 같은 세션 안에서
  회선이 정상화되어 `ollama pull qwen3:14b` 완료 후 복원했다. `qwen3:8b`도 로컬에 남아있으니
  (`ollama list`) 필요하면 `.env`의 `LLM_MODEL`만 바꿔 언제든 되돌릴 수 있다.
- **PostgreSQL 테스트 컨테이너가 떠 있다** (`docker compose -f docker-compose.test.yml up -d`, 포트 5433).
  테스트 실행 시 반드시 이렇게: `TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/signup_test .venv/bin/pytest`
  (⚠️ `tests/conftest.py`의 기본값은 `app_test`인데 실제 컨테이너 DB명은 `signup_test`다 — 둘이 다르다는
  걸 모르고 그냥 `pytest`만 치면 접속 실패한다. 이 불일치는 의도적으로 고치지 않고 남겨뒀다 — 원한다면
  다음 세션에서 둘 중 하나로 통일해도 됨, 지금은 동작에 지장 없음).
- **`data/lecture_notes.db`는 자동 마이그레이션이 안 된다.** 새로 체크아웃한 환경에서는
  `.venv/bin/alembic upgrade head`를 한 번 수동으로 돌려야 한다.
- 실제 검증에 쓴 테스트 서버(uvicorn, 포트 8765)는 이번 세션 종료 시 껐다. 다시 띄우려면:
  `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765`
- 검증에 썼던 세션 레코드(`008e4c1f-...`, status DONE)와 그 오디오 파일(`data/audio/36f554d2....upload`,
  27MB)이 `data/lecture_notes.db`/`data/audio/`에 그대로 남아있다. 실제 동작 증거로 남겨뒀으니 필요하면
  그대로 조회해봐도 되고, 정리하고 싶으면 지워도 무방하다 (테스트 스위트와 무관).
- **프론트를 실행하려면 백엔드와 별도로 둘 다 띄워야 한다**:
  `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765` +
  `cd frontend && npm run dev` (Vite, 기본 5173). 이 Mac에서는 `curl 127.0.0.1:5173`이
  실패하고 `curl localhost:5173`은 되는 IPv4/IPv6 바인딩 차이가 있었다 — 브라우저는 문제
  없이 열리니 `localhost`로 접속할 것.
- 프론트 검증에 쓴 dev 서버 2개는 이번 세션 종료 시 껐다(`pkill -f "uvicorn app.main:app"`,
  `pkill -f vite`). 검증용으로 만들었던 세션들도 삭제해뒀다 — `data/`에는 원래부터 있던
  `008e4c1f-...`(DONE) 1건만 남아있다.

## 3. 다음 단계 (요구사항 문서 §7 기준)

- **그룹 F 완료**: T-30~34 전부 끝남(§-2 참고). 프론트에 남은 계획된 작업 없음.
- **그룹 G 남은 것 — 이제 T-39/T-41 둘 뿐**:
  - **T-38(보안 체크리스트 보고서) 완료** — `backend/SECURITY_REVIEW.md` (§-2 참고). 6개
    항목 전부 통과, 신규 이슈 없음.
  - **T-40(E2E) 완료** — `frontend/e2e/upload-to-export.spec.ts` (§0 참고).
  - **T-39(용어 정확도 측정) — 사용자 지시로 보류 중**: 실제 수업 녹음 3회로 §1.3 목표(90%)
    측정. 지금 있는 실측 샘플은 `008e4c1f-...`(18분, 검증 세션) 1건뿐 — 나머지 2회분
    샘플이 생기면 그때 진행할 것. 다음 세션에서 먼저 나서서 시작하지 말 것(사용자가
    "다음으로 미루자"라고 명시함, 2026-08-23).
  - **T-41(실사용 리허설) — 사용자가 직접 진행**: "내가 직접 테스트해볼게"라고 명시함
    (2026-08-23). Claude가 먼저 나서서 실행하지 말 것.
  - T-39 또는 별도 벤치마크 때 **60분급 실제 강의로 map-reduce 분기가 실제 트리거되는지**
    (T-21 §0 참고) 한 번 확인해두면 좋다 — 지금까지의 실측(18분·3초 샘플)은 전부 단일
    청크였다.

## 4. 알려진 트레이드오프 / 기술 부채 (의도적으로 남긴 것들)

- map-reduce(T-21)의 청크 크기 판단은 **문자 수 근사치**다 (`app/llm/chunking.py`의
  `CHARS_PER_TOKEN_ESTIMATE = 2.2`) — qwen3 전용 토크나이저를 붙이지 않았다. "약 4,000토큰"
  요구사항 자체가 근사치라 실용적으로는 충분하지만, 정확한 토큰 수가 필요해지면 이 상수부터
  재검토할 것.
- reduce 단계 입력(부분 요약들을 합친 텍스트)이 그 자체로 다시 컨텍스트를 넘길 수 있는 극단적
  케이스(청크가 아주 많은 초장시간 강의)는 재귀적 map-reduce 없이 단일 reduce 호출로 처리한다
  — 요구사항이 요구하는 범위(240분 상한)에서는 충분하다고 판단했으나 실측은 아직 없음.
- `db/session.py`는 dialect 중립(SQLite/PostgreSQL) 구조로 돼 있음 — 새 쿼리 짤 때 postgres 전용
  문법(JSONB 연산자 등) 쓰지 않도록 주의.
- 용어집 API에 `PATCH`(수정)가 없다 — 요구사항(§5.3 ⑩)에도 없어서 의도적으로 뺐다. 별칭을
  고치려면 삭제 후 재생성해야 한다.
- 용어집 보정(T-23)은 `transcript_segments.text`(세그먼트별 텍스트)는 건드리지 않는다 —
  `transcripts.text_corrected`(전체 텍스트)만 보정한다. `GET .../transcript`의 `segments[]`는
  `corrected` 쿼리 파라미터와 무관하게 항상 원본 그대로 반환된다 (T-13 구현 당시부터의 기존
  동작, T-23에서 바꾸지 않았다).

## 5. 실측 중 발견한 이슈 (그룹 D 최종 보고서에서 확인, 중요)

- **[수정 완료] `BackgroundTasks` + `get_db` 교착 상태 버그**: FastAPI 0.118+부터 `yield` 의존성의
  기본 `scope`가 `"request"`로 바뀌면서, 응답 전송 후 `db.commit()`이 실행되는 시점이
  `BackgroundTasks`보다 **늦어질 수 있다.** `POST /sessions`·`POST /sessions/{id}/process`처럼
  응답 직후 같은 세션 행을 백그라운드에서 UPDATE하는 라우트에서 이게 실제로 Postgres 행 잠금 교착으로
  이어짐을 재현·확인했다. `Depends(get_db, scope="function")`로 명시해 해결함
  (`app/api/v1/sessions.py` 상단 주석에 근거 기록됨). **다음 세션에서 `BackgroundTasks`를 예약하는
  새 라우트를 추가할 때 반드시 이 패턴을 따를 것** — 안 그러면 같은 교착이 재발할 수 있다.
- **[수정 완료, T-21에서 해결] 요약의 `keyPoints[].atSeconds`가 실제 세그먼트와 대조되지 않던 문제**:
  전사를 `[MM:SS] 발화내용` 형식의 줄 단위로 LLM에 넘기고, 프롬프트에 "atSeconds는 그 줄의
  타임코드에서 그대로 읽어라, 추정하지 마라"를 명시하도록 바꿨다(위 §0 (a)안 채택). 실제
  qwen3:14b로 재요약해 `atSeconds`가 실제 세그먼트 시각과 1~2초 오차로 일치함을 확인했다
  (§1의 실측 기록 참고).
- **[확인됨, 이슈 아님] `OLLAMA_KEEP_ALIVE=30s`가 실제로 동작한다**: 요약 완료 후 `/api/ps`가 빈
  목록을 반환 — 모델이 메모리에서 바로 풀림 (§0 D13 "멀티태스크 제약 없음" 요구사항 충족 확인).
- 60분급 실제 강의로는 아직 T-15 벤치마크를 안 돌려봤다 (18분 샘플만 실측). 원문서 추정대로면
  60분 강의 전사량이 1.5만~2.5만 토큰이라 단일 호출로는 `OLLAMA_NUM_CTX=8192`가 빠듯할 수
  있었는데, **T-21(map-reduce) 완료로 이 문제는 구조적으로 해소됐다** — 전사가
  `SUMMARY_CHUNK_SIZE_TOKENS`(기본 4,000토큰 근사)를 넘으면 자동으로 청크 분할되어 각 LLM
  호출은 항상 그 크기 이하로 유지된다. 그래도 map-reduce 분기 자체가 **실제 모델로** 도는 걸
  60분급 샘플로 한 번은 봐두는 게 안전하다 (지금까지는 Fake Provider 테스트로만 검증됨).

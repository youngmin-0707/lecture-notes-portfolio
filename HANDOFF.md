# 인수인계 — `lecture-notes` 백엔드 (2026-08-22 세션, 야간 연속 세션 갱신)

이 문서는 다음 세션(사람이든 새 Claude Code 세션이든)이 이어받을 때 참고할 현재 상태 요약이다.
전체 요구사항은 `/Users/son/개발/연습장/docs/requirements/stt-transcription.md`가 원본이며,
이 문서는 그 문서의 "지금 어디까지 됐는가"만 다룬다.

## 0. 이어진 세션에서 갱신된 내용 (요약)

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
- 테스트: **196 passed / 1 skipped** (이전 169 → 27개 순증, T-22/T-23 테스트 + 회귀 테스트).

## 1. 완료 상태: P0(그룹 A~D, T-01~T-20) 전부 완료 + P1 그룹 E 일부(T-22, T-23)

```
6dd876e T-01~04  기반 (설정/에러체계/ORM/마이그레이션)
040e93e T-05~08  오디오 검증/스트리밍 저장/네트워크 바인딩
096eec5 T-09     POST /sessions (업로드)
686b0bb T-10     SttProvider 인터페이스 + Fake
1b0e93d chore    LLM_MODEL qwen3:14b → qwen3:8b (네트워크 문제로 임시 하향, §3 참고)
a0a5bcd T-11     로컬 faster-whisper 실제 구현체
16a5696 T-12     전사 오케스트레이션 + 상태 전이
74ed93b T-13     GET /sessions/{id}, GET /sessions/{id}/transcript
1d534b1 T-14~20  LlmProvider(Ollama) + 요약 오케스트레이션 + POST /process + 복구 스윕
fe40604 chore    LLM_MODEL qwen3:8b → qwen3:14b 복원 (회선 정상화)
4ea677e T-22     용어집 CRUD + 기본 용어 100개 시드
96680fd T-23     용어집 기반 전사 보정 (프롬프트 바이어싱 + text_corrected)
```

**실제 파일(`docs/녹음.m4a`, 18.3분 실사용 녹음)로 업로드→전사→요약 전체 파이프라인을 끝까지
검증 완료** (session id `008e4c1f-bbcb-4819-8927-815f2f33902a`, status `DONE`):
- 전사: 272.6초 소요 (약 4배속), 5,411자, 세그먼트 338개, "LLM"/"백엔드"/"프롬프트" 등 기술 용어 정확 인식
- 요약: `qwen3:8b`로 6개 섹션 전부 생성, 코드/과제 없는 경우 "없음" 정확히 표기 확인 (US-05)
- 60분 강의 환산 시 처리시간 17~20분대 예상 — §1.3 목표(로컬 20분 이내)에 근접

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

## 3. 다음 단계 (요구사항 문서 §7 기준)

- **그룹 E 나머지 (P1, T-21, T-24~29)**: T-22·T-23은 완료. §7.1 권장 순서상 다음은
  **T-21(map-reduce 긴 전사 요약)** → T-24(세션 목록/삭제) → T-25(재요약) → T-26(검색) →
  T-27(내보내기 md/txt/srt) → T-28(`/health` 확장) → T-29(선택, 무료 티어 어댑터).
- **그룹 F (P1~P2)**: 프론트엔드 전체 (지금까지 API만 있고 화면 없음).
- **그룹 G 나머지**: T-36(오프라인 검증), T-37(서버 재시작 복구 실측), T-38(보안 점검),
  T-39(용어 정확도 측정), T-40(E2E), T-41(실사용 리허설)은 프론트/실사용 기능이 갖춰진 뒤가 자연스럽다.

## 4. 알려진 트레이드오프 / 기술 부채 (의도적으로 남긴 것들)

- map-reduce(T-21) 미구현 — 현재는 `OLLAMA_NUM_CTX=8192`로 여유를 두는 것으로만 대응. 훨씬 긴 강의
  (60분+)에서 컨텍스트 초과 여부는 아직 실측 안 됨 — **T-21 착수 시 가장 먼저 벤치마크할 대상.**
  (18분 샘플은 5,411자로 여유 있게 들어갔다.)
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
- **[미해결] 요약의 `keyPoints[].atSeconds`가 실제 세그먼트와 대조되지 않음**: 현재 요약 프롬프트는
  세그먼트별 타임코드 없이 전사 전체를 하나의 문자열로 LLM에 넘긴다. 실행 결과 `atSeconds`가
  02:00, 05:46, 08:30…처럼 규칙적으로 나왔는데 이는 **LLM이 추정(사실상 환각)한 값**이지 실제
  세그먼트 시각이 아니다. §3.4가 명시한 "타임스탬프로 원문 대조 가능 → 환각 방어" 목적이 아직
  달성되지 않은 상태. 해결 방향: (a) 프롬프트에 `[MM:SS] 텍스트` 형식으로 세그먼트 타임코드를
  포함시키거나, (b) 응답의 `atSeconds`를 가장 가까운 실제 세그먼트 시각으로 사후 스냅(snapping)하는
  로직 추가. T-21(map-reduce)과 함께 처리하는 걸 권장.
- **[확인됨, 이슈 아님] `OLLAMA_KEEP_ALIVE=30s`가 실제로 동작한다**: 요약 완료 후 `/api/ps`가 빈
  목록을 반환 — 모델이 메모리에서 바로 풀림 (§0 D13 "멀티태스크 제약 없음" 요구사항 충족 확인).
- 60분급 실제 강의로는 아직 T-15 벤치마크를 안 돌려봤다 (18분 샘플만 실측). 원문서 추정대로면
  60분 강의 전사량이 1.5만~2.5만 토큰이라 `OLLAMA_NUM_CTX=8192`로는 빠듯할 수 있음 — 그룹 E 착수
  전에 실제 60분급 샘플로 한 번 더 확인 권장.

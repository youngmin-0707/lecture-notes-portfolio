# 인수인계 — `lecture-notes` 백엔드 (2026-08-22 세션)

이 문서는 다음 세션(사람이든 새 Claude Code 세션이든)이 이어받을 때 참고할 현재 상태 요약이다.
전체 요구사항은 `/Users/son/개발/연습장/docs/requirements/stt-transcription.md`가 원본이며,
이 문서는 그 문서의 "지금 어디까지 됐는가"만 다룬다.

## 1. 완료 상태: P0(그룹 A~D, T-01~T-20) 전부 완료

git 커밋 9개, 테스트 169 passed / 1 skipped(실제 모델 로드 테스트, 수동 실행 시 통과 확인됨).

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
- **LLM_MODEL이 `qwen3:8b`로 임시 하향돼 있다** (원래 계획은 `qwen3:14b`, M4 Pro 24GB 기준 권장값).
  2026-08-22 세션 중 네트워크가 매우 불안정해서(다운로드 도중 진행률이 리셋되는 현상 반복) 안전하게
  `qwen3:8b`로 낮췄다. **회선이 정상화되면**: `ollama pull qwen3:14b` 받은 뒤 `.env`/`.env.example`/
  `app/core/config.py` 3곳의 `LLM_MODEL` 값만 `qwen3:14b`로 바꾸면 끝 (코드 변경 없음).
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

- **그룹 E (P1, T-21~29)**: map-reduce 긴 전사 요약, 용어집 CRUD+시드 100개, 용어 보정, 세션
  목록/삭제, 재요약, 검색, 내보내기(md/txt/srt), `/health` 확장, (선택)무료 티어 어댑터.
  → §7.1 권장 순서상 T-22→T-23→T-21→T-24→T-25→T-26→T-27 순.
- **그룹 F (P1~P2)**: 프론트엔드 전체 (지금까지 API만 있고 화면 없음).
- **그룹 G 나머지**: T-36(오프라인 검증), T-37(서버 재시작 복구 실측), T-38(보안 점검),
  T-39(용어 정확도 측정), T-40(E2E), T-41(실사용 리허설)은 프론트/실사용 기능이 갖춰진 뒤가 자연스럽다.

## 4. 알려진 트레이드오프 / 기술 부채 (의도적으로 남긴 것들)

- `text_corrected`는 항상 NULL (용어집 보정은 T-23에서 구현 예정, 지금은 `GET .../transcript`가
  `corrected=true` 요청에도 `text_raw`로 폴백).
- map-reduce(T-21) 미구현 — 현재는 `OLLAMA_NUM_CTX=8192`로 여유를 두는 것으로만 대응. 훨씬 긴 강의
  (60분+)에서 컨텍스트 초과 여부는 아직 실측 안 됨 — 그룹 E 착수 시 다음 벤치마크 대상.
  (이번에 쓴 18분 샘플은 5,411자로 여유 있게 들어갔다.)
- `db/session.py`는 dialect 중립(SQLite/PostgreSQL) 구조로 돼 있음 — 새 쿼리 짤 때 postgres 전용
  문법(JSONB 연산자 등) 쓰지 않도록 주의.

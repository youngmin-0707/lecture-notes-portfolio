# 인수인계 — `lecture-notes` (2026-08-22~10-07 연속 세션 갱신)

## -9. 2026-10-18 갱신 (DB 백업 + 모노레포)

- **저장소**: backend/frontend 개별 git 저장소를 상위 `연습장/` 하나로 합쳤다(기록 보존,
  `git log -- backend/`). 원래 `.git` 폴더는 `~/개발/.git-backup-연습장-20261018/`에 보관.
  `docs/record/`(원본 녹음)는 gitignore.
- **정기 백업**: `scripts/backup_db.py` → `app/core/backup.py::backup_sqlite`. sqlite 온라인
  백업 API + `integrity_check`. 사본은 `data/backups/`와 iCloud Drive
  `lecture-notes-backups/`에 두고 14일 지나면 삭제. launchd `com.lecturenotes.backup`
  (원본 `deploy/com.lecturenotes.backup.plist`, 매일 03:00, 로그 `logs/backup.*.log`).
- **마이그레이션 전 백업**: `alembic/env.py::_backup_before_schema_change` — CLI로
  `downgrade`는 항상, `upgrade`는 head가 아닐 때만 `-pre-migration.db` 사본을 만든다.
  백업이 실패하면 마이그레이션도 멈춘다. 테스트처럼 `command.upgrade()`를 코드로 부르면 건너뜀.
- **복구**: 백엔드를 멈추고(`launchctl bootout gui/$(id -u)/com.lecturenotes.backend`)
  사본을 `data/lecture_notes.db`로 복사한 뒤 다시 띄운다.
- **발견한 기존 버그(안 고침)**: `8f2a4c1d9b3e`(quizzes) downgrade가 SQLite에서
  `no such index: ix_quizzes_session_id`로 실패한다.

## -8. 2026-10-07 갱신 (홈 화면 세션 다중 선택: 요약 ZIP 다운로드 + 날짜 이동)

**아직 커밋 안 함.** 백엔드/프론트 모두 작업 트리에만 있음.

- **배경**: 세션이 150건 넘게 쌓여, (1) 요약을 하나씩 들어가 받지 않고 여러 개를 한 번에
  꺼내고 싶고 (2) 업로드일과 실제 수업일이 다른 세션을 실제 수업 날짜로 바로잡고 싶다는 요청.
- **백엔드 — 날짜 이동**: 기존 `PATCH /sessions/{id}`(`UpdateSessionRequest`)에
  `recordedAt`(시간대 포함 ISO8601, `AwareDatetime`) 추가. 시간대 없는 값은 400. UTC로
  정규화해 `sessions.recorded_at`에 저장한다. DB 스키마 변경 없음. 제목·`title_customized`는
  건드리지 않는다(기본 제목 "YYYY-MM-DD 수업"의 날짜도 그대로 둔다 — 의도된 결정).
- **백엔드 — ZIP 내보내기**: `POST /api/v1/sessions/export`(신규, 바디 `{sessionIds: []}`,
  1~200개). 세션별 요약 `.md`를 ZIP 하나로 준다. 단건 `md` 내보내기와 달리 **전사 전문은
  넣지 않는다**(`render_markdown_export(transcript=None)`). ZIP 안에서 파일명이 겹치면
  `이름 (2).md`로 번호를 붙인다. 없는 세션이 섞이면 `SESSION_NOT_FOUND`, 요약 없는 세션이
  섞이면 `SUMMARY_NOT_READY`로 통째로 실패(부분 ZIP을 주지 않음).
- **프론트(`home.ts`)**: DONE 세션 카드에만 체크박스. 하나 이상 고르면 선택 막대
  (`#selection-bar`: N건 선택 / 요약 ZIP 다운로드 / 옮길 날짜 + 날짜 이동 / 선택 해제)가
  뜬다. 날짜 이동은 세션마다 PATCH를 순차 호출하며, "고른 날짜 + 원래 시각"을 **브라우저
  현지 시간대**로 계산해 보낸다(`utils/date.ts::moveIsoToLocalDate`) — UTC 날짜를 그대로
  바꾸면 오전 9시(KST) 이전 세션이 하루 어긋난다. 실패한 세션만 선택에 남는다. 필터 변경
  등으로 목록에서 사라진 세션은 선택에서 자동으로 빠진다.
- **알려진 한계(기존 동작, 이번에 안 고침)**: 내보내기 파일명·`- 녹음일:` 줄과
  `date_from`/`date_to` 필터는 여전히 **UTC 날짜** 기준이다. 오전 9시(KST) 이전에 녹음된
  세션은 화면 그룹 날짜보다 하루 이른 날짜가 파일명에 찍힌다.
- 테스트: 백엔드 **465 passed / 4 skipped**(신규 `tests/test_sessions_bulk_export_api.py` 9개,
  `test_sessions_update_api.py::TestUpdateRecordedAt` 5개), 프론트 9 passed(신규
  `utils/date.test.ts` 3개) + `tsc --noEmit` + `ruff` 클린.
- 실브라우저 검증: 격리 인스턴스(8767 + 임시 SQLite, 프론트 5197)에 세션 4건을 시딩해
  체크박스가 DONE에만 뜨는지, 3건 ZIP 다운로드(파일 3개·중복 이름 번호·요약만 포함), 날짜
  미선택 시 안내, 2건 날짜 이동 후 "이전" 그룹으로 옮겨지는지까지 확인(콘솔 에러 0건).
  **운영 DB엔 검증 데이터가 들어가지 않았다.** 검증 후 운영 백엔드를 `launchctl kickstart`로
  재시작해 새 코드 반영(세션 151건 전부 DONE 상태에서 재시작).

## -7. 2026-09-14 추가 갱신 (요약 내용 직접 수정 + 세션 삭제 UI 연결)

**아직 커밋 안 함.** §-6과 같은 세션, 백엔드/프론트 모두 작업 트리에만 있음.

- **배경**: "요약한 파일 내용이 마음에 안 들면 직접 고치거나, 아예 지울 수 있게 해달라"는
  요청. 세션 삭제(`DELETE /sessions/{id}`)는 이미 T-24/US-18로 백엔드에 구현·테스트돼
  있었는데 **프론트에서 어디에도 연결돼 있지 않았다**(`deleteSession()` API 함수가 죽은
  코드였음) — 이번에 세션 상세 화면에 실제로 연결했다.
- **백엔드 — 요약 수정 (`PATCH /api/v1/sessions/{id}/summary`, 신규)**:
  `app/api/v1/sessions.py::update_summary`. 요청 바디(`UpdateSummaryRequest`)는
  `oneLineSummary`/`detailedNotesMarkdown` 둘 다 선택(부분 업데이트) — "핵심 주제"
  (`keyPoints`, 타임스탬프 포함)는 이 라우트로 건드리지 않는다(재생 시각과 묶여 있어 텍스트만
  고치면 원문과 어긋나므로 의도적으로 뺐다). 처리 중(TRANSCRIBING/SUMMARIZING)이면
  `INVALID_SESSION_STATE`, 요약 자체가 없으면 `SUMMARY_NOT_READY`(기존 §5.1 코드 재사용,
  새 에러코드 추가 없음). 재요약(LLM 재호출, `POST .../summarize`)과 달리 비용·지연 없이
  즉시 반영된다. `content_markdown`은 매번 `render_markdown()`으로 다시 조립하는데, 이때
  건드리지 않은 `oneLineSummary`의 현재 값을 알아야 해서 `app/llm/parsing.py`에
  `extract_one_line_summary()`를 새로 뽑아냈다 — 기존 `_extract_summary_preview`(목록
  미리보기)도 이 함수로 리팩터링해 로직이 두 곳에 중복되지 않게 했다.
- **프론트 — 요약 수정 UI**: `sessionDetail.ts`에 "✎ 수정" 버튼(요약 탭 상단, 처리 중일 땐
  숨김) → 인라인 편집 폼으로 전환. **처음엔 원문 마크다운만 보이는 `<textarea>` 하나였는데,
  사용자가 "화면이 통째로 바뀌는 느낌이라 보면서 고치기 어렵다"고 피드백** → 완전
  인라인(WYSIWYG, contenteditable) 편집과 실시간 미리보기 중 하나를 골라달라고 물었고(전자는
  저장 시 HTML→마크다운 역변환 과정에서 제목/목록 구조가 깨질 위험이 있어 비권장으로 제시),
  **실시간 미리보기**를 선택받아 적용했다: 본문 textarea 옆(`.summary-edit-split`, 좁은
  화면 700px 이하는 위아래로 쌓임)에 `renderMarkdown()`(기존 요약 탭이 쓰던 렌더러 그대로
  재사용)으로 즉석 렌더링한 미리보기 패널을 두고, textarea `input` 이벤트마다
  `updateSummaryEditPreview()`가 다시 그린다. 저장되는 값은 항상 순수 마크다운 그대로라
  내보내기(MD/TXT)·재조립 로직과 완전히 호환된다.
- **프론트 — 세션 삭제 UI 연결**: 세션 상세 화면 맨 아래 "danger zone"에 "세션 삭제" 버튼
  추가(`.btn--delete`, 처리 중이면 disabled). 클릭 시 `window.confirm()`으로 한 번 더
  확인(되돌릴 수 없는 동작이라 §서비스 전역에서 유일하게 confirm을 쓰는 곳) → 성공하면
  `navigate("#/")`로 홈 이동, 실패하면 버튼을 원상 복구하고 에러 메시지 표시.
- 테스트: 백엔드 신규 `tests/test_sessions_summary_edit_api.py`(12개: 404/409/검증/부분
  업데이트/keyPoints 보존/빈 바디 no-op/내보내기 반영까지) 포함 **451 passed / 4 skipped**,
  프론트 6 passed + `tsc --noEmit` + `ruff` 클린.
- 실브라우저 검증: 격리 인스턴스(8767/8768 포트 + 임시 SQLite, 프론트 5197/5198)에 세션을
  직접 시딩해 ①요약 수정 저장→API로 반영 확인, ②처리 중 상태에서 수정/삭제 버튼이 실제로
  비활성화되는지, ③실시간 미리보기가 타이핑마다 갱신되는지, ④삭제 확인 다이얼로그→실제 204
  삭제→홈 이동→`GET`이 404로 바뀌는지까지 전부 확인(콘솔 에러 0건). **운영 DB엔 검증
  데이터가 들어가지 않았다.**

## -6. 2026-09-14 갱신 (텍스트 파일 업로드 → 전사 건너뛰고 바로 요약)

**아직 커밋 안 함.** 백엔드/프론트 모두 작업 트리에만 있음.

- **배경**: 이미 텍스트로 정리된 자료(다른 도구로 뽑은 전사문, 수업 필기 등)를 그대로 올려
  요약만 받고 싶다는 요청. 오디오가 아니므로 전사(STT) 단계가 아예 필요 없다.
- **백엔드**
  - `app/text/validation.py`(신규): 텍스트 업로드 판별·디코딩·길이 검증. **오디오와 달리
    확장자를 본다** — 텍스트에는 매직 넘버가 없어 내용만으로 "텍스트다"라고 단정하면 깨진
    오디오가 조용히 텍스트로 처리된다. 확장자 화이트리스트(`txt`/`md`/`markdown`)로 진입
    조건을 정한 뒤, 내용이 실제로 디코딩되는지(utf-8-sig → cp949, 제어문자 없음) 확인하는
    2단 구조. 길이 하한/상한은 `settings.MIN_TEXT_CHARACTERS`(30) /
    `MAX_TEXT_CHARACTERS`(500,000), 용량 한도는 `MAX_TEXT_UPLOAD_SIZE_BYTES`(5MB).
  - `POST /sessions`(`app/api/v1/sessions.py`): 텍스트면 업로드 본문을 `transcripts` 1건으로
    저장(`provider="text_upload"`, 세그먼트 없음)하고 세션은 `TRANSCRIBED`에서 출발한다.
    `autoProcess=true`면 응답 status가 **`SUMMARIZING`**이고, 기존 `run_pipeline()`의
    "전사가 이미 있으면 STT 건너뜀"(§2.4) 규칙을 그대로 타고 요약만 실행된다 — 파이프라인
    쪽에는 텍스트 전용 분기를 만들지 않았다. 업로드 원본 파일은 본문이 DB에 들어간 직후 삭제
    (`audio_path=NULL`, `source="TEXT"`, `duration_seconds=NULL`, mime `text/plain|markdown`).
  - `POST /sessions/{id}/process`: 전사가 이미 있으면 응답 status를 `TRANSCRIBING`이 아니라
    `SUMMARIZING`으로 준다(실제로 하게 될 일과 화면 표시를 맞춤). 텍스트 세션 재시도 경로.
  - `SessionSource.TEXT` 추가, `GET /sessions/{id}` 응답에 `source` 필드 추가(화면이 "오디오
    없음"을 올바른 이유로 설명하기 위해). DB 스키마 변경 없음 — 마이그레이션 불필요.
  - 새 에러코드 `INVALID_TEXT_FILE`/`TEXT_TOO_SHORT`/`TEXT_TOO_LONG`(전부 400),
    `UNSUPPORTED_AUDIO_FORMAT` 문구를 "오디오 또는 텍스트"로 갱신.
  - **환각 타임스탬프 제거**(`app/pipeline/summarization.py::_drop_timestamps_without_timeline`):
    텍스트 세션은 프롬프트 전사가 "[00:00] 본문 전체" 한 줄뿐인데도 LLM이 [00:12]/[00:36]
    같은 시각을 지어내는 걸 로컬 qwen3:14b로 실제 확인했다. `source == "TEXT"`면 저장 전
    `atSeconds`를 전부 `None`으로 떨어뜨린다(세그먼트 유무가 아니라 source로 판단 — 세그먼트
    없이 텍스트만 있는 오디오 세션은 여전히 재생 시각이라는 의미가 살아 있다).
- **프론트**: 드롭존이 `txt/md/markdown`도 받고(accept + 1차 검증, 텍스트는 5MB 한도), 안내
  문구를 오디오/텍스트 2줄로 분리, 제목을 "강의 업로드"로. 업로드 성공 문구는 응답 status가
  `SUMMARIZING`이면 "요약을 시작했습니다". 상세 화면은 `source==="TEXT"`면 오디오 안내
  문구를 "텍스트 파일로 등록한 세션이라 오디오가 없습니다"로 바꾸고, 세그먼트 없는 전사는
  본문을 그대로 렌더링(`.transcript-plain`, 예전엔 "전사 세그먼트가 없습니다"만 떴다).
  `keyPoints[].atSeconds`가 `null`이면 타임스탬프 버튼을 아예 안 그린다.
- 테스트: 백엔드 **439 passed / 4 skipped**(신규 `tests/test_text_validation.py` 18개,
  `test_sessions_create_api.py::TestTextFileUpload` 8개, `test_pipeline_summarization.py::
  TestTextSessionHasNoTimestamps` 2개), 프론트 6 passed + `tsc --noEmit` + `ruff` 클린.
- 실브라우저 검증: 격리 인스턴스(포트 8766 + 임시 SQLite, 프론트 5199, LLM=로컬 ollama)로
  실제 `.txt` 업로드 → "요약을 시작했습니다" → 목록 "요약 중" → DONE → 상세 화면에서 요약/
  전사 탭·오디오 안내 문구·타임스탬프 없음까지 확인(콘솔 에러 0건). 검증 데이터는 운영 DB에
  들어가지 않았고, 검증 후 `launchctl kickstart -k gui/$(id -u)/com.lecturenotes.backend`로
  운영 백엔드를 새 코드로 재시작해 둠(세션 49건 전부 DONE 상태라 중단된 작업 없음).


## -5. 2026-09-01 갱신 (복습 키워드 섹션 제거)

**아직 커밋 안 함.** 위 §-4(2026-08-30)와 마찬가지로 작업 트리에만 있음.

- **배경**: 사용자가 실사용 중 요약 화면의 "복습 키워드" 섹션 사용률이 낮다고 판단해 제거
  요청. 기존 문서(HANDOFF.md 포함)는 소급 수정하지 않고 **앞으로 생성되는 요약부터만**
  적용하는 이 프로젝트의 기존 관례(§-3-1 오디오 자동삭제, §-3 요약 스키마 개정과 동일한
  패턴)를 그대로 따름 — 과거에 저장된 keywords 데이터·마크다운은 손대지 않았다.
- **`app/llm/prompt.py`/`app/llm/openai_provider.py`**: LLM에게 더 이상 `keywords` 필드를
  요청하지 않음. OpenAI structured output의 `_SUMMARY_JSON_SCHEMA`에서도 `keywords`
  property와 `required` 항목을 제거(4개 필드로 축소: `suggestedTitle`/`oneLineSummary`/
  `keyPoints`/`detailedNotes`).
- **`app/llm/parsing.py`**: `render_markdown()`이 더 이상 "## 복습 키워드" 섹션을 마크다운
  끝에 붙이지 않음.
- **`app/llm/schema.py`(`ParsedSummary.keywords`)와 `summaries.keywords` DB 컬럼은
  그대로 유지**했다 — §-3에서 죽은 필드가 된 `concepts`/`code_snippets`/`action_items`와
  같은 방식(과거 데이터 호환용으로 스키마·API에는 남기되 이후 생성되는 요약에는 항상 빈
  배열)을 그대로 따른 결정이다. 컬럼을 드롭하고 싶어지면 그때 가서 별도 마이그레이션으로
  고려할 것.
- **프론트(`frontend/src/pages/sessionDetail.ts`)**: "복습 키워드" `<h3>` 섹션을
  `summary.keywords`가 비어있지 않을 때만 렌더링하도록 조건부로 바꿈 — 별도 분기 없이도
  앞으로 생성되는 요약(keywords 항상 `[]`)은 자연히 안 보이고, 이미 keywords가 채워진
  과거 세션은 계속 그대로 보인다.
- 테스트: `test_llm_parsing.py`(FIXED_HEADERS에서 "## 복습 키워드" 제거,
  `test_empty_key_points_and_keywords_render_none` → `test_empty_key_points_render_none` +
  `test_keywords_section_not_rendered` 신설)/`test_llm_openai.py`(스키마 `required` 집합
  갱신)/`test_pipeline_summarization.py`("## 복습 키워드" 존재 단언 제거) 갱신. 백엔드
  **401 passed / 4 skipped**, 프론트 **6 passed**(vitest) + `tsc --noEmit` 통과, `ruff
  check` 클린. 실브라우저 검증은 아직 안 함(코드 변경 후 dev 서버 재기동해서 세션 상세
  화면을 직접 확인해볼 것).

## -4. 2026-08-30 갱신 (Tailscale 원격 접속 + 안정성 수정 3건 + 신기능 2건)

**아직 커밋 안 함.** 이 세션 전부 작업 트리에만 있음 — 다음 세션에서 검토 후 커밋할 것.
백엔드는 launchd(`~/Library/LaunchAgents/com.lecturenotes.{backend,frontend}.plist`)로
관리되며 재부팅해도 자동 시작·크래시 시 자동 재시작된다. 코드를 수정한 뒤에는
`launchctl kickstart -k gui/$(id -u)/com.lecturenotes.backend`로 재시작할 것(그냥
`uvicorn ...`을 다시 실행하면 launchd가 관리하는 것과 별개의 프로세스가 되어 포트 충돌).

- **Tailscale로 회사 데스크탑에서 접속 가능하게 함**: `tailscale serve`가 `127.0.0.1:8765`/
  `localhost:5173`를 tailnet 전용으로 프록시(`https://macbookpro.example.ts.net[:8765]`)
  — 백엔드 `BIND_HOST=127.0.0.1` 원칙(§3.7)은 안 건드림. `app/main.py`에
  `ALLOW_TAILSCALE_ORIGINS`(기본 False) 켜면 CORS가 `*.ts.net` origin도 허용.
  `frontend/vite.config.ts`의 `server.allowedHosts`에 `.example.ts.net` 추가.
  `frontend/src/api/client.ts`가 `window.location.hostname`이 `.ts.net`로 끝나면 백엔드
  URL을 자동으로 같은 호스트의 8765 포트로 바꿔치기(로컬 접속과 원격 접속 둘 다 같은 빌드로
  동작). 자세한 문서 없음 — 대화 로그가 유일한 설정 기록이니, 다시 설정할 일 있으면
  `tailscale serve status`부터 확인할 것.
- **오디오 자동 삭제(2026-08-29 막바지 추가)**: 요약까지 성공(DONE)하면 원본 오디오 파일을
  지운다(`settings.DELETE_AUDIO_AFTER_PROCESSING`, 기본 True). `sessions.audio_path`를
  `NULL`로 비우고, API에 `audioAvailable` 필드 추가. 프론트는 오디오 없으면 플레이어 대신
  안내 문구. **기존 세션 오디오는 그대로 남겨둠(사용자가 유지 원함) — 일괄 삭제 안 함.**
- **동시 전사 개수 제한(중요, 실제 장애 대응)**: 사용자가 강의 파일 9개를 25초 안에 연달아
  업로드 → 동시 처리 제한이 없어 전부 병렬로 돌면서 CPU를 나눠 쓰다가 4시간 동안 전체
  진행률이 20% 안팎에 머무는 실제 장애를 겪음(단독 실행 시 실시간의 ~5배속인데 9개 동시
  실행 시 집계 처리량이 0.3배속까지 떨어짐 — 실측). `app/pipeline/transcription.py`에
  `threading.Semaphore(settings.MAX_CONCURRENT_TRANSCRIPTIONS)`(기본 1) 추가 — 업로드는
  몇 개든 즉시 접수되지만 실제 전사(CPU 바운드)는 한 번에 1개씩만. 장애 복구 절차: 백엔드
  재시작(복구 스윕이 TRANSCRIBING 세션을 FAILED(INTERRUPTED)로 정리) → 각 세션에
  `POST /sessions/{id}/process` 재호출 → 세마포어가 알아서 줄 세움. 이날 실제로 8개를
  이 방법으로 전부 복구·완료시킴.
- **제목 자동 생성**: `sessions.title_customized`(기본 False) 플래그 추가. 요약 완료 시
  LLM이 제안한 제목(`suggestedTitle`, 새 프롬프트 필드)으로 자동 갱신하되, 사용자가 제목을
  직접 입력/수정한 적이 있으면(업로드 시 명시 입력 또는 PATCH) 절대 안 덮어씀. 업로드 기본
  제목("YYYY-MM-DD 수업")이 하루 여러 건이면 전부 동일해 구별 안 되는 문제(위 장애 상황에서
  실제로 겪음)를 해결.
- **홈 화면 세션 목록 필터**: `GET /sessions`에 `q`(제목+최신 요약 내용 검색, row_number
  서브쿼리로 세션당 최신 요약만 검색), `date_from`/`date_to` 추가. 프론트 `home.ts`에 검색창
  (디바운스 300ms) + 날짜 범위 입력 + 초기화 버튼.
- **map-reduce 청크 크기 provider별 분리(성능 최적화)**: OpenAI는 컨텍스트가 1.05M 토큰(공식
  문서로 확인)이라 이 앱 최장 강의(240분)도 통째로 한 번에 들어가는데, 기존 Ollama용 좁은
  청크 크기(4000)를 그대로 쓰고 있어서 긴 강의마다 불필요하게 2~3번 호출되어(map+reduce)
  시간이 2~3배, 고정 지시문(~1700토큰) 전송도 그만큼 반복되고 있었다 — 실사용 중 요약이
  93~123초씩 걸리는 걸 이상하게 여겨 조사하다 발견. `app/pipeline/summarization.py`의
  `_default_chunk_size_tokens()`가 provider_name으로 분기 —
  openai는 `settings.OPENAI_SUMMARY_CHUNK_SIZE_TOKENS`(200000, 사실상 단일 호출).
- 테스트: 백엔드 401 passed, 프론트 6 passed + tsc 통과, ruff 클린.
- **다음 세션 참고**: 제목 자동 생성/청크 크기 분리 코드는 작성·테스트 완료됐지만, 8개
  동시 처리 장애를 복구하는 동안 백엔드를 안 건드리려고 재시작을 미뤄뒀다 — 세션이 끝날
  때 즈음 재시작해서 반영했는지 다음 세션에서 `git diff`/실제 동작으로 확인할 것. 그 전에
  처리된 세션들은 제목이 자동으로 안 붙어 있을 수 있음(재요약하면 새로 붙음).



이 문서는 다음 세션(사람이든 새 Claude Code 세션이든)이 이어받을 때 참고할 현재 상태 요약이다.
전체 요구사항은 `/Users/son/개발/연습장/docs/requirements/stt-transcription.md`가 원본이며,
이 문서는 그 문서의 "지금 어디까지 됐는가"만 다룬다. **백엔드(`backend/`)와 프론트엔드
(`frontend/`)는 별도 git 저장소다** — 각자 `git log`로 확인할 것.

## -3-1. 2026-08-29 추가 갱신 (요약 완료 후 오디오 자동 삭제)

**아직 커밋 안 함.** 사용자가 실사용 중 "오디오 재생 기능을 거의 안 쓰고 요약/전사 텍스트만
본다"고 확인 — 요약까지 성공(DONE)하면 원본 오디오 파일을 자동 삭제하도록 변경.

- `app/core/config.py`: `DELETE_AUDIO_AFTER_PROCESSING: bool = True` 추가(되돌릴 수 없는
  동작이라 끌 수 있게 설정으로 뺐음).
- `app/pipeline/summarization.py`: `_delete_audio_if_configured()` — `DONE` 전이 직후
  호출, `session.audio_path`를 `None`으로 비움. 재요약 시 오디오가 이미 없어도
  `delete_stored_file()`의 `missing_ok=True`라 조용히 넘어감. 실패(FAILED)한 세션은
  오디오를 안 지움 — 재시도 여지를 남김.
- API: `SessionDetailResponse`에 `audioAvailable: bool` 추가(`app/schemas/session.py`,
  `app/api/v1/sessions.py`). 프론트(`sessionDetail.ts`)는 이 값으로 `<audio>` 엘리먼트
  렌더링 여부를 분기 — 오디오 없으면 빈 플레이어 대신 안내 문구.
- DB 스키마 변경 없음(마이그레이션 불필요) — `audio_path` 컬럼은 원래도 nullable.
- 테스트: 백엔드 368 passed(신규 7개: `test_pipeline_summarization.py`의
  `TestAudioDeletedAfterSuccess`, `test_sessions_read_api.py`의
  `TestSessionDetailAudioAvailable`), 프론트 6 passed + tsc 통과.
- 실사용 검증: 실제 업로드→DONE까지 돌려서 디스크에서 파일 삭제 확인, `audioAvailable`
  false 확인, 프론트 화면에 안내 문구 정상 노출·콘솔 에러 0건 확인.
- **다음 세션 참고**: 이 변경은 **앞으로 완료되는 세션에만** 적용된다 — 기존 12개 세션의
  오디오 파일(`data/audio/`)은 그대로 남아있다. 사용자가 원하면 기존 파일도 일괄 정리하는
  스크립트를 짜줄 수 있음 — 아직 안 함, 명시적으로 요청 없었음.

## -3. 2026-08-29 갱신 (요약 엔진 로컬→클라우드 전환 + 자유형식 본문 도입)

**아직 커밋 안 함** — 이 세션에서 수정한 파일들은 작업 트리에만 있다. 다음 세션(또는 사람)이
검토 후 커밋할 것.

- **배경**: 사용자가 로컬 Ollama(qwen3:14b) 재요약 기능을 실사용하다 (1) 24GB 통합 메모리에서
  STT+LLM을 같이 돌릴 때 메모리 압박(swap 발생)을 겪었고 (2) `think:true`를 켠 뒤로 실제
  재요약이 JSON 스키마 검증 실패로 두 번 연속 실패하는 걸 확인함(로그: `atSeconds` 필드 누락,
  `oneLineSummary` 타입 불일치). 요약 단계만 클라우드(OpenAI)로 옮기기로 함 — 로컬
  STT(faster-whisper)는 계속 오프라인으로 남는다.
- **`app/llm/openai_provider.py` 신규**: `OpenAiLlmProvider`가 `LlmProvider` 인터페이스를
  구현. OpenAI Responses API(`client.responses.create`)의 `text.format` structured
  outputs(`strict: True`)로 JSON 스키마를 서버가 강제 — Ollama의 느슨한 `format:"json"`과
  달리 스키마 위반 자체가 구조적으로 안 생긴다. `app/pipeline/providers.py`의
  `build_llm_provider()`에 `"openai"` 분기 추가. `app/core/config.py`에
  `OPENAI_API_KEY`/`OPENAI_MODEL`(기본 `gpt-5.6-luna`)/`OPENAI_TIMEOUT_SECONDS` 추가.
  실사용 `.env`는 `LLM_PROVIDER=openai`로 전환됨(키는 사용자가 직접 넣음).
- **요약 스키마를 고정 6섹션 → 자유형식 본문으로 전면 개정** (US-05가 원래 요구하던 "6섹션
  항상 존재"를 깨는 결정, 사용자가 명시적으로 승인함): 기존 방식은 "용어: 한 줄 정의"처럼
  뭉뚱그려진 요약으로 이어진다는 게 사용자가 실제 Claude 채팅으로 만든 예시와의 비교로
  드러남(강의마다 섹션 구성이 다를 수 있는데 고정 필드로는 표현 불가). 이제 LLM 응답 JSON은
  4개 필드만 강제: `oneLineSummary`, `keyPoints`(타임스탬프 점프용, 여전히 구조화됨),
  `keywords`, `detailedNotes`(강의 내용에 맞게 LLM이 자유롭게 구성한 마크다운 본문 — 섹션
  개수/제목 유동적, 💡 콜아웃, 중첩 리스트, 코드블록 등 허용). `concepts`/`codeSnippets`/
  `actionItems`는 스키마·API 응답에는 남아있지만(과거 요약 데이터 호환용) 이후 생성되는
  요약에는 항상 빈 배열 — 새로 추가한 `summaries.detailed_notes_markdown` 컬럼(마이그레이션
  `c6691b026114`)이 실제 콘텐츠를 담는다.
  - `app/llm/schema.py`(`ParsedSummary`에서 concepts/code_snippets/action_items 제거,
    `detailed_notes` 추가) / `app/llm/parsing.py`(`render_markdown()`이 "## 한 줄 요약" +
    "## 핵심 주제"만 조립하고 본문은 LLM 마크다운을 그대로 붙임) / `app/llm/prompt.py`(실제
    Claude 채팅 예시를 프롬프트에 few-shot으로 포함, "환각 금지"를 "사실 왜곡 금지"와 "이해를
    돕는 예시 창작은 허용"으로 구분) 모두 함께 개정.
  - 프론트(`frontend/src/pages/sessionDetail.ts`)는 `detailedNotesMarkdown`이 있으면 그걸
    주 콘텐츠로 렌더링(신규 `frontend/src/utils/markdown.ts` — `## `/`-`/`1. `/`**`/코드펜스/
    💡콜아웃만 지원하는 아주 작은 파서, 범용 마크다운 라이브러리 아님), 없으면(2026-08-29
    이전 요약) 예전 개념/코드/과제 구조화 섹션으로 폴백— 과거 데이터도 계속 보임.
- **세션 상세 화면에 "요약 다시 만들기" 버튼 신규 추가**(`sessionDetail.ts`) — 이전엔 백엔드
  API(`POST /sessions/{id}/summarize`, T-25)만 있고 프론트 트리거가 아예 없었다(요구사항
  §7 태스크 목록에도 프론트 태스크로 안 잡혀 있었음, 실제 버그로 확인·수정).
- 테스트: 백엔드 361 passed(신규 테스트 다수 포함: `test_llm_openai.py`,
  `test_health_api.py`의 OpenAI 분기, `test_llm_parsing.py`/`test_pipeline_summarization.py`
  전면 개정), 프론트 6 passed(vitest) + tsc 통과. `docker compose -f docker-compose.test.yml`
  postgres 컨테이너 필요(`TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/signup_test`).
- **실사용 검증**: "녹음 (12)"(22분 RAG 강의)을 새 파이프라인으로 재요약 → 10개 섹션의 풍부한
  본문(중첩 헤더, 💡 콜아웃, 코드블록, 구체적 예시)이 생성됨을 확인, Playwright로 실제
  브라우저 렌더링(헤더/리스트/코드블록/콜아웃 전부 정상)까지 확인 완료.
- **다음 세션 참고**: 아직 git 커밋 안 됨(위 참고). 나머지 8~9개 기존 세션도 "요약 다시
  만들기" 버튼으로 재요약하면 새 형식으로 바뀐다(사용자가 원할 때 직접 누르면 됨, 자동
  일괄 재처리는 하지 않았음). `app/models/summary.py`의 `concepts`/`code_snippets`/
  `action_items` 컬럼은 이제 죽은 코드 경로에 가깝다 — 과거 데이터 조회용으로만 남겨뒀으니
  향후 완전히 정리하고 싶으면 별도 마이그레이션으로 드롭을 고려할 것(지금은 보류).

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

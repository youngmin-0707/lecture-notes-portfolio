# 보안/개인정보 체크리스트 보고서 (T-38)

**대상**: §3.7 보안/개인정보 요구사항
**작성일**: 2026-08-23
**검증 방법**: 자동화 테스트 재실행 + 소스 코드 확인 + 실제 파일시스템 권한 실측

## 요약

| # | 항목 | 결과 |
|---|------|------|
| 1 | 127.0.0.1 바인딩 | ✅ 통과 |
| 2 | API 키 미노출 | ✅ 통과 |
| 3 | 로그에 본문(전사/요약) 미기록 | ✅ 통과 |
| 4 | 경로 순회 차단 | ✅ 통과 |
| 5 | 위장 파일 차단 | ✅ 통과 |
| 6 | `data/` 디렉토리·DB 파일 권한 | ✅ 통과 (실제 취약점 1건 발견 후 수정) |

미통과 항목 없음 — 발견된 취약점(6번)은 이미 수정 완료되어 이슈로 별도 등록하지 않는다.

---

## 1. 127.0.0.1 바인딩 강제

**결과: 통과**

인증이 없는 개인용 로컬 앱이므로 바인딩 주소가 유일한 방어선이다. `app/main.py`에
`BIND_HOST=0.0.0.0`으로 앱을 기동하려는 시도 자체를 앱 시작 단계에서 거부하는
`validate_bind_host()` 가드가 있고(`app/main.py:26-33`), 기본값은
`app/core/config.py:28`에서 `BIND_HOST: str = "127.0.0.1"`로 고정된다.

CORS도 `http://127.0.0.1:*`, `http://localhost:*` 오리진만 허용한다 (`app/main.py:70-82`).

**근거 (재실행 결과, 전부 통과)**:
- `tests/test_bind_host_and_cors.py`
  - `test_bind_host_0000_rejects_app_startup` — `0.0.0.0` 설정 시 앱 기동 자체가 예외로 거부됨
  - `test_bind_host_default_127_0_0_1_starts_successfully`
  - `test_bind_host_explicit_127_0_0_1_starts_successfully`
  - `test_cors_allows_127_0_0_1_origin`
  - `test_cors_allows_localhost_origin_with_port`
  - `test_cors_blocks_other_origins`
  - `test_cors_exposes_content_disposition_header`

---

## 2. API 키 미노출

**결과: 통과**

`GET /api/v1/health` 등 상태 확인 엔드포인트는 `GEMINI_API_KEY`/`GROQ_API_KEY`의 **설정
여부(boolean)만** 노출하고 값 자체는 응답에 절대 포함하지 않는다
(`app/api/v1/health.py:7`, `app/api/v1/health.py:121`:
`configured = bool(settings.GEMINI_API_KEY or settings.GROQ_API_KEY)`).

**근거**: `tests/test_health_api.py` (T-28) — health 응답 바디에 실제 키 값이 없고
`configured` 불리언만 있음을 검증. 재실행 통과.

---

## 3. 로그에 전사/요약 본문 미기록

**결과: 통과**

강의 내용(전사 전문, 요약 본문)은 개인정보/저작권 민감 데이터이므로 로그에는 길이·소요
시간 등 메타데이터만 남기고 본문 텍스트 자체는 절대 기록하지 않는다.

**근거 (재실행 결과, 전부 통과)**:
- `tests/test_no_body_text_in_logs.py`
  - `test_transcript_marker_not_in_logs` — 전사 파이프라인 실행 중 캡처한 모든 로그 레코드에
    실제 전사 본문 마커 문자열이 등장하지 않음을 확인
  - `test_summary_marker_not_in_logs` — 요약 파이프라인도 동일하게 확인
  - `test_logs_still_record_length_and_timing_metadata` — 본문은 없지만 글자 수/소요 시간
    같은 운영에 필요한 메타데이터는 정상적으로 남는지 확인 (과도한 은닉으로 디버깅이
    불가능해지지 않았는지 함께 검증)

---

## 4. 경로 순회(Path Traversal) 차단

**결과: 통과**

업로드 파일의 저장 경로는 서버가 생성한 UUID로만 구성하고, 사용자가 준 원본 파일명은
저장 경로 어디에도 사용하지 않는다 — 이는 경로 순회 취약점을 애초에 발생 불가능하게 만드는
설계다 (`app/audio/storage.py:1-6, 63`: `dest = storage_dir / f"{uuid.uuid4().hex}.upload"`).

다운로드/내보내기(export) 시 사용자에게 보여주는 파일명(세션 제목 기반)은 별도로
새니타이즈해서 `Content-Disposition` 헤더에 넣는다 — 여기서도 `../`나 제어 문자를 통한
경로 순회·헤더 인젝션을 차단한다.

**근거**:
- `app/audio/storage.py:63` — UUID 기반 저장 경로, 원본 파일명 미사용
- `tests/test_export_filename.py` (전부 통과)
  - `test_removes_path_separators`
  - `test_path_traversal_attempt_in_title_is_sanitized` — 제목에 `../../etc/passwd` 같은
    문자열을 넣어도 내보내기 파일명이 안전하게 새니타이즈됨을 확인
  - `test_removes_control_characters`
  - `test_header_value_is_ascii_safe` — `Content-Disposition` 헤더 인젝션 방지
  - 그 외 빈 입력 폴백, UTF-8 확장 파일명 처리 등

---

## 5. 위장 파일(Disguised File) 차단

**결과: 통과**

업로드된 파일의 실제 형식을 **확장자가 아니라 파일 시작 바이트(매직 넘버/컨테이너 헤더)**로
판별한다 (`app/audio/validation.py:1-6, 36-56`의 `detect_audio_format`). 예를 들어
`.mp3` 확장자를 붙인 PDF 파일은 헤더가 `%PDF`이므로 어떤 오디오 포맷 시그니처와도
일치하지 않아 거부된다. 매직 넘버 판별 이후에도 `probe_audio`(PyAV/ffmpeg)로 실제
디코딩 가능 여부까지 재확인한다(`app/audio/validation.py:89-125`) — 이중 방어.

**근거**:
- `app/audio/validation.py:36-56` — 확장자 미참조, RIFF/WAVE, fLaC, OggS, EBML(webm),
  ftyp(mp4/m4a), ID3/MPEG 프레임 헤더로만 판별
- `tests/test_sessions_create_api.py::test_rejects_pdf_disguised_as_mp3` (통과) — `.mp3`
  확장자를 붙인 PDF 바이트를 업로드하면 `INVALID_AUDIO_FILE`로 거부됨을 확인

---

## 6. `data/` 디렉토리 및 DB 파일 권한

**결과: 통과 (실제 취약점 발견 후 수정 완료)**

### 발견된 문제
T-38 점검 중 `data/` 디렉토리가 `0755`, `data/lecture_notes.db`가 `0644`(월드 리더블)
상태로 남아 있던 것을 실제로 발견했다 — 같은 macOS 계정을 공유하는 다른 로컬 사용자가
강의 전사·요약 내용을 읽을 수 있는 상태였다. 원인은 `Path.mkdir(mode=...)`가 디렉토리가
**새로 생성될 때만** 적용되고, 이미 존재하면 그 인자를 조용히 무시하기 때문이었다
(`app/core/fs.py:1-9` 문서화됨).

### 수정
`app/core/fs.py`에 `ensure_private_dir`/`ensure_private_file` 유틸을 추가해, 디렉토리
생성 여부와 무관하게 매번 `chmod`로 권한을 명시적으로 재적용하도록 했다. 이 유틸은
`app/audio/storage.py:40` (`check_disk_space` → 업로드 전 매번 호출)와 DB 연결 경로에서
호출된다.

### 실측 검증 (2026-08-23, 이 보고서 작성 시점)
```
drwx------@ 5 son  staff     160  data
-rw-------@ 1 son  staff  163840  data/lecture_notes.db
```
디렉토리 `0700`, DB 파일 `0600` — 소유자 전용으로 정상 적용되어 있음을 실측으로 확인.

**근거 (재실행 결과, 전부 통과)**:
- `tests/test_data_directory_permissions.py`
  - `test_creates_missing_dir_with_0700`
  - `test_fixes_existing_dir_with_wrong_permissions` — **회귀 재발 방지 테스트**: 이미
    잘못된 권한(0755)으로 존재하는 디렉토리도 다음 호출에서 0700으로 고쳐지는지 확인
  - `test_creates_nested_parents`
  - `test_fixes_existing_file_with_wrong_permissions`
  - `test_missing_file_is_noop`
  - `test_fresh_db_gets_private_dir_and_file`
  - `test_existing_db_with_wrong_permissions_gets_fixed_on_connect`
  - `test_check_disk_space_fixes_existing_wrong_permission_dir` — 업로드 경로에서도
    매번 권한이 재적용되는지 확인

---

## 재현 방법

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5433/signup_test \
  .venv/bin/pytest -q \
  tests/test_bind_host_and_cors.py \
  tests/test_health_api.py \
  tests/test_no_body_text_in_logs.py \
  tests/test_sessions_create_api.py \
  tests/test_data_directory_permissions.py \
  tests/test_export_filename.py
```
2026-08-23 기준 결과: **50 passed**.

## 결론

§3.7의 6개 체크리스트 항목 모두 통과했다. 6번(`data/` 권한) 항목은 점검 과정에서 실제
취약점을 발견해 수정했고, 재발 방지를 위한 회귀 테스트(`test_fixes_existing_dir_with_wrong_permissions`
등)를 추가했다. 신규 이슈로 등록할 미통과 항목은 없다.

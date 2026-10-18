"""처리 중(TRANSCRIBING/SUMMARIZING) 세션의 진행률을 담아두는 프로세스 내 스토어.

`sessions` 테이블에는 진행률 컬럼이 없다 (§2.3) — 진행률은 처리 도중에만 의미가 있는
휘발성 정보이므로 DB에 영구 저장하지 않는다. 대신 이 모듈이 프로세스 메모리에 최신
진행률을 들고 있다가, `GET /sessions/{id}` 조회 시(§5.3③) 읽어서 함께 반환한다.

주의: `BackgroundTasks` 연결(T-19) 전까지는 처리가 요청-응답 흐름 안에서 동기적으로
끝나므로, 실제로 "처리 중" 상태를 외부에서 관찰할 기회는 제한적이다. 그래도 다음 라운드
(T-19)에서 그대로 재사용할 수 있도록 지금 이 형태로 만들어둔다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressInfo:
    """§5.3③ 응답의 `progress` 객체와 1:1 대응."""

    stage: str
    percent: float
    eta_seconds: float | None


_progress_by_session: dict[str, ProgressInfo] = {}


def set_progress(
    session_id: str, *, stage: str, percent: float, eta_seconds: float | None = None
) -> None:
    clamped_percent = max(0.0, min(100.0, percent))
    _progress_by_session[session_id] = ProgressInfo(
        stage=stage, percent=clamped_percent, eta_seconds=eta_seconds
    )


def get_progress(session_id: str) -> ProgressInfo | None:
    return _progress_by_session.get(session_id)


def clear_progress(session_id: str) -> None:
    _progress_by_session.pop(session_id, None)


def clear_all_progress() -> None:
    """테스트 격리용: 프로세스 내 진행률 스토어를 전부 비운다."""
    _progress_by_session.clear()


def make_stt_progress_callback(session_id: str, *, stage: str = "TRANSCRIBING"):
    """`SttProvider.transcribe(progress_callback=...)`에 넘길 콜백을 만든다 (§3.2)."""

    def _callback(processed_seconds: float, duration_seconds: float) -> None:
        if duration_seconds and duration_seconds > 0:
            percent = (processed_seconds / duration_seconds) * 100
            remaining = max(duration_seconds - processed_seconds, 0.0)
            # 지금까지의 처리 속도로 잔여 시간을 어림한다. 처리 속도를 알 수 없는 시작
            # 시점(processed_seconds == 0)에는 eta를 비워둔다.
            eta_seconds = remaining if processed_seconds > 0 else None
        else:
            percent = 0.0
            eta_seconds = None
        set_progress(session_id, stage=stage, percent=percent, eta_seconds=eta_seconds)

    return _callback

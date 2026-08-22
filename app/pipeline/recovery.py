"""비정상 종료 복구 스윕 (T-20, §3.6, US-10).

`BackgroundTasks`는 서버가 재시작되면 진행 중이던 작업을 그대로 잃는다. 서버 기동 시
(`app/main.py`의 lifespan) 이 스윕을 1회 실행해, `TRANSCRIBING`/`SUMMARIZING` 상태로 남아있는
모든 세션을 `FAILED(error_code="INTERRUPTED")`로 전이시킨다.

서버가 방금 기동됐다는 것 자체가 "이전 프로세스가 어떤 이유로든 끝났다"는 뜻이므로, 발견된
처리중 세션은 얼마나 오래 그 상태에 머물렀는지와 무관하게 전부 중단된 것으로 간주한다 — 이는
§3.6의 "30분 이상 TRANSCRIBING에 머문 세션도 동일하게 처리한다"를 상한 없이 포함하는
상위집합이다.

전사(`transcripts`)가 이미 저장되어 있었다면 그대로 남아 있으므로(§2.4, US-08), 사용자가
`POST /sessions/{id}/process`를 다시 호출하면 `app/pipeline/orchestration.run_pipeline()`이
전사를 재사용하고 요약 단계부터 재개한다.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.models.enums import SessionStatus
from app.models.session import Session

logger = logging.getLogger("app.pipeline.recovery")

_INTERRUPTED_MESSAGE = "서버 재시작으로 처리가 중단되었습니다. 다시 시도해 주세요."

_PROCESSING_STATUSES = (SessionStatus.TRANSCRIBING.value, SessionStatus.SUMMARIZING.value)


def sweep_interrupted_sessions(db: DBSession) -> list[str]:
    """`TRANSCRIBING`/`SUMMARIZING` 상태로 남은 세션을 전부 `FAILED(INTERRUPTED)`로 전이한다.

    Returns:
        전이시킨 세션 id 목록. 호출부(`app/main.py`)가 커밋을 책임진다 — 이 함수는
        `flush()`까지만 한다 (다른 pipeline 함수들과 동일한 관례).
    """
    sessions = (
        db.execute(select(Session).where(Session.status.in_(_PROCESSING_STATUSES))).scalars().all()
    )

    swept_ids: list[str] = []
    for session in sessions:
        previous_status = session.status
        session.status = SessionStatus.FAILED.value
        session.error_code = "INTERRUPTED"
        session.error_message = _INTERRUPTED_MESSAGE
        swept_ids.append(session.id)
        logger.warning(
            "recovery sweep: session interrupted id=%s previous_status=%s",
            session.id,
            previous_status,
        )

    db.flush()
    return swept_ids

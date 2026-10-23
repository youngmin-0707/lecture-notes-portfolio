"""전사 자식 프로세스 격리 배선 테스트 (2026-10-23).

실제 모델을 띄우지 않도록 자식 진입점을 이 모듈의 가짜 함수로 바꿔 끼운다
(`spawn`은 진입점을 모듈 경로로 다시 import하므로 모듈 최상위에 정의한다).
"""

from __future__ import annotations

import os

import pytest

from app.core.errors import AppError
from app.stt.base import SttSegment, SttTranscriptionResult
from app.stt.local_whisper import _TranscribeJob, _transcribe_in_subprocess

JOB = _TranscribeJob(
    model_size="fake",
    device="cpu",
    compute_type="int8",
    download_root="/nonexistent",
    vad_filter=True,
    audio_path="/nonexistent.wav",
    language="ko",
    initial_prompt=None,
)


def _ok_entry(job, events):
    events.put(("progress", 1.0, 2.0))
    events.put(("progress", 2.0, 2.0))
    events.put(
        (
            "result",
            SttTranscriptionResult(
                text=f"pid={os.getpid()}",
                segments=[SttSegment(start=0.0, end=2.0, text="안녕")],
                elapsed_seconds=0.1,
                language=job.language,
            ),
        )
    )


def _error_entry(job, events):
    events.put(("error", "STT_FAILED"))


def _crash_entry(job, events):
    os._exit(1)


def test_result_and_progress_come_back_from_child_process():
    progress: list[tuple[float, float]] = []
    result = _transcribe_in_subprocess(JOB, lambda c, t: progress.append((c, t)), entry=_ok_entry)

    assert progress == [(1.0, 2.0), (2.0, 2.0)]
    assert result.segments[0].text == "안녕"
    assert result.text != f"pid={os.getpid()}"  # 다른 프로세스에서 실행됐다


def test_child_error_code_is_raised_as_app_error():
    with pytest.raises(AppError) as excinfo:
        _transcribe_in_subprocess(JOB, None, entry=_error_entry)
    assert excinfo.value.code == "STT_FAILED"


def test_child_crash_becomes_stt_failed():
    with pytest.raises(AppError) as excinfo:
        _transcribe_in_subprocess(JOB, None, entry=_crash_entry)
    assert excinfo.value.code == "STT_FAILED"

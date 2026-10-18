"""로컬 `faster-whisper` 구현체 (T-11, §0 D3, §3.2).

- 모델 `large-v3-turbo`, 언어 `ko` 고정 (§0 D10, `settings.STT_LANGUAGE`를 통해 전달받음)
- VAD 활성화 (§3.2 — 강의 중 침묵이 길어 처리 시간을 크게 줄인다)
- **지연 로딩 + 프로세스 내 캐시**: 모델은 최초 `transcribe()` 호출 시점에 한 번만 로드되고
  이후 호출은 모듈 레벨 캐시에 있는 동일 인스턴스를 재사용한다 (§3.2 "매 요청 재로딩 금지").
- 모델은 `download_root=<settings.MODEL_CACHE_DIR>`에 캐시된다 (최초 1회 다운로드, §3.2).

무거운 의존성(`faster_whisper`, 그리고 그 하위의 `ctranslate2`)은 모듈 최상단이 아니라
`_load_model()` 내부에서 지연 import한다 — 이 모듈을 단순히 import하는 것만으로 무거운
네이티브 라이브러리가 로드되지 않게 하기 위함이다 (§2.2 "무거운 모델 로딩은 첫 사용
시점에 지연 로딩한다").
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import AppError
from app.core.fs import ensure_private_dir
from app.stt.base import ProgressCallback, SttProvider, SttSegment, SttTranscriptionResult

logger = logging.getLogger("app.stt.local_whisper")

# (model_size, device, compute_type, download_root) -> WhisperModel 인스턴스.
# 프로세스 생애주기 동안 유지되는 캐시. 동일 설정으로 여러 `LocalWhisperSttProvider`
# 인스턴스를 만들어도 실제 모델은 한 번만 로드된다.
_model_cache: dict[tuple[str, str, str, str], Any] = {}
_model_cache_lock = threading.Lock()


def _load_model(model_size: str, device: str, compute_type: str, download_root: str) -> Any:
    cache_key = (model_size, device, compute_type, download_root)
    with _model_cache_lock:
        cached = _model_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - 의존성 미설치 환경 방어
            raise AppError("STT_MODEL_UNAVAILABLE") from exc

        ensure_private_dir(Path(download_root))

        logger.info(
            "Loading faster-whisper model (first use): model=%s device=%s compute_type=%s",
            model_size,
            device,
            compute_type,
        )
        # 모델이 이미 캐시돼 있으면 `local_files_only=True`로 완전 오프라인으로 로드한다.
        # 이게 없으면 huggingface_hub이 캐시가 있어도 최신인지 확인하려고 CDN에 접속을
        # 시도한다 — 실측(T-36)으로 확인된 실제 오프라인 모드 위반이었다. 캐시가 없는
        # 최초 실행(§3.2 "모델 다운로드: 최초 1회")까지 막으면 안 되므로, 오프라인 로드가
        # 실패할 때만 네트워크를 쓰는 경로로 폴백한다.
        try:
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=download_root,
                local_files_only=True,
            )
        except Exception:  # noqa: BLE001 — 캐시 미존재를 포함해 어떤 이유든 폴백 대상이다.
            logger.info(
                "Model not found locally, falling back to network download: model=%s",
                model_size,
            )
            try:
                model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                    download_root=download_root,
                )
            except Exception as exc:  # noqa: BLE001 — 다운로드/로드 실패는 모두 모델 준비 실패다.
                raise AppError("STT_MODEL_UNAVAILABLE") from exc

        _model_cache[cache_key] = model
        return model


class LocalWhisperSttProvider(SttProvider):
    """`faster-whisper` 로컬 실행 어댑터."""

    def __init__(
        self,
        *,
        model_size: str | None = None,
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | None = None,
        vad_filter: bool = True,
    ) -> None:
        # 참고: CTranslate2는 Apple Silicon GPU(Metal)를 지원하지 않아 macOS에서는
        # device="cpu"가 사실상 유일한 선택지다. compute_type="int8"은 CPU에서
        # float32 대비 크게 빠르면서 large-v3-turbo 기준 정확도 손실이 미미하다.
        self._model_size = model_size or settings.STT_MODEL
        self._device = device
        self._compute_type = compute_type
        self._download_root = download_root or settings.MODEL_CACHE_DIR
        self._vad_filter = vad_filter

    @property
    def provider_name(self) -> str:
        return "local_whisper"

    @property
    def provider_model(self) -> str:
        return self._model_size

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        language: str,
        initial_prompt: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> SttTranscriptionResult:
        model = _load_model(self._model_size, self._device, self._compute_type, self._download_root)

        started_at = time.monotonic()
        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language,
                initial_prompt=initial_prompt,
                vad_filter=self._vad_filter,
            )

            segments: list[SttSegment] = []
            texts: list[str] = []
            duration = info.duration or 0.0
            for raw_segment in segments_iter:
                text = raw_segment.text.strip()
                segments.append(SttSegment(start=raw_segment.start, end=raw_segment.end, text=text))
                texts.append(text)
                if progress_callback is not None:
                    progress_callback(raw_segment.end, duration)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 — 디코딩/추론 오류는 모두 전사 실패로 취급한다.
            raise AppError("STT_FAILED") from exc

        elapsed_seconds = time.monotonic() - started_at
        return SttTranscriptionResult(
            text=" ".join(t for t in texts if t),
            segments=segments,
            elapsed_seconds=elapsed_seconds,
            language=info.language or language,
        )

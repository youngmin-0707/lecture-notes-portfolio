"""소유자 전용 파일/디렉토리 권한 유틸 (§3.7 "data/ 디렉토리는 소유자 전용 권한(0700)").

`Path.mkdir(mode=...)`는 디렉토리가 **새로 생성될 때만** 적용된다 — 이미 존재하면 그 인자는
조용히 무시된다. 그래서 어떤 이유로든(예: 과거에 다른 경로로 먼저 만들어졌거나, umask가
다르게 설정된 환경) 디렉토리가 이미 잘못된 권한으로 있었다면, `mkdir(mode=0o700)`만 호출하는
코드는 그 실수를 절대 스스로 고치지 못하고 영구히 반복한다. 실제로 이 저장소의 `data/`
디렉토리가 0755, `data/lecture_notes.db`가 0644(월드 리더블)로 남아있던 걸 T-38 보안 점검
중 발견했다 — 다른 로컬 사용자 계정이 강의 전사·요약을 읽을 수 있는 상태였다.
그래서 이 유틸은 항상 `mkdir` 뒤에 `chmod`를 명시적으로 다시 건다.
"""

from __future__ import annotations

from pathlib import Path


def ensure_private_dir(path: Path | str) -> Path:
    """디렉토리를 만들고(이미 있으면 그대로 두고) 소유자 전용 권한(0700)을 매번 강제한다."""
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    resolved.chmod(0o700)
    return resolved


def ensure_private_file(path: Path | str) -> None:
    """파일이 존재하면 소유자 전용 권한(0600)을 강제한다. 없으면 아무 것도 하지 않는다."""
    resolved = Path(path)
    if resolved.exists():
        resolved.chmod(0o600)

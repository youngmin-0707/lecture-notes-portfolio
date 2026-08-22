"""127.0.0.1 바인딩 강제 + CORS 제한 테스트 (T-06, §3.7, US-11).

- BIND_HOST=0.0.0.0이면 `app.main`을 import하는 시점에 기동을 거부해야 한다.
  이는 프로세스 전역 상태(모듈 캐시)에 영향을 주므로 격리된 서브프로세스로 검증한다.
- CORS는 http://127.0.0.1:*, http://localhost:*만 허용해야 한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_import_app_main(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **env_overrides}
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_bind_host_0000_rejects_app_startup() -> None:
    result = _run_import_app_main({"BIND_HOST": "0.0.0.0"})

    assert result.returncode != 0
    assert "0.0.0.0" in (result.stdout + result.stderr)


def test_bind_host_default_127_0_0_1_starts_successfully() -> None:
    result = _run_import_app_main({})

    assert result.returncode == 0, result.stderr


def test_bind_host_explicit_127_0_0_1_starts_successfully() -> None:
    result = _run_import_app_main({"BIND_HOST": "127.0.0.1"})

    assert result.returncode == 0, result.stderr


def test_cors_allows_127_0_0_1_origin() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://127.0.0.1:5500"})

    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5500"


def test_cors_allows_localhost_origin_with_port() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_blocks_other_origins() -> None:
    from app.main import app

    with TestClient(app) as client:
        response = client.get("/health", headers={"Origin": "http://evil.example.com"})

    assert "access-control-allow-origin" not in response.headers

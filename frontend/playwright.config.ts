// E2E 테스트 설정 (T-40). 프론트(Vite dev server)와 백엔드(FastAPI/uvicorn) 둘 다
// 이 설정이 자동으로 띄운다 — `npx playwright test` 한 번으로 전체 스택이 뜬다.
//
// 백엔드는 실제 로컬 STT(faster-whisper, 모델 캐시 재사용)와 실제 LLM(Ollama)로 동작한다
// (Fake Provider가 아니다) — T-40의 목적 자체가 "실제 브라우저 + 실제 전체 스택"이 끝까지
// 도는지 확인하는 것이라 여기서는 의도적으로 백엔드를 목(mock)으로 바꾸지 않는다.
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 5 * 60 * 1000, // 실제 STT+LLM 파이프라인이 끝까지 도는 걸 기다려야 한다.
  expect: { timeout: 10 * 1000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        ".venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765",
      cwd: "../backend",
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: true,
      timeout: 30 * 1000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: true,
      timeout: 30 * 1000,
    },
  ],
});
